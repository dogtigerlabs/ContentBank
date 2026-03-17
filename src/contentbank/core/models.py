"""
Core Pydantic models for ContentBank API layer.

These are the API-facing models. They are derived from (and must stay
consistent with) the SHACL shapes — the shapes are SoT, these are the
Python runtime representations for FastAPI request/response handling.
"""

from __future__ import annotations
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, field_validator
import re
import uuid


# ---------------------------------------------------------------------------
# ID helpers
# ---------------------------------------------------------------------------

ID_PATTERN = re.compile(r"^urn:cb:[a-z][a-z0-9_-]+:[0-9a-f-]{36}$")


def make_id(type_slug: str) -> str:
    return f"urn:cb:{type_slug}:{uuid.uuid4()}"


def validate_id(v: str) -> str:
    if not ID_PATTERN.match(v):
        raise ValueError(f"Invalid ContentBank ID format: {v}")
    return v


# ---------------------------------------------------------------------------
# Scope constants
# ---------------------------------------------------------------------------

SCOPE_INDIVIDUAL = "https://tinylibrary.io/ns#Individual"
SCOPE_COMMUNITY  = "https://tinylibrary.io/ns#Community"


# ---------------------------------------------------------------------------
# BlobAttachment
# ---------------------------------------------------------------------------

class BlobAttachmentModel(BaseModel):
    cid: str
    mime_type: str
    blob_role: str  # primary | thumbnail | raw | transcript | preview
    byte_size: Optional[int] = None
    content_hash: Optional[str] = None


# ---------------------------------------------------------------------------
# Base Object (maps to tl:Object)
# ---------------------------------------------------------------------------

class ObjectBase(BaseModel):
    """Shared fields for all ContentBank object create requests."""
    owner: str      # urn:cb:agent:{uuid} or urn:cb:scope_group:{uuid}
    scope: str      # tl:Individual | tl:Community | urn:cb:scope_group:{uuid}
    blobs: list[BlobAttachmentModel] = []


class ObjectResponse(BaseModel):
    """Shared read fields present on all ContentBank object responses."""
    id: str
    type_slug: str
    owner: str
    scope: str
    created_at: datetime
    updated_at: datetime
    source_node: Optional[str] = None
    content_hash: Optional[str] = None
    blobs: list[BlobAttachmentModel] = []


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class AgentCreate(BaseModel):
    display_name: str
    public_key: str  # ECDH public key, base64url


class AgentResponse(BaseModel):
    id: str
    display_name: str
    public_key: str
    created_at: datetime


# ---------------------------------------------------------------------------
# ScopeGroup
# ---------------------------------------------------------------------------

class ScopeGroupCreate(BaseModel):
    name: str
    group_type: str  # family | group
    member_ids: list[str]  # list of urn:cb:agent:{uuid}


class ScopeGroupResponse(BaseModel):
    id: str
    name: str
    group_type: str
    member_ids: list[str]
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

class Page(BaseModel):
    items: list
    total: Optional[int] = None
    cursor: Optional[str] = None
    has_more: bool = False
