# radar — инварианты

Нумерация правил — из спека, раздел `## Domain design / 1. Правила`.

| # | Инвариант | Где держится |
|---|---|---|
| R1 | Находка (кластер дублей) доставляется владельцу не больше одного раза | claim `UPDATE findings SET status='delivering' WHERE id=:f AND status='accepted'` до отправки; отправляет только выигравший; сбой отправки → `unclaim`; claim старше `CLAIM_STALE_S` → `RedeliverStale` |
| R2 | Сообщение `(source_id, message_id)` проходит отбор не больше одного раза (в окне `MESSAGES_RETENTION_DAYS`) | PK `messages(source_id, message_id)` + `INSERT … ON CONFLICT DO NOTHING RETURNING`; в конвейер идёт только вставивший. Сбой обработки → `forget` (запись стёрта, курсор не сдвинут — опрос возьмёт снова); после падения процесса записи без `processed_at` стираются на старте (I5) |
| R3 | Источник закреплён не больше чем за одним аккаунтом | conditional write `UPDATE sources SET assigned_account_id=:a WHERE id=:s AND assigned_account_id IS NULL` (`SourceRepository.assign`) |
| R4 | `membership_count + external_memberships ≤ MEMBERSHIP_CAP`; `membership_count` = закреплённые источники с членством (группы и инвайты, включая висящие заявки на вступление — M3), `external_memberships` = чаты вне учёта, узнанные по `ChannelsTooMuch` (M4) | закрепление и `membership_count+1 WHERE membership_count + external_memberships < cap` — одна транзакция; `release`/`release_all_of` уменьшают в той же транзакции (не ниже 0); обе записи поднимают `accounts.version` |
| R9b | Источник с `access_hash` читает и вступает только аккаунт, которому хэш выдан (`hash_account_id`) | `set_resolved`/`set_peer` пишут владельца; `AssignWork` закрепляет только за ним; чужой хэш (`ChannelInvalid` → `TgPeerStale`) или выбывший владелец → `requeue` (хэш стёрт, → `candidate`) |
| R7 | Источник в каталоге один раз | unique по `username`, `invite_hash`, `peer_id`; `add_candidate … ON CONFLICT DO NOTHING`; инвайт, разрешившийся в уже известный `peer_id`, → `rejected` |
| R5 | Вступлений аккаунта за сутки ≤ `join.daily_limit` (25–30, снижается автоторможением), интервал между вступлениями ≥ `uniform(300,600) × interval_factor` | `Pacer` в корне `Account`; запись `AccountRepository.save` по `version` (`StaleAccount` → повтор до 3 раз в `AccountService`) |
| R6 | Аккаунт не в `active` не читает, не вступает, не резолвит | `Account.can_join/can_resolve`; `list_active` для пула |
| R8 (eventual) | Расход LLM за сутки ≤ `LLM_DAILY_TOKEN_LIMIT`, перелёт ≤ ошибки оценки одного пакета | `UsageRepository.reserve`: conditional `UPDATE daily_stats … WHERE факт+резерв+оценка ≤ limit` до вызова LLM |
| R9 (eventual) | «Также в» у отправленной находки отражает все её копии | событие `CopyAttached` → редактирование карточки; копии, пришедшие во время отправки, догоняются правкой сразу после `mark_delivered` |
| R10 (eventual) | Отбор использует текущую версию требований | находка хранит `requirements_version`, с которой классифицирована |
| R11 | Командовать ботом может только владелец; бот пишет только владельцу | `router.message.filter(F.from_user.id == OWNER_TELEGRAM_ID)` (без ответа остальным); `AiogramNotifier` шлёт только в `OWNER_TELEGRAM_ID` |
| — | Секреты аккаунта (`session`, `api_hash`) в БД только Fernet-шифрованные (`USERBOT_STORE_KEY`); 2FA-пароль и device-секреты не читаются из файла импорта, не хранятся и не логируются | `ImportAccount` (берёт только `phone`, `session_str|session`, `app_id`, `app_hash`), `FernetSecretBox` |
