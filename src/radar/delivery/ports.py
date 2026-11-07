from typing import Protocol


class DeliveryRejected(Exception):
    """Telegram не принял сообщение (BadRequest: разметка, длина, ссылка) — повтор того же текста бесполезен."""


class Notifier(Protocol):
    """Бот пишет только владельцу (OWNER_TELEGRAM_ID)."""

    async def send(self, text: str, parse_mode: str | None = "HTML") -> int:
        """→ message_id отправленного сообщения. Отказ Telegram → DeliveryRejected, сеть → прочие исключения."""

    async def edit(self, message_id: int, text: str) -> None:
        """Повторное редактирование тем же текстом — не ошибка (идемпотентно)."""
