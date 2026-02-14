# Деплой на сервер 192.168.1.149

Роутер уже направляет порты 80 и 443 на 192.168.1.149. После выгрузки и настройки сайт будет доступен по stakingphxpw.com.

## 1. Выгрузить проект с Mac на сервер

На **этом Mac** в терминале:

```bash
cd "/Users/Den/Downloads/Игра/deploy"
chmod +x upload_to_149.sh
./upload_to_149.sh
```

Если на 149 другой пользователь (например `root`):

```bash
./upload_to_149.sh root
```

Нужен доступ по SSH без пароля (ключ) или введите пароль по запросу.

## 2. Развернуть на сервере

По SSH зайти на сервер и запустить скрипт установки:

```bash
ssh 192.168.1.149
sudo bash /tmp/igra_upload/deploy/setup_on_149.sh
```

Скрипт:
- копирует файлы в `/var/www/stakingphxpw`;
- создаёт venv и ставит зависимости бэкенда;
- добавляет конфиг nginx для stakingphxpw.com (порт 80);
- создаёт systemd-сервис `stakingphxpw-backend` (uvicorn на 8000) и запускает его.

## 3. Проверить

- На сервере: `curl -s http://127.0.0.1:8000/health` → `{"status":"ok"}`
- В браузере: `http://stakingphxpw.com` (если DNS уже указывает на ваш роутер)

## 4. HTTPS (для Telegram Web App)

На сервере:

```bash
sudo certbot --nginx -d stakingphxpw.com -d www.stakingphxpw.com
```

После этого в боте указывайте URL: `https://stakingphxpw.com`

## 5. Бэкенд и .env на 149

В `Игра/бэкенд/.env` на сервере должны быть:
- **DATABASE_URL** — Postgres на этом же сервере, например:  
  `postgresql://phoenix:ПАРОЛЬ@127.0.0.1:5440/village_era`  
  (или ваша БД на 149)
- **CORS_ORIGINS** — скрипт добавляет сам; при необходимости допишите вручную.

Редактирование: `sudo nano /var/www/stakingphxpw/бэкенд/.env`  
После правок: `sudo systemctl restart stakingphxpw-backend`

## Полезные команды на сервере

| Действие              | Команда |
|----------------------|--------|
| Логи бэкенда         | `journalctl -u stakingphxpw-backend -f` |
| Перезапуск бэкенда   | `sudo systemctl restart stakingphxpw-backend` |
| Проверка nginx       | `sudo nginx -t && sudo systemctl reload nginx` |
