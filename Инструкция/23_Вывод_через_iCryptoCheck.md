# Вывод и переводы через iCryptoCheck

iCryptoCheck — платёжный шлюз для TON и токенов проекта. В этом файле: **все виды транзакций и переводов**, шаблоны запросов/ответов и то, **что у нас уже работает по API**.

Условия вывода (eligibility, риск, правило 10%) — в [08_Вывод_и_антихалява.md](08_Вывод_и_антихалява.md). Стейкинг — [22_Стейкинг_токена.md](22_Стейкинг_токена.md).

---

## 1. Переменные окружения (env)

В `бэкенд/.env` (шаблон в `бэкенд/env.example`):

| Переменная | Назначение |
|------------|------------|
| `ICRYPTOCHECK_API_URL` | Базовый URL API, например `https://api.icryptocheck.com/api/v1` |
| `ICRYPTOCHECK_API_KEY` | Общий API-ключ (если используется одним заголовком для всех вызовов) |
| `ICRYPTOCHECK_TOKEN_SYMBOL` | Символ токена в iCryptoCheck (PHXPW / PHOEX) |
| `ICRYPTOCHECK_RATE_LIMIT` | Лимит запросов (например 100) |
| `ICRYPTOCHECK_MIN_DELAY` | Минимальная задержка между запросами в секундах (например 0.2) |
| `PROJECT_WALLET_ID` | API-токен приложения «Кошелёк проекта» |
| `STAKING_POOL_WALLET_ID` | Пул стейкинга |
| `ANIMALS_POOL_WALLET_ID` | Пул животных |
| `USER_PAYOUTS_WALLET_ID` | Выплаты пользователям |
| `PROJECT_INCOME_WALLET_ID` | Доход проекта |
| `BURN_WALLET_ID` | Burn |
| `HOLDERS_REWARDS_WALLET_ID` | Награды холдерам |

**Важно:** в iCryptoCheck каждый `*_WALLET_ID` — это **API-токен приложения** (wallet_id). Для запросов баланса используется заголовок `iCryptoCheck-Key: <wallet_id>`.

---

## 2. Общие заголовки запросов

| Заголовок | Значение | Когда использовать |
|-----------|----------|--------------------|
| `iCryptoCheck-Key` | `ICRYPTOCHECK_API_KEY` | **POST /app/transfer** — перевод пользователю (общий ключ приложения) |
| `iCryptoCheck-Key` | Значение `*_WALLET_ID` (API-токен приложения) | **GET /app/info** — баланс конкретного кошелька |
| `Accept` | `application/json` | Все запросы |
| `Content-Type` | `application/json` | POST с телом |

**Важно:** для **перевода** используется **общий ключ** `ICRYPTOCHECK_API_KEY`. Для **баланса кошелька** — соответствующий `*_WALLET_ID`.

---

## 3. Типы операций и шаблоны

### 3.1 GET /app/info — баланс приложения (кошелька)

**Назначение:** получить баланс приложения (TON и токены). Это **не** баланс пользователя — баланс того приложения/кошелька, чей `wallet_id` передан в заголовке.

**Статус у нас:** ✅ **работает**. Используется в скрипте `бэкенд/скрипты/check_icryptocheck_balances.py`.

**Запрос:**

```http
GET {ICRYPTOCHECK_API_URL}/app/info
iCryptoCheck-Key: <wallet_id>
Accept: application/json
```

**Пример (curl):**

```bash
curl -s -H "iCryptoCheck-Key: YOUR_PROJECT_WALLET_ID" \
     -H "Accept: application/json" \
     "https://api.icryptocheck.com/api/v1/app/info"
```

**Пример ответа (уже получаем в коде):**

```json
{
  "success": true,
  "data": {
    "name": "Название приложения",
    "balances": [
      { "token": "TON", "balance": "1.5" },
      { "token": "PHXPW", "balance": "100000.0" }
    ]
  }
}
```

Если `balances` приходит объектом (ключ — символ токена), в скрипте это приводится к списку. Символ токена в ответе может быть `PHXPW`, `PHOEX` или иной — в env задаётся `ICRYPTOCHECK_TOKEN_SYMBOL`.

---

### 3.2 POST /app/transfer — перевод на Telegram ID

**Назначение:** отправить TON или токен пользователю по его **Telegram ID**. Получатель получает вывод через бота iCryptoCheck.

**Статус у нас:** ✅ **работает** (проверено тестами). В бэкенде автоматический вызов из `POST /api/game/withdraw/request` пока не подключён — тест выполнялся скриптом/curl.

**Заголовок:** обязательно **`iCryptoCheck-Key: <ICRYPTOCHECK_API_KEY>`** (общий API-ключ приложения), **не** `*_WALLET_ID`.

**Запрос:**

```http
POST {ICRYPTOCHECK_API_URL}/app/transfer
Content-Type: application/json
iCryptoCheck-Key: <ICRYPTOCHECK_API_KEY>
Accept: application/json

{
  "tgUserId": "496560064",
  "currency": "PHXPW",
  "amount": "1000",
  "description": "награды за задания"
}
```

**Поля (обязательные и проверенные):**

| Поле | Тип | Описание | Пример |
|------|-----|----------|--------|
| `tgUserId` | строка | ID пользователя в Telegram | `"496560064"` |
| `currency` | строка | Символ токена или TON | `"PHXPW"`, `"TON"` |
| `amount` | строка или число | Сумма | `"1000"` или `1000` |
| `description` | строка | Комментарий к переводу (показывается получателю) | `"награды за задания"` |

**Важно:** для комментария в сообщении получателю используется поле **`description`**. Поле `comment` API игнорирует.

**Пример ответа (201 Created):**

```json
{
  "success": true,
  "data": {
    "id": "6990f228758bbc0deb8c171d",
    "tgUserId": "496560064",
    "currency": "PHXPW",
    "amount": "1000.000000000",
    "description": "награды за задания"
  }
}
```

При ошибке валидации — `400` и `success: false`, в `errors` — список полей (например `tgUserId`, `currency` обязательны).

---

### 3.3 POST /app/withdrawal — вывод на TON-адрес

**Назначение:** вывод на произвольный **TON-адрес** (холодный кошелёк и т.п.).

**Статус у нас:** в бэкенде **не вызывается**. Тот же `POST /api/game/withdraw/request` при `to_address` в body должен в итоге вызывать этот метод.

**Шаблон запроса:**

```http
POST {ICRYPTOCHECK_API_URL}/app/withdrawal
Content-Type: application/json
iCryptoCheck-Key: <wallet_id>
Accept: application/json

{
  "address": "UQxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "amount": "1.5",
  "currency": "TON"
}
```

**Варианты полей:**

| Поле | Описание | Пример |
|------|----------|--------|
| `address` | TON-адрес получателя | `"UQ..."` |
| `amount` | Сумма | `"1.5"` |
| `currency` | `"TON"` или символ токена | `"PHXPW"` |
| `comment` | Комментарий (опционально) | `"withdraw"` |

**Шаблон ответа:**

```json
{
  "success": true,
  "data": {
    "transaction_id": "...",
    "status": "pending"
  }
}
```

Имена полей и коды ошибок — по официальной документации iCryptoCheck.

---

### 3.4 POST /app/payment-addresses — адрес для депозита (стейкинг, оплаты)

**Назначение:** получить **уникальный адрес депозита** для зачисления средств (стейкинг, пополнение). Пользователь переводит на этот адрес; по блокчейну мы зачисляем на баланс/стейк.

**Статус у нас:** в бэкенде **заглушка**. `POST /api/game/staking/create` возвращает `"iCryptoCheck payment-addresses not configured"`, адрес не запрашивается.

**Шаблон запроса:**

```http
POST {ICRYPTOCHECK_API_URL}/app/payment-addresses
Content-Type: application/json
iCryptoCheck-Key: <wallet_id>   # например STAKING_POOL_WALLET_ID
Accept: application/json

{
  "user_id": "123456789",
  "telegram_id": 123456789,
  "session_id": "staking_abc123",
  "expires_in_seconds": 3600
}
```

**Варианты полей:**

| Поле | Описание | Пример |
|------|----------|--------|
| `user_id` / `telegram_id` | Идентификатор пользователя | число или строка |
| `session_id` | Уникальный ID сессии (стейк, заказ) | строка |
| `expires_in_seconds` | Время жизни адреса (опционально) | `3600` |
| `comment_prefix` | Префикс комментария для зачисления (если поддерживается) | `"ref:123"` |

**Шаблон ответа:**

```json
{
  "success": true,
  "data": {
    "payment_address": "UQxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
    "expires_at": "2025-02-08T12:00:00Z"
  }
}
```

После подключения: в `POST /api/game/staking/create` вызывать этот endpoint, сохранять `payment_address` в `staking_sessions` и отдавать клиенту.

---

## 4. Что у нас уже работает и выводится по API

| Операция | Метод iCryptoCheck | У нас в коде | Доступ для других |
|----------|--------------------|--------------|--------------------|
| Баланс приложения (кошелька) | GET /app/info | ✅ Скрипт `скрипты/check_icryptocheck_balances.py` | Запуск: `python скрипты/check_icryptocheck_balances.py` из папки бэкенд. В заголовке — `*_WALLET_ID`. |
| Перевод на Telegram ID | POST /app/transfer | ✅ Проверено (тест скриптом) | Ключ: `ICRYPTOCHECK_API_KEY`. Поля: `tgUserId`, `currency`, `amount`, `description`. Автовызов из `POST /api/game/withdraw/request` — пока не подключён. |
| Вывод на TON-адрес | POST /app/withdrawal | ❌ Не вызывается | В обработчике withdraw при `to_address`. |
| Адрес депозита (стейкинг) | POST /app/payment-addresses | ❌ Заглушка в `POST /api/game/staking/create` | Подключить в стейкинг-логике, сохранять адрес в БД. |

**Проверка балансов (помощь другим):**  
Из корня бэкенда выполнить:

```bash
cd бэкенд
python скрипты/check_icryptocheck_balances.py
```

Скрипт читает из `.env` все `*_WALLET_ID`, для каждого делает GET /app/info и выводит TON и токен проекта. Если какой-то wallet_id не задан или неверный — будет предупреждение или ошибка.

---

## 5. Чего iCryptoCheck не делает (наша зона ответственности)

- **Баланс пользователя в игре** — храним в нашей БД (`user_balances`).
- **История транзакций пользователя** — наша БД (`token_transactions`, `withdraw_gating` и т.д.).
- **Проверки:** eligibility, risk_score, правило 10%, лимиты — всё на нашей стороне перед вызовом transfer/withdrawal.

---

## 6. Связь с нашим API

| Наш эндпоинт | Назначение | iCryptoCheck |
|--------------|------------|---------------|
| GET /api/game/withdraw/eligibility | Проверить, можно ли выводить | не вызывается |
| POST /api/game/withdraw/request | Запрос вывода (body: amount, to_telegram_id или to_address) | должен вызывать /app/transfer или /app/withdrawal |
| POST /api/game/staking/create | Создать стейк-сессию, получить адрес депозита | должен вызывать /app/payment-addresses |

Webhook от iCryptoCheck (если включён): в env задаются `ICRYPTOCHECK_WEBHOOK_URL`, `ICRYPTOCHECK_WEBHOOK_SECRET` — для уведомлений о статусе платежей/выводов.

---

## 7. Краткая шпаргалка по шаблонам

| Тип | URL | Метод | Ключ в заголовке | Тело (POST) |
|-----|-----|--------|-------------------|-------------|
| Баланс приложения | `/app/info` | GET | iCryptoCheck-Key: `*_WALLET_ID` | — |
| Перевод на Telegram | `/app/transfer` | POST | iCryptoCheck-Key: **ICRYPTOCHECK_API_KEY** | tgUserId, currency, amount, description |
| Вывод на адрес | `/app/withdrawal` | POST | iCryptoCheck-Key: wallet_id | address, amount, currency |
| Адрес депозита | `/app/payment-addresses` | POST | iCryptoCheck-Key: wallet_id | user_id/telegram_id, session_id |

Базовый URL: `ICRYPTOCHECK_API_URL`. Точные имена полей и коды ответов уточняйте в документации iCryptoCheck, предоставленной вам как партнёру.
