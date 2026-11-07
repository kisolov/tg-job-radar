from datetime import datetime


class InMemoryMessageLog:
    def __init__(self) -> None:
        self.seen: dict[tuple[int, int], datetime] = {}
        self.processed: set[tuple[int, int]] = set()

    async def remember(self, source_id: int, message_id: int, seen_at: datetime) -> bool:
        key = (source_id, message_id)
        if key in self.seen:
            return False
        self.seen[key] = seen_at
        return True

    async def done(self, source_id: int, message_id: int) -> None:
        if (source_id, message_id) in self.seen:
            self.processed.add((source_id, message_id))

    async def forget(self, source_id: int, message_id: int) -> None:
        self.seen.pop((source_id, message_id), None)
        self.processed.discard((source_id, message_id))

    async def purge_unprocessed(self) -> int:
        stale = [k for k in self.seen if k not in self.processed]
        for k in stale:
            del self.seen[k]
        return len(stale)

    async def purge_older(self, before: datetime) -> int:
        old = [k for k, ts in self.seen.items() if ts < before]
        for k in old:
            del self.seen[k]
        return len(old)
