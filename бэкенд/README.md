# Village Era — бэкенд

API для игры «Эра Деревни». Единая точка входа по бэкенду: каждая тема описана в одном документе (ссылки ниже).

---

## Стек

Python 3.10+, FastAPI, asyncpg (PostgreSQL), Redis (опционально).

---

## Источники (один документ на тему)

| Тема | Документ |
|------|----------|
| **Запуск локально** | [RUN_LOCAL.md](RUN_LOCAL.md) — Postgres, Redis (Docker), venv, фронт, переменные. |
| **REST API (эндпоинты)** | [API_REFERENCE.md](API_REFERENCE.md) — все пути, заголовки, env для API и внешних сервисов. |
| **Соответствие архитектуре** | [СООТВЕТСТВИЕ_АРХИТЕКТУРЕ.md](СООТВЕТСТВИЕ_АРХИТЕКТУРЕ.md) — что реализовано / не реализовано по 25_Архитектура и 18_Dev. |
| **Docker (Redis, опц. Postgres)** | [docker/README.md](docker/README.md) — `docker-compose.yml` в папке **docker/**; команды из `бэкенд/docker`. |
| **Скрипты проверки** | [скрипты/README.md](скрипты/README.md) — БД, API, iCryptoCheck-балансы. |
| **Тесты** | [tests/README_TESTS.md](tests/README_TESTS.md) — запуск E2E, TEST_API_BASE_URL. |
| **Админ-панель** | [API_REFERENCE.md](API_REFERENCE.md) § 0.1 — партнёрские токены, задания, тексты страниц (доступ по GAME_ADMIN_TG_ID). |
| **Переменные окружения** | [env.example](env.example) — полный список ключей. Как задать .env: см. [../ENV_README.md](../ENV_README.md). |

Механики игры (чекин, шахта, крафт, вывод и т.д.) описаны в **[Инструкция](../Инструкция/00_ОГЛАВЛЕНИЕ.md)**; архитектура и потоки — в [Инструкция/25_Архитектура.md](../Инструкция/25_Архитектура.md).

---

## Быстрый старт

```bash
cd бэкенд
pip install -r requirements.txt
# Задать DATABASE_URL, REDIS_URL в .env (см. env.example и RUN_LOCAL.md)
uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
```

Проверка подключений: `python скрипты/check_db_connections.py` (см. скрипты/README.md).
