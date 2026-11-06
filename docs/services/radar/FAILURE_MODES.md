# radar — отказы и гонки

| Ситуация | Что происходит | Защита |
|---|---|---|
| Две записи одного аккаунта одновременно (флуд + учёт вступления) | второй `save` получает `StaleAccount` | conditional update `WHERE version=:v`; `AccountService` перечитывает и повторяет до 3 раз; алерт — только после успешной записи |
| Повторное `banned`/`unauthorized` по тому же аккаунту | алерт не дублируется | алерт только при смене статуса |
| Импорт с неавторизованной сессией | аккаунт сохранён `unauthorized`, в пул не попадает | `SessionProbe.check` до сохранения |
| Две корутины закрепляют одну группу | одна выигрывает, вторая получает `False` и берёт следующий источник | conditional write `assigned_account_id IS NULL`; Postgres блокирует строку до коммита первой |
| Аккаунт упёрся в лимит членства во время закрепления | закрепление откатывается целиком, счётчик не растёт | `membership_count < cap` в той же транзакции; `AssignWork` исключает аккаунт из кандидатов |
| Курсор опроса пытаются сдвинуть назад (опоздавший опрос) | курсор не меняется | `WHERE last_message_id < :m` |
| Одно сообщение пришло live и опросом / из двух аккаунтов | обрабатывается один раз | unique `messages(source_id, message_id)`, `ON CONFLICT DO NOTHING`; проигравший ничего не делает (R2) |
| Рестарт процесса | опрос продолжается с курсора из БД; зависшие `resolving` → `candidate` (`reset_resolving` при старте) | курсор и статусы в БД |
| Потерян `USERBOT_STORE_KEY` | сессии не расшифровать | аккаунты ввести заново (`radar accounts login`) |

### Ошибки Telegram (маппинг в `telethon_gateway.map_error`)

| Ошибка Telethon | Порт | Реакция |
|---|---|---|
| `FloodWaitError`, `FloodPremiumWaitError` | `TgFlood(s)` | вступление/резолв: `apply_flood` (пауза s, ×1.5 интервал, −5 лимит; > 1 ч → `flood_wait` + алерт); опрос: пауза опроса аккаунта на s |
| `UserDeactivatedBanError`, `PhoneNumberBannedError` | `TgBanned` | `banned`, алерт, все источники аккаунта освобождаются, корутина аккаунта завершается; остальные работают |
| `UserDeactivatedError`, `AuthKey*`, `SessionRevoked/Expired` | `TgUnauthorized` | `unauthorized`, то же |
| `ChannelPrivate/Invalid`, `UsernameInvalid/NotOccupied`, `UserBannedInChannel`, `InviteHashExpired/Invalid`, `ChannelBanned`, `ChatForbidden` | `TgSourceGone` | источник `dead`, закрепление снимается, счётчик членств −1 |
| `InviteRequestSentError` | `TgJoinRequested` | источник `rejected`, закрепление снимается |
| `ChannelsTooMuchError` | `TgChannelsTooMuch` | `membership_count = cap`, пауза вступлений 1 ч |
| прочие (сеть и т.п.) | — | шаг логируется, корутина живёт; переподключение — Telethon |
| Инвайт привёл в уже известный чат | — | источник `rejected`, выход из чата, слот освобождается (R7) |

