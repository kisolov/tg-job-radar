"""initial schema

Revision ID: 0001
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

TS = sa.DateTime(timezone=True)

# Снимок стартовых требований на момент миграции (дальше — версии через /setreq).
from radar.screening.requirements_default import DEFAULT_REQUIREMENTS  # noqa: E402

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
        sa.Column("hash_account_id", UUID(as_uuid=True), sa.ForeignKey("accounts.id", ondelete="SET NULL")),
        sa.Column("joined", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("last_message_id", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("last_polled_at", TS),
        sa.Column("found_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("read_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("passed_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("activated_at", TS),
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
        sa.Column("processed_at", TS),
    )
    op.create_index("ix_messages_seen_at", "messages", ["seen_at"])
    req = op.create_table(
        "requirements",
        sa.Column("version", sa.Integer, primary_key=True, autoincrement=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
    )
    op.bulk_insert(req, [{"version": 1, "text": DEFAULT_REQUIREMENTS}])
    op.create_table(
        "daily_stats",
        sa.Column("day", sa.Date, primary_key=True),
        *(sa.Column(c, sa.BigInteger, nullable=False, server_default="0") for c in (
            "read", "passed_prefilter", "llm_items", "findings", "requests",
            "prompt_tokens", "completion_tokens", "reserved",
        )),
    )


    op.create_table(
        "findings",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("fingerprint", sa.Text, nullable=False),
        sa.Column("shingles", sa.LargeBinary, nullable=False),
        sa.Column("shingle_count", sa.Integer, nullable=False),
        sa.Column("text_snapshot", sa.Text, nullable=False),
        sa.Column("link_snapshot", sa.Text, nullable=False),
        sa.Column("sender_username", sa.Text),
        sa.Column("sender_id", sa.BigInteger),
        sa.Column("sender_is_user", sa.Boolean, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("classification", JSONB),
        sa.Column("requirements_version", sa.Integer),
        sa.Column("claimed_at", TS),
        sa.Column("delivered_at", TS),
        sa.Column("bot_message_id", sa.BigInteger),
        sa.Column("llm_attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", TS, nullable=False),
    )
    op.create_index("ix_findings_fp", "findings", ["fingerprint", "created_at"])
    op.create_index("ix_findings_window", "findings", ["created_at", "shingle_count"])
    op.create_index("ix_findings_status", "findings", ["status", "created_at"])
    op.create_table(
        "finding_copies",
        sa.Column("finding_id", sa.BigInteger, sa.ForeignKey("findings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_id", sa.BigInteger, primary_key=True),
        sa.Column("message_id", sa.BigInteger, primary_key=True),
        sa.Column("link", sa.Text, nullable=False),
        sa.Column("source_title", sa.Text),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_finding_copies_finding", "finding_copies", ["finding_id"])


def downgrade() -> None:
    op.drop_table("finding_copies")
    op.drop_table("findings")
    op.drop_table("daily_stats")
    op.drop_table("requirements")
    op.drop_table("messages")
    op.drop_table("sources")
    op.drop_table("accounts")
    op.drop_table("settings_overrides")
