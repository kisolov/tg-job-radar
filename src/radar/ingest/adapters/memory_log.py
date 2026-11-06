from datetime import datetime


class InMemoryMessageLog:
    def __init__(self) -> None:
        self.seen: dict[tuple[int, int], datetime] = {}

    async def remember(self, source_id: int, message_id: int, seen_at: datetime) -> bool:
        key = (source_id, message_id)
        if key in self.seen:
            return False
        self.seen[key] = seen_at
        return True

    async def purge_older(self, before: datetime) -> int:
        old = [k for k, ts in self.seen.items() if ts < before]
        for k in old:
            del self.seen[k]
        return len(old)
