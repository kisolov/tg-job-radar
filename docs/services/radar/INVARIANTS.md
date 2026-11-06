# radar — инварианты

Нумерация правил — из спека, раздел `## Domain design / 1. Правила`.

| # | Инвариант | Где держится |
|---|---|---|
| R3 | Источник закреплён не больше чем за одним аккаунтом | conditional write `UPDATE sources SET assigned_account_id=:a WHERE id=:s AND assigned_account_id IS NULL` (`SourceRepository.assign`) |
| R4 | `accounts.membership_count ≤ MEMBERSHIP_CAP`; счётчик = число закреплённых за аккаунтом групп | закрепление группы и `membership_count+1 WHERE membership_count < cap` — одна транзакция; `release`/`release_all_of` уменьшают в той же транзакции (не ниже 0); обе записи поднимают `accounts.version` |
| R7 | Источник в каталоге один раз | unique по `username`, `invite_hash`, `peer_id`; `add_candidate … ON CONFLICT DO NOTHING`; инвайт, разрешившийся в уже известный `peer_id`, → `rejected` |
| R5 | Вступлений аккаунта за сутки ≤ `join.daily_limit` (25–30, снижается автоторможением), интервал между вступлениями ≥ `uniform(300,600) × interval_factor` | `Pacer` в корне `Account`; запись `AccountRepository.save` по `version` (`StaleAccount` → повтор до 3 раз в `AccountService`) |
| R6 | Аккаунт не в `active` не читает, не вступает, не резолвит | `Account.can_join/can_resolve`; `list_active` для пула |
| — | Секреты аккаунта (`session`, `api_hash`) в БД только Fernet-шифрованные (`USERBOT_STORE_KEY`); 2FA-пароль и device-секреты не читаются из файла импорта, не хранятся и не логируются | `ImportAccount` (берёт только `phone`, `session_str|session`, `app_id`, `app_hash`), `FernetSecretBox` |
