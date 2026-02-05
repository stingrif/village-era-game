# Village Era Game Backend

API для игры «Эра Деревни»: состояние, действия, квест ФЕНИКС, уведомление админу. Критичные данные вынесены в отдельные поля и таблицы.

## Стек

- Python 3.10+, FastAPI, asyncpg (PostgreSQL), Redis (опционально)

## Переменные окружения

- `DATABASE_URL` — PostgreSQL
- `REDIS_URL` — кэш (опционально)
- `GAME_ADMIN_TG_ID` — Telegram ID админа (496560064)
- `GAME_NOTIFY_BOT_TOKEN` — токен бота для уведомлений
- `PHOENIX_QUEST_REWARD_AMOUNT` — 100000
- `MIN_BURN_COUNT_FOR_PHOENIX_QUEST` — минимум сжиганий для награды (по умолчанию 5)
- `MIN_ACCOUNT_AGE_DAYS_FOR_PHOENIX_QUEST` — минимум дней в игре (по умолчанию 3)
- `PHOENIX_QUEST_SUBMIT_RATE_LIMIT_SEC` — пауза между попытками завершить квест (сек)
- `BURN_DIMINISHING_AFTER` — после скольких сжиганий опыт ×0.5 (по умолчанию 50)

## Запуск

```bash
cd "Игра/бэкенд"
pip install -r requirements.txt
uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
```

## Эндпоинты

- `GET /api/game/state` — состояние игрока (заголовок `X-Telegram-User-Id` или `X-User-Id`)
- `POST /api/game/action` — действие: `sync`, `collect`, `burn`, `sell`, `buy_diamonds_points`, `phoenix_quest_submit`. Для квеста в `params` обязательно передаётся `letters_sequence: "ФЕНИКС"`; проверка последовательности и условий только на сервере.

Отдельного эндпоинта под награду квеста нет — всё через `action`.

## БД

- `game_players`: критические поля в колонках (`phoenix_quest_completed`, `burned_count`, `points_balance`, `created_at`), остальное в JSON `state`.
- `pending_payouts`: заявки на выплату (claim-ticket). Выплату 100k Phoenix обрабатывать вручную или воркером по этой таблице.

## Поинты

- Целые числа, округление на сервере (`math.ceil` от TON × POINTS_PER_TON). Дробные в БД не хранятся.

## Награда квеста ФЕНИКС

- Не мгновенная выплата: создаётся запись в `pending_payouts`, админу уходит уведомление в Telegram.
- Условия: минимум N сжиганий и M дней с создания аккаунта (см. переменные выше), плюс серверная проверка последовательности букв и rate-limit на попытки.

## Фронт

В HTML задать `G.API_BASE = 'http://...'` для работы с API. Завершение квеста — через `action: 'phoenix_quest_submit'` с `params.letters_sequence: 'ФЕНИКС'`.
