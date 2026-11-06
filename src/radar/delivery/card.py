"""Как находка выглядит в боте: HTML-карточка ≤ 4096 символов."""
import re
from html import escape

from radar.findings.entities import Copy, Finding

TELEGRAM_LIMIT = 4096
ALSO_IN_MAX = 10
_KIND = {"vacancy": "💼 <b>Вакансия</b>", "project": "🛠 <b>Проект</b>"}
_TME = re.compile(r"(?:https?://)?t\.me/([A-Za-z]\w{3,31})", re.IGNORECASE)
_AT = re.compile(r"@([A-Za-z]\w{3,31})")


def contact_line(f: Finding) -> str:
    """Контакт по порядку: из ответа LLM (если он есть в тексте) → @отправитель-человек →
    ссылка на профиль отправителя → «контакта нет»."""
    text = (f.text_snapshot or "").lower()
    llm = (f.classification.contact if f.classification else None) or ""
    for m in (_AT.search(llm), _TME.search(llm)):
        if m and m.group(1).lower() in text:
            if m.re is _AT:
                return f"@{escape(m.group(1))}"
            name = escape(m.group(1))
            return f'<a href="https://t.me/{name}">t.me/{name}</a>'
    if f.sender_is_user and f.sender_username:
        return f"@{escape(f.sender_username)}"
    if f.sender_is_user and f.sender_id:
        return f'<a href="tg://user?id={f.sender_id}">профиль автора</a>'
    return "контакта нет"


def _also_in(copies: list[Copy]) -> str | None:
    if not copies:
        return None
    seen = {copies[0].source_id}
    titles = []
    for c in copies[1:]:
        if c.source_id in seen:
            continue
        seen.add(c.source_id)
        titles.append(escape(c.source_title or f"чат {c.source_id}"))
    if not titles:
        return None
    shown = ", ".join(titles[:ALSO_IN_MAX])
    rest = len(titles) - ALSO_IN_MAX
    return f"Также в: {shown}" + (f", и ещё {rest}" if rest > 0 else "")


def render_card(f: Finding, copies: list[Copy]) -> str:
    cls = f.classification
    first = copies[0] if copies else None
    link = first.link if first else f.link_snapshot
    link_title = escape(first.source_title or "сообщение") if first else "сообщение"

    head = [_KIND.get(cls.kind if cls else None, "📌 <b>Находка</b>")]
    tail = []
    if cls and cls.money:
        tail.append(f"💰 {escape(cls.money)}")
    if cls and cls.work_format:
        tail.append(f"📍 {escape(cls.work_format)}")
    tail.append(f"👤 {contact_line(f)}")
    tail.append(f'🔗 <a href="{escape(link, quote=True)}">{link_title}</a>')
    if cls and cls.reason:
        tail.append(f"✅ {escape(cls.reason)}")
    if also := _also_in(copies):
        tail.append(also)

    summary = escape((cls.summary if cls else "") or f.text_snapshot[:300])
    fixed = len("\n".join(head + tail)) + 1
    room = TELEGRAM_LIMIT - fixed - 1
    if len(summary) > room:
        # обрезка не должна резать HTML-сущность (&lt; и т.п.) пополам
        summary = re.sub(r"&[^;\s]*$", "", summary[: max(0, room - 1)]) + "…"
    return "\n".join(head + [summary] + tail)
