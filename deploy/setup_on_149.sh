#!/bin/bash
# Развёртывание Village Era на сервере (192.168.1.149).
# Запускать на сервере с sudo: sudo bash setup_on_149.sh
# Ожидает, что проект уже скопирован в /tmp/igra_upload (см. upload_to_149.sh).

set -e
SOURCE_DIR="${DEPLOY_SOURCE:-/tmp/igra_upload}"
WEB_ROOT="/var/www/stakingphxpw"
BACKEND_DIR="$WEB_ROOT/бэкенд"

if [ ! -d "$SOURCE_DIR" ]; then
  echo "Папка $SOURCE_DIR не найдена. Сначала выполните upload_to_149.sh с этого Mac."
  exit 1
fi

echo "=== Развёртывание stakingphxpw.com на этом сервере ==="
echo "Источник: $SOURCE_DIR"
echo "Веб-корень: $WEB_ROOT"
echo ""

# Копирование в /var/www
mkdir -p "$WEB_ROOT"
cp -a "$SOURCE_DIR"/* "$WEB_ROOT/"
echo "Файлы скопированы в $WEB_ROOT"

# config.js для продакшена (если нет)
if [ ! -f "$WEB_ROOT/config.js" ]; then
  echo 'window.GAME_API_BASE = "https://stakingphxpw.com/api";' > "$WEB_ROOT/config.js"
  echo "Создан config.js"
fi

# Бэкенд .env на сервере
if [ ! -f "$BACKEND_DIR/.env" ]; then
  if [ -f "$BACKEND_DIR/env.example" ]; then
    cp "$BACKEND_DIR/env.example" "$BACKEND_DIR/.env"
    echo "Создан $BACKEND_DIR/.env из env.example — отредактируйте DATABASE_URL и CORS_ORIGINS."
  else
    touch "$BACKEND_DIR/.env"
  fi
fi
# Обязательные переменные для продакшена
grep -q "CORS_ORIGINS=" "$BACKEND_DIR/.env" 2>/dev/null || \
  echo "CORS_ORIGINS=https://stakingphxpw.com,https://www.stakingphxpw.com,https://web.telegram.org,https://t.me" >> "$BACKEND_DIR/.env"

# Виртуальное окружение и зависимости
if [ ! -d "$BACKEND_DIR/venv" ]; then
  echo "Создание venv и установка зависимостей..."
  python3 -m venv "$BACKEND_DIR/venv"
  "$BACKEND_DIR/venv/bin/pip" install -q --upgrade pip
  "$BACKEND_DIR/venv/bin/pip" install -q -r "$BACKEND_DIR/requirements.txt"
  echo "venv готов."
fi

# Nginx: конфиг для stakingphxpw.com
NGINX_CONF="/etc/nginx/sites-available/stakingphxpw"
if [ -d /etc/nginx/sites-available ]; then
  cat > "$NGINX_CONF" << 'NGINX_EOF'
# Village Era / stakingphxpw.com
server {
    listen 80;
    server_name stakingphxpw.com www.stakingphxpw.com;
    root /var/www/stakingphxpw;
    index village-era-game-final.html;

    location = / {
        try_files /village-era-game-final.html =404;
    }
    location / {
        try_files $uri $uri/ /village-era-game-final.html;
    }

    location /api {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
NGINX_EOF
  [ -L /etc/nginx/sites-enabled/stakingphxpw ] 2>/dev/null || ln -s "$NGINX_CONF" /etc/nginx/sites-enabled/stakingphxpw
  nginx -t && systemctl reload nginx
  echo "Nginx: конфиг добавлен и перезагружен."
else
  echo "Nginx sites-available не найден. Установите nginx и добавьте конфиг вручную из deploy/nginx-stakingphxpw.conf (root=$WEB_ROOT)."
fi

# Systemd: автозапуск бэкенда
UNIT_FILE="/etc/systemd/system/stakingphxpw-backend.service"
cat > "$UNIT_FILE" << UNIT_EOF
[Unit]
Description=Village Era Game API (stakingphxpw.com)
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$BACKEND_DIR
Environment=PATH=$BACKEND_DIR/venv/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=$BACKEND_DIR/venv/bin/uvicorn api.main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT_EOF
systemctl daemon-reload
systemctl enable stakingphxpw-backend
systemctl restart stakingphxpw-backend
echo "Бэкенд: systemd сервис stakingphxpw-backend включён и запущен."

echo ""
echo "=== Готово ==="
echo "Проверка: curl -s http://127.0.0.1:8000/health"
echo "Сайт: http://stakingphxpw.com (после DNS и при необходимости HTTPS: certbot --nginx -d stakingphxpw.com -d www.stakingphxpw.com)"
echo "Логи бэкенда: journalctl -u stakingphxpw-backend -f"
