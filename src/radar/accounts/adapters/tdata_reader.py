"""tdata (Telegram Desktop) → Telethon StringSession через opentele. Без сети: ключ авторизации берётся как есть."""
from pathlib import Path

from opentele.api import UseCurrentSession
from opentele.exception import OpenTeleException, TDataBadDecryptKey
from opentele.td import TDesktop
from telethon.sessions import StringSession

from radar.accounts.ports import TdataSession
from radar.accounts.usecases import InvalidAccountPayload


def _tdata_dir(path: Path) -> Path:
    """Принимает и саму tdata, и папку аккаунта, в которой она лежит."""
    if not any(path.glob("key_data*")) and (path / "tdata").is_dir():
        return path / "tdata"
    return path


class OpenteleTdataReader:
    async def read(self, path: Path | str, passcode: str | None = None) -> list[TdataSession]:
        base = _tdata_dir(Path(path))
        if not base.is_dir():
            raise InvalidAccountPayload(f"Папка tdata не найдена: {path}")
        try:  # OpenTeleException наследует BaseException — ловим явно
            tdesk = TDesktop(str(base), passcode=passcode)
        except TDataBadDecryptKey as exc:
            raise InvalidAccountPayload("tdata защищена локальным код-паролем: укажите верный --passcode") from exc
        except (OpenTeleException, OSError, ValueError) as exc:
            raise InvalidAccountPayload(f"Не похоже на tdata Telegram Desktop ({type(exc).__name__})") from exc
        if not tdesk.isLoaded() or not tdesk.accounts:
            raise InvalidAccountPayload("В tdata нет авторизованных аккаунтов")
        out = []
        for acc in tdesk.accounts:
            # UseCurrentSession: тот же ключ авторизации, без подключения и без новой авторизации.
            # session=None: opentele создаёт сессию в памяти (объект Session он не принимает — баг 1.15.1).
            client = await acc.ToTelethon(session=None, flag=UseCurrentSession)
            src = client.session
            session = StringSession()
            session.set_dc(src.dc_id, src.server_address, src.port)
            session.auth_key = src.auth_key
            src.close()
            out.append(TdataSession(session=session.save(), api_id=acc.api.api_id, api_hash=acc.api.api_hash,
                                    user_id=int(acc.UserId) if acc.UserId else None))
        return out
