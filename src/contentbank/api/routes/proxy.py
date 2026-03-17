"""
Sharing proxy and grant management routes.

Grants (grantor-facing):
  POST   /proxy/grants              create a sharing grant
  GET    /proxy/grants/{id}         get grant details (grantor only)
  POST   /proxy/grants/{id}/objects add objects to a grant (grantor only)
  POST   /proxy/grants/{id}/revoke  revoke a grant (grantor only)

Proxy (recipient-facing):
  GET    /proxy/objects/{id}        pull a shared object (grant JWT auth)

Subscriptions:
  POST   /proxy/subscriptions       register push-on-change callback (grant JWT)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Header, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from contentbank.db.database import get_db
from contentbank.db.models import (
    SharingGrant, SharingGrantObject, Object as ObjectRow, BlobAttachment
)
from contentbank.auth.dependencies import require_agent
from contentbank.auth.keys import verify_nonce_signature
from contentbank.sharing.grants import (
    create_grant, revoke_grant, validate_grant_for_object,
    add_objects_to_grant, GrantError
)
from contentbank.core.models import BlobAttachmentModel, ObjectResponse

router = APIRouter(prefix="/proxy", tags=["proxy"])

_bearer = HTTPBearer(auto_error=False)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class GrantCreateRequest(BaseModel):
    grant_key: str              # purpose-specific public key (base64url)
    object_ids: list[str]
    allow_subscribe: bool = False
    expires_at: Optional[datetime] = None


class GrantObjectsAddRequest(BaseModel):
    object_ids: list[str]


class GrantResponse(BaseModel):
    id: str
    grant_key: str
    grantor_id: str
    object_ids: list[str]
    allow_subscribe: bool
    expires_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class SubscriptionRequest(BaseModel):
    object_id: str
    callback_url: str


class SubscriptionResponse(BaseModel):
    subscription_id: str
    object_id: str
    callback_url: str


# In-memory subscription store — in production this belongs in the DB
_subscriptions: dict[str, dict] = {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _grant_to_response(
    db: AsyncSession, grant: SharingGrant
) -> GrantResponse:
    result = await db.execute(
        select(SharingGrantObject.object_id).where(
            SharingGrantObject.grant_id == grant.id
        )
    )
    object_ids = [row[0] for row in result.all()]
    return GrantResponse(
        id=grant.id,
        grant_key=grant.grant_key,
        grantor_id=grant.grantor_id,
        object_ids=object_ids,
        allow_subscribe=grant.allow_subscribe,
        expires_at=grant.expires_at,
        revoked_at=grant.revoked_at,
        created_at=grant.created_at,
        updated_at=grant.updated_at,
    )


async def _require_grant_jwt(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> tuple[str, str]:
    """
    Verify a grant-access JWT and return (grant_key, object_id from path).
    Note: object_id is not available here; caller validates per-request.
    Just returns the grant_key from the JWT sub claim.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer token required",
        )
    from contentbank.auth.tokens import verify_grant_token, TokenError
    try:
        grant_id, grant_key = verify_grant_token(credentials.credentials)
    except TokenError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
        )
    return grant_id, grant_key


def _obj_to_response(obj: ObjectRow) -> ObjectResponse:
    return ObjectResponse(
        id=obj.id,
        type_slug=obj.type_slug,
        owner=obj.owner_agent_id or obj.owner_group_id,
        scope=obj.scope,
        created_at=obj.created_at,
        updated_at=obj.updated_at,
        source_node=obj.source_node,
        content_hash=obj.content_hash,
        blobs=[
            BlobAttachmentModel(
                cid=b.cid,
                mime_type=b.mime_type,
                blob_role=b.blob_role,
                byte_size=b.byte_size,
                content_hash=b.content_hash,
            )
            for b in (obj.blobs or [])
        ],
    )


# ---------------------------------------------------------------------------
# Grant management (grantor-facing, agent JWT auth)
# ---------------------------------------------------------------------------

@router.post("/grants", response_model=GrantResponse, status_code=201)
async def create_sharing_grant(
    body: GrantCreateRequest,
    grantor_id: str = Depends(require_agent),
    db: AsyncSession = Depends(get_db),
):
    """
    Create a sharing grant. The requesting agent becomes the grantor.
    Only objects owned by the grantor may be included.
    """
    try:
        grant = await create_grant(
            db,
            grantor_id=grantor_id,
            grant_key=body.grant_key,
            object_ids=body.object_ids,
            allow_subscribe=body.allow_subscribe,
            expires_at=body.expires_at,
        )
    except GrantError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return await _grant_to_response(db, grant)


@router.get("/grants/{grant_id}", response_model=GrantResponse)
async def get_grant(
    grant_id: str,
    grantor_id: str = Depends(require_agent),
    db: AsyncSession = Depends(get_db),
):
    """Get grant details. Grantor only."""
    result = await db.execute(
        select(SharingGrant).where(SharingGrant.id == grant_id)
    )
    grant = result.scalar_one_or_none()
    if grant is None:
        raise HTTPException(status_code=404, detail="Grant not found")
    if grant.grantor_id != grantor_id:
        raise HTTPException(status_code=403, detail="Access denied")

    return await _grant_to_response(db, grant)


@router.post("/grants/{grant_id}/objects",
             response_model=GrantResponse, status_code=201)
async def add_grant_objects(
    grant_id: str,
    body: GrantObjectsAddRequest,
    grantor_id: str = Depends(require_agent),
    db: AsyncSession = Depends(get_db),
):
    """Add objects to a grant. Grantor only."""
    try:
        grant = await add_objects_to_grant(
            db,
            grant_id=grant_id,
            grantor_id=grantor_id,
            object_ids=body.object_ids,
        )
    except GrantError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return await _grant_to_response(db, grant)


@router.post("/grants/{grant_id}/revoke", response_model=GrantResponse)
async def revoke_sharing_grant(
    grant_id: str,
    grantor_id: str = Depends(require_agent),
    db: AsyncSession = Depends(get_db),
):
    """Revoke a sharing grant. Grantor only. Soft delete — audit trail preserved."""
    try:
        grant = await revoke_grant(
            db, grant_id=grant_id, revoking_agent_id=grantor_id
        )
    except GrantError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return await _grant_to_response(db, grant)


# ---------------------------------------------------------------------------
# Proxy pull (recipient-facing, grant JWT auth)
# ---------------------------------------------------------------------------

@router.get("/objects/{object_id}", response_model=ObjectResponse)
async def proxy_get_object(
    object_id: str,
    grant_credentials: tuple[str, str] = Depends(_require_grant_jwt),
    db: AsyncSession = Depends(get_db),
):
    """
    Pull a shared object.
    Authorization: Bearer {grant JWT signed with purpose-specific key}.
    Returns object metadata only — blobs fetched from IPFS by CID.
    """
    _grant_id, grant_key = grant_credentials

    try:
        await validate_grant_for_object(
            db, grant_key=grant_key, object_id=object_id
        )
    except GrantError as e:
        raise HTTPException(status_code=403, detail=str(e))

    result = await db.execute(
        select(ObjectRow).where(ObjectRow.id == object_id)
    )
    obj = result.scalar_one_or_none()
    if obj is None:
        raise HTTPException(status_code=404, detail="Object not found")

    return _obj_to_response(obj)


# ---------------------------------------------------------------------------
# Subscriptions (recipient-facing, grant JWT auth)
# ---------------------------------------------------------------------------

@router.post("/subscriptions",
             response_model=SubscriptionResponse, status_code=201)
async def create_subscription(
    body: SubscriptionRequest,
    grant_credentials: tuple[str, str] = Depends(_require_grant_jwt),
    db: AsyncSession = Depends(get_db),
):
    """
    Register a callback URL for push-on-change notifications.
    Requires tl:allowSubscribe = true on the grant.
    """
    _grant_id, grant_key = grant_credentials

    try:
        grant = await validate_grant_for_object(
            db, grant_key=grant_key, object_id=body.object_id
        )
    except GrantError as e:
        raise HTTPException(status_code=403, detail=str(e))

    if not grant.allow_subscribe:
        raise HTTPException(
            status_code=403,
            detail="This grant does not allow subscriptions",
        )

    sub_id = str(uuid.uuid4())
    _subscriptions[sub_id] = {
        "grant_id": grant.id,
        "object_id": body.object_id,
        "callback_url": body.callback_url,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    return SubscriptionResponse(
        subscription_id=sub_id,
        object_id=body.object_id,
        callback_url=body.callback_url,
    )


# ---------------------------------------------------------------------------
# Notify subscribers on object change (called from storage layer)
# ---------------------------------------------------------------------------

async def notify_subscribers(object_id: str, payload: dict) -> None:
    """
    Fire-and-forget POST to all registered callbacks for an object.
    Called after a successful write to a granted object.
    """
    import httpx

    subs = [s for s in _subscriptions.values()
            if s["object_id"] == object_id]
    if not subs:
        return

    async with httpx.AsyncClient(timeout=10.0) as client:
        for sub in subs:
            try:
                await client.post(sub["callback_url"], json=payload)
            except Exception:
                pass  # Best-effort delivery; no retry in v0.1
