"""
SQLAlchemy ORM models for ContentBank.

These map directly to the SHACL-defined data model:
  - cb_agents       → tl:Agent
  - cb_scope_groups → tl:ScopeGroup
  - cb_scope_group_members → tl:ScopeGroup tl:member
  - cb_objects      → tl:Object (all Capability types)
  - cb_blobs        → tl:BlobAttachment
  - cb_sharing_grants → tl:SharingGrant
  - cb_replication_peers → tl:ReplicationPeer
  - replication_log → change log (application layer, not content)
  - replication_peer_state → per-peer sync state
"""

from datetime import datetime
from sqlalchemy import (
    Column, String, Boolean, Integer, BigInteger, Numeric,
    DateTime, ForeignKey, Text, Index, UniqueConstraint,
    JSON, Enum as SAEnum
)
from sqlalchemy.orm import relationship
from contentbank.db.database import Base


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------

class Agent(Base):
    __tablename__ = "cb_agents"

    id           = Column(String, primary_key=True)  # urn:cb:agent:{uuid}
    display_name = Column(String, nullable=False)
    public_key   = Column(String, nullable=False)
    created_at   = Column(DateTime(timezone=True), nullable=False)

    # Relationships
    owned_objects = relationship("Object", back_populates="owner_agent",
                                 foreign_keys="Object.owner_agent_id")
    group_memberships = relationship("ScopeGroupMember", back_populates="agent")


# ---------------------------------------------------------------------------
# Scope Groups
# ---------------------------------------------------------------------------

class ScopeGroup(Base):
    __tablename__ = "cb_scope_groups"

    id         = Column(String, primary_key=True)  # urn:cb:scope_group:{uuid}
    name       = Column(String, nullable=False)
    group_type = Column(SAEnum("family", "group", name="group_type_enum"),
                        nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)

    members = relationship("ScopeGroupMember", back_populates="group",
                           cascade="all, delete-orphan")
    owned_objects = relationship("Object", back_populates="owner_group",
                                 foreign_keys="Object.owner_group_id")


class ScopeGroupMember(Base):
    __tablename__ = "cb_scope_group_members"

    group_id = Column(String, ForeignKey("cb_scope_groups.id",
                      ondelete="CASCADE"), primary_key=True)
    agent_id = Column(String, ForeignKey("cb_agents.id",
                      ondelete="CASCADE"), primary_key=True)

    group = relationship("ScopeGroup", back_populates="members")
    agent = relationship("Agent", back_populates="group_memberships")


# ---------------------------------------------------------------------------
# Objects (all Capability types share this table)
# ---------------------------------------------------------------------------

class Object(Base):
    __tablename__ = "cb_objects"

    # --- Identity ---
    id        = Column(String, primary_key=True)   # urn:cb:{type_slug}:{uuid}
    type_slug = Column(String, nullable=False, index=True)

    # --- Ownership (one of owner_agent_id or owner_group_id, not both) ---
    owner_agent_id = Column(String, ForeignKey("cb_agents.id",
                            ondelete="RESTRICT"), nullable=True, index=True)
    owner_group_id = Column(String, ForeignKey("cb_scope_groups.id",
                            ondelete="RESTRICT"), nullable=True, index=True)

    # --- Scope ---
    # 'individual' | 'community' | urn:cb:scope_group:{uuid}
    scope = Column(String, nullable=False, index=True)

    # --- Timestamps ---
    created_at = Column(DateTime(timezone=True), nullable=False, index=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, index=True)

    # --- Provenance ---
    source_node  = Column(String, nullable=True)
    content_hash = Column(String, nullable=True)

    # --- Capability-specific metadata (JSON) ---
    # Stores all Capability-specific fields as a JSON document.
    # The structure is validated against generated JSON Schema before write.
    capability_data = Column(JSON, nullable=False, default=dict)

    # --- RDF serialization (for SHACL validation and AGE graph) ---
    # Canonical Turtle serialization of this object's RDF graph.
    # Used for replication payloads and AGE ingestion.
    rdf_turtle = Column(Text, nullable=True)

    # --- Relationships ---
    owner_agent = relationship("Agent", back_populates="owned_objects",
                               foreign_keys=[owner_agent_id])
    owner_group = relationship("ScopeGroup", back_populates="owned_objects",
                               foreign_keys=[owner_group_id])
    blobs = relationship("BlobAttachment", back_populates="object",
                         cascade="all, delete-orphan")

    __table_args__ = (
        # Exactly one of owner_agent_id or owner_group_id must be set
        # (enforced at application layer, documented here)
        Index("ix_cb_objects_owner_agent_type", "owner_agent_id", "type_slug"),
        Index("ix_cb_objects_owner_group_type", "owner_group_id", "type_slug"),
        Index("ix_cb_objects_scope_type", "scope", "type_slug"),
        Index("ix_cb_objects_updated", "updated_at"),
    )


# ---------------------------------------------------------------------------
# Blob Attachments
# ---------------------------------------------------------------------------

class BlobAttachment(Base):
    __tablename__ = "cb_blobs"

    id          = Column(String, primary_key=True)  # urn:cb:blob:{uuid}
    object_id   = Column(String, ForeignKey("cb_objects.id",
                         ondelete="CASCADE"), nullable=False, index=True)
    cid         = Column(String, nullable=False)   # IPFS CIDv1
    mime_type   = Column(String, nullable=False)
    blob_role   = Column(String, nullable=False)   # primary|thumbnail|raw|...
    byte_size   = Column(BigInteger, nullable=True)
    content_hash = Column(String, nullable=True)   # SHA-256 hex

    object = relationship("Object", back_populates="blobs")

    __table_args__ = (
        Index("ix_cb_blobs_object_role", "object_id", "blob_role"),
    )


# ---------------------------------------------------------------------------
# Sharing Grants
# ---------------------------------------------------------------------------

class SharingGrant(Base):
    __tablename__ = "cb_sharing_grants"

    id             = Column(String, primary_key=True)  # urn:cb:sharing_grant:{uuid}
    grant_key      = Column(String, nullable=False, unique=True)  # purpose-specific pubkey
    grantor_id     = Column(String, ForeignKey("cb_agents.id",
                            ondelete="RESTRICT"), nullable=False)
    allow_subscribe = Column(Boolean, nullable=False, default=False)
    expires_at     = Column(DateTime(timezone=True), nullable=True)
    revoked_at     = Column(DateTime(timezone=True), nullable=True)
    revoked_by_id  = Column(String, ForeignKey("cb_agents.id",
                            ondelete="SET NULL"), nullable=True)
    created_at     = Column(DateTime(timezone=True), nullable=False)
    updated_at     = Column(DateTime(timezone=True), nullable=False)

    granted_objects = relationship("SharingGrantObject",
                                   cascade="all, delete-orphan")


class SharingGrantObject(Base):
    __tablename__ = "cb_sharing_grant_objects"

    grant_id  = Column(String, ForeignKey("cb_sharing_grants.id",
                       ondelete="CASCADE"), primary_key=True)
    object_id = Column(String, ForeignKey("cb_objects.id",
                       ondelete="CASCADE"), primary_key=True)


# ---------------------------------------------------------------------------
# Replication Peers (content object — replicates across mesh)
# ---------------------------------------------------------------------------

class ReplicationPeer(Base):
    __tablename__ = "cb_replication_peers"

    id                   = Column(String, primary_key=True)
    peer_node_id         = Column(String, nullable=False, unique=True)
    endpoint             = Column(String, nullable=False)
    transport_type       = Column(SAEnum("https", "mesh",
                                  name="transport_type_enum"), nullable=False)
    sync_interval_seconds = Column(Integer, nullable=False, default=60)
    sync_enabled         = Column(Boolean, nullable=False, default=True)
    peer_public_key      = Column(String, nullable=False)
    created_at           = Column(DateTime(timezone=True), nullable=False)
    updated_at           = Column(DateTime(timezone=True), nullable=False)


# ---------------------------------------------------------------------------
# Replication Log (application layer — not content)
# ---------------------------------------------------------------------------

class ReplicationLog(Base):
    __tablename__ = "replication_log"
    __table_args__ = {"schema": "replication"}

    seq                   = Column(BigInteger, primary_key=True, autoincrement=True)
    node_id               = Column(String, nullable=False)
    node_seq              = Column(BigInteger, nullable=False)
    object_id             = Column(String, nullable=False, index=True)
    change_type           = Column(SAEnum("insert", "update", "delete",
                                   name="change_type_enum"), nullable=False)
    updated_at            = Column(DateTime(timezone=True), nullable=False)
    scope_group_dep_node  = Column(String, nullable=True)
    scope_group_dep_seq   = Column(BigInteger, nullable=True)

    __table_args__ = (
        Index("ix_repl_log_node_seq", "node_id", "node_seq"),
        Index("ix_repl_log_object", "object_id"),
        {"schema": "replication"},
    )


# ---------------------------------------------------------------------------
# Replication Peer State (application layer)
# ---------------------------------------------------------------------------

class ReplicationPeerState(Base):
    __tablename__ = "peer_state"
    __table_args__ = {"schema": "replication"}

    peer_node_id  = Column(String, primary_key=True)
    last_seen_seq = Column(BigInteger, nullable=False, default=0)
    last_sync_at  = Column(DateTime(timezone=True), nullable=True)
