# Раздача игры с этого ПК (потом перенесёте на сервер)

Раздавать игру и API с вашего Mac. Роутер направляет 80/443 на этот ПК.

---

## 1. Nginx (уже установлен и настроен)

Конфиг: **Intel Mac** `/usr/local/etc/nginx/servers/stakingphxpw.conf`  
**Apple Silicon** `/opt/homebrew/etc/nginx/servers/stakingphxpw.conf`

Nginx слушает порт **8080** (на Mac порт 80 без sudo недоступен).  
**На роутере** настройте проброс: **внешний порт 80 → IP этого ПК, внутренний порт 8080**.

Проверка и перезапуск:

```bash
nginx -t
brew services restart nginx
```

## 3. Запускать бэкенд на ПК

В отдельном терминале (или в фоне):

```bash
cd "/Users/Den/Downloads/Игра/бэкенд"
./venv/bin/uvicorn api.main:app --host 127.0.0.1 --port 8000
```

Либо из папки `Игра/deploy`: `./START_BACKEND.sh`

Пока этот процесс работает, API доступен по `http://127.0.0.1:8000`, nginx проксирует на него запросы к `/api`.

## 4. HTTPS (чтобы открывалось в Telegram)

Telegram требует HTTPS с валидным сертификатом.

1. **DNS:** у домена stakingphxpw.com A-запись должна указывать на **внешний IP вашего роутера**.
2. **Роутер:** проброс внешний 443 → этот ПК. Для certbot на этом ПК нужен порт 443 (запуск с `sudo` или проброс 443 → другой порт и правка конфига nginx).
3. **Certbot:**

   ```bash
   brew install certbot
   sudo certbot --nginx -d stakingphxpw.com -d www.stakingphxpw.com
   ```

   Certbot добавит блок с 443 и путями к сертификатам. Продление: `sudo certbot renew`.

После этого: в браузере и в Telegram Web App URL: `https://stakingphxpw.com`

## 5. Кратко: что запускать каждый раз при «раздаче с ПК»

1. **nginx** — один раз настроили и включили (`brew services start nginx`), он стартует и после перезагрузки.
2. **Бэкенд** — каждый раз, когда хотите раздавать игру:
   ```bash
   cd /Users/Den/Downloads/Игра/бэкенд
   ./venv/bin/uvicorn api.main:app --host 127.0.0.1 --port 8000
   ```

В `config.js` уже стоит `GAME_API_BASE = 'https://stakingphxpw.com/api'`. В бэкенд `.env` добавьте `CORS_ORIGINS=https://stakingphxpw.com,https://www.stakingphxpw.com` (и при необходимости другие origins).

Когда перенесёте на сервер — те же конфиги (nginx, .env) используете там, роутер переключите обратно на IP сервера.
