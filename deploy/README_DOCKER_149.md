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
- **stakingphxpw-web** — nginx (порт 80 на хосте)
- **stakingphxpw-redis** — Redis

## 3. Бэкенд .env на сервере

В **/home/kim/stakingphxpw/бэкенд/.env** должен быть **DATABASE_URL** (Postgres).  
Если файла не было, он создаётся из `env.example` — отредактируйте:

```bash
ssh kim@192.168.1.149
nano /home/kim/stakingphxpw/бэкенд/.env
# Задайте DATABASE_URL=postgresql://user:pass@host:port/dbname
# Затем перезапуск: cd /home/kim/stakingphxpw && docker compose -f deploy/docker-compose.149.yml restart app
```

## 4. Если порт 80 на 149 уже занят (n8n и т.п.)

В **deploy/docker-compose.149.yml** замените у сервиса `web`:

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

## 6. HTTPS

После выхода в интернет по stakingphxpw.com на хосте 149 можно поставить certbot и выдать сертификаты. Если nginx на хосте уже слушает 80/443, добавьте в его конфиг server для stakingphxpw.com с proxy_pass на контейнер (например `http://127.0.0.1:80` если контейнер слушает 80).
