"""Ссылки на чаты: нормализация к ключу каталога (`username` в нижнем регистре или `+invite`)."""
import re

_USERNAME = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]{3,31}$")
_TG_LINK = re.compile(
    r"(?:https?://)?(?:www\.)?(?:t|telegram)\.me/(?:s/)?(\+[\w-]+|joinchat/[\w-]+|[a-zA-Z][\w]{3,31})",
    re.IGNORECASE,
)
_RESERVED = {"addstickers", "share", "proxy", "socks", "joinchat", "iv", "login", "setlanguage", "addtheme"}


def _username(name: str) -> str | None:
    if not _USERNAME.match(name) or name.lower().endswith("bot") or name.lower() in _RESERVED:
        return None
    return name.lower()


def normalize_username(raw: str) -> str | None:
    """`@Foo`, `t.me/Foo`, `https://t.me/s/Foo/12`, `foo` → `foo`; `t.me/+hash`, `t.me/joinchat/hash` → `+hash`.

    Боты, служебные пути t.me и не-Telegram URL → None.
    """
    raw = raw.strip().rstrip(".,;:!?)»")
    m = _TG_LINK.match(raw)
    if m:
        part = m.group(1)
        if part.startswith("+"):
            return part
        if part.lower().startswith("joinchat/"):
            return "+" + part.split("/", 1)[1]
        return _username(part)
    if "/" in raw or "." in raw:
        return None
    return _username(raw[1:] if raw.startswith("@") else raw)


def extract_chat_links(text: str) -> list[str]:
    """Ссылки t.me/telegram.me из текста, нормализованные, без повторов, в порядке появления.

    @упоминания не берутся: в вакансиях это почти всегда контакт человека, а не чат.
    """
    out: list[str] = []
    for m in _TG_LINK.finditer(text or ""):
        ref = normalize_username(m.group(0))
        if ref and ref not in out:
            out.append(ref)
    return out
