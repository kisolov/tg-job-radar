"""Режим без бота: «доставка» — это появление находки в панели. Отправлять некуда, сообщение считается доставленным."""
import itertools


class PanelOnlyNotifier:
    def __init__(self) -> None:
        self._ids = itertools.count(1)

    async def send(self, text: str, parse_mode: str | None = "HTML") -> int:
        return next(self._ids)

    async def edit(self, message_id: int, text: str) -> None:
        return None

    async def notify(self, text: str) -> None:
        return None
