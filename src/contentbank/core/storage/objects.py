"""
ContentBank object storage layer.

All writes pass through:
  1. SHACL validation (pySHACL against shapes/)
  2. Scope/ownership compatibility check
  3. Database write + replication log entry

All reads enforce scope access:
  - Individual: owner_agent_id must match requesting_agent_id
  - ScopeGroup: requesting_agent_id must be a member of the group
  - Community: any authenticated agent in the deployment
"""

from __future__ import annotations

import uuid
import hashlib
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, and_, or_, desc, asc
from sqlalchemy.ext.asyncio import AsyncSession
from rdflib import Graph, Namespace, URIRef, Literal, BNode
from rdflib.namespace import RDF, XSD

from contentbank.config import settings
from contentbank.core.validation import validate_object
from contentbank.db.models import (
    Object, BlobAttachment, Agent, ScopeGroup,
    ScopeGroupMember, ReplicationLog
)

TL = Namespace("https://tinylibrary.io/ns#")

SCOPE_INDIVIDUAL = "https://tinylibrary.io/ns#Individual"
SCOPE_COMMUNITY  = "https://tinylibrary.io/ns#Community"


# ---------------------------------------------------------------------------
# Scope access check
# ---------------------------------------------------------------------------

async def check_scope_access(
    db: AsyncSession,
    obj: Object,
    requesting_agent_id: str,
) -> bool:
    """
    Return True if requesting_agent_id may read obj.

    Rules:
      Community  → any agent
      ScopeGroup → agent must be a member
      Individual → agent must be the owner
    """
    scope = obj.scope

    if scope == SCOPE_COMMUNITY:
        return True

    if scope == SCOPE_INDIVIDUAL:
        return obj.owner_agent_id == requesting_agent_id

    # ScopeGroup IRI
    result = await db.execute(
        select(ScopeGroupMember).where(
            and_(
                ScopeGroupMember.group_id == scope,
                ScopeGroupMember.agent_id == requesting_agent_id,
            )
        )
    )
    return result.scalar_one_or_none() is not None


# ---------------------------------------------------------------------------
# Build RDF graph from Object row (for SHACL validation)
# ---------------------------------------------------------------------------

def object_to_rdf(
    obj_id: str,
    type_slug: str,
    owner_id: str,
    scope: str,
    created_at: datetime,
    updated_at: datetime,
    capability_data: dict,
    source_node: Optional[str] = None,
) -> Graph:
    """
    Build a minimal rdflib Graph for a ContentBank object.
    Used to run SHACL validation before writes.
    """
    g = Graph()
    g.bind("tl", TL)

    obj = URIRef(obj_id)
    g.add((obj, RDF.type, TL.Object))
    g.add((obj, TL.id, Literal(obj_id, datatype=XSD.string)))
    g.add((obj, TL.typeSlug, Literal(type_slug, datatype=XSD.string)))

    # Owner — add type declaration so sh:class passes
    owner_ref = URIRef(owner_id)
    if "scope_group" in owner_id:
        g.add((owner_ref, RDF.type, TL.ScopeGroup))
    else:
        g.add((owner_ref, RDF.type, TL.Agent))
        # Minimal Agent fields required by AgentShape
        g.add((owner_ref, TL.id, Literal(owner_id, datatype=XSD.string)))
        g.add((owner_ref, TL.displayName, Literal("_", datatype=XSD.string)))
        g.add((owner_ref, TL.publicKey, Literal("_", datatype=XSD.string)))
        g.add((owner_ref, TL.createdAt,
               Literal(created_at.isoformat(), datatype=XSD.dateTime)))

    g.add((obj, TL.owner, owner_ref))

    # Scope — add type declaration
    if scope in (SCOPE_INDIVIDUAL, SCOPE_COMMUNITY):
        scope_ref = URIRef(scope)
        g.add((scope_ref, RDF.type, TL.Scope))
        order = 3 if scope == SCOPE_INDIVIDUAL else 0
        g.add((scope_ref, TL.scopeOrder, Literal(order, datatype=XSD.integer)))
    else:
        scope_ref = URIRef(scope)
        g.add((scope_ref, RDF.type, TL.ScopeGroup))

    g.add((obj, TL.scope, scope_ref))

    g.add((obj, TL.createdAt,
           Literal(created_at.isoformat(), datatype=XSD.dateTime)))
    g.add((obj, TL.updatedAt,
           Literal(updated_at.isoformat(), datatype=XSD.dateTime)))

    if source_node:
        g.add((obj, TL.sourceNode, Literal(source_node, datatype=XSD.string)))

    return g


def compute_content_hash(
    obj_id: str,
    type_slug: str,
    owner_id: str,
    scope: str,
    capability_data: dict,
) -> str:
    """SHA-256 of canonical object fields for replication verification."""
    import json
    payload = json.dumps({
        "id": obj_id,
        "type_slug": type_slug,
        "owner": owner_id,
        "scope": scope,
        "capability_data": metadata,
    }, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

async def create_object(
    db: AsyncSession,
    *,
    type_slug: str,
    owner_id: str,
    scope: str,
    capability_data: dict,
    blobs: list[dict] | None = None,
    source_node: Optional[str] = None,
    validate: bool = True,
) -> Object:
    """
    Create a new ContentBank object.

    Args:
        type_slug:   e.g. 'calendar_event', 'inventory_item'
        owner_id:    urn:cb:agent:{uuid} or urn:cb:scope_group:{uuid}
        scope:       tl:Individual | tl:Community | urn:cb:scope_group:{uuid}
        metadata:    Capability-specific fields (validated against JSON Schema)
        blobs:       list of {cid, mime_type, blob_role, byte_size?, content_hash?}
        source_node: originating node ID (defaults to settings.node_id)
        validate:    run SHACL validation (disable only for replication ingestion)

    Returns:
        Persisted Object row.

    Raises:
        ValueError: SHACL validation failure with violation messages.
    """
    now = datetime.now(timezone.utc)
    obj_id = f"urn:cb:{type_slug}:{uuid.uuid4()}"
    source = source_node or settings.node_id

    if validate:
        rdf_graph = object_to_rdf(
            obj_id, type_slug, owner_id, scope, now, now, metadata, source
        )
        valid, violations = validate_object(rdf_graph, str(settings.shapes_dir))
        if not valid:
            raise ValueError(f"SHACL validation failed:\n" + "\n".join(violations))

    content_hash = compute_content_hash(obj_id, type_slug, owner_id, scope, metadata)

    # Determine owner columns
    owner_agent_id = owner_id if "scope_group" not in owner_id else None
    owner_group_id = owner_id if "scope_group" in owner_id else None

    obj = Object(
        id=obj_id,
        type_slug=type_slug,
        owner_agent_id=owner_agent_id,
        owner_group_id=owner_group_id,
        scope=scope,
        created_at=now,
        updated_at=now,
        source_node=source,
        content_hash=content_hash,
        capability_data=capability_data,
    )
    db.add(obj)

    # Blob attachments
    for blob_data in (blobs or []):
        blob = BlobAttachment(
            id=f"urn:cb:blob:{uuid.uuid4()}",
            object_id=obj_id,
            cid=blob_data["cid"],
            mime_type=blob_data["mime_type"],
            blob_role=blob_data["blob_role"],
            byte_size=blob_data.get("byte_size"),
            content_hash=blob_data.get("content_hash"),
        )
        db.add(blob)

    # Replication log entry
    await _log_change(db, obj_id, "insert", now)

    await db.flush()
    return obj


async def update_object(
    db: AsyncSession,
    *,
    obj_id: str,
    requesting_agent_id: str,
    metadata: dict | None = None,
    scope: str | None = None,
    blobs_add: list[dict] | None = None,
    blobs_remove: list[str] | None = None,
    validate: bool = True,
) -> Object:
    """
    Update a ContentBank object (PATCH semantics — only provided fields change).
    Requester must be the owner.
    """
    result = await db.execute(select(Object).where(Object.id == obj_id))
    obj = result.scalar_one_or_none()
    if obj is None:
        raise KeyError(f"Object not found: {obj_id}")

    # Ownership check — only owner may update
    if obj.owner_agent_id != requesting_agent_id:
        raise PermissionError(f"Agent {requesting_agent_id} is not the owner of {obj_id}")

    now = datetime.now(timezone.utc)

    if metadata is not None:
        obj.capability_data = {**obj.capability_data, **metadata}
    if scope is not None:
        obj.scope = scope

    obj.updated_at = now
    obj.content_hash = compute_content_hash(
        obj.id, obj.type_slug,
        obj.owner_agent_id or obj.owner_group_id,
        obj.scope, obj.capability_data
    )

    if validate:
        owner_id = obj.owner_agent_id or obj.owner_group_id
        rdf_graph = object_to_rdf(
            obj.id, obj.type_slug, owner_id, obj.scope,
            obj.created_at, now, obj.capability_data, obj.source_node
        )
        valid, violations = validate_object(rdf_graph, str(settings.shapes_dir))
        if not valid:
            raise ValueError(f"SHACL validation failed:\n" + "\n".join(violations))

    # Add new blobs
    for blob_data in (blobs_add or []):
        blob = BlobAttachment(
            id=f"urn:cb:blob:{uuid.uuid4()}",
            object_id=obj_id,
            cid=blob_data["cid"],
            mime_type=blob_data["mime_type"],
            blob_role=blob_data["blob_role"],
            byte_size=blob_data.get("byte_size"),
            content_hash=blob_data.get("content_hash"),
        )
        db.add(blob)

    # Remove blobs by ID
    for blob_id in (blobs_remove or []):
        result = await db.execute(
            select(BlobAttachment).where(
                and_(BlobAttachment.id == blob_id,
                     BlobAttachment.object_id == obj_id)
            )
        )
        blob = result.scalar_one_or_none()
        if blob:
            await db.delete(blob)

    await _log_change(db, obj_id, "update", now)
    await db.flush()
    return obj


async def delete_object(
    db: AsyncSession,
    *,
    obj_id: str,
    requesting_agent_id: str,
) -> None:
    """Delete an object. Requester must be the owner."""
    result = await db.execute(select(Object).where(Object.id == obj_id))
    obj = result.scalar_one_or_none()
    if obj is None:
        raise KeyError(f"Object not found: {obj_id}")
    if obj.owner_agent_id != requesting_agent_id:
        raise PermissionError(f"Agent {requesting_agent_id} is not the owner of {obj_id}")

    await db.delete(obj)
    await _log_change(db, obj_id, "delete", datetime.now(timezone.utc))
    await db.flush()


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

async def get_object(
    db: AsyncSession,
    *,
    obj_id: str,
    requesting_agent_id: str,
) -> Object:
    """
    Fetch a single object by ID with scope access enforcement.
    Raises KeyError if not found, PermissionError if access denied.
    """
    result = await db.execute(
        select(Object).where(Object.id == obj_id)
    )
    obj = result.scalar_one_or_none()
    if obj is None:
        raise KeyError(f"Object not found: {obj_id}")

    if not await check_scope_access(db, obj, requesting_agent_id):
        raise PermissionError(f"Access denied to {obj_id}")

    return obj


async def list_objects(
    db: AsyncSession,
    *,
    requesting_agent_id: str,
    type_slug: str | None = None,
    owner: str | None = None,
    scope: str | None = None,
    sort: str = "-updated_at",
    cursor: str | None = None,
    limit: int = 50,
) -> tuple[list[Object], str | None]:
    """
    List objects visible to requesting_agent_id.

    Scope filtering logic:
      Returns objects where the agent is allowed to read:
        - scope == Community
        - scope == Individual AND owner_agent_id == requesting_agent_id
        - scope == a ScopeGroup the agent is a member of

    Returns (objects, next_cursor).
    """
    # Build the scope visibility filter
    # Get groups the agent belongs to
    groups_result = await db.execute(
        select(ScopeGroupMember.group_id).where(
            ScopeGroupMember.agent_id == requesting_agent_id
        )
    )
    group_ids = [row[0] for row in groups_result.all()]

    scope_filter = or_(
        Object.scope == SCOPE_COMMUNITY,
        and_(Object.scope == SCOPE_INDIVIDUAL,
             Object.owner_agent_id == requesting_agent_id),
        Object.scope.in_(group_ids) if group_ids else False,
    )

    conditions = [scope_filter]

    if type_slug:
        conditions.append(Object.type_slug == type_slug)
    if owner:
        conditions.append(
            or_(Object.owner_agent_id == owner,
                Object.owner_group_id == owner)
        )
    if scope:
        conditions.append(Object.scope == scope)

    # Cursor-based pagination on updated_at + id
    if cursor:
        import base64, json
        try:
            cursor_data = json.loads(base64.b64decode(cursor).decode())
            cursor_updated_at = datetime.fromisoformat(cursor_data["updated_at"])
            cursor_id = cursor_data["id"]
            conditions.append(
                or_(
                    Object.updated_at < cursor_updated_at,
                    and_(Object.updated_at == cursor_updated_at,
                         Object.id < cursor_id)
                )
            )
        except Exception:
            pass  # Invalid cursor — ignore, return from beginning

    # Sort
    sort_col = Object.updated_at
    if sort.lstrip("-") == "created_at":
        sort_col = Object.created_at
    order = desc(sort_col) if not sort.startswith("-") is False else desc(sort_col)

    query = (
        select(Object)
        .where(and_(*conditions))
        .order_by(order, desc(Object.id))
        .limit(limit + 1)
    )

    result = await db.execute(query)
    rows = result.scalars().all()

    has_more = len(rows) > limit
    objects = list(rows[:limit])

    next_cursor = None
    if has_more and objects:
        import base64, json
        last = objects[-1]
        cursor_data = {"updated_at": last.updated_at.isoformat(), "id": last.id}
        next_cursor = base64.b64encode(
            json.dumps(cursor_data).encode()
        ).decode()

    return objects, next_cursor


# ---------------------------------------------------------------------------
# Replication log helper
# ---------------------------------------------------------------------------

async def _log_change(
    db: AsyncSession,
    object_id: str,
    change_type: str,
    updated_at: datetime,
    scope_group_dep_node: str | None = None,
    scope_group_dep_seq: int | None = None,
) -> None:
    """Append an entry to the replication log."""
    log_entry = ReplicationLog(
        node_id=settings.node_id,
        node_seq=0,  # Assigned by DB autoincrement on seq; node_seq set post-flush
        object_id=object_id,
        change_type=change_type,
        updated_at=updated_at,
        scope_group_dep_node=scope_group_dep_node,
        scope_group_dep_seq=scope_group_dep_seq,
    )
    db.add(log_entry)
