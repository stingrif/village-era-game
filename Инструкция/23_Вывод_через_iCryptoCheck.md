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
| `iCryptoCheck-Key` | Значение `*_WALLET_ID` (API-токен приложения) | GET /app/info, привязка к конкретному кошельку |
| `Accept` | `application/json` | Все запросы |
| `Content-Type` | `application/json` | POST с телом |

По документации iCryptoCheck может использоваться один общий ключ или ключ на приложение — уточняйте в вашем контракте/документации iCryptoCheck.

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

**Назначение:** отправить TON или токен пользователю по его **Telegram ID**. Получатель получит вывод через бота iCryptoCheck (или встроенный механизм шлюза).

**Статус у нас:** в бэкенде **заглушка**. Эндпоинт `POST /api/game/withdraw/request` проверяет eligibility и возвращает `"iCryptoCheck not configured"`; реальный вызов iCryptoCheck не выполняется.

**Шаблон запроса:**

```http
POST {ICRYPTOCHECK_API_URL}/app/transfer
Content-Type: application/json
iCryptoCheck-Key: <wallet_id>   # обычно USER_PAYOUTS_WALLET_ID или PROJECT_WALLET_ID
Accept: application/json

{
  "telegram_id": 123456789,
  "amount": "1.5",
  "currency": "TON"
}
```

**Варианты полей (подставить по доке iCryptoCheck):**

| Поле | Описание | Пример |
|------|----------|--------|
| `telegram_id` | ID пользователя в Telegram | `123456789` |
| `amount` | Сумма (строка или число) | `"1.5"` |
| `currency` | TON или символ токена | `"TON"`, `"PHXPW"` |
| `comment` | Комментарий к переводу (опционально) | `"withdraw"` |

**Шаблон ответа (ожидаемый):**

```json
{
  "success": true,
  "data": {
    "transaction_id": "...",
    "status": "pending"
  }
}
```

При ошибке — `success: false`, в теле сообщение об ошибке. После подключения в коде вызывать из обработчика `POST /api/game/withdraw/request` (body: `amount`, `to_telegram_id`).

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
| Баланс приложения (кошелька) | GET /app/info | ✅ Скрипт `скрипты/check_icryptocheck_balances.py` | Запуск: `python скрипты/check_icryptocheck_balances.py` из папки бэкенд. В env задать нужные `*_WALLET_ID`. |
| Перевод на Telegram ID | POST /app/transfer | ❌ Заглушка в `POST /api/game/withdraw/request` | Подключить вызов iCryptoCheck в `api/routes.py` по шаблону выше. |
| Вывод на TON-адрес | POST /app/withdrawal | ❌ Не вызывается | Аналогично, в обработчике withdraw при `to_address`. |
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
| Баланс приложения | `/app/info` | GET | iCryptoCheck-Key: wallet_id | — |
| Перевод на Telegram | `/app/transfer` | POST | iCryptoCheck-Key: wallet_id | telegram_id, amount, currency |
| Вывод на адрес | `/app/withdrawal` | POST | iCryptoCheck-Key: wallet_id | address, amount, currency |
| Адрес депозита | `/app/payment-addresses` | POST | iCryptoCheck-Key: wallet_id | user_id/telegram_id, session_id |

Базовый URL: `ICRYPTOCHECK_API_URL`. Точные имена полей и коды ответов уточняйте в документации iCryptoCheck, предоставленной вам как партнёру.
