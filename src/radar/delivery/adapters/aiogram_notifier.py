import logging

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import LinkPreviewOptions

logger = logging.getLogger(__name__)
_NO_PREVIEW = LinkPreviewOptions(is_disabled=True)


class AiogramNotifier:
    """Notifier и AlertSink поверх одного бота; адресат всегда владелец."""

    def __init__(self, bot: Bot, owner_id: int) -> None:
        self._bot, self._owner = bot, owner_id

    async def send(self, text: str, parse_mode: str = "HTML") -> int:
        msg = await self._bot.send_message(self._owner, text, parse_mode=parse_mode, link_preview_options=_NO_PREVIEW)
        return msg.message_id

    async def edit(self, message_id: int, text: str) -> None:
        try:
            await self._bot.edit_message_text(text=text, chat_id=self._owner, message_id=message_id,
                                              parse_mode="HTML", link_preview_options=_NO_PREVIEW)
        except TelegramBadRequest as exc:
            if "message is not modified" not in str(exc):
                raise

    async def notify(self, text: str) -> None:
        try:
            await self.send(text, parse_mode=None)
        except Exception:
            logger.exception("Не удалось отправить алерт: %s", text)
