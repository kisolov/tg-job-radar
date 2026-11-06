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

settings_overrides = sa.Table(
    "settings_overrides", metadata,
    sa.Column("key", sa.Text, primary_key=True),
    sa.Column("value", sa.Text, nullable=False),
)
