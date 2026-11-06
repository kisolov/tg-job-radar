from typing import Protocol


class Notifier(Protocol):
    """Бот пишет только владельцу (OWNER_TELEGRAM_ID)."""

    async def send(self, text: str, parse_mode: str = "HTML") -> int:
        """→ message_id отправленного сообщения."""

    async def edit(self, message_id: int, text: str) -> None:
        """Повторное редактирование тем же текстом — не ошибка (идемпотентно)."""
