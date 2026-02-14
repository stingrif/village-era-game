# Docker — раздача игры с ПК

Поднять всё одной командой: **сайт и API** в контейнерах, доступны на порту 80.

Команды — из каталога **бэкенд/docker**:
```bash
cd /Users/Den/Downloads/Игра/бэкенд/docker
```

## Запуск (сайт сразу доступен)

1. В **бэкенд/.env** задайте `DATABASE_URL` (ваш Postgres). Пример:
   ```env
   DATABASE_URL=postgresql://user:password@192.168.1.149:5432/village_era
   ```

2. Запустите контейнеры:
   ```bash
   docker compose up -d
   ```

3. Сайт: **http://localhost** (с этого ПК) или по вашему домену, если роутер смотрит на этот ПК и DNS настроен (например https://stakingphxpw.com).

Внутри поднимаются:
- **web** — nginx, раздаёт папку игры и проксирует `/api` на бэкенд (порт 80).
- **app** — бэкенд (uvicorn на 8000).

## Остановка

```bash
docker compose down
```

## Локальный Postgres в Docker (по желанию)

Если нужна своя БД в контейнере:

```bash
docker compose --profile db up -d
```

В **бэкенд/.env**:
```env
DATABASE_URL=postgresql://village:village@postgres:5432/village_era
```

(Контейнер postgres при этом должен быть в той же сети — он поднимется с профилем `db`.)

## Только Redis (без всего остального)

```bash
docker compose up redis -d
```

В `.env`: `REDIS_URL=redis://localhost:6379/0`

## Полезные команды

| Действие | Команда |
|--------|---------|
| Поднять сайт + API | `docker compose up -d` |
| Поднять с локальным Postgres | `docker compose --profile db up -d` |
| Логи | `docker compose logs -f app` или `docker compose logs -f web` |
| Остановить всё | `docker compose down` |
