# Скрипты бэкенда

Все скрипты читают переменные из `.env` в папке бэкенда. Запуск из папки **бэкенд**: `python скрипты/<имя>.py`.

---

## check_db_connections.py

Проверка связи с БД из `.env`:

- **PostgreSQL** — `DATABASE_URL` (или сборка из `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`)
- **Redis** — `REDIS_URL`

Пароли в выводе маскируются.

```bash
python скрипты/check_db_connections.py
```

---

## check_apis.py

Проверка доступности внешних API:

- **TON API** — `TON_API_URL`, `TON_API_KEY`
- **TonViewer** — `TONVIEWER_API_URL`
- **DYOR** — `DYOR_API_URL`, `DYOR_API_KEY`

```bash
python скрипты/check_apis.py
```

---

## check_icryptocheck_balances.py

Проверка балансов кошельков проекта в iCryptoCheck. В iCryptoCheck **wallet_id = API-токен** приложения. Для каждого из переменных `PROJECT_WALLET_ID`, `STAKING_POOL_WALLET_ID`, `ANIMALS_POOL_WALLET_ID`, `USER_PAYOUTS_WALLET_ID`, `PROJECT_INCOME_WALLET_ID`, `BURN_WALLET_ID`, `HOLDERS_REWARDS_WALLET_ID` выполняется запрос `GET /app/info` с заголовком `iCryptoCheck-Key: <wallet_id>` и выводятся балансы TON и токена проекта.

Используются: `ICRYPTOCHECK_API_URL`, `TOKEN_DISPLAY_SYMBOL`, `ICRYPTOCHECK_TOKEN_SYMBOL`. В заголовке — соответствующий `*_WALLET_ID`.

**Перевод (POST /app/transfer):** работает с ключом `ICRYPTOCHECK_API_KEY` (не wallet_id). Поля: `tgUserId`, `currency`, `amount`, `description`. Полное описание — [Инструкция 23 — Вывод через iCryptoCheck](../../Инструкция/23_Вывод_через_iCryptoCheck.md).

```bash
python скрипты/check_icryptocheck_balances.py
```

---

## Запуск всех проверок

```bash
python скрипты/check_db_connections.py && python скрипты/check_apis.py && python скрипты/check_icryptocheck_balances.py
```

Код возврата: `0` — успех, `1` — есть ошибки.
