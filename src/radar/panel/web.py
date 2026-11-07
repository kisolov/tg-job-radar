"""HTTP панели (aiohttp): страница без сборки + JSON-ручки. Вход — только по ссылке /web из бота."""
import dataclasses
import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from uuid import UUID

from aiohttp import web

from radar.delivery.usecases import SetPaused
from radar.panel.auth import SESSION_TTL_S, PanelAuth
from radar.panel.usecases import GetFinding, GetOverview, ListFindings, ListPanelSources, RemoveSourceById
from radar.sources.usecases import AddSource

COOKIE = "radar_session"
CSRF_HEADER = "X-Radar"
STATIC = Path(__file__).parent / "static"
BAD_LINK = ("Ссылка входа недействительна или устарела. "
            "Пришлите боту /web и откройте новую ссылку в течение 10 минут.")


@dataclass
class PanelDeps:
    auth: PanelAuth
    overview: GetOverview
    findings: ListFindings
    finding: GetFinding
    sources: ListPanelSources
    add_source: AddSource
    remove_source: RemoveSourceById
    set_paused: SetPaused
    secure_cookie: bool


def _default(o):
    if isinstance(o, datetime | date):
        return o.isoformat()
    if isinstance(o, UUID):
        return str(o)
    raise TypeError(type(o).__name__)


def _json(data, status: int = 200) -> web.Response:
    if dataclasses.is_dataclass(data):
        data = dataclasses.asdict(data)
    return web.Response(text=json.dumps(data, default=_default, ensure_ascii=False), status=status,
                        content_type="application/json")


def _error(status: int, message: str) -> web.Response:
    return _json({"error": message}, status)


def _int(raw: str, default: int = 1) -> int:
    return int(raw) if raw.isdigit() else default


def build_app(deps: PanelDeps) -> web.Application:
    @web.middleware
    async def guard(request: web.Request, handler):
        if request.path.startswith("/api/"):
            if not deps.auth.check_session(request.cookies.get(COOKIE, "")):
                return _error(401, "нужен вход: команда /web в боте")
            if request.method not in ("GET", "HEAD") and request.headers.get(CSRF_HEADER) != "1":
                return _error(403, "нет заголовка X-Radar")
        try:
            return await handler(request)
        except ValueError as exc:
            return _error(400, str(exc))

    async def index(_: web.Request) -> web.FileResponse:
        return web.FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store"})

    async def login(request: web.Request) -> web.Response:
        session = deps.auth.redeem_login(request.query.get("t", ""))
        if session is None:
            return web.Response(text=BAD_LINK, status=403)
        resp = web.Response(status=302, headers={"Location": "/"})
        resp.set_cookie(COOKIE, session, max_age=SESSION_TTL_S, httponly=True, samesite="Lax",
                        secure=deps.secure_cookie, path="/")
        return resp

    async def overview(_: web.Request) -> web.Response:
        return _json(await deps.overview.execute())

    async def findings(request: web.Request) -> web.Response:
        q = request.query
        page = await deps.findings.execute(tab=q.get("tab", "all"), kind=q.get("kind") or None,
                                           period=q.get("period", "7d"), q=q.get("q", ""),
                                           page=_int(q.get("page", "1")))
        return _json(page)

    async def finding(request: web.Request) -> web.Response:
        raw = request.match_info["id"]
        detail = await deps.finding.execute(int(raw)) if raw.isdigit() else None
        return _json(detail) if detail else _error(404, "находка не найдена")

    async def sources(request: web.Request) -> web.Response:
        q = request.query
        page, counts = await deps.sources.execute(tab=q.get("tab", "all"), kind=q.get("kind") or None,
                                                  sort=q.get("sort", "found"), page=_int(q.get("page", "1")))
        return _json({"page": dataclasses.asdict(page), "counts": dataclasses.asdict(counts)})

    async def add_sources(request: web.Request) -> web.Response:
        body = await request.json()
        return _json(await deps.add_source.execute(str(body.get("text", ""))))

    async def remove_source(request: web.Request) -> web.Response:
        raw = request.match_info["id"]
        ok = raw.isdigit() and await deps.remove_source.execute(int(raw))
        return _json({"ok": True}) if ok else _error(404, "источник не найден")

    async def delivery(request: web.Request) -> web.Response:
        body = await request.json()
        await deps.set_paused.execute(bool(body.get("paused")))
        return _json({"paused": bool(body.get("paused"))})

    app = web.Application(middlewares=[guard])
    app.add_routes([
        web.get("/", index),
        web.get("/login", login),
        web.static("/static", STATIC),
        web.get("/api/overview", overview),
        web.get("/api/findings", findings),
        web.get("/api/findings/{id}", finding),
        web.get("/api/sources", sources),
        web.post("/api/sources", add_sources),
        web.delete("/api/sources/{id}", remove_source),
        web.post("/api/delivery", delivery),
    ])
    return app
