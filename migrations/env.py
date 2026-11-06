import asyncio
import os

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from radar.shared.models import metadata

URL = context.config.attributes.get("url") or os.environ["DATABASE_URL"]


def _run(connection) -> None:
    context.configure(connection=connection, target_metadata=metadata)
    with context.begin_transaction():
        context.run_migrations()


async def _main() -> None:
    engine = create_async_engine(URL)
    async with engine.connect() as conn:
        await conn.run_sync(_run)
        await conn.commit()
    await engine.dispose()


asyncio.run(_main())
