from datetime import datetime

from sqlalchemy.dialects.postgresql import insert

from radar.shared.db import SessionFactory, transaction
from radar.shared.models import messages as t


class SqlAlchemyMessageLog:
    def __init__(self, sf: SessionFactory) -> None:
        self._sf = sf

    async def remember(self, source_id: int, message_id: int, seen_at: datetime) -> bool:
        stmt = (insert(t).values(source_id=source_id, message_id=message_id, seen_at=seen_at)
                .on_conflict_do_nothing().returning(t.c.source_id))
        async with transaction(self._sf) as s:
            return (await s.execute(stmt)).first() is not None

    async def purge_older(self, before: datetime) -> int:
        async with transaction(self._sf) as s:
            return (await s.execute(t.delete().where(t.c.seen_at < before))).rowcount
