"""SQLAlchemy Core-таблицы всех модулей (одна схема, один процесс)."""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

metadata = sa.MetaData()

TS = sa.DateTime(timezone=True)

accounts = sa.Table(
    "accounts", metadata,
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

sources = sa.Table(
    "sources", metadata,
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
    sa.Index("ix_sources_resolve_queue", "status", sa.text("priority DESC"), "id"),
    sa.Index("ix_sources_assigned", "assigned_account_id", "kind"),
)

requirements = sa.Table(
    "requirements", metadata,
    sa.Column("version", sa.Integer, primary_key=True, autoincrement=False),
    sa.Column("text", sa.Text, nullable=False),
    sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
)

daily_stats = sa.Table(
    "daily_stats", metadata,
    sa.Column("day", sa.Date, primary_key=True),
    *(sa.Column(c, sa.BigInteger, nullable=False, server_default="0") for c in (
        "read", "passed_prefilter", "llm_items", "findings", "requests",
        "prompt_tokens", "completion_tokens", "reserved",
    )),
)

messages = sa.Table(
    "messages", metadata,
    sa.Column("source_id", sa.BigInteger, primary_key=True),
    sa.Column("message_id", sa.BigInteger, primary_key=True),
    sa.Column("seen_at", TS, nullable=False),
    sa.Index("ix_messages_seen_at", "seen_at"),
)

settings_overrides = sa.Table(
    "settings_overrides", metadata,
    sa.Column("key", sa.Text, primary_key=True),
    sa.Column("value", sa.Text, nullable=False),
)
