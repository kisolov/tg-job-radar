# radar — инварианты

Нумерация правил — из спека, раздел `## Domain design / 1. Правила`.

| # | Инвариант | Где держится |
|---|---|---|
| R5 | Вступлений аккаунта за сутки ≤ `join.daily_limit` (25–30, снижается автоторможением), интервал между вступлениями ≥ `uniform(300,600) × interval_factor` | `Pacer` в корне `Account`; запись `AccountRepository.save` по `version` (`StaleAccount` → повтор до 3 раз в `AccountService`) |
| R6 | Аккаунт не в `active` не читает, не вступает, не резолвит | `Account.can_join/can_resolve`; `list_active` для пула |
| — | Секреты аккаунта (`session`, `api_hash`) в БД только Fernet-шифрованные (`USERBOT_STORE_KEY`); 2FA-пароль и device-секреты не читаются из файла импорта, не хранятся и не логируются | `ImportAccount` (берёт только `phone`, `session_str|session`, `app_id`, `app_hash`), `FernetSecretBox` |
