# tg-job-radar

Userbot-пул читает как можно больше русскоязычных Telegram-чатов и каналов, отбирает вакансии и заказы под
требования владельца и сразу присылает каждую находку в личку через бота — с прямым контактом автора и ссылкой на
сообщение. Сам никому не пишет.

```
Telegram (Telethon, пул аккаунтов) → предфильтр → склейка дублей → LLM (NeuroAPI, пакетами) → карточка в бота
```

Дизайн: `docs/superpowers/specs/2026-11-04-tg-job-radar-design.md`. Как устроено сейчас: `docs/services/radar/`.

## Запуск

```bash
cp .env.example .env            # заполнить обязательные (см. ниже)
docker compose up -d db app     # миграции применяются при старте
docker compose exec app radar accounts login --phone +7...   # код и 2FA вводите вы
docker compose exec app radar sources import seeds/sources.txt
```

Ключ шифрования сессий: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.
Потеряете его — сессии придётся завести заново.

Локально без Docker: `uv sync`, `docker compose up -d db-test`, `uv run pytest`.

## Переменные окружения

Обязательные: `DATABASE_URL`, `OWNER_TELEGRAM_ID` (ваш числовой id — только он управляет ботом и получает
находки), `BOT_TOKEN`, `USERBOT_STORE_KEY`, `NEUROAPI_BASE_URL`, `NEUROAPI_KEY`, `NEUROAPI_MODEL`.

| Переменная | Дефолт | Смысл |
|---|---|---|
| `TELEGRAM_API_ID`, `TELEGRAM_API_HASH` | — | дефолт для `accounts login` |
| `USERBOT_DEVICE_PROFILE` | `default` | профиль устройства (Telethon решает сам) |
| `JOIN_DAILY_MIN` / `JOIN_DAILY_MAX` | 25 / 30 | вступлений в сутки на аккаунт (случайно в диапазоне, раз в сутки) |
| `JOIN_INTERVAL_MIN_S` / `JOIN_INTERVAL_MAX_S` | 300 / 600 | пауза между вступлениями |
| `RESOLVE_INTERVAL_S` | 60 | пауза между резолвами (и поиском) |
| `THROTTLE_FACTOR` / `THROTTLE_MAX_FACTOR` | 1.5 / 8.0 | FloodWait умножает интервал, но не выше |
| `THROTTLE_LIMIT_STEP` / `THROTTLE_LIMIT_FLOOR` | 5 / 5 | FloodWait снижает суточный лимит на шаг, не ниже |
| `THROTTLE_RECOVERY_DAYS` | 3 | суток без флуда до начала восстановления темпа |
| `MEMBERSHIP_CAP` | 500 | групп на аккаунт (1000 с Premium) |
| `CHANNEL_POLL_INTERVAL_S` | 300 | как часто опрашивать канал |
| `LLM_BATCH_SIZE` / `LLM_BATCH_WAIT_S` | 10 / 60 | размер пакета и максимальное ожидание его набора |
| `LLM_MAX_CHARS` | 1500 | обрезка сообщения перед LLM |
| `LLM_DAILY_TOKEN_LIMIT` | 2 000 000 | дневной лимит токенов; исчерпан — пауза до конца суток UTC + алерт |
| `LLM_PRICE_PER_1K_PROMPT` / `_COMPLETION` | 0 / 0 | цена для «≈стоимость» в `/status` |
| `PREFILTER_MIN_LEN` | 60 | короче — не вакансия |
| `PREFILTER_MARKERS`, `PREFILTER_STOPWORDS`, `AGGREGATOR_DOMAINS` | в коде | списки через запятую |
| `DEDUP_WINDOW_DAYS` / `DEDUP_JACCARD` | 7 / 0.6 | окно и порог похожести дублей |
| `CLAIM_STALE_S` | 600 | зависшая отправка повторяется через |
| `MESSAGES_RETENTION_DAYS` | 7 | сколько помнить виденные сообщения |

## Бот (только владелец, остальным — тишина)

| Команда | Что делает |
|---|---|
| `/status` | аккаунты и источники по статусам; за сутки: прочитано / прошло предфильтр / в LLM / находок; токены и ≈стоимость |
| `/add t.me/x @y …` | добавить источники |
| `/remove t.me/x` | убрать (из вступленной группы аккаунт выйдет сам) |
| `/sources [страница]` | источники по числу находок |
| `/req`, `/setreq` | показать / заменить требования (новый текст — следующим сообщением) |
| `/pause`, `/resume` | пауза доставки; находки копятся и придут после `/resume` |
| `/set KEY VALUE` | на ходу: `LLM_BATCH_SIZE`, `LLM_BATCH_WAIT_S`, `LLM_MAX_CHARS`, `LLM_DAILY_TOKEN_LIMIT`, `NEUROAPI_MODEL`, `PREFILTER_MIN_LEN` |

## CLI

```
radar accounts import FILE.json      # берутся только phone, session_str|session, app_id, app_hash
radar accounts login --phone +7...   # интерактивный вход; 2FA не сохраняется
radar accounts list | disable PHONE
radar sources import seeds/sources.txt
radar sources add t.me/x @y
radar sources search "вакансии python" "фриланс заказы" …   # глобальный поиск → кандидаты
radar llm models                      # модели NeuroAPI
radar llm probe gpt-4o-mini gpt-4.1-mini gpt-4o   # 6 эталонных сообщений; берите самую дешёвую с 6/6
```

## Как поменять модель или бюджет

Без перезапуска: `/set NEUROAPI_MODEL gpt-4.1-mini`, `/set LLM_DAILY_TOKEN_LIMIT 500000`. Насовсем — в `.env`.
Дешевле: больше `LLM_BATCH_SIZE`, меньше `LLM_MAX_CHARS`, строже предфильтр (`PREFILTER_MIN_LEN`, стоп-слова).

## Добавить аккаунт

`radar accounts login --phone …` или `radar accounts import account.json` — подхватывается без перезапуска (раз в
минуту). Бан или разлогин аккаунта — алерт в бота, его группы уходят другим аккаунтам.
