# radar — архитектура

Один процесс asyncio (одна реплика: Telethon-сессию нельзя держать в двух процессах).
Спек: `docs/superpowers/specs/2026-11-04-tg-job-radar-design.md`.

## Модули

| Модуль | Секрет | Слои |
|---|---|---|
| `shared` | настройки, БД, часы | — |
| `accounts` | жизненный цикл и темп аккаунтов-читателей | usecases (`ImportAccount`, `LoginAccount`, `ListAccounts`, `DisableAccount`) → `AccountService` (темп, статусы, алерты) → порты `AccountRepository`, `SecretBox`, `SessionProbe`, `DeviceProfileProvider`, `AlertSink` |
| `ingest` | транспорт Telegram (Telethon) | usecases (`ReceiveMessage`, `PollChannels`, `RunJoinQueue`, `RunResolveQueue`, `SearchSources`) → порты `TelegramGateway`, `MessageLog`, `MessageSink` (сервиса нет); `pool.py` — `PoolRunner` + `AccountWorker` |
| `sources` | какие чаты читаем и кто их читает | usecases (`AddSource`, `RemoveSource`, `ImportSeeds`, `AssignWork`, `ReleaseAccountSources`) → `SourceService` → `SourceRepository` |

### sources

- Ключ каталога — `normalize_username`: `username` в нижнем регистре или `+invite`. Боты и служебные пути t.me
  отбрасываются. `extract_chat_links` берёт из текста только t.me-ссылки (`@упоминания` — почти всегда
  контакт человека).
- Статусы: `candidate → (resolve) → active | dead | rejected`.
- `AssignWork`: свободные `active` группы и каналы → наименее загруженному `active` аккаунту (группы — по
  `membership_count`, каналы — по числу закреплённых каналов). Каналы не тратят лимит членства.
- Владелец добавляет с priority 10, стартовый список — 10 (строка с `!`) или 5.
- CLI: `radar sources import FILE | add LINK…`.

### accounts

- `Account` — корень: статус, `status_until`, счётчик членств, два `Pacer` (`join`, `resolve`), `version`.
- `Pacer` — суточный лимит (случайный в `[JOIN_DAILY_MIN, JOIN_DAILY_MAX]` раз в сутки UTC) и интервал
  `uniform(min,max) × interval_factor`. `FloodWait` → пауза на указанное время, `factor × THROTTLE_FACTOR`
  (≤ `THROTTLE_MAX_FACTOR`), лимит `− THROTTLE_LIMIT_STEP` (≥ `THROTTLE_LIMIT_FLOOR`). После
  `THROTTLE_RECOVERY_DAYS` календарных суток без флуда — по шагу восстановления в сутки. Resolve-`Pacer`
  без суточного лимита, интервал `RESOLVE_INTERVAL_S`.
- `FloodWait > 1 ч` → статус `flood_wait` до `status_until` (+ алерт); `AccountService.wake_expired`
  возвращает в `active`.
- CLI: `radar accounts import FILE | login --phone P | list | disable PHONE`. Повторный импорт того же
  номера обновляет сессию.

## Слои

- Каждый внешний вход (обработчик бота, апдейт Telethon, фоновый воркер) вызывает **usecase** —
  точка входа и граница транзакции (`shared.db.transaction`).
- **service** — только там, где живут правила.
- **port** — только там, где есть подмена (фейк / второй провайдер); у каждого порта есть фейк,
  оба проходят одни контрактные тесты.

## Хранилище

PostgreSQL, одна схема. Таблицы описаны в `src/radar/shared/models.py`; миграции — `migrations/`.

| Таблица | Назначение |
|---|---|
| `settings_overrides(key, value)` | настройки, перекрывающие env (меняются командой бота `/set`) |
| `accounts` | пул аккаунтов: шифрованные секреты, статус, `membership_count`, `join_state`/`resolve_state` (JSONB-снимок `Pacer`), `version` |
| `messages(source_id, message_id, seen_at)` | журнал виденных сообщений (R2), чистится старше `MESSAGES_RETENTION_DAYS` |
| `sources` | каталог: ключи (`username`/`invite_hash`/`peer_id`, все unique), тип, статус, закрепление, курсор опроса, статистика |
