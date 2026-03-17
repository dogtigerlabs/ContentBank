"""
Generic object CRUD routes.
Capability-specific routes (calendar, inventory) extend these patterns.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from contentbank.db.database import get_db
from contentbank.core.models import ObjectResponse, Page

router = APIRouter(prefix="/objects", tags=["objects"])


@router.get("/{object_id}", response_model=ObjectResponse)
async def get_object(
    object_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Retrieve a ContentBank object by ID.
    Access enforced by owner/scope rules.
    """
    # TODO: implement storage lookup + scope access check
    raise HTTPException(status_code=501, detail="Not implemented")


@router.get("/", response_model=Page)
async def list_objects(
    type_slug: str | None = Query(None, description="Filter by type slug"),
    owner: str | None = Query(None, description="Filter by owner IRI"),
    scope: str | None = Query(None, description="Filter by scope IRI"),
    cursor: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    sort: str = Query("-updated_at"),
    db: AsyncSession = Depends(get_db),
):
    """List ContentBank objects with optional filters."""
    # TODO: implement
    raise HTTPException(status_code=501, detail="Not implemented")


@router.delete("/{object_id}", status_code=204)
async def delete_object(
    object_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Delete a ContentBank object. Requester must be owner."""
    # TODO: implement
    raise HTTPException(status_code=501, detail="Not implemented")
