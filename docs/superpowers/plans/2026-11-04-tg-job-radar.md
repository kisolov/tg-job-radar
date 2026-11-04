# tg-job-radar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Userbot-пул читает максимум русскоязычных Telegram-чатов, отбирает вакансии и заказы под требования Алексея и сразу присылает каждую находку с прямым контактом в личку через бота.

**Architecture:** Один процесс (asyncio): пул Telethon-клиентов (по одному на аккаунт) читает группы live и опрашивает каналы; сообщения проходят предфильтр → дедуп-кластеризацию (advisory lock) → пакетную LLM-классификацию (NeuroAPI) → доставку ботом aiogram с conditional claim. Модули `accounts / sources / ingest / screening / findings / delivery`, слои — usecase везде как вход, service только где есть правила, порты там, где есть фейк.

**Tech Stack:** Python 3.12, uv, Telethon ≥1.36, aiogram 3, SQLAlchemy 2 async + asyncpg, Alembic, PostgreSQL 16, pydantic-settings, dependency-injector, httpx, cryptography (Fernet), pytest + pytest-asyncio, Docker Compose.

**Spec:** `docs/superpowers/specs/2026-11-04-tg-job-radar-design.md` (включая `## Domain design`). Образец пула аккаунтов: `~/projects/infomir/infomir-backend/services/lot-parsing` (`src/parsing/usecases/import_account.py`, `join_scheduler.py`, `cli.py`, `adapters/fernet_secret_box.py`, `device_profiles.py`, `telethon_session_probe.py`, `telegram_userbot_source.py`).

## Global Constraints

- Один пользователь: все команды бота принимаются только от `OWNER_TELEGRAM_ID` (R11); остальным — молчание.
- Бот никому, кроме владельца, не пишет; userbot ничего не пишет никуда.
- Только русскоязычные сообщения и источники.
- Сообщение, где вакансия — только ссылка на агрегатор (домены из `AGGREGATOR_DOMAINS`, дефолт: `hh.ru, career.habr.com, getmatch.ru, superjob.ru, rabota.ru, zarplata.ru, trudvsem.ru, geekjob.ru, careerspace.app`) — отбрасывается.
- Секреты аккаунта в БД только шифрованные (Fernet, `USERBOT_STORE_KEY`); 2FA-пароль, device-секреты не хранятся и не логируются.
- Вступления: дефолт 25–30 в сутки на аккаунт (суточный лимит выбирается случайно в этом диапазоне раз в сутки), интервал 300–600 с с джиттером; автоторможение на `FloodWait`.
- LLM: только через NeuroAPI (OpenAI-совместимый, `NEUROAPI_BASE_URL`, `NEUROAPI_KEY`, `NEUROAPI_MODEL`); всё, что влияет на расход, — настройка.
- Любой порт с фейком проходит те же контрактные тесты, что и реальный адаптер.
- Каждая задача обновляет `docs/services/radar/{ARCHITECTURE,DATA_FLOWS,INVARIANTS,FAILURE_MODES}.md` для своего модуля в том же коммите (clean-backend-documentation).
- Коммиты без строки `Co-Authored-By` и без упоминаний Claude.

## Review Focus

1. **Сообщение без текста / только медиа с подписью / огромный текст (>4096)** — медиа без подписи отбрасывается предфильтром, подпись считается текстом, длинный текст обрезается до `LLM_MAX_CHARS` перед LLM и до лимита Telegram в карточке. Тесты: Task 6 (`test_caption_counts_as_text`, `test_media_without_text_dropped`), Task 9 (`test_card_truncated_to_telegram_limit`).
2. **LLM вернул мусор / не тот JSON / меньше элементов, чем в пакете / таймаут** — пакет не теряется: невалидный ответ → один повтор, затем кластеры остаются `pending` до следующего цикла; пропущенные id остаются `pending`. Тест: Task 7 (`test_malformed_response_keeps_pending`, `test_missing_ids_stay_pending`).
3. **Автор группы без username** — контакт = `tg://user?id=<id>` ссылка, если это пользователь; канал/анонимный админ → «контакта нет» + ссылка на сообщение. Тест: Task 9 (`test_contact_fallbacks`).
4. **Источник удалён / стал приватным / аккаунт кикнут из группы** — источник → `dead`, закрепление снимается, счётчик членств аккаунта уменьшается, работа остальных не прерывается. Тест: Task 5 (`test_channel_private_marks_source_dead`).
5. **Перезапуск процесса посреди работы** — курсоры опроса и claim'ы в БД: после рестарта нет повторной доставки и нет повторного LLM для уже классифицированных; claim без отправки старше 10 мин переотправляется. Тест: Task 8 (`test_stale_claim_redelivered_once`), Task 5 (`test_poll_resumes_from_cursor`).

---

## File Structure

```
pyproject.toml  Dockerfile  docker-compose.yml  .env.example  alembic.ini  README.md
migrations/env.py  migrations/versions/0001_initial.py
seeds/sources.txt
src/radar/
  shared/settings.py        # pydantic-settings, все настройки
  shared/db.py              # engine, session factory, transaction()
  shared/clock.py           # Clock порт + SystemClock/FakeClock
  shared/models.py          # SQLAlchemy-модели всех таблиц
  accounts/entities.py      # Account, AccountStatus, Pacer, DeviceProfile
  accounts/ports.py         # AccountRepository, SecretBox, SessionProbe, DeviceProfileProvider, AlertSink
  accounts/service.py       # AccountService: темп, статусы
  accounts/usecases.py      # ImportAccount, LoginAccount, ReportFlood, ReportAccountFailure
  accounts/adapters/{sqlalchemy_repo,memory_repo,fernet_box,device_profiles,session_probe}.py
  sources/entities.py       # Source, SourceKind, SourceStatus
  sources/ports.py          # SourceRepository
  sources/service.py        # SourceService: закрепление, кандидаты, relay-эвристика
  sources/usecases.py       # AddSource, RemoveSource, ImportSeeds, AssignWork, ReleaseAccountSources
  sources/links.py          # извлечение ссылок на чаты из текста
  sources/adapters/{sqlalchemy_repo,memory_repo}.py
  ingest/ports.py           # TelegramGateway, IncomingMessage, TG-исключения
  ingest/usecases.py        # ReceiveMessage, PollChannels, RunJoinQueue, RunResolveQueue
  ingest/adapters/{telethon_gateway,fake_gateway}.py
  ingest/pool.py            # PoolRunner: задача на active-аккаунт
  screening/prefilter.py    # чистые функции предфильтра
  screening/ports.py        # LlmClassifier, UsageRepository, RequirementsRepository
  screening/service.py      # ScreeningService: бюджет, сборка пакета
  screening/usecases.py     # ClassifyPending (воркер с окном пакета)
  screening/adapters/{neuroapi_classifier,fake_classifier,sqlalchemy_repos,memory_repos}.py
  findings/similarity.py    # normalize(), fingerprint(), shingles(), jaccard()
  findings/entities.py      # Finding, FindingStatus, Copy, Classification
  findings/ports.py         # FindingRepository
  findings/service.py       # FindingService: кластер, claim
  findings/usecases.py      # ClusterMessage, DeliverAccepted, RedeliverStale, AttachCopyEdit
  findings/adapters/{sqlalchemy_repo,memory_repo}.py
  delivery/ports.py         # Notifier
  delivery/card.py          # render_card(finding) -> str
  delivery/usecases.py      # SendCard, EditCard, StatusReport, admin-операции
  delivery/bot.py           # aiogram Router, OwnerOnly-фильтр, команды
  delivery/adapters/{aiogram_notifier,fake_notifier}.py
  bootstrap/di.py  bootstrap/main.py  bootstrap/cli.py
tests/
  conftest.py               # pg-фикстура (db-test из compose), truncate per test, FakeClock
  contract/                 # контрактные тесты репозиториев: параметризованы [sqlalchemy, memory]
  unit/<module>/...
  e2e/test_pipeline.py      # весь конвейер на фейках + реальная БД
docs/services/radar/{ARCHITECTURE,DATA_FLOWS,INVARIANTS,FAILURE_MODES}.md
```

Таблицы (одна миграция `0001`, дописывается в задачах 2–8 до первого деплоя; после деплоя — только новые миграции):
`accounts`, `sources`, `messages(source_id, message_id, seen_at)` unique, `findings`, `finding_copies`, `requirements(version, text, created_at)`, `daily_stats(day, read, passed_prefilter, llm_items, findings, requests, prompt_tokens, completion_tokens, reserved)`, `settings_overrides(key, value)`.

---

### Task 1: Каркас проекта, настройки, БД, тестовая инфраструктура

**Files:**
- Create: `pyproject.toml`, `Dockerfile`, `docker-compose.yml`, `.env.example`, `alembic.ini`, `migrations/env.py`, `migrations/versions/0001_initial.py` (пустая схема), `src/radar/shared/{settings,db,clock,models}.py`, `tests/conftest.py`, `docs/services/radar/*.md` (каркас 4 файлов)
- Test: `tests/unit/shared/test_settings.py`, `tests/unit/shared/test_db.py`

**Interfaces:**
- Produces: `Settings` (все поля ниже), `get_settings()`; `make_engine(url)`, `session_factory`, `async with transaction(sf) as session` (commit/rollback); `Clock.now() -> datetime (UTC)`, `FakeClock(now).advance(seconds)`; фикстуры `pg_sessionmaker`, `clock`.

`Settings` поля и дефолты: `DATABASE_URL`, `OWNER_TELEGRAM_ID:int`, `BOT_TOKEN`, `USERBOT_STORE_KEY`, `TELEGRAM_API_ID:int|None`, `TELEGRAM_API_HASH:str|None`, `USERBOT_DEVICE_PROFILE="default"`, `JOIN_DAILY_MIN=25`, `JOIN_DAILY_MAX=30`, `JOIN_INTERVAL_MIN_S=300`, `JOIN_INTERVAL_MAX_S=600`, `RESOLVE_INTERVAL_S=60`, `THROTTLE_FACTOR=1.5`, `THROTTLE_MAX_FACTOR=8.0`, `THROTTLE_LIMIT_STEP=5`, `THROTTLE_LIMIT_FLOOR=5`, `THROTTLE_RECOVERY_DAYS=3`, `MEMBERSHIP_CAP=500`, `CHANNEL_POLL_INTERVAL_S=300`, `NEUROAPI_BASE_URL`, `NEUROAPI_KEY`, `NEUROAPI_MODEL`, `LLM_BATCH_SIZE=10`, `LLM_BATCH_WAIT_S=60`, `LLM_MAX_CHARS=1500`, `LLM_DAILY_TOKEN_LIMIT=2_000_000`, `LLM_PRICE_PER_1K_PROMPT=0.0`, `LLM_PRICE_PER_1K_COMPLETION=0.0`, `PREFILTER_MIN_LEN=60`, `PREFILTER_MARKERS` (список, дефолт — Task 6), `PREFILTER_STOPWORDS` (Task 6), `AGGREGATOR_DOMAINS` (Global Constraints), `DEDUP_WINDOW_DAYS=7`, `DEDUP_JACCARD=0.6`, `CLAIM_STALE_S=600`, `MESSAGES_RETENTION_DAYS=7`.

- [ ] **Step 1:** `uv init`, зависимости из Tech Stack, `[tool.pytest.ini_options] asyncio_mode="auto"`; `docker-compose.yml`: сервисы `app`, `db` (postgres:16), `db-test` (postgres:16, порт `55432`, tmpfs).
- [ ] **Step 2: failing tests**

```python
def test_defaults(monkeypatch):  # минимальный env
    s = Settings(_env_file=None, DATABASE_URL="postgresql+asyncpg://x", OWNER_TELEGRAM_ID=1, BOT_TOKEN="t", USERBOT_STORE_KEY="k", NEUROAPI_BASE_URL="u", NEUROAPI_KEY="k", NEUROAPI_MODEL="m")
    assert (s.JOIN_DAILY_MIN, s.JOIN_DAILY_MAX) == (25, 30)
    assert s.LLM_BATCH_WAIT_S == 60 and "hh.ru" in s.AGGREGATOR_DOMAINS

async def test_transaction_rolls_back(pg_sessionmaker): ...  # исключение внутри transaction → строки нет
```
- [ ] **Step 3:** `docker compose up -d db-test && uv run pytest tests/unit/shared -v` → FAIL (нет модулей).
- [ ] **Step 4:** Реализовать `settings.py`, `db.py`, `clock.py`, conftest (`alembic upgrade head` один раз на сессию, `TRUNCATE ... RESTART IDENTITY CASCADE` перед каждым тестом).
- [ ] **Step 5:** `uv run pytest -v` → PASS.
- [ ] **Step 6:** commit `feat: project skeleton`.

---

### Task 2: accounts — сущность Account и автоторможение (чистая логика)

**Files:** Create `src/radar/accounts/entities.py`; Test `tests/unit/accounts/test_pacer.py`

**Interfaces:**
- Produces:
  - `AccountStatus(str, Enum)`: `active, flood_wait, banned, unauthorized, disabled`
  - `@dataclass Pacer`: `interval_factor: float=1.0`, `daily_limit: int`, `base_daily_limit: int`, `done_today: int=0`, `day: date`, `next_allowed_at: datetime`, `last_flood_at: datetime|None`, `last_recovery_at: datetime|None`
  - `Pacer.can_act(now) -> bool`, `Pacer.record_action(now, rng) -> None`, `Pacer.record_flood(now, seconds) -> None`, `Pacer.roll_day(now, rng) -> None`
  - `@dataclass Account`: `id: UUID, phone, api_id, api_hash_enc, session_enc, device_profile, status, status_until, last_error, membership_count: int, join: Pacer, resolve: Pacer, version: int`
  - `Account.can_join(now) -> bool` (= `status==active and membership_count < cap and join.can_act(now)`), `Account.can_resolve(now)`

Правила (из спека, раздел 5):
- `roll_day`: на смене даты UTC `done_today=0`; `base_daily_limit = rng.randint(JOIN_DAILY_MIN, JOIN_DAILY_MAX)`; восстановление: если `last_flood_at` старше `THROTTLE_RECOVERY_DAYS` суток и с `last_recovery_at` прошло ≥1 сут — `interval_factor = max(1, factor / THROTTLE_FACTOR)`, `daily_limit = min(base, daily_limit + THROTTLE_LIMIT_STEP)`.
- `record_action`: `done_today += 1`; `next_allowed_at = now + uniform(INTERVAL_MIN, INTERVAL_MAX) * interval_factor`.
- `record_flood(seconds)`: `next_allowed_at = now + seconds`; `interval_factor = min(MAX_FACTOR, factor * THROTTLE_FACTOR)`; `daily_limit = max(FLOOR, daily_limit - STEP)`; `last_flood_at = now`.
- Для `resolve`-Pacer интервал = `RESOLVE_INTERVAL_S` × factor, лимит суток не ограничивает (`daily_limit` = большое число из настроек не нужно — `can_act` для resolve проверяет только `next_allowed_at`).

- [ ] **Step 1: failing tests**

```python
def test_daily_limit_within_25_30(): ...      # roll_day c rng seed → 25 <= base <= 30, daily_limit == base
def test_cannot_exceed_daily_limit(): ...     # после daily_limit record_action → can_act False до следующих суток
def test_interval_respected(): ...            # сразу после action can_act False; через INTERVAL_MAX*factor — True
def test_flood_throttles(): ...               # flood(120): factor 1.5, limit base-5, can_act False 119 с, True после 120 с + интервала нет
def test_flood_floor_and_cap(): ...           # 10 флудов: factor == 8.0, limit == 5
def test_recovery_after_quiet_days(): ...     # flood, затем 3 суток roll_day → factor 1.0, limit base-0 шагами по 5 в сутки
def test_banned_cannot_join(): ...
def test_membership_cap_blocks_join(): ...    # membership_count == 500 → can_join False
```
- [ ] **Step 2:** `uv run pytest tests/unit/accounts/test_pacer.py -v` → FAIL.
- [ ] **Step 3:** Реализовать; константы — из `Settings`, передаются в методы через `PacingPolicy` dataclass (`from_settings(s)`), сущность не читает env.
- [ ] **Step 4:** PASS. **Step 5:** commit `feat(accounts): pacing with auto-throttle`.

---

### Task 3: accounts — репозиторий, шифрование, импорт/логин, CLI

**Files:** Create `accounts/ports.py`, `accounts/service.py`, `accounts/usecases.py`, `accounts/adapters/*.py`, `bootstrap/cli.py` (группа `accounts`), модель `accounts` в `shared/models.py` + миграция; Test `tests/contract/test_account_repository.py`, `tests/unit/accounts/test_import_account.py`, `tests/unit/accounts/test_account_service.py`

**Interfaces:**
- Consumes: `Account`, `Pacer`, `AccountStatus` (Task 2).
- Produces:
  - `AccountRepository`: `add(a) -> None` (unique phone → `AccountExists`), `get(id) -> Account|None`, `get_by_phone(phone)`, `list_active() -> list[Account]`, `list_all()`, `save(a) -> None` — **conditional by version**: `UPDATE … WHERE id=:id AND version=:v`, `version+1`; 0 строк → `StaleAccount`.
  - `SecretBox.encrypt/decrypt` (перенос `fernet_secret_box.py`), `DeviceProfileProvider.get(name)` (перенос, только `default`), `SessionProbe.check(...)` (перенос), `AlertSink.notify(text)` (реализация — Notifier из Task 9; здесь `LogAlertSink`).
  - `AccountService`: `apply_flood(account_id, action: Literal["join","resolve"], seconds)`, `mark_failed(account_id, status, error)` (алерт на `banned/unauthorized`, на `flood_wait > 3600`), `record_action(account_id, action)` — каждый: load → mutate → `save` с повтором до 3 раз на `StaleAccount`.
  - usecases `ImportAccount.execute(json_bytes) -> Account` и `LoginAccount.execute(phone)` — поведение 1:1 с infomir (берутся только `phone`, `session_str|session`, `app_id`, `app_hash`; неавторизована → `unauthorized`).
  - CLI: `radar accounts import FILE`, `radar accounts login --phone P`, `radar accounts list`, `radar accounts disable PHONE`.

- [ ] **Step 1: failing contract tests** (параметр `repo` ∈ {sqlalchemy, memory}):

```python
async def test_save_with_stale_version_raises(repo): ...   # два get одного аккаунта; save первого OK, save второго → StaleAccount
async def test_memory_repo_returns_copies(repo): ...       # изменение полученного объекта без save не видно при следующем get
async def test_list_active_excludes_banned(repo): ...
async def test_duplicate_phone(repo): ...
```
- [ ] **Step 2: failing unit tests**: `test_import_takes_only_allowed_fields` (лишние поля не в БД и не в caplog), `test_unauthorized_session_saved_as_unauthorized`, `test_ban_alerts_once`, `test_flood_over_hour_alerts`, `test_secrets_encrypted_at_rest` (в строке БД нет plain session).
- [ ] **Step 3:** run → FAIL. **Step 4:** реализовать (перенос из infomir с переименованием). **Step 5:** run → PASS.
- [ ] **Step 6:** docs (INVARIANTS: R5, R6, шифрование) → commit `feat(accounts): pool storage, import, login`.

---

### Task 4: sources — каталог, закрепление, лимит членства

**Files:** Create `sources/{entities,ports,service,usecases,links}.py`, `sources/adapters/*`, модель `sources` + миграция; Test `tests/contract/test_source_repository.py`, `tests/unit/sources/test_links.py`, `tests/unit/sources/test_assign.py`

**Interfaces:**
- Consumes: `AccountRepository`, `Account.membership_count`.
- Produces:
  - `SourceKind`: `channel, group`; `SourceStatus`: `candidate, resolving, active, dead, rejected`
  - `@dataclass Source`: `id:int, username:str|None, invite_hash:str|None, peer_id:int|None, access_hash:int|None, kind:SourceKind|None, title, status, assigned_account_id:UUID|None, joined:bool, last_message_id:int, found_count:int, relay_score:float, added_by: Literal["seed","discovery","owner"], priority:int, version:int`
  - `normalize_username(s: str) -> str|None` (`@Foo`, `t.me/Foo`, `https://t.me/s/Foo` → `foo`; `t.me/+hash`/`joinchat/hash` → invite) in `links.py`; `extract_chat_links(text: str) -> list[str]`.
  - `SourceRepository`: `add_candidate(username|invite, added_by, priority) -> Source|None` (unique по `username` и по `peer_id` → `None` при дубле, **R7**), `get`, `next_to_resolve(limit)`, `set_resolved(id, peer_id, access_hash, kind, title)`, `mark(id, status)`, `assign(source_id, account_id) -> bool` — **одна транзакция**: `UPDATE sources SET assigned_account_id=:a WHERE id=:s AND assigned_account_id IS NULL`; если 1 строка и `kind=group` → `UPDATE accounts SET membership_count=membership_count+1, version=version+1 WHERE id=:a AND membership_count < :cap`; 0 строк → rollback, `False` (**R3, R4**). `release(source_id)` — обратное, декремент. `release_all_of(account_id)`. `list_assigned(account_id, kind)`, `set_cursor(id, last_message_id)` (только вперёд: `WHERE last_message_id < :m`).
  - usecases: `AddSource(owner)`, `RemoveSource`, `ImportSeeds(path)` (по строке, комментарии `#`, priority: группа-фриланс/вакансии 10, прочее 5 — задаётся префиксом строки `!`), `AssignWork.execute()` — раздаёт незакреплённые `active` каналы и группы `active`-аккаунтам round-robin по наименьшей загрузке, `ReleaseAccountSources(account_id)`.

- [ ] **Step 1: failing tests**

```python
@pytest.mark.parametrize("raw,exp", [("@Freelance_IT","freelance_it"),("https://t.me/s/jobs_py","jobs_py"),("t.me/+AbC","+AbC"),("http://example.com",None)])
def test_normalize_username(raw, exp): ...
def test_extract_chat_links(): ...                      # из текста с 3 ссылками и email → 3 ссылки, без email
async def test_duplicate_candidate_ignored(repo): ...   # @a и t.me/a → один источник
async def test_assign_only_once(repo): ...              # gather(assign(s,a1), assign(s,a2)) → ровно один True (sqlalchemy: два соединения)
async def test_membership_cap(repo): ...                # аккаунт с count=cap-1: две группы → одна закреплена
async def test_release_all_of_account(repo): ...        # счётчик 0, источники свободны
async def test_cursor_never_moves_back(repo): ...
```
- [ ] **Step 2:** FAIL. **Step 3:** реализовать. **Step 4:** PASS.
- [ ] **Step 5:** docs (R3, R4, R7) → commit `feat(sources): catalog and assignment`.

---

### Task 5: ingest — шлюз Telegram, пул, опрос, вступление, резолв

**Files:** Create `ingest/{ports,usecases,pool}.py`, `ingest/adapters/{telethon_gateway,fake_gateway}.py`, модель `messages` + миграция; Test `tests/unit/ingest/test_receive.py`, `test_join_queue.py`, `test_resolve_queue.py`, `test_poll.py`, `test_pool.py`

**Interfaces:**
- Consumes: `AccountService`, `SourceRepository`, `Account`.
- Produces:
  - `@dataclass IncomingMessage`: `source_id:int, message_id:int, text:str, date:datetime, sender_id:int|None, sender_username:str|None, sender_is_user:bool, fwd_from_username:str|None, link:str` (`https://t.me/<username>/<id>` или `https://t.me/c/<peer>/<id>`)
  - Исключения шлюза: `TgFlood(seconds)`, `TgBanned`, `TgUnauthorized`, `TgSourceGone` (private/invalid/kicked), `TgJoinRequested`.
  - `TelegramGateway` (на один аккаунт): `start(account) -> None`, `stop()`, `on_message(cb)` (live для закреплённых групп; фильтрует по `peer_id` закреплённых), `fetch_new(source, min_id, limit=100) -> list[IncomingMessage]`, `resolve(username|invite) -> (peer_id, access_hash, kind, title)`, `join(source) -> None`, `leave(source)`, `search(query) -> list[tuple[str, str, SourceKind]]` (`contacts.SearchRequest`, username/title/kind; паузится resolve-Pacer'ом). CLI `radar sources search "<запрос>"` печатает результаты и добавляет их кандидатами с `added_by="seed"`.
  - `ReceiveMessage.execute(msg) -> bool`: `INSERT INTO messages … ON CONFLICT DO NOTHING`; `False` → стоп (**R2**); `True` → `pipeline.submit(msg)` (порт `MessageSink`, реализует Task 10; в тестах — список).
  - `PollChannels.execute(account_id)`: для закреплённых каналов, у которых прошло `CHANNEL_POLL_INTERVAL_S`, `fetch_new(min_id=cursor)` → `ReceiveMessage` на каждое по возрастанию id → `set_cursor`.
  - `RunJoinQueue.tick(account_id)`: если `account.can_join(now)` — берёт закреплённую незаджойненную группу, `join`, `record_action("join")`; `TgFlood` → `apply_flood("join")`; `TgSourceGone` → source `dead` + `release`; `TgJoinRequested` → source `rejected`, `release`.
  - `RunResolveQueue.tick(account_id)`: `can_resolve` → `next_to_resolve(1)` по priority desc → `resolve` → `set_resolved` / `dead`; flood → `apply_flood("resolve")`.
  - `PoolRunner`: на каждый `active` аккаунт — свой gateway и одна корутина-цикл (join tick, resolve tick, poll) с `asyncio.sleep(5)`; `TgBanned/TgUnauthorized` → `mark_failed` + `ReleaseAccountSources` + остановка только этой корутины; раз в минуту подхватывает новые `active` аккаунты (горячее добавление).
  - `telethon_gateway.py` — маппинг ошибок Telethon как в infomir `telegram_userbot_source.py`: `FloodWaitError`→`TgFlood`, `UserDeactivated*/AuthKey*/SessionRevoked`→`TgBanned|TgUnauthorized`, `ChannelPrivateError/UsernameInvalid/UsernameNotOccupied/ChannelInvalid/UserBannedInChannel`→`TgSourceGone`, `InviteRequestSentError`→`TgJoinRequested`, `ChannelsTooMuchError`→`TgFlood(3600)` + выставить `membership_count=cap`. Резолв по username — `contacts.ResolveUsernameRequest`; по invite — `CheckChatInviteRequest`/`ImportChatInviteRequest`.

- [ ] **Step 1: failing tests (FakeGateway + FakeClock + реальная БД)**

```python
async def test_same_message_twice_processed_once(): ...       # live + poll одного (source,id) → sink получил 1
async def test_poll_resumes_from_cursor(): ...                # курсор 10, gateway отдаёт 11..13 → cursor 13; «рестарт» → fetch_new(min_id=13)
async def test_join_respects_pacer(): ...                     # 2 группы, tick, tick сразу → 1 join
async def test_flood_on_join_throttles_account(): ...         # TgFlood(300) → account.join.interval_factor == 1.5
async def test_channel_private_marks_source_dead(): ...       # Review Focus 4: dead, assigned None, membership_count -1, корутина жива
async def test_ban_stops_only_that_account(): ...             # 2 аккаунта, у одного TgBanned → status banned, алерт, второй продолжает poll; его группы освобождены
async def test_resolve_priority_order(): ...                  # priority 10 резолвится раньше 5
```
- [ ] **Step 2:** FAIL. **Step 3:** реализовать. **Step 4:** PASS.
- [ ] **Step 5:** ручная проверка с реальным аккаунтом не здесь (Task 12). docs (DATA_FLOWS: чтение; FAILURE_MODES: ошибки Telegram) → commit `feat(ingest): userbot pool, polling, joining`.

---

### Task 6: screening — предфильтр

**Files:** Create `screening/prefilter.py`; Test `tests/unit/screening/test_prefilter.py`

**Interfaces:**
- Produces: `@dataclass PrefilterConfig` (`min_len, markers, stopwords, aggregator_domains`, `from_settings`); `prefilter(text: str|None, cfg) -> PrefilterVerdict` где `PrefilterVerdict = Literal["pass","empty","short","not_russian","no_marker","stopword","aggregator_only"]`; `is_russian(text) -> bool` (доля кириллицы среди букв ≥ 0.5); `is_aggregator_only(text, domains) -> bool` (есть ссылка на домен агрегатора и после удаления ссылок, хэштегов и эмодзи остаётся < 200 символов **или** нет ни одного @username / t.me/ ссылки на человека).

Дефолт `PREFILTER_MARKERS` (подстроки, регистр игнор): `ищем, ищу разработчик, ищу программист, нужен, нужна, нужны, требуется, вакансия, ваканси, заказ, проект, тз, техзадан, бюджет, оплата, ставка, зп, з/п, оклад, фриланс, подряд, сделать бота, разработать, доработать, удалён, remote`.
Дефолт `PREFILTER_STOPWORDS`: `ищу работу, #резюме, #ищуработу, резюме кандидата, курс, обучение с нуля, вебинар, без опыта, пассивный доход, арбитраж, p2p, заработок от, казино, ставки на спорт`.

- [ ] **Step 1: failing tests**

```python
def test_media_without_text_dropped(): assert prefilter(None, cfg) == "empty"
def test_caption_counts_as_text(): ...                       # подпись медиа с вакансией → "pass"
def test_hh_link_only_dropped(): assert prefilter("Python dev 🔥 https://hh.ru/vacancy/123 #python #вакансия", cfg) == "aggregator_only"
def test_hh_link_with_full_text_and_contact_passes(): ...    # длинное описание + @hr_anna + hh-ссылка → "pass"
def test_english_dropped(): ...                              # "We are hiring Python developer..." → "not_russian"
def test_resume_dropped(): ...                               # "#резюме Ищу работу Python..." → "stopword"
def test_order_passes(): assert prefilter("Нужен бот для записи клиентов в салон, бюджет 30к, пишите @ivan", cfg) == "pass"
def test_short_dropped(): ...
```
- [ ] **Step 2:** FAIL. **Step 3:** реализовать. **Step 4:** PASS. **Step 5:** commit `feat(screening): prefilter`.

---

### Task 7: screening — требования, бюджет, NeuroAPI-классификатор

**Files:** Create `screening/{ports,service}.py`, `screening/adapters/*`, модели `requirements`, `daily_stats` + миграция; Test `tests/unit/screening/test_classifier_adapter.py` (httpx MockTransport), `tests/contract/test_usage_repository.py`, `tests/unit/screening/test_budget.py`

**Interfaces:**
- Produces:
  - `@dataclass Classification`: `relevant:bool, kind: Literal["vacancy","project"]|None, summary:str, money:str|None, work_format:str|None, contact:str|None, reason:str`
  - `LlmClassifier.classify(items: list[tuple[str,str]], requirements: str) -> tuple[dict[str, Classification], Usage]` (`id → результат`; отсутствующие id не в словаре); `Usage(prompt_tokens, completion_tokens)`; исключение `LlmUnavailable`.
  - `NeuroApiClassifier(base_url, key, model, timeout=60)`: `POST {base}/chat/completions`, `response_format={"type":"json_object"}`, `temperature=0`; system = требования + инструкция; user = JSON `[{"id","text"}]` (текст обрезан до `LLM_MAX_CHARS`); ожидаемый ответ `{"items":[{"id","relevant","kind","summary","money","format","contact","reason"}]}`; невалидный JSON → 1 повтор → `LlmUnavailable`.
  - `RequirementsRepository`: `current() -> (version:int, text:str)`, `set(text) -> int`; миграция сидит версию 1 текстом из спека, раздел 4 («Присылать» / «Не присылать», с фронтендом и без нижней границы денег).
  - `UsageRepository`: `reserve(day, estimated_tokens, limit) -> bool` — `UPDATE daily_stats SET reserved=reserved+:e WHERE day=:d AND prompt_tokens+completion_tokens+reserved+:e <= :limit` (upsert строки дня); `commit_usage(day, reserved, usage)` — снять резерв, прибавить факт (**R8**, перелёт ≤ одного пакета — допускается оценкой).
  - `UsageRepository.bump(day, **counters)` — атомарный инкремент счётчиков `read / passed_prefilter / llm_items / findings` (вызывают `ReceiveMessage`, `ClusterMessage`, `ClassifyPending`, `DeliverAccepted`); `get(day) -> DailyStats` — для `/status`.
  - `ScreeningService.can_spend(batch) -> bool` (оценка токенов = символы/3 + 400 на системный промпт; при отказе — алерт владельцу один раз в сутки «дневной лимит LLM исчерпан»).

- [ ] **Step 1: failing tests**

```python
async def test_parses_items(): ...                     # MockTransport отдаёт валидный JSON → 2 Classification, Usage из "usage"
async def test_malformed_response_keeps_pending(): ... # 2 раза мусор → LlmUnavailable (Review Focus 2)
async def test_missing_ids_stay_pending(): ...         # в ответе 1 из 2 id → словарь из 1
async def test_text_truncated(): ...                   # отправленный текст ≤ LLM_MAX_CHARS
async def test_budget_blocks_over_limit(repo): ...     # limit 1000, reserve 800 OK, reserve 300 → False
async def test_budget_alert_once_per_day(): ...
async def test_requirements_versioned(repo): ...       # set → version 2, current() возвращает новый текст
```
- [ ] **Step 2:** FAIL. **Step 3:** реализовать. **Step 4:** PASS.
- [ ] **Step 5: выбор модели.** Нужен `NEUROAPI_KEY` и base URL от Алексея (если нет в `.env` — спросить). `GET {base}/models`, сверить с прайсом NeuroAPI; кандидаты по порядку: `gpt-4o-mini`, `gpt-4.1-mini`, `gpt-4o`. Прогнать `uv run python -m radar.bootstrap.cli llm probe` (команда отправляет 6 фикстурных сообщений из `tests/fixtures/samples.json`: 3 подходящих, 3 нет) на каждом кандидате; выбрать самую дешёвую, у которой 6/6. Записать выбор в `.env.example` и спек (раздел 5).
- [ ] **Step 6:** commit `feat(screening): neuroapi classifier, budget, requirements`.

---

### Task 8: findings — похожесть, кластеры, claim доставки

**Files:** Create `findings/{similarity,entities,ports,service,usecases}.py`, `findings/adapters/*`, модели `findings`, `finding_copies` + миграция; Test `tests/unit/findings/test_similarity.py`, `tests/contract/test_finding_repository.py`, `tests/unit/findings/test_cluster.py`

**Interfaces:**
- Consumes: `IncomingMessage` (Task 5), `Classification` (Task 7).
- Produces:
  - `normalize(text) -> str` (нижний регистр, убрать URL, @упоминания, эмодзи, хэштеги, пунктуацию, схлопнуть пробелы); `fingerprint(norm) -> str` (sha1); `shingles(norm, k=5) -> set[int]` (хэши символьных 5-грамм); `jaccard(a,b) -> float`.
  - `FindingStatus`: `pending, rejected, accepted, delivering, delivered`
  - `@dataclass Finding`: `id, fingerprint, shingles: bytes (упакованный set), text_snapshot, link_snapshot, sender_username, sender_id, sender_is_user, status, classification: Classification|None, requirements_version, claimed_at, delivered_at, bot_message_id, created_at`; `Copy(finding_id, source_id, message_id, link, source_title)`.
  - `FindingRepository`:
    - `cluster(msg, norm, fp, sh, window_days, threshold) -> tuple[Finding, bool]` — в одной транзакции под `pg_advisory_xact_lock(hashtext('findings-dedup'))`: точное совпадение `fingerprint` → иначе перебор `shingles` кластеров за окно (jaccard ≥ threshold) → иначе insert; всегда вставляет `Copy`; `bool` = создан новый (**race window 1**). Memory-фейк — `asyncio.Lock`.
    - `pending(limit) -> list[Finding]`, `set_classification(id, cls, req_version)` (`pending` → `accepted|rejected`, условие `status='pending'`).
    - `claim(id, now) -> bool` — `UPDATE … SET status='delivering', claimed_at=:now WHERE id=:id AND status='accepted'` (**R1**); `mark_delivered(id, bot_message_id, now)`; `unclaim(id)` → `accepted`; `stale_claims(older_than) -> list[Finding]`.
    - `copies(id) -> list[Copy]`.
  - `ClusterMessage.execute(msg) -> None`: prefilter (Task 6) ≠ `pass` → стоп; кластер; новый → ничего (ждёт классификации); не новый и `delivered` → публикует `CopyAttached(finding_id)` (in-process `asyncio.Queue`, порт `EventBus`).
  - `DeliverAccepted.execute()`: для каждого `accepted`: `claim` → `Notifier.send_card` → `mark_delivered`; ошибка отправки → `unclaim`.
  - `RedeliverStale.execute()`: `stale_claims(CLAIM_STALE_S)` → `unclaim` (дальше их возьмёт `DeliverAccepted`).

- [ ] **Step 1: failing tests**

```python
def test_reposts_cluster_together(): ...       # тот же текст с другими эмодзи/хэштегами/ссылкой → jaccard ≥ 0.6
def test_different_vacancies_apart(): ...      # две разные Python-вакансии одного шаблона → < 0.6
async def test_concurrent_copies_one_cluster(repo): ...  # gather из 5 cluster() одинакового текста (разные соединения) → 1 finding, 5 copies
async def test_claim_once(repo): ...           # gather(claim, claim) → ровно один True
async def test_classification_only_from_pending(repo): ...
async def test_stale_claim_redelivered_once(): ...  # claim, «падение», +601 с → RedeliverStale → DeliverAccepted → 1 отправка (Review Focus 5)
async def test_copy_after_delivery_emits_event(): ...
async def test_window_respected(): ...         # копия через 8 суток → новый кластер
```
- [ ] **Step 2:** FAIL. **Step 3:** реализовать. **Step 4:** PASS.
- [ ] **Step 5:** docs (R1, R2, гонки 1–2 в FAILURE_MODES) → commit `feat(findings): dedup clusters and delivery claim`.

---

### Task 9: delivery — карточка, Notifier, бот управления

**Files:** Create `delivery/{ports,card,usecases,bot}.py`, `delivery/adapters/*`; Modify `accounts` — `TelegramBotAlertSink` поверх `Notifier`; Test `tests/unit/delivery/test_card.py`, `test_bot_commands.py`, `test_owner_only.py`

**Interfaces:**
- Consumes: `Finding`, `Copy`, `FindingRepository`, `SourceRepository`, `AccountRepository`, `RequirementsRepository`, `UsageRepository`.
- Produces:
  - `Notifier`: `send(text, parse_mode="HTML") -> int (message_id)`, `edit(message_id, text)`; aiogram-адаптер шлёт только в `OWNER_TELEGRAM_ID`.
  - `render_card(f: Finding, copies: list[Copy]) -> str` — HTML, ≤ 4096 символов:
    ```
    💼 Вакансия | 🛠 Проект
    <summary>
    💰 <money>        (строка только если есть)
    📍 <work_format>  (строка только если есть)
    👤 <contact>
    🔗 <link первой копии>
    ✅ <reason>
    Также в: <title1>, <title2>…   (только если копий > 1; список обрезается «и ещё N»)
    ```
  - Контакт (порядок): `classification.contact` если это @username/t.me-ссылка из текста → иначе `@sender_username` → иначе `tg://user?id=<sender_id>` если `sender_is_user` → иначе «контакта нет».
  - `AttachCopyEdit` — потребитель `CopyAttached`: `edit(bot_message_id, render_card(...))`; `MessageNotModified` игнорируется (идемпотентно, R9).
  - Команды бота (Router с фильтром `F.from_user.id == OWNER_TELEGRAM_ID`; остальным — без ответа): `/status` (аккаунты по статусам, источники по статусам, за сутки: прочитано / прошло предфильтр / в LLM / находок, токены и ≈стоимость), `/add <ссылка…>` (несколько через пробел/строки), `/remove <ссылка>`, `/sources [page]` (топ по found_count), `/req` (показать текущие требования), `/setreq` (следующее сообщение — новый текст), `/pause`, `/resume` (флаг в `settings_overrides`, `DeliverAccepted` при паузе не отправляет, находки копятся `accepted`), `/set <KEY> <VALUE>` для расходных настроек: `LLM_BATCH_SIZE, LLM_BATCH_WAIT_S, LLM_MAX_CHARS, LLM_DAILY_TOKEN_LIMIT, NEUROAPI_MODEL, PREFILTER_MIN_LEN` (хранятся в `settings_overrides`, перекрывают env; воркеры читают на каждом цикле).

- [ ] **Step 1: failing tests**

```python
def test_card_vacancy_full(): ...                 # все поля → ожидаемый текст (сравнение со строкой-эталоном)
def test_card_truncated_to_telegram_limit(): ...  # summary 5000 символов → len ≤ 4096 (Review Focus 1)
def test_contact_fallbacks(): ...                 # 4 случая порядка контакта (Review Focus 3)
def test_also_in_list_capped(): ...               # 30 копий → «и ещё N»
async def test_non_owner_ignored(): ...           # апдейт от другого id → ни один хендлер не вызван, notifier пуст
async def test_setreq_flow(): ...                 # /setreq, затем текст → requirements version +1
async def test_pause_holds_delivery(): ...
async def test_set_rejects_unknown_key(): ...
```
- [ ] **Step 2:** FAIL. **Step 3:** реализовать. **Step 4:** PASS. **Step 5:** commit `feat(delivery): cards and owner bot`.

---

### Task 10: конвейер и сборка процесса

**Files:** Create `screening/usecases.py` (`ClassifyPending`), `bootstrap/{di,main}.py`; Test `tests/e2e/test_pipeline.py`

**Interfaces:**
- Consumes: всё выше.
- Produces:
  - `ClassifyPending.run_forever()` — цикл: ждёт, пока `pending` наберётся `LLM_BATCH_SIZE` или самый старый `pending` старше `LLM_BATCH_WAIT_S`; `can_spend` → `classify` → `set_classification` с текущей версией требований → триггер `DeliverAccepted`; `LlmUnavailable` → пауза 60 с, кластеры остаются `pending`.
  - `MessageSink` из Task 5 реализуется `ClusterMessage`.
  - `main.py`: DI-контейнер, `alembic upgrade head` при старте, задачи: `PoolRunner`, `ClassifyPending`, `DeliverAccepted` (по событию + раз в 30 с), `RedeliverStale` (раз в минуту), `AttachCopyEdit` (очередь), чистка `messages` старше `MESSAGES_RETENTION_DAYS` (раз в час), aiogram polling. Падение одной задачи логируется и перезапускает её с backoff, не валит процесс.

- [ ] **Step 1: failing e2e test** (FakeGateway с 2 аккаунтами, FakeClassifier, FakeNotifier, реальная БД, FakeClock):

```python
async def test_pipeline_end_to_end(): 
    # одна вакансия в 3 группах + 1 «ищу работу» + 1 hh-ссылка-only + 1 англ.
    # → notifier.sent == 1 карточка; после 3-й копии карточка отредактирована и содержит 2 названия «Также в»
    # → classifier вызван 1 раз с 1 элементом (дубли и мусор не дошли до LLM)
async def test_restart_no_redelivery(): ...   # прогон, пересоздание контейнера, тот же поток сообщений → sent всё ещё 1
```
- [ ] **Step 2:** FAIL. **Step 3:** реализовать. **Step 4:** PASS (`uv run pytest -v` целиком).
- [ ] **Step 5:** commit `feat: pipeline wiring`.

---

### Task 11: автопополнение источников и отсев ретрансляторов

**Files:** Modify `sources/service.py`, `sources/usecases.py`, `findings/usecases.py` (`ClusterMessage` вызывает discovery); Test `tests/unit/sources/test_discovery.py`

**Interfaces:**
- Produces:
  - `DiscoverFromMessage.execute(msg)` — вызывается для **каждого** входящего сообщения (до предфильтра): `extract_chat_links(text)` + `fwd_from_username` → `add_candidate(..., added_by="discovery", priority=1)`; не больше 5 кандидатов с одного сообщения.
  - Проверка кандидата после резолва (`SourceService.vet(source, title, about, sample: list[str]) -> SourceStatus`): `rejected`, если название+описание не русские или не содержат ни одного из `работа, ваканс, фриланс, заказ, удалён, it, айти, разработ, программ, python, питон, frontend, фронтенд, веб, web, digital, junior, middle, senior`; `rejected` как ретранслятор, если в выборке ≥20 последних сообщений доля `aggregator_only` ≥ 0.5; иначе `active`.
  - Источник `active`, давший 0 находок и 0 сообщений, прошедших предфильтр, за 14 суток при ≥ 100 прочитанных → `rejected` и `release` (освобождает членство). Запуск раз в сутки.
  - При `membership_count == cap` у всех аккаунтов: новая группа вытесняет закреплённую группу с наименьшим `found_count` за 14 суток, только если у вытесняемой `found_count == 0` (иначе группа ждёт в `active`-незакреплённых).

- [ ] **Step 1: failing tests:** `test_links_become_candidates`, `test_max_five_candidates_per_message`, `test_forward_source_becomes_candidate`, `test_english_chat_rejected`, `test_relay_channel_rejected` (20 сообщений, 12 hh-only), `test_useless_group_released_after_14_days`, `test_eviction_only_of_zero_yield`.
- [ ] **Step 2:** FAIL. **Step 3:** реализовать. **Step 4:** PASS. **Step 5:** commit `feat(sources): discovery and vetting`.

---

### Task 12: стартовый список источников и боевой прогон

Не TDD: исследование + ручная проверка. Нужно от Алексея: номер(а) аккаунта для `accounts login` (или JSON-сессии), `BOT_TOKEN`, `NEUROAPI_KEY`.

**Files:** Create `seeds/sources.txt`, `seeds/README.md` (откуда собрано)

- [ ] **Step 1:** Собрать список: каталоги tgstat.ru (категории «Работа и вакансии», «Технологии», «Фриланс»), telemetr.io, подборки «IT-чаты вакансий / фриланса» (Хабр, vc.ru, GitHub awesome-списки русскоязычных IT-чатов), глобальный поиск Telegram (через `radar sources search "<запрос>"` — команда вызывает `contacts.SearchRequest` с паузами Pacer resolve) по запросам: `вакансии python, работа python, фриланс программист, заказы разработка, удалённая работа it, вакансии frontend, вакансии backend, фриланс заказы, ищу разработчика, telegram боты заказ`. Формат строки: `!@username` (группа фриланса/вакансий, priority 10) или `@username`. Цель ≥ 300 групп и ≥ 1000 каналов; исключить ретрансляторы hh, если они видны по названию.
- [ ] **Step 2:** `radar sources import seeds/sources.txt` → вывод: добавлено N, дублей M.
- [ ] **Step 3:** `.env` на VPS, `docker compose up -d`; `radar accounts login --phone …` (код вводит Алексей) для каждого аккаунта.
- [ ] **Step 4:** проверить в течение часа: `/status` показывает рост `active` источников и прочитанных сообщений; в логах нет циклических ошибок; первые карточки приходят. Записать фактические числа (источники, сообщений/ч, доля прошедших предфильтр, токены/ч) в `docs/services/radar/ARCHITECTURE.md` раздел «Нагрузка».
- [ ] **Step 5:** commit `chore: seed sources and deploy notes`.

---

### Task 13: README и закрытие

**Files:** Create/Modify `README.md`, `docs/services/radar/*.md`

- [ ] **Step 1:** README: что делает, переменные окружения (все из `Settings` с дефолтами), запуск, команды CLI и бота, как добавить аккаунт, как поменять модель/бюджет.
- [ ] **Step 2:** Сверка docs: INVARIANTS содержит R1–R7, R11; FAILURE_MODES — все строки таблицы «Гонки» и ошибки Telegram из Task 5.
- [ ] **Step 3:** `uv run pytest -v` → всё PASS; `docker compose build` → OK.
- [ ] **Step 4:** commit `docs: readme and service docs`.
