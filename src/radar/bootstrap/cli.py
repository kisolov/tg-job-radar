"""radar CLI: управление аккаунтами и источниками без бота."""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from radar.accounts.usecases import InvalidAccountPayload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="radar")
    groups = parser.add_subparsers(dest="group", required=True)

    acc = groups.add_parser("accounts", help="пул аккаунтов-читателей").add_subparsers(dest="cmd", required=True)
    imp = acc.add_parser("import", help="импорт аккаунта из JSON (phone, session_str|session, app_id, app_hash)")
    imp.add_argument("file", type=Path)
    login = acc.add_parser("login", help="вход по коду (код и 2FA вводит человек)")
    login.add_argument("--phone", required=True)
    login.add_argument("--api-id", type=int)
    login.add_argument("--api-hash")
    acc.add_parser("list", help="список аккаунтов")
    dis = acc.add_parser("disable", help="отключить аккаунт")
    dis.add_argument("phone")

    src = groups.add_parser("sources", help="каталог источников").add_subparsers(dest="cmd", required=True)
    simp = src.add_parser("import", help="импорт стартового списка (строка: [!]@name | t.me/...)")
    simp.add_argument("file", type=Path)
    sadd = src.add_parser("add", help="добавить источники (ссылки через пробел)")
    sadd.add_argument("links", nargs="+")
    ssearch = src.add_parser("search", help="глобальный поиск Telegram; находки → кандидаты")
    ssearch.add_argument("queries", nargs="+", help="запросы (каждый в кавычках)")
    return parser


async def run(argv: list[str], container) -> int:
    args = build_parser().parse_args(argv)
    if args.group == "accounts":
        return await _accounts(args, container)
    if args.group == "sources":
        return await _sources(args, container)
    return 2


async def _sources(args, c) -> int:
    if args.cmd == "import":
        r = await c.import_seeds().execute(args.file)
        print(f"добавлено {r.added}, дублей {r.duplicates}, нераспознано {r.invalid}")
    elif args.cmd == "add":
        r = await c.add_source().execute(" ".join(args.links))
        print(f"добавлено: {', '.join(r.added) or '—'}; уже были: {', '.join(r.duplicates) or '—'}")
    elif args.cmd == "search":
        r = await c.search_sources().execute(args.queries)
        print(f"найдено новых {len(r.added)}, уже были {len(r.duplicates)}")
        for ref in r.added:
            print(f"  + {ref}")
    return 0


async def _accounts(args, c) -> int:
    if args.cmd == "import":
        try:
            account = await c.import_account().execute(args.file.read_bytes())
        except (OSError, InvalidAccountPayload) as exc:
            print(f"Ошибка: {exc}", file=sys.stderr)
            return 1
        print(f"{account.phone}: {account.status.value}")
    elif args.cmd == "login":
        s = c.settings()
        api_id, api_hash = args.api_id or s.TELEGRAM_API_ID, args.api_hash or s.TELEGRAM_API_HASH
        if not api_id or not api_hash:
            print("Нужны --api-id/--api-hash или TELEGRAM_API_ID/TELEGRAM_API_HASH в .env", file=sys.stderr)
            return 1
        account = await c.login_account().execute(args.phone, api_id, api_hash)
        print(f"{account.phone}: {account.status.value}")
    elif args.cmd == "list":
        for a in await c.list_accounts().execute():
            print(f"{a.phone}\t{a.status.value}\tгрупп={a.membership_count}\t"
                  f"вступлений сегодня={a.join.done_today}/{a.join.daily_limit}\t{a.last_error or ''}")
    elif args.cmd == "disable":
        account = await c.disable_account().execute(args.phone)
        print(f"{account.phone}: {account.status.value}" if account else "Аккаунт не найден")
        return 0 if account else 1
    return 0


def main() -> None:
    from radar.bootstrap.di import Container

    build_parser().parse_args(sys.argv[1:])  # --help и ошибки аргументов — до чтения настроек
    container = Container()

    async def _go() -> int:
        try:
            return await run(sys.argv[1:], container)
        finally:
            await container.engine().dispose()

    raise SystemExit(asyncio.run(_go()))


if __name__ == "__main__":
    main()
