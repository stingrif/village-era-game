# Деплой на kim@192.168.1.149 в Docker

## 0. Один раз: вход по ключу (без пароля)

Чтобы не вводить пароль при каждой выгрузке, настройте ключ **один раз**:

```bash
cd "/Users/Den/Downloads/Игра/deploy"
chmod +x setup_ssh_key_149.sh
./setup_ssh_key_149.sh
```

Когда скрипт попросит пароль — введите пароль от пользователя **kim** на сервере.  
Создаётся ключ **без пароля** (`~/.ssh/stakingphxpw_149`), он копируется на 149 и добавляется в `~/.ssh/config`. Дальше `ssh` и выгрузка работают без ввода пароля.

**Неинтерактивно** (пароль не сохраняется в файлах, только в этой команде):

```bash
brew install sshpass   # если ещё нет
SSHPASS=ВАШ_ПАРОЛЬ ./setup_ssh_key_149.sh
```

## 1. Выгрузить проект с Mac

На **этом Mac**:

```bash
cd "/Users/Den/Downloads/Игра/deploy"
chmod +x upload_to_149_docker.sh
./upload_to_149_docker.sh
```

Файлы попадут в **/home/kim/stakingphxpw** на сервере.

## 2. Развернуть в Docker на сервере

Подключиться к серверу и запустить деплой:

```bash
ssh kim@192.168.1.149
cd /home/kim/stakingphxpw && bash deploy/deploy_docker_on_149.sh
```

Или одной командой с Mac:

```bash
ssh kim@192.168.1.149 'cd /home/kim/stakingphxpw && bash deploy/deploy_docker_on_149.sh'
```

Скрипт создаст при необходимости `config.js` и `бэкенд/.env`, затем поднимет контейнеры:
- **stakingphxpw-app** — API (uvicorn:8000)
- **stakingphxpw-api-gateway** — nginx, единая точка входа (порт 8081; статика, /api, /ws, /internal/health, /internal/ready; server для tigrit.stakingphxpw.com → tigrit-web)
- **stakingphxpw-health** — микросервис Health Check (liveness /health, readiness /ready с проверкой БД и Redis)
- **stakingphxpw-tigrit-bot** — бот «Деревня Тигрит» (общая БД, ensure-user к app, tigrit_shared)
- **stakingphxpw-tigrit-api** — веб-API Тигрит (FastAPI, данные из PostgreSQL через tigrit_shared)
- **stakingphxpw-tigrit-web** — фронт Тигрит (Vite + nginx, /api проксируется на tigrit-api)
- **stakingphxpw-secrets**, **stakingphxpw-auth**, **stakingphxpw-sessions** — микросервисы (при наличии .env.secrets)
- **stakingphxpw-redis** — Redis

## 3. Бэкенд .env на сервере

В **/home/kim/stakingphxpw/бэкенд/.env** должен быть **DATABASE_URL** (Postgres).  
Если файла не было, он создаётся из `env.example` — отредактируйте:

```bash
ssh kim@192.168.1.149
nano /home/kim/stakingphxpw/бэкенд/.env
# Задайте DATABASE_URL=postgresql://user:pass@host:port/dbname
# Для бота Тигрит: TELEGRAM_BOT_TOKEN=... (токен бота Деревня Тигрит), INTERNAL_API_SECRET=... (тот же, что для internal API)
# Затем перезапуск: cd /home/kim/stakingphxpw && docker compose -f deploy/docker-compose.149.yml restart app
```

## 4. Если порт 80 на 149 уже занят (n8n и т.п.)

В **deploy/docker-compose.149.yml** замените у сервиса `api-gateway`:

```yaml
ports:
  - "8080:80"
```

Тогда сайт будет на порту 8080. Проброс на роутере: внешний 80 → 192.168.1.149:8080, либо настройте основной nginx на 149 как прокси для stakingphxpw.com на `http://127.0.0.1:8080`.

## 5. Полезные команды на сервере

| Действие | Команда |
|----------|--------|
| Логи | `cd /home/kim/stakingphxpw && docker compose -f deploy/docker-compose.149.yml logs -f` |
| Остановить | `docker compose -f deploy/docker-compose.149.yml down` |
| Перезапуск после правок | `docker compose -f deploy/docker-compose.149.yml up -d --build` |
| Проверка API | `docker exec stakingphxpw-app curl -s http://127.0.0.1:8000/health` |
| Агрегированный health/ready | `curl -s http://127.0.0.1:8081/internal/health` или `.../internal/ready` |

## 6. Поддомен Тигрит (tigrit.stakingphxpw.com) и HTTPS

**Ошибка «Не удаётся установить безопасное соединение» / ERR_SSL_PROTOCOL_ERROR** значит: на хосте не настроен HTTPS для поддомена. Браузер идёт по https://tigrit.stakingphxpw.com, а сервер не отдаёт сертификат.

**Вариант А — автоматически (на сервере 149):**

```bash
ssh kim@192.168.1.149
cd /home/kim/stakingphxpw && bash deploy/patch_caddy_tigrit.sh
sudo systemctl reload caddy
```

Скрипт допишет блок для tigrit.stakingphxpw.com в Caddyfile и не меняет остальное.

**Вариант Б — вручную:** откройте на 149 конфиг Caddy и добавьте блок (полный пример с существующим stakingphxpw.com — **deploy/Caddyfile.149.example**):

```
tigrit.stakingphxpw.com {
    reverse_proxy localhost:8081
}
```

Затем: `sudo systemctl reload caddy` (или перезапуск контейнера Caddy).

После этого Caddy получит сертификат для tigrit.stakingphxpw.com (Let's Encrypt) и будет проксировать трафик на api-gateway (порт 8081). В nginx-docker.conf уже есть маршрутизация по `Host: tigrit.stakingphxpw.com` на tigrit-web.

## 7. HTTPS

После выхода в интернет по stakingphxpw.com на хосте 149 можно поставить certbot и выдать сертификаты. Если nginx на хосте уже слушает 80/443, добавьте в его конфиг server для stakingphxpw.com с proxy_pass на контейнер (например `http://127.0.0.1:8081`).
