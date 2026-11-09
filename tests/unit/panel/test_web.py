from datetime import UTC, datetime

import pytest
from aiohttp.test_utils import TestClient, TestServer

from radar.accounts.adapters.memory_repo import InMemoryAccountRepository
from radar.delivery.usecases import SetPaused
from radar.panel.auth import PanelAuth
from radar.panel.ports import FindingDetail, FindingRow
from radar.panel.usecases import GetFinding, GetOverview, ListFindings, ListPanelSources, RemoveSourceById
from radar.panel.web import COOKIE, DEPS_KEY, PanelDeps, build_app
from radar.screening.adapters.memory_repos import InMemoryUsageRepository
from radar.shared.clock import FakeClock
from radar.sources.adapters.memory_repo import InMemorySourceRepository
from radar.sources.service import SourceService
from radar.sources.usecases import AddSource
from tests.unit.panel.test_usecases import NOW, StubReadModel, runtime

ROW = FindingRow(7, "delivered", "vacancy", "Python-бэкенд", "250к", "удалёнка", "@hr_anna", "Python Jobs", 2,
                 NOW, NOW)


class ReadModel(StubReadModel):
    channels: dict = {}

    async def finding(self, finding_id):
        return FindingDetail(ROW, "текст", "https://t.me/x/1", "подходит", 3, "hr_anna") if finding_id == 7 else None


@pytest.fixture
async def env():
    clock = FakeClock(NOW)
    accounts = InMemoryAccountRepository()
    sources = InMemorySourceRepository(accounts, membership_cap=500)
    service = SourceService(sources=sources, accounts=accounts, aggregator_domains=[])
    rt = runtime()
    rm = ReadModel()
    auth = PanelAuth(b"s" * 32, clock)
    deps = PanelDeps(
        auth=auth, overview=GetOverview(rm, accounts, InMemoryUsageRepository(), rt, clock),
        findings=ListFindings(rm, clock), finding=GetFinding(rm), sources=ListPanelSources(rm, clock),
        add_source=AddSource(service), remove_source=RemoveSourceById(sources, service),
        set_paused=SetPaused(rt), secure_cookie=False, password="pass-123", bot_login=True,
    )
    client = TestClient(TestServer(build_app(deps)))
    await client.start_server()

    async def login():
        r = await client.get(f"/login?t={auth.issue_login()}", allow_redirects=False)
        assert r.status == 302 and r.headers["Location"] == "/"
        return r

    yield client, login, rt, sources
    await client.close()


async def test_api_requires_session_and_page_is_public(env):
    client, login, *_ = env
    assert (await client.get("/api/overview")).status == 401
    page = await client.get("/")
    assert page.status == 200 and "tg-job-radar" in await page.text()
    assert (await client.get("/static/panel.js")).status == 200


async def test_bad_login_link_is_rejected(env):
    client, *_ = env
    r = await client.get("/login?t=forged", allow_redirects=False)
    assert r.status == 403 and "/web" in await r.text()
    assert COOKIE not in r.cookies


async def test_login_sets_httponly_cookie_and_opens_api(env):
    client, login, *_ = env
    r = await login()
    morsel = r.cookies[COOKIE]
    assert morsel["httponly"] and morsel["samesite"] == "Lax"
    o = await (await client.get("/api/overview")).json()
    assert o["day"] == "2026-11-06" and o["counts"]["unique"] == 20 and len(o["week"]) == 7


async def test_findings_endpoints(env):
    client, login, *_ = env
    await login()
    assert (await client.get("/api/findings?tab=delivered&period=today&q=бот&page=2")).status == 200
    assert (await client.get("/api/findings?tab=nope")).status == 400
    d = await (await client.get("/api/findings/7")).json()
    assert d["row"]["title"] == "Python-бэкенд" and d["row"]["created_at"] == NOW.isoformat()
    assert (await client.get("/api/findings/8")).status == 404
    assert (await client.get("/api/findings/abc")).status == 404


async def test_mutations_need_csrf_header(env):
    client, login, rt, sources = env
    await login()
    assert (await client.post("/api/delivery", json={"paused": True})).status == 403
    r = await client.post("/api/delivery", json={"paused": True}, headers={"X-Radar": "1"})
    assert r.status == 200 and await rt.paused() is True

    r = await client.post("/api/sources", json={"text": "t.me/pyjobs @remote_it"}, headers={"X-Radar": "1"})
    body = await r.json()
    assert body["added"] == ["pyjobs", "remote_it"] and body["duplicates"] == []
    s = await sources.find("pyjobs")
    assert (await client.delete(f"/api/sources/{s.id}", headers={"X-Radar": "1"})).status == 200
    assert (await client.delete("/api/sources/999", headers={"X-Radar": "1"})).status == 404


async def test_sources_endpoint(env):
    client, login, *_ = env
    await login()
    body = await (await client.get("/api/sources?tab=reading&kind=group&sort=read&page=1")).json()
    assert body["page"]["total"] == 2 and body["counts"]["reading"] == 10
    assert body["page"]["items"][0]["account_phone"] == "+7 900 ••• 45 67"
    assert (await client.get("/api/sources?sort=bad")).status == 400


def test_now_is_utc():
    assert datetime.now(UTC).tzinfo is UTC


async def test_password_login_sets_session(env):
    client, *_ = env
    r = await client.get("/api/overview")
    assert r.status == 401 and set((await r.json())["login"]) == {"bot", "password"}
    bad = await client.post("/login", json={"password": "nope"}, allow_redirects=False)
    assert bad.status == 403 and COOKIE not in bad.cookies
    ok = await client.post("/login", json={"password": "pass-123"}, allow_redirects=False)
    assert ok.status == 200 and COOKIE in ok.cookies
    assert (await client.get("/api/overview")).status == 200


async def test_password_login_disabled_without_password(env):
    client, *_ = env
    client.server.app[DEPS_KEY].password = ""
    r = await client.post("/login", json={"password": ""}, allow_redirects=False)
    assert r.status == 403
    assert (await (await client.get("/api/overview")).json())["login"] == ["bot"]
