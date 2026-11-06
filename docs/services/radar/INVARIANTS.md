# radar — инварианты

Нумерация правил — из спека, раздел `## Domain design / 1. Правила`.

| # | Инвариант | Где держится |
|---|---|---|
| R1 | Находка (кластер дублей) доставляется владельцу не больше одного раза | claim `UPDATE findings SET status='delivering' WHERE id=:f AND status='accepted'` до отправки; отправляет только выигравший; сбой отправки → `unclaim`; claim старше `CLAIM_STALE_S` → `RedeliverStale` |
| R2 | Сообщение `(source_id, message_id)` проходит отбор не больше одного раза (в окне `MESSAGES_RETENTION_DAYS`) | PK `messages(source_id, message_id)` + `INSERT … ON CONFLICT DO NOTHING RETURNING`; в конвейер идёт только вставивший |
| R3 | Источник закреплён не больше чем за одним аккаунтом | conditional write `UPDATE sources SET assigned_account_id=:a WHERE id=:s AND assigned_account_id IS NULL` (`SourceRepository.assign`) |
| R4 | `accounts.membership_count ≤ MEMBERSHIP_CAP`; счётчик = число закреплённых за аккаунтом групп | закрепление группы и `membership_count+1 WHERE membership_count < cap` — одна транзакция; `release`/`release_all_of` уменьшают в той же транзакции (не ниже 0); обе записи поднимают `accounts.version` |
| R7 | Источник в каталоге один раз | unique по `username`, `invite_hash`, `peer_id`; `add_candidate … ON CONFLICT DO NOTHING`; инвайт, разрешившийся в уже известный `peer_id`, → `rejected` |
| R5 | Вступлений аккаунта за сутки ≤ `join.daily_limit` (25–30, снижается автоторможением), интервал между вступлениями ≥ `uniform(300,600) × interval_factor` | `Pacer` в корне `Account`; запись `AccountRepository.save` по `version` (`StaleAccount` → повтор до 3 раз в `AccountService`) |
| R6 | Аккаунт не в `active` не читает, не вступает, не резолвит | `Account.can_join/can_resolve`; `list_active` для пула |
| R8 (eventual) | Расход LLM за сутки ≤ `LLM_DAILY_TOKEN_LIMIT`, перелёт ≤ ошибки оценки одного пакета | `UsageRepository.reserve`: conditional `UPDATE daily_stats … WHERE факт+резерв+оценка ≤ limit` до вызова LLM |
| R9 (eventual) | «Также в» у отправленной находки отражает все её копии | событие `CopyAttached` → редактирование карточки; копии, пришедшие во время отправки, догоняются правкой сразу после `mark_delivered` |
| R10 (eventual) | Отбор использует текущую версию требований | находка хранит `requirements_version`, с которой классифицирована |
| — | Секреты аккаунта (`session`, `api_hash`) в БД только Fernet-шифрованные (`USERBOT_STORE_KEY`); 2FA-пароль и device-секреты не читаются из файла импорта, не хранятся и не логируются | `ImportAccount` (берёт только `phone`, `session_str|session`, `app_id`, `app_hash`), `FernetSecretBox` |
