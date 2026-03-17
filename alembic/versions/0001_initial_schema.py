"""Initial ContentBank schema

Revision ID: 0001
Revises:
Create Date: 2026-03-16
"""

from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create replication schema
    op.execute("CREATE SCHEMA IF NOT EXISTS replication")

    # Agents
    op.create_table(
        "cb_agents",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("display_name", sa.String, nullable=False),
        sa.Column("public_key", sa.String, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    # Scope Groups
    op.create_table(
        "cb_scope_groups",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("group_type", sa.Enum("family", "group",
                  name="group_type_enum"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "cb_scope_group_members",
        sa.Column("group_id", sa.String,
                  sa.ForeignKey("cb_scope_groups.id", ondelete="CASCADE"),
                  primary_key=True),
        sa.Column("agent_id", sa.String,
                  sa.ForeignKey("cb_agents.id", ondelete="CASCADE"),
                  primary_key=True),
    )

    # Objects
    op.create_table(
        "cb_objects",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("type_slug", sa.String, nullable=False),
        sa.Column("owner_agent_id", sa.String,
                  sa.ForeignKey("cb_agents.id", ondelete="RESTRICT"),
                  nullable=True),
        sa.Column("owner_group_id", sa.String,
                  sa.ForeignKey("cb_scope_groups.id", ondelete="RESTRICT"),
                  nullable=True),
        sa.Column("scope", sa.String, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_node", sa.String, nullable=True),
        sa.Column("content_hash", sa.String, nullable=True),
        sa.Column("capability_data", sa.JSON, nullable=False,
                  server_default="{}"),
        sa.Column("rdf_turtle", sa.Text, nullable=True),
    )
    op.create_index("ix_cb_objects_type_slug", "cb_objects", ["type_slug"])
    op.create_index("ix_cb_objects_owner_agent", "cb_objects", ["owner_agent_id"])
    op.create_index("ix_cb_objects_owner_group", "cb_objects", ["owner_group_id"])
    op.create_index("ix_cb_objects_scope", "cb_objects", ["scope"])
    op.create_index("ix_cb_objects_updated_at", "cb_objects", ["updated_at"])
    op.create_index("ix_cb_objects_created_at", "cb_objects", ["created_at"])

    # Blobs
    op.create_table(
        "cb_blobs",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("object_id", sa.String,
                  sa.ForeignKey("cb_objects.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("cid", sa.String, nullable=False),
        sa.Column("mime_type", sa.String, nullable=False),
        sa.Column("blob_role", sa.String, nullable=False),
        sa.Column("byte_size", sa.BigInteger, nullable=True),
        sa.Column("content_hash", sa.String, nullable=True),
    )
    op.create_index("ix_cb_blobs_object_id", "cb_blobs", ["object_id"])

    # Sharing Grants
    op.create_table(
        "cb_sharing_grants",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("grant_key", sa.String, nullable=False, unique=True),
        sa.Column("grantor_id", sa.String,
                  sa.ForeignKey("cb_agents.id", ondelete="RESTRICT"),
                  nullable=False),
        sa.Column("allow_subscribe", sa.Boolean, nullable=False,
                  server_default="false"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by_id", sa.String,
                  sa.ForeignKey("cb_agents.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "cb_sharing_grant_objects",
        sa.Column("grant_id", sa.String,
                  sa.ForeignKey("cb_sharing_grants.id", ondelete="CASCADE"),
                  primary_key=True),
        sa.Column("object_id", sa.String,
                  sa.ForeignKey("cb_objects.id", ondelete="CASCADE"),
                  primary_key=True),
    )

    # Replication Peers
    op.create_table(
        "cb_replication_peers",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("peer_node_id", sa.String, nullable=False, unique=True),
        sa.Column("endpoint", sa.String, nullable=False),
        sa.Column("transport_type", sa.Enum("https", "mesh",
                  name="transport_type_enum"), nullable=False),
        sa.Column("sync_interval_seconds", sa.Integer, nullable=False,
                  server_default="60"),
        sa.Column("sync_enabled", sa.Boolean, nullable=False,
                  server_default="true"),
        sa.Column("peer_public_key", sa.String, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    # Replication log (replication schema)
    op.create_table(
        "replication_log",
        sa.Column("seq", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("node_id", sa.String, nullable=False),
        sa.Column("node_seq", sa.BigInteger, nullable=False),
        sa.Column("object_id", sa.String, nullable=False),
        sa.Column("change_type", sa.Enum("insert", "update", "delete",
                  name="change_type_enum"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scope_group_dep_node", sa.String, nullable=True),
        sa.Column("scope_group_dep_seq", sa.BigInteger, nullable=True),
        schema="replication",
    )
    op.create_index("ix_repl_log_node_seq", "replication_log",
                    ["node_id", "node_seq"], schema="replication")
    op.create_index("ix_repl_log_object", "replication_log",
                    ["object_id"], schema="replication")

    # Replication peer state
    op.create_table(
        "peer_state",
        sa.Column("peer_node_id", sa.String, primary_key=True),
        sa.Column("last_seen_seq", sa.BigInteger, nullable=False,
                  server_default="0"),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        schema="replication",
    )


def downgrade() -> None:
    op.drop_table("peer_state", schema="replication")
    op.drop_index("ix_repl_log_object", "replication_log", schema="replication")
    op.drop_index("ix_repl_log_node_seq", "replication_log", schema="replication")
    op.drop_table("replication_log", schema="replication")
    op.execute("DROP SCHEMA IF EXISTS replication CASCADE")

    op.drop_table("cb_replication_peers")
    op.drop_table("cb_sharing_grant_objects")
    op.drop_table("cb_sharing_grants")
    op.drop_index("ix_cb_blobs_object_id", "cb_blobs")
    op.drop_table("cb_blobs")
    op.drop_index("ix_cb_objects_created_at", "cb_objects")
    op.drop_index("ix_cb_objects_updated_at", "cb_objects")
    op.drop_index("ix_cb_objects_scope", "cb_objects")
    op.drop_index("ix_cb_objects_owner_group", "cb_objects")
    op.drop_index("ix_cb_objects_owner_agent", "cb_objects")
    op.drop_index("ix_cb_objects_type_slug", "cb_objects")
    op.drop_table("cb_objects")
    op.drop_table("cb_scope_group_members")
    op.drop_table("cb_scope_groups")
    op.drop_table("cb_agents")
    op.execute("DROP TYPE IF EXISTS group_type_enum")
    op.execute("DROP TYPE IF EXISTS transport_type_enum")
    op.execute("DROP TYPE IF EXISTS change_type_enum")
