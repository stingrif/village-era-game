# Деплой на stakingphxpw.com

## Синхронизация с кабзда

При обновлении контента в **кабзда** скопировать в deploy:

```bash
# из папки Игра/deploy (или из корня: bash Игра/deploy/sync_from_cabzda.sh)
bash sync_from_cabzda.sh
```

Скрипт:
- копирует в `tigrit_api/backend/data/`: `tile_data.json`, `building_data.json`, `character_data.json`, `village_map.json` из `кабзда/tigrit_web/backend/data/`;
- обновляет копию фронта в `tigrit_web/frontend/` (index.html, package.json, src/ и т.д.) из `кабзда/tigrit_web/frontend/`.

Ожидается структура: рядом с папкой `Игра/` лежит папка `кабзда/`. Или задать путь: `CABZDA=/путь/к/кабзда bash sync_from_cabzda.sh`.

После синхронизации при необходимости пересобрать образы (docker build).

---

## Чек-лист (по плану)

1. **Фронт:** в `config.js` задано `window.GAME_API_BASE = 'https://stakingphxpw.com/api'`.
2. **Бэкенд:** в `Игра/бэкенд/.env` добавить:
   ```bash
   CORS_ORIGINS=https://stakingphxpw.com,https://www.stakingphxpw.com
   ```
3. **Роутер:** проброс 80 и 443 на IP машины, где крутится nginx (например 192.168.1.247).
4. **DNS:** A-запись stakingphxpw.com (и www) на внешний IP роутера.
5. **Сервер:** nginx + SSL + бэкенд (uvicorn на 8000).

## Nginx

- Использовать конфиг `nginx-stakingphxpw.conf`.
- Заменить `/var/www/stakingphxpw` на реальный путь к папке с игрой (в ней должны быть `village-era-game-final.html`, `config.js`, `frontend/`).
- Скопировать конфиг в `/etc/nginx/sites-available/`, создать симлинк в `sites-enabled`, проверить `nginx -t`, перезагрузить nginx.
- SSL: `certbot --nginx -d stakingphxpw.com -d www.stakingphxpw.com` (или раскомментировать блок 443 в конфиге и указать пути к сертификатам).

## Бэкенд

На той же машине запускать API:

```bash
cd /путь/к/Игра/бэкенд
./venv/bin/uvicorn api.main:app --host 127.0.0.1 --port 8000
```

Или через systemd/supervisor для автозапуска.

## Тигрит-клиент (tigrit.stakingphxpw.com)

Статика веб-клиента Тигрит раздаётся по адресу **https://tigrit.stakingphxpw.com** через контейнер `tigrit-web`, прописанный в `docker-compose.149.yml` (в связке с nginx-шлюзом).

После изменений в `deploy/tigrit_web/frontend/` (HTML, JS, CSS) нужно:

```bash
# из корня проекта (Игра/)
bash deploy/deploy_docker_on_149.sh
```

Скрипт выполняет `docker compose -f deploy/docker-compose.149.yml up -d --build` — пересборка образа `tigrit-web` и перезапуск контейнеров уже входят.

Проверка после деплоя:

```bash
# Фронт Тигрит — ожидается 200
curl -s -o /dev/null -w "%{http_code}" -H "Host: tigrit.stakingphxpw.com" http://127.0.0.1:8081/

# API village — 200 или 404
curl -s -o /dev/null -w "%{http_code}" -H "Host: tigrit.stakingphxpw.com" http://127.0.0.1:8081/api/village

# Health — {"status":"ok"}
curl -s -H "Host: tigrit.stakingphxpw.com" http://127.0.0.1:8081/api/health

# Единый каталог предметов — массив из 122+ объектов
curl -s -H "Host: tigrit.stakingphxpw.com" http://127.0.0.1:8081/api/items-catalog | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d), 'предметов')"
```

---

## Telegram Web App (кнопка «Игра» в боте)

- **URL в настройках бота (BotFather → Menu Button или web_app-кнопка):** `https://stakingphxpw.com` или `https://stakingphxpw.com/village-era-game-final.html` — тот адрес, по которому открывается игра в браузере.
- **Обязательно HTTPS** — Telegram не открывает Web App по HTTP (кроме localhost для разработки). Сертификат должен быть валидным (не самоподписанный).
- **CORS:** в бэкенде уже добавлены origins `https://web.telegram.org` и `https://t.me`, запросы к API из Telegram должны проходить.
- Если приложение «не открывает»: проверить, что по этому URL страница открывается в браузере по HTTPS и что нет 404/500 на самой странице и на `config.js`.
