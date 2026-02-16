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
echo "Ожидание готовности контейнеров (10 с)..."
sleep 10

echo "Проверка (шлюз Фазы 6.4):"
GATEWAY="http://127.0.0.1:8081"
TIGRIT_HOST="Host: tigrit.stakingphxpw.com"
# Статика Тигрит (tigrit-web)
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -H "$TIGRIT_HOST" "$GATEWAY/" 2>/dev/null || echo "000")
if [ "$STATUS" = "200" ]; then
  echo "  [OK] tigrit.stakingphxpw.com/ — статика tigrit-web, HTTP $STATUS"
else
  echo "  [??] tigrit.stakingphxpw.com/ — HTTP $STATUS (ожидалось 200)"
fi
# API Тигрит (прокси на tigrit-api)
API_STATUS=$(curl -s -o /dev/null -w "%{http_code}" -H "$TIGRIT_HOST" "$GATEWAY/api/village" 2>/dev/null || echo "000")
if [ "$API_STATUS" = "200" ] || [ "$API_STATUS" = "404" ]; then
  echo "  [OK] tigrit.stakingphxpw.com/api/village — прокси на tigrit-api, HTTP $API_STATUS"
else
  echo "  [??] tigrit.stakingphxpw.com/api/village — HTTP $API_STATUS (ожидалось 200 или 404)"
fi
# Игра: config
CONFIG_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$GATEWAY/api/game/config" 2>/dev/null || echo "000")
if [ "$CONFIG_STATUS" = "200" ]; then
  echo "  [OK] /api/game/config — бэкенд Игра, HTTP $CONFIG_STATUS"
else
  echo "  [??] /api/game/config — HTTP $CONFIG_STATUS"
fi

echo ""
echo "=== Готово ==="
echo "Проверка API: curl -s http://127.0.0.1:8000/health (внутри сети) или: docker exec stakingphxpw-app curl -s http://127.0.0.1:8000/health"
echo "Сайт: http://stakingphxpw.com (порт 8081); Тигрит: curl -H 'Host: tigrit.stakingphxpw.com' http://127.0.0.1:8081/"
echo "Повторная проверка: bash deploy/verify_after_deploy.sh"
echo "Логи: docker compose -f deploy/docker-compose.149.yml logs -f"
echo "Остановка: docker compose -f deploy/docker-compose.149.yml down"
