"""
Sharing grant management.

Create, revoke, and validate SharingGrants.
Grants authorize a recipient (identified by a purpose-specific key pair)
to pull specific objects from this ContentBank via the proxy endpoint.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from contentbank.db.models import (
    SharingGrant, SharingGrantObject, Object
)


class GrantError(Exception):
    pass


async def create_grant(
    db: AsyncSession,
    *,
    grantor_id: str,
    grant_key: str,           # purpose-specific public key (base64url)
    object_ids: list[str],
    allow_subscribe: bool = False,
    expires_at: Optional[datetime] = None,
) -> SharingGrant:
    """
    Create a new SharingGrant.

    Args:
        grantor_id:      urn:cb:agent:{uuid} of the granting agent
        grant_key:       base64url public key of the purpose-specific key pair
        object_ids:      list of object IRIs to grant access to
        allow_subscribe: whether recipient may subscribe to push notifications
        expires_at:      optional expiry datetime

    Returns:
        The persisted SharingGrant row.
    """
    # Verify all objects exist and are owned by the grantor
    for obj_id in object_ids:
        result = await db.execute(
            select(Object).where(Object.id == obj_id)
        )
        obj = result.scalar_one_or_none()
        if obj is None:
            raise GrantError(f"Object not found: {obj_id}")
        if obj.owner_agent_id != grantor_id:
            raise GrantError(
                f"Object {obj_id} is not owned by agent {grantor_id}"
            )

    now = datetime.now(timezone.utc)
    grant_id = f"urn:cb:sharing_grant:{uuid.uuid4()}"

    grant = SharingGrant(
        id=grant_id,
        grant_key=grant_key,
        grantor_id=grantor_id,
        allow_subscribe=allow_subscribe,
        expires_at=expires_at,
        created_at=now,
        updated_at=now,
    )
    db.add(grant)

    for obj_id in object_ids:
        db.add(SharingGrantObject(grant_id=grant_id, object_id=obj_id))

    await db.flush()
    return grant


async def revoke_grant(
    db: AsyncSession,
    *,
    grant_id: str,
    revoking_agent_id: str,
) -> SharingGrant:
    """
    Revoke a SharingGrant. Only the grantor may revoke.
    Sets revokedAt — soft delete, preserves audit trail.
    """
    result = await db.execute(
        select(SharingGrant).where(SharingGrant.id == grant_id)
    )
    grant = result.scalar_one_or_none()
    if grant is None:
        raise GrantError(f"Grant not found: {grant_id}")
    if grant.grantor_id != revoking_agent_id:
        raise GrantError("Only the grantor may revoke this grant")
    if grant.revoked_at is not None:
        raise GrantError("Grant is already revoked")

    grant.revoked_at = datetime.now(timezone.utc)
    grant.revoked_by_id = revoking_agent_id
    grant.updated_at = datetime.now(timezone.utc)
    await db.flush()
    return grant


async def validate_grant_for_object(
    db: AsyncSession,
    *,
    grant_key: str,
    object_id: str,
) -> SharingGrant:
    """
    Verify a grant key is authorized to access an object.

    Checks:
      1. Grant exists with this key
      2. Not revoked
      3. Not expired
      4. Object is in the grant's allowed list

    Returns the grant on success.
    Raises GrantError on any failure.
    """
    result = await db.execute(
        select(SharingGrant).where(SharingGrant.grant_key == grant_key)
    )
    grant = result.scalar_one_or_none()

    if grant is None:
        raise GrantError("Invalid grant key")

    if grant.revoked_at is not None:
        raise GrantError("Grant has been revoked")

    now = datetime.now(timezone.utc)
    if grant.expires_at and grant.expires_at < now:
        raise GrantError("Grant has expired")

    # Check object is in granted list
    obj_result = await db.execute(
        select(SharingGrantObject).where(
            and_(
                SharingGrantObject.grant_id == grant.id,
                SharingGrantObject.object_id == object_id,
            )
        )
    )
    if obj_result.scalar_one_or_none() is None:
        raise GrantError(f"Object {object_id} is not in this grant")

    return grant


async def add_objects_to_grant(
    db: AsyncSession,
    *,
    grant_id: str,
    grantor_id: str,
    object_ids: list[str],
) -> SharingGrant:
    """Add objects to an existing grant. Grantor only."""
    result = await db.execute(
        select(SharingGrant).where(SharingGrant.id == grant_id)
    )
    grant = result.scalar_one_or_none()
    if grant is None:
        raise GrantError(f"Grant not found: {grant_id}")
    if grant.grantor_id != grantor_id:
        raise GrantError("Only the grantor may modify this grant")
    if grant.revoked_at is not None:
        raise GrantError("Cannot modify a revoked grant")

    for obj_id in object_ids:
        obj_result = await db.execute(
            select(Object).where(Object.id == obj_id)
        )
        obj = obj_result.scalar_one_or_none()
        if obj is None:
            raise GrantError(f"Object not found: {obj_id}")
        if obj.owner_agent_id != grantor_id:
            raise GrantError(f"Object {obj_id} not owned by grantor")

        # Idempotent
        existing = await db.execute(
            select(SharingGrantObject).where(
                and_(
                    SharingGrantObject.grant_id == grant_id,
                    SharingGrantObject.object_id == obj_id,
                )
            )
        )
        if existing.scalar_one_or_none() is None:
            db.add(SharingGrantObject(grant_id=grant_id, object_id=obj_id))

    grant.updated_at = datetime.now(timezone.utc)
    await db.flush()
    return grant
