#!/bin/bash
# Проверка после деплоя (шлюз Фазы 6.4 + smoke).
# Запуск на сервере: cd /home/kim/stakingphxpw && bash deploy/verify_after_deploy.sh

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_DIR"

GATEWAY="${GATEWAY:-http://127.0.0.1:8081}"
TIGRIT_HOST="Host: tigrit.stakingphxpw.com"
FAIL=0

echo "=== Проверка деплоя ==="
echo "Шлюз: $GATEWAY"
echo ""

# 1. Игра: config
S=$(curl -s -o /dev/null -w "%{http_code}" "$GATEWAY/api/game/config" 2>/dev/null || echo "000")
if [ "$S" = "200" ]; then
  echo "[OK] GET /api/game/config — $S"
else
  echo "[FAIL] GET /api/game/config — $S (ожидалось 200)"
  FAIL=1
fi

# 2. Тигрит: статика
S=$(curl -s -o /dev/null -w "%{http_code}" -H "$TIGRIT_HOST" "$GATEWAY/" 2>/dev/null || echo "000")
if [ "$S" = "200" ]; then
  echo "[OK] tigrit.stakingphxpw.com/ (статика) — $S"
else
  echo "[FAIL] tigrit.stakingphxpw.com/ — $S (ожидалось 200)"
  FAIL=1
fi

# 3. Тигрит: API (прокси на tigrit-api)
S=$(curl -s -o /dev/null -w "%{http_code}" -H "$TIGRIT_HOST" "$GATEWAY/api/village" 2>/dev/null || echo "000")
if [ "$S" = "200" ] || [ "$S" = "404" ]; then
  echo "[OK] tigrit.stakingphxpw.com/api/village — $S"
else
  echo "[FAIL] tigrit.stakingphxpw.com/api/village — $S (ожидалось 200 или 404)"
  FAIL=1
fi

# 4. Health (через gateway)
S=$(curl -s -o /dev/null -w "%{http_code}" "$GATEWAY/internal/health" 2>/dev/null || echo "000")
if [ "$S" = "200" ]; then
  echo "[OK] GET /internal/health — $S"
else
  echo "[??] GET /internal/health — $S"
fi

echo ""
if [ $FAIL -eq 0 ]; then
  echo "Проверки пройдены."
  exit 0
else
  echo "Часть проверок не пройдена. Логи: docker compose -f deploy/docker-compose.149.yml logs -f"
  exit 1
fi
