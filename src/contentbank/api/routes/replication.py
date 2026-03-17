"""
Replication sync endpoint.
Peer nodes pull changes since a given sequence number.
"""

from fastapi import APIRouter, Depends, Query, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from datetime import datetime
from typing import Optional

from contentbank.db.database import get_db

router = APIRouter(prefix="/replication", tags=["replication"])


class SyncEvent(BaseModel):
    node_id: str
    node_seq: int
    object_id: str
    change_type: str  # insert | update | delete
    updated_at: datetime
    object_payload: Optional[dict] = None
    scope_group_dep_node: Optional[str] = None
    scope_group_dep_seq: Optional[int] = None


class SyncResponse(BaseModel):
    events: list[SyncEvent]
    has_more: bool
    next_seq: Optional[int] = None


@router.get("/sync", response_model=SyncResponse)
async def sync(
    since: int = Query(0, description="Return events with node_seq > since"),
    limit: int = Query(500, ge=1, le=500),
    authorization: str = Header(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Pull replication events since a given sequence number.
    Caller must present a valid node JWT signed with their node key.
    """
    # TODO: verify JWT, fetch events from replication.log, return batch
    raise HTTPException(status_code=501, detail="Not implemented")
