"""
Agent and ScopeGroup management routes.

Agents:
  GET    /agents/me           — current agent's profile
  GET    /agents/{id}         — get agent by ID
  PATCH  /agents/me           — update display name

ScopeGroups:
  POST   /groups              — create a group (agent becomes first member)
  GET    /groups/{id}         — get group (members only)
  PATCH  /groups/{id}         — update name or group_type (members only)
  POST   /groups/{id}/members — add a member (members only)
  DELETE /groups/{id}/members/{agent_id} — remove a member (members only)
  DELETE /groups/{id}         — delete a group (members only, no owned objects)
"""

from __future__ import annotations
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from contentbank.db.database import get_db
from contentbank.db.models import Agent, ScopeGroup, ScopeGroupMember, Object
from contentbank.auth.dependencies import require_agent

router = APIRouter(tags=["agents & groups"])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class AgentResponse(BaseModel):
    id: str
    display_name: str
    public_key: str
    created_at: datetime


class AgentUpdateRequest(BaseModel):
    display_name: str


class ScopeGroupCreate(BaseModel):
    name: str
    group_type: str  # "family" | "group"


class ScopeGroupUpdate(BaseModel):
    name: Optional[str] = None


class ScopeGroupResponse(BaseModel):
    id: str
    name: str
    group_type: str
    member_ids: list[str]
    created_at: datetime
    updated_at: datetime


class MemberAddRequest(BaseModel):
    agent_id: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_agent_or_404(db: AsyncSession, agent_id: str) -> Agent:
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


async def _get_group_or_404(db: AsyncSession, group_id: str) -> ScopeGroup:
    result = await db.execute(
        select(ScopeGroup).where(ScopeGroup.id == group_id)
    )
    group = result.scalar_one_or_none()
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")
    return group


async def _require_group_member(
    db: AsyncSession, group_id: str, agent_id: str
) -> None:
    """Raise 403 if agent is not a member of the group."""
    result = await db.execute(
        select(ScopeGroupMember).where(
            and_(
                ScopeGroupMember.group_id == group_id,
                ScopeGroupMember.agent_id == agent_id,
            )
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a member of this group",
        )


async def _group_member_ids(db: AsyncSession, group_id: str) -> list[str]:
    result = await db.execute(
        select(ScopeGroupMember.agent_id).where(
            ScopeGroupMember.group_id == group_id
        )
    )
    return [row[0] for row in result.all()]


def _group_to_response(group: ScopeGroup, member_ids: list[str]) -> ScopeGroupResponse:
    return ScopeGroupResponse(
        id=group.id,
        name=group.name,
        group_type=group.group_type,
        member_ids=member_ids,
        created_at=group.created_at,
        updated_at=group.updated_at,
    )


# ---------------------------------------------------------------------------
# Agent routes
# ---------------------------------------------------------------------------

@router.get("/agents/me", response_model=AgentResponse)
async def get_my_profile(
    requesting_agent_id: str = Depends(require_agent),
    db: AsyncSession = Depends(get_db),
):
    """Return the current agent's profile."""
    agent = await _get_agent_or_404(db, requesting_agent_id)
    return AgentResponse(
        id=agent.id,
        display_name=agent.display_name,
        public_key=agent.public_key,
        created_at=agent.created_at,
    )


@router.get("/agents/{agent_id}", response_model=AgentResponse)
async def get_agent(
    agent_id: str,
    requesting_agent_id: str = Depends(require_agent),
    db: AsyncSession = Depends(get_db),
):
    """
    Get an agent's public profile.
    Public key is included — it is a public value by design.
    """
    agent = await _get_agent_or_404(db, agent_id)
    return AgentResponse(
        id=agent.id,
        display_name=agent.display_name,
        public_key=agent.public_key,
        created_at=agent.created_at,
    )


@router.patch("/agents/me", response_model=AgentResponse)
async def update_my_profile(
    body: AgentUpdateRequest,
    requesting_agent_id: str = Depends(require_agent),
    db: AsyncSession = Depends(get_db),
):
    """Update the current agent's display name."""
    agent = await _get_agent_or_404(db, requesting_agent_id)
    agent.display_name = body.display_name
    await db.flush()
    return AgentResponse(
        id=agent.id,
        display_name=agent.display_name,
        public_key=agent.public_key,
        created_at=agent.created_at,
    )


# ---------------------------------------------------------------------------
# ScopeGroup routes
# ---------------------------------------------------------------------------

@router.post("/groups", response_model=ScopeGroupResponse, status_code=201)
async def create_group(
    body: ScopeGroupCreate,
    requesting_agent_id: str = Depends(require_agent),
    db: AsyncSession = Depends(get_db),
):
    """
    Create a new ScopeGroup. The requesting agent is automatically
    added as the first member.
    """
    if body.group_type not in ("family", "group"):
        raise HTTPException(
            status_code=422,
            detail="group_type must be 'family' or 'group'",
        )

    now = datetime.now(timezone.utc)
    group_id = f"urn:cb:scope_group:{uuid.uuid4()}"

    group = ScopeGroup(
        id=group_id,
        name=body.name,
        group_type=body.group_type,
        created_at=now,
        updated_at=now,
    )
    db.add(group)

    member = ScopeGroupMember(
        group_id=group_id,
        agent_id=requesting_agent_id,
    )
    db.add(member)
    await db.flush()

    return _group_to_response(group, [requesting_agent_id])


@router.get("/groups/{group_id}", response_model=ScopeGroupResponse)
async def get_group(
    group_id: str,
    requesting_agent_id: str = Depends(require_agent),
    db: AsyncSession = Depends(get_db),
):
    """Get a group's details. Requester must be a member."""
    group = await _get_group_or_404(db, group_id)
    await _require_group_member(db, group_id, requesting_agent_id)
    member_ids = await _group_member_ids(db, group_id)
    return _group_to_response(group, member_ids)


@router.patch("/groups/{group_id}", response_model=ScopeGroupResponse)
async def update_group(
    group_id: str,
    body: ScopeGroupUpdate,
    requesting_agent_id: str = Depends(require_agent),
    db: AsyncSession = Depends(get_db),
):
    """Update a group's name. Requester must be a member."""
    group = await _get_group_or_404(db, group_id)
    await _require_group_member(db, group_id, requesting_agent_id)

    if body.name is not None:
        group.name = body.name
    group.updated_at = datetime.now(timezone.utc)
    await db.flush()

    member_ids = await _group_member_ids(db, group_id)
    return _group_to_response(group, member_ids)


@router.post("/groups/{group_id}/members",
             response_model=ScopeGroupResponse, status_code=201)
async def add_member(
    group_id: str,
    body: MemberAddRequest,
    requesting_agent_id: str = Depends(require_agent),
    db: AsyncSession = Depends(get_db),
):
    """
    Add an agent to a group. Requester must be a member.
    The new member must already be registered as an agent.
    """
    group = await _get_group_or_404(db, group_id)
    await _require_group_member(db, group_id, requesting_agent_id)

    # Verify target agent exists
    await _get_agent_or_404(db, body.agent_id)

    # Idempotent — no error if already a member
    result = await db.execute(
        select(ScopeGroupMember).where(
            and_(
                ScopeGroupMember.group_id == group_id,
                ScopeGroupMember.agent_id == body.agent_id,
            )
        )
    )
    if result.scalar_one_or_none() is None:
        db.add(ScopeGroupMember(group_id=group_id, agent_id=body.agent_id))
        group.updated_at = datetime.now(timezone.utc)
        await db.flush()

    member_ids = await _group_member_ids(db, group_id)
    return _group_to_response(group, member_ids)


@router.delete("/groups/{group_id}/members/{agent_id}", status_code=204)
async def remove_member(
    group_id: str,
    agent_id: str,
    requesting_agent_id: str = Depends(require_agent),
    db: AsyncSession = Depends(get_db),
):
    """
    Remove an agent from a group. Requester must be a member.
    An agent may remove themselves. Removing the last member is not allowed
    (delete the group instead).
    """
    await _get_group_or_404(db, group_id)
    await _require_group_member(db, group_id, requesting_agent_id)

    result = await db.execute(
        select(ScopeGroupMember).where(
            and_(
                ScopeGroupMember.group_id == group_id,
                ScopeGroupMember.agent_id == agent_id,
            )
        )
    )
    member = result.scalar_one_or_none()
    if member is None:
        raise HTTPException(status_code=404, detail="Agent is not a member")

    # Prevent removing last member
    current_members = await _group_member_ids(db, group_id)
    if len(current_members) <= 1:
        raise HTTPException(
            status_code=422,
            detail="Cannot remove the last member. Delete the group instead.",
        )

    await db.delete(member)

    # Update group updated_at
    result2 = await db.execute(
        select(ScopeGroup).where(ScopeGroup.id == group_id)
    )
    group = result2.scalar_one()
    group.updated_at = datetime.now(timezone.utc)
    await db.flush()


@router.delete("/groups/{group_id}", status_code=204)
async def delete_group(
    group_id: str,
    requesting_agent_id: str = Depends(require_agent),
    db: AsyncSession = Depends(get_db),
):
    """
    Delete a group. Requester must be a member.
    Fails if any objects are owned by or scoped to this group —
    reassign or delete those objects first.
    """
    group = await _get_group_or_404(db, group_id)
    await _require_group_member(db, group_id, requesting_agent_id)

    # Check for objects owned by or scoped to this group
    owned = await db.execute(
        select(Object.id).where(Object.owner_group_id == group_id).limit(1)
    )
    if owned.scalar_one_or_none():
        raise HTTPException(
            status_code=422,
            detail="Group owns objects. Reassign or delete them before deleting the group.",
        )

    scoped = await db.execute(
        select(Object.id).where(Object.scope == group_id).limit(1)
    )
    if scoped.scalar_one_or_none():
        raise HTTPException(
            status_code=422,
            detail="Objects are scoped to this group. Change their scope before deleting the group.",
        )

    await db.delete(group)
    await db.flush()
