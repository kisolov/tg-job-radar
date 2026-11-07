"""Бот управления: команды только от владельца (R11), остальным — молчание."""
from collections.abc import Callable
from dataclasses import dataclass

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from radar.accounts.ports import AccountRepository
from radar.delivery.usecases import (
    ListSources,
    SetOverride,
    SetPaused,
    SetRequirements,
    ShowRequirements,
    StatusReport,
)
from radar.screening.ports import RequirementsRepository, UsageRepository
from radar.shared.clock import Clock
from radar.shared.runtime import EDITABLE, RuntimeConfig, UnknownSetting
from radar.sources.ports import SourceRepository
from radar.sources.service import SourceService
from radar.sources.usecases import AddSource, RemoveSource

HELP = (
    "Команды:\n"
    "/status — состояние и расход за сутки\n"
    "/add <ссылки> — добавить источники (через пробел или строки)\n"
    "/remove <ссылка> — убрать источник\n"
    "/sources [страница] — источники по числу находок\n"
    "/req — текущие требования; /setreq — заменить (следующим сообщением)\n"
    "/pause, /resume — пауза доставки (находки копятся)\n"
    "/web — ссылка входа в веб-панель\n"
    "/set <KEY> <VALUE> — " + ", ".join(EDITABLE)
)


@dataclass
class BotDeps:
    accounts: AccountRepository
    sources: SourceRepository
    source_service: SourceService
    requirements: RequirementsRepository
    usage: UsageRepository
    runtime: RuntimeConfig
    clock: Clock
    web_link: Callable[[], str] | None = None  # одноразовая ссылка входа в панель; None — панель выключена


class ReqEdit(StatesGroup):
    waiting_text = State()


def build_router(owner_id: int, deps: BotDeps) -> Router:
    router = Router(name="owner")
    router.message.filter(F.from_user.id == owner_id)

    status = StatusReport(deps.accounts, deps.sources, deps.usage, deps.runtime, deps.clock)
    add_source, remove_source = AddSource(deps.source_service), RemoveSource(deps.source_service)
    list_sources = ListSources(deps.sources)
    show_req, set_req = ShowRequirements(deps.requirements), SetRequirements(deps.requirements)
    set_paused, set_override = SetPaused(deps.runtime), SetOverride(deps.runtime)

    @router.message(Command("start", "help"))
    async def _help(m: Message) -> None:
        await m.answer(HELP)

    @router.message(Command("cancel"))
    async def _cancel(m: Message, state: FSMContext) -> None:
        await state.clear()
        await m.answer("Отменено.")

    @router.message(ReqEdit.waiting_text, F.text, ~F.text.startswith("/"))  # M5: команды — не текст
    async def _req_text(m: Message, state: FSMContext) -> None:
        try:
            version = await set_req.execute(m.text)
        except ValueError:
            await m.answer("Пустой текст. Пришлите требования одним сообщением или /cancel.")
            return
        await state.clear()
        await m.answer(f"Требования обновлены, версия {version}. Новые пакеты LLM идут с ней.")

    @router.message(Command("status"))
    async def _status(m: Message) -> None:
        await m.answer(await status.execute())

    @router.message(Command("add"))
    async def _add(m: Message, command: CommandObject) -> None:
        res = await add_source.execute(command.args or "")
        if not res.added and not res.duplicates:
            await m.answer("Не нашёл ссылок. Пример: /add t.me/chat @channel")
            return
        await m.answer(f"Добавлено: {', '.join(res.added) or '—'}\nУже были: {', '.join(res.duplicates) or '—'}")

    @router.message(Command("remove"))
    async def _remove(m: Message, command: CommandObject) -> None:
        link = (command.args or "").strip()
        ok = bool(link) and await remove_source.execute(link.split()[0])
        await m.answer("Источник удалён." if ok else "Источник не найден.")

    @router.message(Command("sources"))
    async def _sources(m: Message, command: CommandObject) -> None:
        arg = (command.args or "1").strip()
        await m.answer(await list_sources.execute(int(arg) if arg.isdigit() else 1))

    @router.message(Command("req"))
    async def _req(m: Message) -> None:
        version, text = await show_req.execute()
        await m.answer(f"Требования, версия {version}:\n\n{text}")

    @router.message(Command("setreq"))
    async def _setreq(m: Message, state: FSMContext) -> None:
        await state.set_state(ReqEdit.waiting_text)
        await m.answer("Пришлите новый текст требований следующим сообщением (/cancel — отмена).")

    @router.message(Command("pause"))
    async def _pause(m: Message) -> None:
        await set_paused.execute(True)
        await m.answer("⏸ Доставка на паузе. Находки копятся; /resume — продолжить.")

    @router.message(Command("resume"))
    async def _resume(m: Message) -> None:
        await set_paused.execute(False)
        await m.answer("▶️ Доставка возобновлена.")

    @router.message(Command("web"))
    async def _web(m: Message) -> None:
        if deps.web_link is None:
            await m.answer("Веб-панель выключена (WEB_PORT=0).")
            return
        await m.answer(f"Вход в панель (ссылка одноразовая, 10 минут):\n{deps.web_link()}")

    @router.message(Command("set"))
    async def _set(m: Message, command: CommandObject) -> None:
        parts = (command.args or "").split(maxsplit=1)
        if len(parts) != 2:
            await m.answer("Формат: /set KEY VALUE. Можно: " + ", ".join(EDITABLE))
            return
        key, raw = parts[0].upper(), parts[1]
        try:
            value = await set_override.execute(key, raw)
        except UnknownSetting:
            await m.answer(f"Нельзя менять {key}. Можно: " + ", ".join(EDITABLE))
            return
        except ValueError as exc:
            await m.answer(f"Ошибка: {exc}")
            return
        await m.answer(f"{key} = {value}")

    @router.message()
    async def _fallback(m: Message) -> None:
        await m.answer(HELP)

    return router
