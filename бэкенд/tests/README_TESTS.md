# Запуск тестов (Village Era Game API)

## Требования

- Python 3.10+
- Установленные зависимости: `pip install -r requirements.txt`
- Для E2E: `pip install pytest httpx`
- **БД:** тесты вызывают реальное API с lifespan; нужен доступный PostgreSQL (по умолчанию `DATABASE_URL=postgresql://localhost/village_era`). Либо задайте переменную окружения:

  ```bash
  export DATABASE_URL="postgresql://user:pass@host:5432/village_era_test"
  ```

  Redis по умолчанию `redis://localhost:6379/0`; при его отсутствии кэш может не работать, но основные эндпоинты должны отвечать.

## Запуск

Из корня **бэкенда**:

```bash
cd бэкенд
python -m pytest tests/test_game_api_e2e.py -v
```

Если тесты падают из‑за несовместимости `TestClient` (starlette/httpx) или сервер не поднимается в субпроцессе, запустите API вручную и укажите базовый URL:

```bash
# Терминал 1
uvicorn api.main:app --reload --port 8000

# Терминал 2
export TEST_API_BASE_URL=http://127.0.0.1:8000
python -m pytest tests/test_game_api_e2e.py -v
```

С выводом логов:

```bash
python -m pytest tests/test_game_api_e2e.py -v -s
```

Только «дымовые» тесты (быстрая проверка):

```bash
python -m pytest tests/test_game_api_e2e.py -v -m smoke
```

## Что проверяет test_game_api_e2e.py

- Health и публичный конфиг (field, mine, eggs)
- Чекин, checkin-state, attempts
- Шахта: create, dig, get session
- Балансы и инвентарь
- Поле: field, buildings/def, place, demolish, upgrade, slots, equip, unequip, collect
- Крафт: merge, upgrade, reroll (в т.ч. ожидаемые 400 при нехватке ресурсов)
- Рынок: список ордеров, создание ордера, fill/cancel; trade-offers create/accept/cancel
- Вывод: eligibility, withdraw/request (заглушка), ads/view, donate
- Стейкинг: sessions, create (заглушка)
- Лидерборды

Подробный чеклист и рекомендации — в **docs/MEGA_AUDIT_REPORT.md** (в корне проекта Игра).
