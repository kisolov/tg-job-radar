"""Сборка панели в контейнере и запуск сервера (lesson #521: зелёные юниты не гарантируют wiring)."""
import asyncio
import socket

import aiohttp
from dependency_injector import providers

from radar.bootstrap.di import Container
from radar.bootstrap.main import serve_panel
from radar.shared.settings import Settings
from tests.unit.shared.test_settings import MIN_ENV


VALID = {"BOT_TOKEN": "42:TESTTOKEN", "USERBOT_STORE_KEY": "ZmDfcTF7_60GrrY167zsiPd67pEvs0aGOv2oasOM1Pg="}


def container(**env) -> Container:
    c = Container()
    c.settings.override(providers.Object(Settings(_env_file=None, **{**MIN_ENV, **VALID, **env})))
    return c


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def test_container_builds_panel_and_login_link():
    c = container(WEB_BASE_URL="https://radar.example/")
    deps = c.panel_deps()
    assert deps.secure_cookie is True
    link = c.bot_deps().web_link()
    assert link.startswith("https://radar.example/login?t=login.")
    assert deps.auth.redeem_login(link.split("t=", 1)[1])  # ссылка бота открывает сессию панели
    await c.engine().dispose()


async def test_panel_disabled_by_zero_port():
    c = container(WEB_PORT=0)
    assert c.bot_deps().web_link is None
    await c.engine().dispose()


async def test_serve_panel_answers_http():
    port = free_port()
    c = container(WEB_PORT=port, WEB_HOST="127.0.0.1")
    task = asyncio.create_task(serve_panel(c))
    try:
        for _ in range(50):
            try:
                async with aiohttp.ClientSession() as http, http.get(f"http://127.0.0.1:{port}/api/overview") as r:
                    assert r.status == 401
                    break
            except aiohttp.ClientConnectorError:
                await asyncio.sleep(0.05)
        else:
            raise AssertionError("панель не поднялась")
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await c.engine().dispose()


NO_BOT = {"BOT_TOKEN": "", "OWNER_TELEGRAM_ID": 0, "WEB_PASSWORD": "pass-123"}


async def test_without_bot_findings_go_to_panel_and_alerts_are_kept():
    from radar.bootstrap.main import build_jobs
    from radar.delivery.adapters.panel_notifier import PanelOnlyNotifier

    c = container(**NO_BOT)
    assert c.bot() is None and isinstance(c.notifier(), PanelOnlyNotifier)
    assert await c.notifier().send("<b>карточка</b>") > 0
    await c.alerts().notify("⚠️ тест")
    assert [a.text for a in c.alert_log().recent()] == ["⚠️ тест"]
    jobs = build_jobs(c)
    assert "bot" not in jobs and {"deliver", "web", "pool", "classify"} <= set(jobs)
    await c.engine().dispose()


async def test_with_bot_alerts_go_to_both():
    from radar.bootstrap.main import build_jobs
    from radar.delivery.adapters.aiogram_notifier import AiogramNotifier

    c = container()
    assert isinstance(c.notifier(), AiogramNotifier) and "bot" in build_jobs(c)
    await c.bot().session.close()
    await c.engine().dispose()
