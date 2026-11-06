"""Прогон апдейтов через настоящий aiogram Dispatcher без сети: сессия бота записывает вызовы API."""
from datetime import UTC, datetime
from itertools import count

from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.methods import SendMessage
from aiogram.types import Chat, Message, Update, User

_ids = count(1)


class RecordingSession(BaseSession):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list = []

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        if isinstance(method, SendMessage):
            return Message(message_id=next(_ids), date=datetime.now(UTC), text=method.text,
                           chat=Chat(id=method.chat_id, type="private"))
        return True

    async def stream_content(self, *a, **kw):  # pragma: no cover
        raise NotImplementedError

    async def close(self) -> None:
        pass

    @property
    def texts(self) -> list[str]:
        return [c.text for c in self.calls if isinstance(c, SendMessage)]


def make_bot() -> tuple[Bot, RecordingSession]:
    session = RecordingSession()
    return Bot(token="42:TEST", session=session), session


def update(text: str, user_id: int) -> Update:
    user = User(id=user_id, is_bot=False, first_name="u")
    msg = Message(message_id=next(_ids), date=datetime.now(UTC), text=text, from_user=user,
                  chat=Chat(id=user_id, type="private"))
    return Update(update_id=next(_ids), message=msg)


async def send(dp: Dispatcher, bot: Bot, text: str, user_id: int):
    return await dp.feed_update(bot, update(text, user_id))
