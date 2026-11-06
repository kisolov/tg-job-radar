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
