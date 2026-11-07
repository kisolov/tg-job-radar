from datetime import UTC, datetime

from radar.delivery.card import FIELD_MAX, TELEGRAM_LIMIT, contact_line, render_card, to_plain
from radar.findings.entities import Classification, Copy, Finding, FindingStatus

T0 = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
TEXT = "Ищем Python-разработчика. FastAPI. Удалённо. 250к. Пишите @hr_anna"


def finding(cls: Classification | None = None, **kw) -> Finding:
    base = dict(
        id=1, fingerprint="fp", shingles=b"", text_snapshot=TEXT, link_snapshot="https://t.me/jobs/5",
        sender_username="poster", sender_id=500, sender_is_user=True, status=FindingStatus.accepted,
        classification=cls or Classification(True, "vacancy", "Python-бэкенд на FastAPI в маркетплейс", "250к",
                                             "удалёнка", "@hr_anna", "Python-бэкенд, удалёнка"),
        requirements_version=1, claimed_at=None, delivered_at=None, bot_message_id=None, created_at=T0,
    )
    base.update(kw)
    return Finding(**base)


def copy(i: int, title: str | None = None) -> Copy:
    return Copy(1, i, 5, f"https://t.me/c/{i}/5", title or f"Чат {i}")


def test_card_vacancy_full():
    card = render_card(finding(), [copy(1, "Python Jobs"), copy(2, "IT <Вакансии>")])
    assert card == (
        "💼 <b>Вакансия</b>\n"
        "Python-бэкенд на FastAPI в маркетплейс\n"
        "💰 250к\n"
        "📍 удалёнка\n"
        "👤 @hr_anna\n"
        '🔗 <a href="https://t.me/c/1/5">Python Jobs</a>\n'
        "✅ Python-бэкенд, удалёнка\n"
        "Также в: IT &lt;Вакансии&gt;"
    )


def test_card_project_minimal():
    cls = Classification(True, "project", "Telegram-бот для салона", None, None, None, "бот на Python")
    card = render_card(finding(cls, text_snapshot="Нужен бот для салона"), [copy(1)])
    assert card.startswith("🛠 <b>Проект</b>\nTelegram-бот для салона\n👤 @poster\n")
    assert "💰" not in card and "📍" not in card and "Также в" not in card


def test_card_truncated_to_telegram_limit():
    cls = Classification(True, "vacancy", "очень длинно " * 500, None, None, None, "причина")
    card = render_card(finding(cls), [copy(i) for i in range(1, 40)])
    assert len(card) <= TELEGRAM_LIMIT
    assert card.endswith("и ещё 28")
    assert "🔗" in card  # ссылка и контакт не теряются при обрезке


def test_contact_fallbacks():
    # 1) контакт из ответа LLM, если он есть в тексте
    assert contact_line(finding()) == "@hr_anna"
    # 2) LLM выдумал контакт, которого нет в тексте → отправитель
    hallucinated = Classification(True, "vacancy", "s", None, None, "@ghost_hr", "r")
    assert contact_line(finding(hallucinated)) == "@poster"
    # 3) отправитель без username → ссылка на профиль
    no_contact = Classification(True, "vacancy", "s", None, None, None, "r")
    assert contact_line(finding(no_contact, sender_username=None, text_snapshot="без контактов")) == \
        '<a href="tg://user?id=500">профиль автора</a>'
    # 4) пост от имени канала / анонимный админ → «контакта нет»
    assert contact_line(finding(no_contact, sender_username="some_channel", sender_is_user=False,
                                text_snapshot="без контактов")) == "контакта нет"


def test_contact_tme_link_from_text():
    cls = Classification(True, "project", "s", None, None, "t.me/ivan_dev", "r")
    f = finding(cls, text_snapshot="Пишите в t.me/ivan_dev")
    assert contact_line(f) == '<a href="https://t.me/ivan_dev">t.me/ivan_dev</a>'


def test_also_in_list_capped():
    card = render_card(finding(), [copy(i) for i in range(1, 31)])
    tail = card.split("Также в: ")[1]
    assert tail.endswith("и ещё 19") and tail.count(",") == 10


def test_also_in_dedups_same_chat():
    card = render_card(finding(), [copy(1, "A"), copy(1, "A"), copy(2, "B")])
    assert card.endswith("Также в: B")


def test_long_llm_fields_are_capped_and_card_fits():
    """I6: длинные money/format/reason/summary от LLM не выталкивают карточку за 4096."""
    huge = "очень длинно " * 400
    card = render_card(finding(Classification(True, "vacancy", huge, huge, huge, None, huge)),
                       [copy(i, "Чат с очень длинным названием " * 5) for i in range(1, 30)])
    assert len(card) <= TELEGRAM_LIMIT
    money_line = next(ln for ln in card.split("\n") if ln.startswith("💰"))
    assert len(money_line) <= FIELD_MAX + 4 and money_line.endswith("…")


def test_plain_fallback_keeps_urls_and_drops_tg_links():
    html = ('💼 <b>Вакансия</b>\nсуть &lt;тег&gt;\n👤 <a href="tg://user?id=5">профиль автора</a>\n'
            '🔗 <a href="https://t.me/c/1/5">Python Jobs</a>')
    assert to_plain(html) == ("💼 Вакансия\nсуть <тег>\n👤 профиль автора\n"
                              "🔗 Python Jobs: https://t.me/c/1/5")


def test_llm_contact_must_match_a_whole_username():
    """M6: обрезанный/выдуманный @ivan не засчитывается, если в тексте только @ivan_petrov."""
    f = finding(Classification(True, "vacancy", "s", None, None, "@ivan", "r"),
                text_snapshot="Пишите @ivan_petrov", sender_username=None, sender_is_user=False)
    assert contact_line(f) == "контакта нет"
    f2 = finding(Classification(True, "vacancy", "s", None, None, "@ivan_petrov", "r"),
                 text_snapshot="Пишите @Ivan_Petrov.", sender_username=None, sender_is_user=False)
    assert contact_line(f2) == "@ivan_petrov"


def test_card_without_message_link_shows_title_only():
    """M2: у обычной группы ссылок на сообщения нет — название чата без ссылки."""
    card = render_card(finding(link_snapshot=""), [Copy(1, 1, 5, "", "Старая группа")])
    assert "🔗 Старая группа" in card and "href=\"\"" not in card
