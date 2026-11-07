"""Как находка выглядит в боте: HTML-карточка ≤ 4096 символов."""
import re
from html import escape, unescape

from radar.findings.entities import Copy, Finding

TELEGRAM_LIMIT = 4096
ALSO_IN_MAX = 10
FIELD_MAX = 300  # поле от LLM длиннее — обрезается (I6: карточка всегда влезает)
TITLE_MAX = 80
_KIND = {"vacancy": "💼 <b>Вакансия</b>", "project": "🛠 <b>Проект</b>"}
_TME = re.compile(r"(?:https?://)?t\.me/([A-Za-z]\w{3,31})", re.IGNORECASE)
_AT = re.compile(r"@([A-Za-z]\w{3,31})")


def contact_line(f: Finding) -> str:
    """Контакт по порядку: из ответа LLM (если он есть в тексте) → @отправитель-человек →
    ссылка на профиль отправителя → «контакта нет»."""
    text = (f.text_snapshot or "").lower()
    llm = (f.classification.contact if f.classification else None) or ""
    for m in (_AT.search(llm), _TME.search(llm)):
        # M6: username из ответа LLM засчитывается, только если он стоит в тексте целым словом
        if m and re.search(rf"(?<!\w){re.escape(m.group(1).lower())}(?!\w)", text.replace("@", " ")):
            if m.re is _AT:
                return f"@{escape(m.group(1))}"
            name = escape(m.group(1))
            return f'<a href="https://t.me/{name}">t.me/{name}</a>'
    if f.sender_is_user and f.sender_username:
        return f"@{escape(f.sender_username)}"
    if f.sender_is_user and f.sender_id:
        return f'<a href="tg://user?id={f.sender_id}">профиль автора</a>'
    return "контакта нет"


def _cap(text: str, limit: int = FIELD_MAX) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


_A = re.compile(r'<a href="([^"]*)">(.*?)</a>', re.DOTALL)


def to_plain(html: str) -> str:
    """Запасная карточка без разметки (I6): внешние ссылки выписаны, tg:// убран — его Telegram может не принять."""
    def link(m: re.Match) -> str:
        url, label = unescape(m.group(1)), m.group(2)
        return label if url.startswith("tg://") else f"{label}: {url}"

    return unescape(re.sub(r"</?b>", "", _A.sub(link, html)))


def _also_in(copies: list[Copy]) -> str | None:
    if not copies:
        return None
    seen = {copies[0].source_id}
    titles = []
    for c in copies[1:]:
        if c.source_id in seen:
            continue
        seen.add(c.source_id)
        titles.append(escape(_cap(c.source_title or f"чат {c.source_id}", TITLE_MAX)))
    if not titles:
        return None
    shown = ", ".join(titles[:ALSO_IN_MAX])
    rest = len(titles) - ALSO_IN_MAX
    return f"Также в: {shown}" + (f", и ещё {rest}" if rest > 0 else "")


def render_card(f: Finding, copies: list[Copy]) -> str:
    cls = f.classification
    first = copies[0] if copies else None
    link = first.link if first else f.link_snapshot
    link_title = escape(_cap(first.source_title or "сообщение", TITLE_MAX)) if first else "сообщение"

    head = [_KIND.get(cls.kind if cls else None, "📌 <b>Находка</b>")]
    tail = []
    if cls and cls.money:
        tail.append(f"💰 {escape(_cap(cls.money))}")
    if cls and cls.work_format:
        tail.append(f"📍 {escape(_cap(cls.work_format))}")
    tail.append(f"👤 {contact_line(f)}")
    # M2: у обычной группы ссылок на сообщения нет — только название
    tail.append(f'🔗 <a href="{escape(link, quote=True)}">{link_title}</a>' if link else f"🔗 {link_title}")
    if cls and cls.reason:
        tail.append(f"✅ {escape(_cap(cls.reason))}")
    if also := _also_in(copies):
        tail.append(also)

    summary = escape((cls.summary if cls else "") or f.text_snapshot[:300])
    fixed = len("\n".join(head + tail)) + 1
    room = TELEGRAM_LIMIT - fixed - 1
    if len(summary) > room:
        # обрезка не должна резать HTML-сущность (&lt; и т.п.) пополам
        summary = re.sub(r"&[^;\s]*$", "", summary[: max(0, room - 1)]) + "…"
    return "\n".join(head + [summary] + tail)
