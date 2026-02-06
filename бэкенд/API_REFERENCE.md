# Справочник: ключи, API и парсинг данных

Универсальный файл: все переменные окружения (из env.example и проекта НОВЫЙ) и как правильно вызывать каждый элемент API для парсинга данных.

---

## 0. Игровое REST API (Village Era, 25_Архитектура)

Базовый префикс: `/api/game`. Заголовок идентификации: `X-Telegram-User-Id` или `X-User-Id` (telegram_id).

| Метод и путь | Назначение |
|--------------|------------|
| GET `/api/game/config` | Публичный конфиг: field, mine, eggs (без авторизации) |
| GET `/api/game/state` | Состояние игры (legacy JSONB) |
| POST `/api/game/action` | Действия: collect, burn, phoenix_quest_submit, buy_diamonds_points, sell, sync |
| POST `/api/game/checkin` | Чекин: раз в 10 ч → 3 попытки шахты |
| GET `/api/game/checkin-state` | next_checkin_at, streak |
| GET `/api/game/attempts` | Текущий баланс попыток копания |
| POST `/api/game/mine/create` | Создать сессию шахты 6×6 → mine_id |
| POST `/api/game/mine/dig` | Копать ячейку: body `{ "mine_id", "cell_index" }` |
| GET `/api/game/mine/{mine_id}` | Сессия шахты (grid_size, opened_cells, без призовых) |
| GET `/api/game/partner-tokens` | Список активных партнёрских токенов (для оплаты и т.д.) |
| GET `/api/game/tasks` | Список активных заданий/контрактов |
| GET `/api/game/page-texts/{page_id}` | Тексты страницы (косметика): village, mine, profile, about и т.д. |

Конфиг игры: `GAME_CONFIG_PATH` (по умолчанию `data/game_config.json`). См. [18_Dev_таблицы_и_формулы.md](../Инструкция/18_Dev_таблицы_и_формулы.md), [25_Архитектура.md](../Инструкция/25_Архитектура.md).

---

## 0.1 Админ-панель API

Префикс: `/api/admin`. Доступ только при `X-Telegram-User-Id` = `GAME_ADMIN_TG_ID` (иначе 403). Во всех списках и создании сущностей можно передать `project_id` (query или body, по умолчанию `1`) для мультипроектности.

| Метод и путь | Назначение |
|--------------|------------|
| GET `/api/admin/partner-tokens` | Список партнёрских токенов (query: `project_id`, `active_only`) |
| POST `/api/admin/partner-tokens` | Добавить токен: body `{ "token_address", "symbol", "name?", "usage?", "sort_order?", "project_id?" }` |
| DELETE `/api/admin/partner-tokens/{id}` | Удалить партнёрский токен |
| GET `/api/admin/tasks` | Список заданий (query: `project_id`, `active_only`) |
| POST `/api/admin/tasks` | Добавить задание: body `{ "task_key", "title", "description?", "reward_type?", "reward_value?", "conditions_json?", "sort_order?", "project_id?" }` |
| PUT `/api/admin/tasks/{id}` | Обновить задание (поля по необходимости) |
| DELETE `/api/admin/tasks/{id}` | Удалить задание |
| GET `/api/admin/page-texts` | Все тексты по страницам (query: `project_id`) |
| GET `/api/admin/page-texts/{page_id}` | Тексты одной страницы (query: `project_id`) |
| PUT `/api/admin/page-texts/{page_id}` | Сохранить тексты: body `{ "key1": "value1", ... }`; опционально `project_id` в body |
| GET `/api/admin/channels` | Список каналов/чатов проекта (query: `project_id`, `active_only`) |
| POST `/api/admin/channels` | Добавить канал/чат: body `{ "chat_id", "title?", "channel_type?", "sort_order?", "project_id?" }` |
| DELETE `/api/admin/channels/{channel_id}` | Удалить канал/чат из проекта |
| GET `/api/admin/check-user-in-chat` | Проверить, в чате ли пользователь (query: `chat_id`, `user_id` — telegram_id). Нужен `BOT_TOKEN`, бот — админ в чате |
| POST `/api/admin/activity` | Записать событие активности: body `{ "telegram_id", "event_type", "channel_id?", "event_meta?", "project_id?" }`. event_type: `message_sent`, `reaction_received` и др. |
| GET `/api/admin/activity/log` | Лог активности (query: `project_id`, `user_id?`, `telegram_id?`, `limit`, `offset`) |
| GET `/api/admin/activity/stats` | Сводка по пользователям: всего сообщений, реакций, по типам реакций, последняя активность (query: `project_id`, `user_id?`) |

Партнёрские токены — только те, что в партнёрстве (оплата, призовой пул и т.д.). Задания — контракты/квесты с наградами. Тексты страниц — произвольные ключ/значение для подписей, описаний на экранах (village, mine, profile, about и др.). Каналы/чаты привязываются к проекту для рассылок и проверки участников. Активность: мониторинг сообщений, реакций, где и когда пользователь активен — пишется в `activity_log` и агрегаты в `user_activity_stats`.

---

## 1. Все переменные окружения по разделам

(Полный список — в `env.example`; здесь — краткая сводка для вызова API и парсинга.)

| Раздел | Переменные |
|--------|------------|
| **TON API** | `TON_API_URL`, `TON_API_KEY` |
| **TonViewer** | `TONVIEWER_API_URL`, `TONVIEWER_API_KEY` |
| **DYOR (цены)** | `DYOR_API_URL`, `DYOR_RATE_LIMIT`, `DYOR_MIN_DELAY`, `DYOR_API_KEY`, `DYOR_CURRENCY` |
| **iCryptoCheck** | `ICRYPTOCHECK_API_URL`, `ICRYPTOCHECK_API_KEY`, `*_WALLET_ID` (PROJECT, STAKING_POOL, ANIMALS_POOL, USER_PAYOUTS, PROJECT_INCOME, BURN, HOLDERS_REWARDS) |
| **Rate limits** | `TONAPI_RATE_LIMIT`, `TONAPI_MIN_DELAY`, `DEXSCREENER_RATE_LIMIT`, `DEXSCREENER_MIN_DELAY`, `ICRYPTOCHECK_RATE_LIMIT`, `ICRYPTOCHECK_MIN_DELAY` |
| **Адреса TON** | `PHOEX_TOKEN_ADDRESS`, `PROJECT_WALLET_ADDRESS`, `BURN_WALLET_ADDRESS`, `HOLDERS_POOL_WALLET_ADDRESS`, `STAKING_POOL_WALLET_ADDRESS`, `PRIMARY_NFT_COLLECTION`, `STONFI_POOL_ADDRESS`, `DEDUST_POOL_ADDRESS`, `USDT_POOL_ADDRESS` |
| **Каналы/чаты** | `PHOEX_CHANNEL_ID`, `PHOEX_CHAT_ID`, `PHXPW_*`, `PHOENIX_REWARD_CHANNEL_ID`, `PHOENIX_LUCKY_CHAT_ID`, `WHALES_CHAT_ID`, `PREMIUM_PHOENIX_CLUB_ID` |
| **Ссылки** | `PHOEX_CHANNEL_LINK`, `PHOEX_CHAT_LINK`, `DEX_POOL_LINK`, `SWAP_LINK`, `WEBSITE_LINK`, `NFT_COLLECTION_LINK`, `JVAULT_STAKING_LINK` и др. |
| **Игра** | `GAME_ADMIN_TG_ID`, `GAME_NOTIFY_BOT_TOKEN`, `PHOENIX_QUEST_REWARD_AMOUNT`, `POINTS_PER_TON`, `MIN_BURN_COUNT_FOR_PHOENIX_QUEST`, `MIN_ACCOUNT_AGE_DAYS_FOR_PHOENIX_QUEST` |
| **БД** | `DATABASE_URL`, `REDIS_URL` (опционально) |
| **Telegram** | `BOT_TOKEN`, `ADMIN_IDS`, `CREATOR_ID`, `FEEDBACK_CHAT_ID` |
| **Прочее** | `PROXY_URL`, `TIMEZONE`, комиссии, чекин, бэкапы — см. env.example |

---

## 2. TonAPI (tonapi.io/v2)

Базовый URL: `TON_API_URL` (например `https://tonapi.io/v2`).  
Заголовок: `Authorization: Bearer <TON_API_KEY>`.

Соответствие путей и официальных имён в документации:

| Справочник (путь) | Официальное имя TonAPI | Документация |
|-------------------|------------------------|--------------|
| GET /accounts/{id}/events?limit=100 | getAccountEvents | [Accounts](https://docs.tonconsole.com/tonapi/rest-api/accounts) |
| GET /accounts/{id}/transactions?limit=100 | getAccountTransactions | [Accounts](https://docs.tonconsole.com/tonapi/rest-api/accounts) |
| GET /accounts/{id} | getAccount | [Accounts](https://docs.tonconsole.com/tonapi/rest-api/accounts) |
| GET /accounts/{id}/jettons | getAccountJettonsBalances | [Accounts](https://docs.tonconsole.com/tonapi/rest-api/accounts) |
| GET /accounts/{acc}/jettons/{jetton_id} | getAccountJettonBalance | [Accounts](https://docs.tonconsole.com/tonapi/rest-api/accounts) |
| GET /jettons/{jetton_id}/transfers?limit=100 | (Jettons) | [Jettons](https://docs.tonconsole.com/tonapi/rest-api/jettons) |
| GET /accounts/{id}/nfts?limit=100 | getAccountNftItems | [NFT](https://docs.tonconsole.com/tonapi/rest-api/nft) |

Общая ссылка REST: [TonAPI REST](https://docs.tonconsole.com/tonapi/rest-api).

### 2.1 События аккаунта (events)

**URL (подставить адрес из текста/сообщения):**
```text
GET {TON_API_URL}/accounts/{address}/events?limit=100
```
Пример из n8n: адрес из ввода — `https://tonapi.io/v2/accounts/{{ $json.message.text }}/events` (вместо `{address}` подставляется `$json.message.text`).

Опционально: `&start_from={event_id}` — пагинация.

**Ответ:** `{ "events": [ ... ] }`

**Парсинг одного события (как в n8n / из текста НОВЫЙ):**
```javascript
const events = $json.events || [];
return events.map(e => {
  const action0 = (e.actions && e.actions[0]) ? e.actions[0] : {};
  const preview = action0.simple_preview || {};
  const subject = action0[action0.type] || {}; // объект по типу действия
  return {
    json: {
      event_id: e.event_id,
      ts: e.timestamp,
      time_iso: new Date((e.timestamp || 0) * 1000).toISOString(),
      account: e.account?.address,
      action_type: action0.type,
      action_status: action0.status,
      title: preview.name,
      description: preview.description,
      ton_attached: subject.ton_attached ?? null,
      executor: subject.executor?.address ?? null,
      contract: subject.contract?.address ?? null,
      operation: subject.operation ?? null,
    }
  };
});
```

В Python (пример):
```python
data = await client.get(f"{TON_API_URL}/accounts/{address}/events", params={"limit": 100})
events = data.get("events", [])
for e in events:
    action0 = (e.get("actions") or [None])[0]
    if not action0: continue
    action_type = action0.get("type")
    subject = action0.get(action_type, {})
    # ton_attached, executor, contract, operation — из subject
```

### 2.2 Транзакции аккаунта

**Запрос:**
```http
GET {TON_API_URL}/accounts/{address}/transactions?limit=100
```
Подставить вместо `{address}` адрес кошелька или jetton-wallet. Пример из текста: `GET https://tonapi.io/v2/accounts/{JETTON_WALLET}/transactions?limit=100` — история транзакций по jetton-кошельку.

Используется для истории переводов по адресу (в т.ч. кошелёк проекта).

### 2.3 Информация об аккаунте (баланс TON)

**Запрос:**
```http
GET {TON_API_URL}/accounts/{address}
```

**Парсинг:**
- Поле `balance` — целое число в **минимальных единицах TON**. Значение в TON: `int(balance) / 1_000_000_000` (1 TON = 10^9 минимальных единиц). [get-account-state-and-balance (toncenter)](https://docs.ton.org/ecosystem/api/toncenter/v2/accounts/get-account-state-and-balance)

### 2.4 Jettons аккаунта (балансы токенов)

**Запрос:**
```http
GET {TON_API_URL}/accounts/{address}/jettons
```

**Ответ:** `{ "balances": [ { "jetton": { "address", "symbol", "name", "decimals" }, "balance": "..." } ] }`

**Парсинг баланса PHOEX:**
- Найти в `balances` элемент, где `jetton.address == PHOEX_TOKEN_ADDRESS` (или `jetton.symbol == "PHOEX"`).
- `balance` — строка с количеством в **минимальных единицах** jetton. Человекочитаемое значение: `int(balance) / (10 ** jetton["decimals"])`. [TonAPI dapp building (tonconsole)](https://docs.tonconsole.com/tonapi/dapp/building)

### 2.5 Баланс одного jetton у аккаунта

**Запрос:**
```http
GET {TON_API_URL}/accounts/{account_address}/jettons/{jetton_master_address}
```

Возвращает один объект с `balance` и `jetton` (decimals и т.д.). Удобно для пула ликвидности или одного токена.

### 2.6 Информация о jetton (контракт токена)

**Запрос:**
```http
GET {TON_API_URL}/jettons/{jetton_address}
```
Или по пути из доки TonAPI для метаданных токена.

### 2.7 Транзакции/transfers jetton

**Запрос:**
```http
GET {TON_API_URL}/jettons/{jetton_address}/transfers?limit=100
```
Опционально: `&start_from={event_id}`.

**Ответ:** `{ "transfers": [ ... ] }` — список переводов токена (входящие/исходящие по контракту jetton).

### 2.8 NFT аккаунта

**Запрос:**
```http
GET {TON_API_URL}/accounts/{address}/nfts?limit=100
```

**Ответ:** `{ "nft_items": [ { "address", "collection", "metadata" } ] }`.

---

## 3. TonViewer API

Базовый URL: `TONVIEWER_API_URL` (например `https://tonviewer.com/api/v2`).  
Заголовок с ключом — по документации TonViewer (если требуется).

Используется как альтернативный источник данных по адресам/транзакциям; конкретные эндпоинты см. в официальной доке TonViewer.

---

## 4. iCryptoCheck API

Базовый URL: `ICRYPTOCHECK_API_URL` (например `https://api.icryptocheck.com/api/v1`).  
Ключ: `ICRYPTOCHECK_API_KEY` (заголовок или query — по доке iCryptoCheck).

**Идентификаторы кошельков (wallet_id):** в env заданы как `PROJECT_WALLET_ID`, `STAKING_POOL_WALLET_ID`, `ANIMALS_POOL_WALLET_ID`, `USER_PAYOUTS_WALLET_ID`, `PROJECT_INCOME_WALLET_ID`, `BURN_WALLET_ID`, `HOLDERS_REWARDS_WALLET_ID`. Каждый `wallet_id` соответствует приложению/токену в iCryptoCheck — подставлять в вызовы API по балансам/выводам согласно документации iCryptoCheck.

**Лимиты:** `ICRYPTOCHECK_RATE_LIMIT`, задержка `ICRYPTOCHECK_MIN_DELAY` между запросами.

---

## 5. DexScreener (пулы/цена)

Ссылка на пул из env: `DEX_POOL_LINK` (например DexScreener TON).  
Для программного доступа — публичное API DexScreener (если используется): обычно по пару или адресу контракта. Лимиты: `DEXSCREENER_RATE_LIMIT`, `DEXSCREENER_MIN_DELAY`.

---

## 6. DYOR API (цены)

Базовый URL: `DYOR_API_URL` = `https://api.dyor.io` (без `/v1` в base). [Overview: docs.dyor.io](https://docs.dyor.io)  
Эндпоинты сами добавляют путь (например `/v1/...`).  
Рекомендуемый лимит — не более **1 запроса в секунду** на ключ (Client Requests). [DYOR Technical Guides — Client](https://docs.dyor.io/technical-guides/client)  
В env: `DYOR_RATE_LIMIT`, задержка `DYOR_MIN_DELAY` (не менее 1 с) между запросами.

Используется для получения курсов (например TON/USD, токен/USD).

---

## 7. Адреса и константы Phoenix (из конфига)

- **PHOEX (токен):** `EQABtSLSzrAOISWPfIjBl2VmeStkM1eHaPrUxRTj8mY-9h43`
- **Кошелёк проекта:** `UQDNjfMdhOSkXdyzuicb9rr7Ot1ukln5TFgGchtjgc7PaoaR`
- **Burn wallet:** `UQB9lT-CTjv-jk6tl3nGtsMFMES3JS0ecUJhB4LCbgC6CLPa`
- **Holders pool:** `UQAHDtsPtjX1F_bpanpCl2Wd3c0PA3ACy77ofdX7yp3rBwi8`
- **STONFI pool:** `EQCMuqMuALJE-tzVLS1tD72l4dM8TDw3-xDe68_wnAadmTP8`
- **NFT коллекция:** `EQBnGWMCf3-FZZq1W4IWcWiGAc3PHuZ0_H-7sad2oY00o83S`

Подставлять в запросы вместо `{address}` или `{jetton_address}`.

---

## 8. Rate limits и задержки

- **TonAPI:** рекомендуется не чаще 1 запроса в 1.2 с (при наличии ключа), иначе возможен 429. При 429 — заголовок `Retry-After`, подождать указанное время.
- **DYOR:** 1 req/sec без ключа.
- В коде (как в НОВЫЙ): хранить `last_request_time` и делать `sleep(min_delay)` перед следующим запросом.

---

## 9. Итоговая таблица вызовов для парсинга

| Что нужно | Метод и путь | Ключевые поля ответа |
|-----------|--------------|------------------------|
| События кошелька | GET `/accounts/{address}/events?limit=100` | `events[].actions[].type`, `simple_preview`, subject по типу |
| Транзакции кошелька | GET `/accounts/{address}/transactions?limit=100` | Список транзакций |
| Баланс TON | GET `/accounts/{address}` | `balance` (минимальные единицы) |
| Балансы jettons | GET `/accounts/{address}/jettons` | `balances[].jetton`, `balances[].balance` |
| Баланс одного jetton | GET `/accounts/{acc}/jettons/{jetton_addr}` | `balance`, `jetton.decimals` |
| Переводы токена | GET `/jettons/{jetton_addr}/transfers?limit=100` | `transfers[]` |
| NFT пользователя | GET `/accounts/{address}/nfts?limit=100` | `nft_items[]` |

Все запросы к TonAPI — с заголовком `Authorization: Bearer <TON_API_KEY>`.

---

## 10. Ссылки для самопроверки

- TonAPI REST: https://docs.tonconsole.com/tonapi/rest-api  
- TonAPI Accounts: https://docs.tonconsole.com/tonapi/rest-api/accounts  
- TonAPI Jettons: https://docs.tonconsole.com/tonapi/rest-api/jettons  
- TonAPI NFT: https://docs.tonconsole.com/tonapi/rest-api/nft  
- TON APIs (общий контекст): https://docs.ton.org/v3/guidelines/dapps/apis-sdks/api-types  
- Toncenter (баланс в минимальных единицах): https://docs.ton.org/ecosystem/api/toncenter/v2/accounts/get-account-state-and-balance  
- DYOR docs: https://docs.dyor.io  
- DYOR client (1 req/s): https://docs.dyor.io/technical-guides/client
