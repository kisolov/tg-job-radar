# radar — потоки данных

## Чтение Telegram (`ingest`)

```
PoolRunner.sync (раз в 60 с)
  ├─ AccountService.wake_expired          flood_wait с истёкшим status_until → active
  ├─ на каждый новый active-аккаунт       AccountWorker: gateway.start() → корутина
  └─ AssignWork                            свободные active-источники → наименее загруженным аккаунтам

AccountWorker.step (раз в 5 с, строго последовательно внутри аккаунта)
  ├─ roll_day при смене суток UTC; watch(вступленные группы) для live-апдейтов
  ├─ RunJoinQueue.tick       can_join → одна закреплённая невступленная группа (priority desc) → gateway.join
  ├─ RunResolveQueue.tick    can_resolve → claim_candidate (SKIP LOCKED) → gateway.resolve → set_resolved
  └─ PollChannels            до 5 источников, не опрошенных CHANNEL_POLL_INTERVAL_S:
                             fetch_new(min_id=курсор) → ReceiveMessage по возрастанию id → set_polled

live-апдейт группы ─┐
опрос канала/группы ─┴→ ReceiveMessage: set_cursor (только вперёд) → messages INSERT ON CONFLICT DO NOTHING
                        → только победитель вставки → MessageSink.submit (конвейер отбора)
```

- Первый опрос источника (курсор 0) берёт ≤ 20 последних сообщений и отдаёт в отбор только моложе 24 ч;
  старая история лишь сдвигает курсор.
- Инвайт-ссылка резолвится без id (`CheckChatInvite`); id и access_hash приходят при вступлении (`set_peer`).
- `radar sources search "запрос" …` — глобальный поиск с первого active-аккаунта, пауза resolve-Pacer между
  запросами, находки → кандидаты `seed`.

## Отбор и доставка

```
MessageSink = ClusterMessage.submit(msg)
  ├─ prefilter(text) ≠ pass → daily_stats.read+1, конец
  ├─ daily_stats.read+1, passed_prefilter+1
  ├─ FindingService.cluster → FindingRepository.cluster (advisory lock): новый pending-кластер или копия
  └─ копия уже доставленной находки → CopyAttached → AttachCopyEdit правит карточку (R9)

ClassifyPending.run_forever
  ├─ ждёт LLM_BATCH_SIZE pending или старейший старше LLM_BATCH_WAIT_S
  ├─ ScreeningService.reserve (R8) — нет бюджета → пауза до конца суток, алерт
  ├─ LlmClassifier.classify(пакет, текущие требования, модель из runtime)
  │     LlmUnavailable → резерв снят, кластеры pending, пауза 60 с
  ├─ commit_usage, llm_items+N; set_classification (только из pending, с версией требований — R10)
  └─ принятые: sources.found_count+1 по копиям; будит DeliverAccepted

DeliverAccepted (по будильнику и раз в 30 с; на /pause — ничего)
  claim (accepted→delivering, R1) → render_card → Notifier.send → mark_delivered → findings+1
  → сверка копий: пришедшие во время отправки дописываются правкой
RedeliverStale (раз в минуту): delivering старше CLAIM_STALE_S → accepted
Чистка messages старше MESSAGES_RETENTION_DAYS — раз в час
```

## Процесс (`bootstrap/main.py`)

`alembic upgrade head` → `RuntimeConfig.load` → `reset_resolving` → задачи под `supervise` (падение/выход →
перезапуск с паузой 5 → 10 → … ≤ 300 с): `pool`, `classify`, `deliver`, `copy-edit`, `redeliver-stale`,
`purge-messages`, `bot` (aiogram polling), `web` (панель на `WEB_HOST:WEB_PORT`, если `WEB_PORT` ≠ 0).

## Панель

Браузер → `/api/*` → usecase панели → `PanelReadModel` (SELECT по `findings`, `finding_copies`, `sources`,
`accounts`) + `UsageRepository.get(сегодня UTC)` + `RuntimeConfig`. Сутки KPI — UTC, как `daily_stats`; «Находки за 7
дней» — `delivered_at` по дням UTC. Запись из панели идёт теми же путями, что и бот: `AddSource` → `SourceService.add_refs`,
удаление → `SourceService.remove(ref)`, пауза → `RuntimeConfig.set_paused`.
