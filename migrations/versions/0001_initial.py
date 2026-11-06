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


def downgrade() -> None:
    op.drop_table("accounts")
    op.drop_table("settings_overrides")
