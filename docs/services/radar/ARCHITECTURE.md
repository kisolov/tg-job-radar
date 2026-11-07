# radar — архитектура

Один процесс asyncio (одна реплика: Telethon-сессию нельзя держать в двух процессах).
Спек: `docs/superpowers/specs/2026-11-04-tg-job-radar-design.md`.

## Модули

| Модуль | Секрет | Слои |
|---|---|---|
| `shared` | настройки, БД, часы | — |
| `accounts` | жизненный цикл и темп аккаунтов-читателей | usecases (`ImportAccount`, `LoginAccount`, `ListAccounts`, `DisableAccount`) → `AccountService` (темп, статусы, алерты) → порты `AccountRepository`, `SecretBox`, `SessionProbe`, `DeviceProfileProvider`, `AlertSink` |
| `ingest` | транспорт Telegram (Telethon) | usecases (`ReceiveMessage`, `PollChannels`, `RunJoinQueue`, `RunResolveQueue`, `SearchSources`) → порты `TelegramGateway`, `MessageLog`, `MessageSink` (сервиса нет); `pool.py` — `PoolRunner` + `AccountWorker` |
| `delivery` | как находка и управление выглядят в боте | `bot.py` (aiogram Router, фильтр владельца) → usecases (`StatusReport`, `ListSources`, `ShowRequirements`, `SetRequirements`, `SetPaused`, `SetOverride`, `AttachCopyEdit`) → порт `Notifier` (`AiogramNotifier` / фейк; он же `AlertSink`); `card.py` |
| `findings` | что считать одной находкой | usecases (`ClusterMessage` — `MessageSink` конвейера, `DeliverAccepted`, `RedeliverStale`) → `FindingService` → `FindingRepository`; `similarity.py`, `events.py` (`CopyAttached`, `InProcessEventBus`) |
| `sources` | какие чаты читаем и кто их читает | usecases (`AddSource`, `RemoveSource`, `ImportSeeds`, `AssignWork`, `ReleaseAccountSources`) → `SourceService` → `SourceRepository` |
| `panel` | как состояние системы выглядит в браузере | `web.py` (aiohttp, страница `static/` без сборки + JSON) → usecases (`GetOverview`, `ListFindings`, `GetFinding`, `ListPanelSources`, `RemoveSourceById`; запись — `AddSource`, `SetPaused`) → порт `PanelReadModel` (только SQL-реализация, тесты на Postgres); `auth.py` — вход по одноразовой ссылке |
| `screening` | решение «подходит ли сообщение» | `prefilter.py` (чистые функции); usecases (`ProbeModel`, `ClassifyPending`) → `ScreeningService` (оценка пакета, бюджет) → порты `LlmClassifier` (NeuroAPI / фейк), `UsageRepository`, `RequirementsRepository` |

### screening — LLM

- `NeuroApiClassifier`: `POST {NEUROAPI_BASE_URL}/chat/completions`, `temperature=0`, `response_format=json_object`;
  system = инструкция + текущие требования; user = JSON `[{"id","text"}]` (текст обрезан до `LLM_MAX_CHARS`).
  Ответ `{"items":[{"id","relevant","kind","summary","money","format","contact","reason"}]}`. Невалидный ответ,
  5xx, таймаут → один повтор → `LlmUnavailable`. Элементы с чужим id или без булева `relevant` отбрасываются
  (их сообщения остаются `pending`). Модель и `max_chars` можно переопределить на вызов (`/set`).
- Бюджет: оценка пакета = символы/3 + 400; `reserve` атомарно проверяет факт+резерв+оценка ≤
  `LLM_DAILY_TOKEN_LIMIT`; после ответа `commit_usage` меняет резерв на факт. Лимит исчерпан → алерт раз в сутки.
- Требования версионируются (`requirements`), версия 1 — из спека (раздел 4), сидится миграцией.
- `radar llm models` — список моделей NeuroAPI; `radar llm probe M1 M2 …` — 6 эталонных сообщений
  (`screening/probe_samples.json`) на каждой модели, выбрать самую дешёвую с 6/6.

### screening — предфильтр

Порядок проверок (первая сработавшая — вердикт): `empty` (нет текста; подпись медиа считается текстом) →
`aggregator_only` (ссылка на домен из `AGGREGATOR_DOMAINS`, включая поддомены, и остаток без ссылок/хэштегов/эмодзи
< 200 символов **или** нет контакта `@username`/t.me) → `short` (< `PREFILTER_MIN_LEN`) → `not_russian` (кириллица < 50 %
букв, ссылки и упоминания не считаются) → `stopword` → `no_marker` → `pass`. Слова сравниваются с начала слова,
короткие (≤ 3 символа: «тз», «зп») — целиком; «ё» = «е».

### delivery

Карточка (HTML, ≤ 4096; при переполнении обрезается суть, ссылка и контакт остаются):

```
💼 Вакансия | 🛠 Проект
<суть>
💰 <деньги>          — если есть
📍 <формат>          — если есть
👤 <контакт>
🔗 <ссылка на первую копию: название чата>
✅ <почему подходит>
Также в: <чат>, …, и ещё N   — если копий из других чатов > 0 (до 10 названий)
```

Контакт: `contact` из ответа LLM, только если этот @username / t.me-ссылка есть в тексте → `@отправитель`, если это
человек → `tg://user?id=` → «контакта нет» (пост канала, анонимный админ).

Команды (только `OWNER_TELEGRAM_ID`, остальным — тишина): `/status`, `/add`, `/remove`, `/sources [стр]`, `/req`,
`/setreq` (следующее сообщение — новый текст, `/cancel`), `/pause`, `/resume`, `/web` (ссылка входа в панель), `/set KEY VALUE` для
`LLM_BATCH_SIZE, LLM_BATCH_WAIT_S, LLM_MAX_CHARS, LLM_DAILY_TOKEN_LIMIT, NEUROAPI_MODEL, PREFILTER_MIN_LEN`.

`shared/runtime.py` — `RuntimeConfig`: env + `settings_overrides`; снимок в памяти процесса, обновляется при `/set`
(допущение одной реплики). Флаг паузы — ключ `DELIVERY_PAUSED`.

### panel

Спек: `docs/superpowers/specs/2026-11-07-web-panel-design.md`, макет: `design/web-panel/`. Три экрана (`#/`, `#/findings`,
`#/sources`), автообновление шапки и обзора раз в 30 с. Ручки: `GET /api/overview`, `GET /api/findings?tab&kind&period&q&page`,
`GET /api/findings/{id}`, `GET /api/sources?tab&kind&sort&page`, `POST /api/sources {text}`, `DELETE /api/sources/{id}`,
`POST /api/delivery {paused}`. Статус источника на экране вычисляется: `active` и (канал или вступили) → «читается»,
`active` группа без вступления → «ждёт вступления», `candidate`/`resolving` → «ждёт резолва».

Вход: `/web` → `WEB_BASE_URL/login?t=<login.exp.nonce.hmac>` (10 мин, одноразово — nonce в памяти процесса) →
cookie `radar_session` (HMAC, 30 дней, HttpOnly, SameSite=Lax, Secure при https). Секрет — `WEB_SECRET` или sha256 от
`BOT_TOKEN`. Изменяющие запросы требуют `X-Radar: 1`.

### findings

- `normalize`: нижний регистр, ё→е, без ссылок, @упоминаний, хэштегов, пунктуации и эмодзи. Отпечаток — sha1
  нормализованного текста; шинглы — crc32 символьных 5-грамм (стабильны между процессами, лежат в БД).
- Кластер: тот же отпечаток за `DEDUP_WINDOW_DAYS` → иначе Жаккар ≥ `DEDUP_JACCARD` (кандидаты отсекаются по числу
  шинглов: min/max ≥ порога) → иначе новый `pending`. Копия `(source_id, message_id)` пишется всегда.
- Статусы: `pending → accepted | rejected` (LLM) → `delivering` (claim) → `delivered`.

### sources

- Ключ каталога — `normalize_username`: `username` в нижнем регистре или `+invite`. Боты и служебные пути t.me
  отбрасываются. `extract_chat_links` берёт из текста только t.me-ссылки (`@упоминания` — почти всегда
  контакт человека).
- Статусы: `candidate → (resolve) → active | dead | rejected`.
- `AssignWork`: свободные `active` источники → `active` аккаунту. Источник с `access_hash` — только его владельцу
  (`hash_account_id`, R9b): Telegram выдаёт хэш паре (чат, аккаунт). Владелец забанен / разлогинен / выключен →
  `requeue` (на повторный резолв); владелец в паузе — источник ждёт его. Без хэша — наименее загруженному.
- Членство (`Source.needs_membership`) нужно группам и любым источникам по инвайту (приватный канал читается только
  изнутри): они тратят слот R4, вступают через `RunJoinQueue` (по инвайту — всегда `ImportChatInvite`) и опрашиваются
  только с известным `peer_id`. Публичные каналы читаются без вступления и лимит не тратят.
- Владелец добавляет с priority 10, стартовый список — 10 (строка с `!`) или 5.
- CLI: `radar sources import FILE | add LINK… | search "запрос"…`.
- Автопополнение (`DiscoverFromMessage`, на каждое прочитанное сообщение до предфильтра): t.me-ссылки и источник
  репоста → кандидаты `discovery`, priority 1, не больше 5 с сообщения.
- Проверка кандидата `discovery` после резолва (`SourceService.vet`): название/описание или выборка из 30
  последних сообщений по-русски, в названии есть тематическое слово (`TOPIC_WORDS`), и не ретранслятор: при
  выборке ≥ 20 доля «только ссылка на агрегатор» < 50 %. Иначе `rejected`. `seed` и `owner` не проверяются.
- Снятие с чтения (`retire`): невступленный источник освобождается сразу; вступленная группа помечается
  `rejected`, а воркер её аккаунта выходит из чата и только потом освобождает слот (`list_to_leave`) — иначе
  Telegram продолжит считать её в лимите членства. Так работают `/remove`, отсев и вытеснение.
- Раз в сутки `RetireUseless`: вступленные группы старше 14 суток без находок и без прошедших предфильтр при ≥ 100
  прочитанных → сняты. Когда все аккаунты упёрлись в лимит, а свободная группа ждёт, `AssignWork` снимает одну
  вступленную группу без находок за 14 суток (наименее полезную).

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
| `requirements(version, text, created_at)` | версии текста требований для LLM |
| `daily_stats(day, …)` | счётчики суток: read, passed_prefilter, llm_items, findings, requests, prompt/completion_tokens, reserved |
| `findings` | кластеры дублей: отпечаток, шинглы, снимок первой копии, классификация (JSONB), статус, claim, `bot_message_id` |
| `finding_copies(source_id, message_id)` | где встречалась находка (для «Также в») |
| `messages(source_id, message_id, seen_at)` | журнал виденных сообщений (R2), чистится старше `MESSAGES_RETENTION_DAYS` |
| `sources` | каталог: ключи (`username`/`invite_hash`/`peer_id`, все unique), тип, статус, закрепление, курсор опроса, статистика |
