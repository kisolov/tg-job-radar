from datetime import UTC, datetime

from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import EditMessageText, SendMessage

from radar.delivery.adapters.aiogram_notifier import AiogramNotifier
from radar.delivery.adapters.fake_notifier import FakeNotifier
from radar.delivery.usecases import AttachCopyEdit
from radar.findings.adapters.memory_repo import InMemoryFindingRepository
from radar.findings.entities import Classification
from radar.findings.events import CopyAttached
from radar.findings.similarity import fingerprint, normalize, shingles
from radar.ingest.ports import IncomingMessage
from tests.unit.delivery.botkit import make_bot

OWNER = 1001


async def test_send_goes_only_to_owner_without_preview():
    bot, session = make_bot()
    n = AiogramNotifier(bot, OWNER)
    mid = await n.send("<b>x</b>")
    call = session.calls[0]
    assert isinstance(call, SendMessage) and call.chat_id == OWNER and call.parse_mode == "HTML"
    assert call.link_preview_options.is_disabled and mid > 0
    await n.notify("alert")
    assert session.calls[1].chat_id == OWNER


async def test_edit_not_modified_ignored():
    bot, session = make_bot()

    async def boom(bot_, method, timeout=None):
        session.calls.append(method)
        raise TelegramBadRequest(method, "Bad Request: message is not modified")

    session.make_request = boom
    await AiogramNotifier(bot, OWNER).edit(5, "same")
    assert isinstance(session.calls[0], EditMessageText) and session.calls[0].message_id == 5


async def test_attach_copy_edit_updates_delivered_card():
    repo, notifier = InMemoryFindingRepository(), FakeNotifier()
    now = datetime(2026, 11, 4, tzinfo=UTC)
    text = "Ищем Python-разработчика, удалённо, пишите @hr"

    def m(src):
        return IncomingMessage(src, 1, text, now, 1, "a", True, None, f"https://t.me/c/{src}/1", f"Чат {src}")

    norm = normalize(text)
    f, _ = await repo.cluster(m(1), norm, fingerprint(norm), shingles(norm), 7, 0.6, now)
    edit = AttachCopyEdit(repo, notifier, lambda f, copies: f"{len(copies)} копий")
    assert not await edit.execute(CopyAttached(f.id))  # ещё не доставлена — править нечего
    await repo.set_classification(f.id, Classification(True, "vacancy", "s", None, None, None, "r"), 1)
    await repo.claim(f.id, now)
    await repo.mark_delivered(f.id, 42, now)
    await repo.cluster(m(2), norm, fingerprint(norm), shingles(norm), 7, 0.6, now)
    assert await edit.execute(CopyAttached(f.id))
    assert await edit.execute(CopyAttached(f.id))  # повтор — та же правка, идемпотентно
    assert notifier.edits == [(42, "2 копий"), (42, "2 копий")]
