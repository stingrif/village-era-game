# Docker — сервисы бэкенда

Postgres у вас уже есть. Остальное (Redis и при необходимости локальный Postgres) поднимается через Docker Compose **независимо**.

Команды ниже — из каталога **бэкенд/docker** (здесь лежит `docker-compose.yml`). Из корня проекта:
```bash
cd бэкенд/docker
```
или: `cd /Users/Den/Downloads/Игра/бэкенд/docker`

## Только Redis

```bash
cd бэкенд/docker
docker compose up redis -d
```

В `.env` укажите:
```env
REDIS_URL=redis://localhost:6379/0
```

Проверка: `python скрипты/check_db_connections.py`

Остановка: `docker compose stop redis`

## Локальный Postgres (опционально)

Если нужен свой контейнер с БД для разработки (без внешнего Postgres):

```bash
cd бэкенд/docker
docker compose --profile db up -d
```

В `.env`:
```env
DATABASE_URL=postgresql://village:village@127.0.0.1:5432/village_era
REDIS_URL=redis://localhost:6379/0
```

## Полезные команды

| Действие | Команда |
|--------|---------|
| Поднять только Redis | `docker compose up redis -d` |
| Поднять Redis + локальный Postgres | `docker compose --profile db up -d` |
| Логи Redis | `docker compose logs -f redis` |
| Остановить всё | `docker compose down` |
| Остановить и удалить тома | `docker compose down -v` |

Данные Redis и Postgres хранятся в именованных томах и сохраняются между перезапусками.
