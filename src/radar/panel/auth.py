"""Вход в панель: одноразовая ссылка из бота (/web) → подписанная cookie сессии. Без состояния в БД."""
import base64
import hashlib
import hmac
import secrets

from radar.shared.clock import Clock

LOGIN_TTL_S = 600
SESSION_TTL_S = 30 * 86400


def secret_from(web_secret: str, fallback: str) -> bytes:
    """Явный WEB_SECRET, иначе производный от USERBOT_STORE_KEY (есть всегда, и с ботом, и без)."""
    if web_secret:
        return web_secret.encode()
    return hashlib.sha256(b"radar-panel:" + fallback.encode()).digest()


class PanelAuth:
    def __init__(self, secret: bytes, clock: Clock, login_ttl_s: int = LOGIN_TTL_S,
                 session_ttl_s: int = SESSION_TTL_S) -> None:
        self._secret, self._clock = secret, clock
        self._login_ttl, self._session_ttl = login_ttl_s, session_ttl_s
        self._used: dict[str, int] = {}  # nonce → exp; один процесс, ссылки живут минуты

    def _now(self) -> int:
        return int(self._clock.now().timestamp())

    def _sign(self, payload: str) -> str:
        mac = hmac.new(self._secret, payload.encode(), hashlib.sha256).digest()
        return base64.urlsafe_b64encode(mac).decode().rstrip("=")

    def _make(self, kind: str, ttl: int) -> str:
        payload = f"{kind}.{self._now() + ttl}.{secrets.token_urlsafe(12)}"
        return f"{payload}.{self._sign(payload)}"

    def _open(self, token: str, kind: str) -> tuple[int, str] | None:
        parts = (token or "").split(".")
        if len(parts) != 4 or parts[0] != kind or not parts[1].isdigit():
            return None
        payload = ".".join(parts[:3])
        if not hmac.compare_digest(self._sign(payload), parts[3]):
            return None
        exp = int(parts[1])
        return (exp, parts[2]) if exp >= self._now() else None

    def issue_login(self) -> str:
        return self._make("login", self._login_ttl)

    def redeem_login(self, token: str) -> str | None:
        opened = self._open(token, "login")
        if opened is None:
            return None
        exp, nonce = opened
        now = self._now()
        self._used = {n: e for n, e in self._used.items() if e >= now}
        if nonce in self._used:
            return None
        self._used[nonce] = exp
        return self._make("session", self._session_ttl)

    def password_session(self, given: str, expected: str) -> str | None:
        """Вход по WEB_PASSWORD (режим без бота). Пустой пароль в настройках — вход выключен."""
        if not expected or not hmac.compare_digest(given.encode(), expected.encode()):
            return None
        return self._make("session", self._session_ttl)

    def check_session(self, value: str) -> bool:
        return self._open(value, "session") is not None
