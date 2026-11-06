"""SQLAlchemy Core-таблицы всех модулей (одна схема, один процесс)."""
import sqlalchemy as sa

metadata = sa.MetaData()

settings_overrides = sa.Table(
    "settings_overrides", metadata,
    sa.Column("key", sa.Text, primary_key=True),
    sa.Column("value", sa.Text, nullable=False),
)
