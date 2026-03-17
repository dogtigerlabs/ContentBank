"""
Sharing proxy endpoint.
Recipient nodes pull objects they have been granted access to.
"""

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from contentbank.db.database import get_db
from contentbank.core.models import ObjectResponse

router = APIRouter(prefix="/proxy", tags=["proxy"])


@router.get("/objects/{object_id}", response_model=ObjectResponse)
async def proxy_get_object(
    object_id: str,
    authorization: str = Header(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Pull a shared object.
    Authorization: Bearer JWT signed with purpose-specific grant key.
    Validates: JWT signature against tl:grantKey, object in tl:grantedObject,
    grant not revoked or expired.
    Returns object metadata only — blobs fetched from IPFS separately by CID.
    """
    # TODO: verify grant JWT, check grantedObjects, return object
    raise HTTPException(status_code=501, detail="Not implemented")


@router.post("/subscriptions", status_code=201)
async def create_subscription(
    object_id: str,
    callback_url: str,
    authorization: str = Header(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Register a callback for push-on-change notifications for a granted object.
    Requires tl:allowSubscribe = true on the SharingGrant.
    """
    # TODO: verify grant, register subscription
    raise HTTPException(status_code=501, detail="Not implemented")
