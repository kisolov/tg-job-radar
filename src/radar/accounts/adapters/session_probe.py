from telethon import TelegramClient
from telethon.sessions import StringSession

from radar.accounts.entities import DeviceProfile


class TelethonSessionProbe:
    async def check(self, session: str, api_id: int, api_hash: str, device: DeviceProfile) -> bool:
        client = TelegramClient(StringSession(session), api_id, api_hash, **device.as_client_kwargs())
        await client.connect()
        try:
            return await client.is_user_authorized()
        finally:
            await client.disconnect()

    async def phone(self, session: str, api_id: int, api_hash: str, device: DeviceProfile) -> str | None:
        client = TelegramClient(StringSession(session), api_id, api_hash, **device.as_client_kwargs())
        await client.connect()
        try:
            if not await client.is_user_authorized():
                return None
            me = await client.get_me()
            return me.phone if me else None
        finally:
            await client.disconnect()


async def interactive_login(phone: str, api_id: int, api_hash: str) -> str:
    """Код из Telegram и пароль 2FA Telethon спрашивает сам (input/getpass); пароль нигде не сохраняется."""
    client = TelegramClient(StringSession(), api_id, api_hash)
    await client.start(phone=phone)
    try:
        return client.session.save()
    finally:
        await client.disconnect()
