#!/bin/bash
# Развёртывание Village Era в Docker на 192.168.1.149
# Запускать на сервере из корня проекта: bash deploy/deploy_docker_on_149.sh
# Или: cd /home/kim/stakingphxpw && bash deploy/deploy_docker_on_149.sh

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_DIR"

echo "=== Деплой stakingphxpw в Docker ==="
echo "Проект: $PROJECT_DIR"
echo ""

# config.js для продакшена
if [ ! -f "$PROJECT_DIR/config.js" ]; then
  printf '%s\n' '// Production' 'window.GAME_API_BASE = "https://stakingphxpw.com";' > "$PROJECT_DIR/config.js"
  echo "Создан config.js"
fi

# Бэкенд .env
BACKEND_ENV="$PROJECT_DIR/бэкенд/.env"
if [ ! -f "$BACKEND_ENV" ]; then
  if [ -f "$PROJECT_DIR/бэкенд/env.example" ]; then
    cp "$PROJECT_DIR/бэкенд/env.example" "$BACKEND_ENV"
    echo "Создан $BACKEND_ENV из env.example — проверьте DATABASE_URL."
  else
    touch "$BACKEND_ENV"
  fi
fi
grep -q "CORS_ORIGINS=" "$BACKEND_ENV" 2>/dev/null || \
  echo "CORS_ORIGINS=https://stakingphxpw.com,https://www.stakingphxpw.com,https://web.telegram.org,https://t.me" >> "$BACKEND_ENV"

# Docker
if ! command -v docker &>/dev/null; then
  echo "Ошибка: docker не установлен. Установите Docker на сервере."
  exit 1
fi

echo "Запуск контейнеров..."
docker compose -f deploy/docker-compose.149.yml up -d --build

echo ""
echo "=== Готово ==="
echo "Проверка API: curl -s http://127.0.0.1:8000/health (внутри сети) или с хоста: docker exec stakingphxpw-app curl -s http://127.0.0.1:8000/health"
echo "Сайт: http://stakingphxpw.com (порт 80 проброшен в контейнер web)"
echo "Логи: docker compose -f deploy/docker-compose.149.yml logs -f"
echo "Остановка: docker compose -f deploy/docker-compose.149.yml down"
