# Audit — E2E, безопасность, вывод, производительность

Тесты покрывают все API: успех и отказ, формат ответов, безопасность и базовую производительность.

## Требования

- Python 3.10+
- Для полного прогона: запущенный бэкенд игры (или будет поднят через TestClient), при необходимости — Tigrit API и БД/Redis по инструкции бэкенда.
- Рекомендуется задать **TEST_API_BASE_URL** (URL работающего бэкенда): при использовании TestClient против приложения с asyncpg/БД возможны ошибки пула соединений и event loop; против живого сервера все тесты проходят стабильно.

## Переменные окружения

| Переменная | Описание |
|------------|----------|
| `TEST_API_BASE_URL` | Базовый URL бэкенда игры (например `http://localhost:8000`). Пусто — используется TestClient к приложению из `бэкенд/api/main.py`. |
| `TIGRIT_API_BASE` | Базовый URL Tigrit API (например `http://localhost:8004`). Пусто — тесты Tigrit пропускаются. |
| `INTERNAL_API_SECRET` | Секрет для `POST /internal/ensure-user`. Нужен для позитивных тестов internal. |
| `EDITOR_API_KEY` | Ключ редактора карты для `PUT /api/map` Tigrit. Нужен для позитивного теста сохранения карты. |

## Запуск

```bash
cd audit
pip install -r requirements.txt
pytest
```

- Только E2E: `pytest -m e2e`
- Только безопасность: `pytest -m security`
- Только вывод: `pytest -m output`
- Только производительность: `pytest -m performance`
- Только игра: `pytest e2e/test_game_api.py`
- Только Tigrit: `pytest e2e/test_tigrit_api.py`
- Только internal: `pytest e2e/test_internal_api.py`

При отсутствии URL/секретов отдельные тесты помечаются skip.
