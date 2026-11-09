"""Процесс radar: миграции → пул аккаунтов, отбор, доставка, бот. Падение одной задачи её перезапускает."""
import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import timedelta

from aiogram import Dispatcher
from aiohttp import web

from radar.bootstrap.di import Container
from radar.delivery.bot import build_router
from radar.panel.web import build_app

logger = logging.getLogger("radar")

Sleep = Callable[[float], Awaitable[None]]
BACKOFF_START_S = 5
BACKOFF_MAX_S = 300
DELIVER_FALLBACK_S = 30


async def supervise(name: str, factory: Callable[[], Awaitable[None]], sleep: Sleep = asyncio.sleep,
                    monotonic: Callable[[], float] = time.monotonic) -> None:
    """Перезапускать задачу при падении или выходе, с растущей паузой. Отмена — не перезапускается.
    Проработала дольше BACKOFF_MAX_S — пауза снова с начала (M7)."""
    delay = BACKOFF_START_S
    while True:
        started = monotonic()
        try:
            await factory()
            logger.warning("Задача %s завершилась, перезапуск", name)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Задача %s упала, перезапуск через %s с", name, delay)
        if monotonic() - started > BACKOFF_MAX_S:
            delay = BACKOFF_START_S
        await sleep(delay)
        delay = min(delay * 2, BACKOFF_MAX_S)


async def every(seconds: float, fn: Callable[[], Awaitable[object]], sleep: Sleep = asyncio.sleep) -> None:
    while True:
        try:
            await fn()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Периодическая задача упала")
        await sleep(seconds)


def run_migrations(url: str) -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config("alembic.ini")
    cfg.attributes["url"] = url
    command.upgrade(cfg, "head")


async def _deliver_loop(c: Container) -> None:
    trigger, deliver = c.delivery_trigger(), c.deliver_accepted()
    while True:
        try:
            await asyncio.wait_for(trigger.event.wait(), DELIVER_FALLBACK_S)
        except TimeoutError:
            pass
        trigger.event.clear()
        await deliver.execute()


async def _copy_edit_loop(c: Container) -> None:
    bus, edit = c.bus(), c.attach_copy_edit()
    while True:
        event = await bus.queue.get()
        try:
            await edit.execute(event)
        except Exception:
            logger.exception("Не удалось обновить «Также в» у находки %s", event.finding_id)


async def _purge_messages(c: Container) -> None:
    keep = timedelta(days=c.settings().MESSAGES_RETENTION_DAYS)
    removed = await c.message_log().purge_older(c.clock().now() - keep)
    logger.info("Чистка messages: удалено %s", removed)


async def serve_panel(c: Container) -> None:
    """Веб-панель в том же процессе; живёт до отмены задачи."""
    s = c.settings()
    runner = web.AppRunner(build_app(c.panel_deps()), access_log=None)
    await runner.setup()
    try:
        await web.TCPSite(runner, s.WEB_HOST, s.WEB_PORT).start()
        logger.info("Панель: http://%s:%s (ссылка входа — /web в боте)", s.WEB_HOST, s.WEB_PORT)
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()


def build_jobs(c: Container) -> dict[str, Callable[[], Awaitable[None]]]:
    """Задачи процесса. Без BOT_TOKEN нет задачи «bot»: находки «доставляются» в панель (PanelOnlyNotifier)."""
    s = c.settings()
    jobs = {
        "pool": c.pool_runner().run_forever,
        "classify": c.classify_pending().run_forever,
        "deliver": lambda: _deliver_loop(c),
        "copy-edit": lambda: _copy_edit_loop(c),
        "redeliver-stale": lambda: every(60, c.redeliver_stale().execute),
        "purge-messages": lambda: every(3600, lambda: _purge_messages(c)),
        "retire-useless": lambda: every(86400, c.retire_useless().execute),
    }
    bot = c.bot()
    if bot is not None:
        dp = Dispatcher()
        dp.include_router(build_router(s.OWNER_TELEGRAM_ID, c.bot_deps()))
        jobs["bot"] = lambda: dp.start_polling(bot, handle_signals=False)
    if s.WEB_PORT:
        jobs["web"] = lambda: serve_panel(c)
    return jobs


async def run(c: Container) -> None:
    s = c.settings()
    await asyncio.to_thread(run_migrations, s.DATABASE_URL)
    await c.runtime().load()
    await c.source_repo().reset_resolving()
    await c.message_log().purge_unprocessed()  # I5: перечитать то, что упало посередине
    await c.usage_repo().reset_reserved()  # M8: резервы пакетов, умерших с прошлым процессом

    jobs = build_jobs(c)
    bot = c.bot()
    tasks = [asyncio.create_task(supervise(name, job), name=name) for name, job in jobs.items()]
    logger.info("radar запущен: %s", ", ".join(jobs))
    try:
        await asyncio.gather(*tasks)
    finally:
        for t in tasks:
            t.cancel()
        await c.pool_runner().stop()
        if bot is not None:
            await bot.session.close()
        await c.engine().dispose()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("telethon").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    asyncio.run(run(Container()))


if __name__ == "__main__":
    main()
