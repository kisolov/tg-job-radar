"""initial schema

Revision ID: 0001
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

TS = sa.DateTime(timezone=True)

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "settings_overrides",
        sa.Column("key", sa.Text, primary_key=True),
        sa.Column("value", sa.Text, nullable=False),
    )
    op.create_table(
        "accounts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("phone", sa.Text, nullable=False, unique=True),
        sa.Column("api_id", sa.Integer, nullable=False),
        sa.Column("api_hash_enc", sa.Text, nullable=False),
        sa.Column("session_enc", sa.Text, nullable=False),
        sa.Column("device_profile", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("status_until", TS),
        sa.Column("last_error", sa.Text),
        sa.Column("membership_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("join_state", JSONB, nullable=False),
        sa.Column("resolve_state", JSONB, nullable=False),
        sa.Column("version", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", TS, nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "sources",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("username", sa.Text, unique=True),
        sa.Column("invite_hash", sa.Text, unique=True),
        sa.Column("peer_id", sa.BigInteger, unique=True),
        sa.Column("access_hash", sa.BigInteger),
        sa.Column("kind", sa.Text),
        sa.Column("title", sa.Text),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("assigned_account_id", UUID(as_uuid=True), sa.ForeignKey("accounts.id", ondelete="SET NULL")),
        sa.Column("joined", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("last_message_id", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("last_polled_at", TS),
        sa.Column("found_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("relay_score", sa.Float, nullable=False, server_default="0"),
        sa.Column("added_by", sa.Text, nullable=False),
        sa.Column("priority", sa.Integer, nullable=False, server_default="5"),
        sa.Column("version", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", TS, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_sources_resolve_queue", "sources", ["status", sa.text("priority DESC"), "id"])
    op.create_index("ix_sources_assigned", "sources", ["assigned_account_id", "kind"])
    op.create_table(
        "messages",
        sa.Column("source_id", sa.BigInteger, primary_key=True),
        sa.Column("message_id", sa.BigInteger, primary_key=True),
        sa.Column("seen_at", TS, nullable=False),
    )
    op.create_index("ix_messages_seen_at", "messages", ["seen_at"])


def downgrade() -> None:
    op.drop_table("messages")
    op.drop_table("sources")
    op.drop_table("accounts")
    op.drop_table("settings_overrides")
