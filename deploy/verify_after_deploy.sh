#!/bin/bash
# Проверка после деплоя: smoke-тесты всех эндпоинтов Тигрит и Village Era.
# Запуск на сервере: cd /home/kim/stakingphxpw && bash deploy/verify_after_deploy.sh

set -euo pipefail
GATEWAY="${GATEWAY:-http://127.0.0.1:8081}"
TIGRIT_HOST="tigrit.stakingphxpw.com"
# Admin-ключ из env (не хардкодить)
ADMIN_KEY="${TIGRIT_ADMIN_API_KEY:-}"
FAIL=0

ok()   { echo "[OK]   $1 — $2"; }
fail() { echo "[FAIL] $1 — $2 (ожидалось: $3)"; FAIL=1; }
skip() { echo "[SKIP] $1 — нет ключа (пропущено)"; }

check() {
  local label="$1"; local expected="$2"; shift 2
  local code
  code=$(curl -s -o /dev/null -w "%{http_code}" "$@" 2>/dev/null || echo "000")
  if [ "$code" = "$expected" ]; then ok "$label" "$code"
  else fail "$label" "$code" "$expected"
  fi
}

echo "=== Проверка деплоя Тигрит ==="
echo "Шлюз: $GATEWAY | Host: $TIGRIT_HOST"
echo ""

# ─── Village Era (основное приложение) ───────────────────────────
echo "--- Village Era ---"
S=$(curl -s -o /dev/null -w "%{http_code}" "$GATEWAY/api/game/config" 2>/dev/null || echo "000")
if [ "$S" = "200" ]; then ok "GET /api/game/config" "$S"
else echo "[??] GET /api/game/config — $S (может быть норма если ещё не деплоили)"; fi

# ─── Тигрит: статика ─────────────────────────────────────────────
echo ""
echo "--- Тигрит: статика ---"
check "GET / (tigrit-web статика)" "200" -H "Host: $TIGRIT_HOST" "$GATEWAY/"

# ─── Тигрит: публичные API ───────────────────────────────────────
echo ""
echo "--- Тигрит: публичные API ---"
check "GET /api/health"         "200" -H "Host: $TIGRIT_HOST" "$GATEWAY/api/health"
check "GET /api/village"        "200" -H "Host: $TIGRIT_HOST" "$GATEWAY/api/village" || true
check "GET /api/zones"          "200" -H "Host: $TIGRIT_HOST" "$GATEWAY/api/zones"
check "GET /api/items-catalog"  "200" -H "Host: $TIGRIT_HOST" "$GATEWAY/api/items-catalog"

# POST /api/chat/message
BODY='{"text":"smoke test","xp":1,"zone_id":"zone_1"}'
CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST \
  -H "Host: $TIGRIT_HOST" -H "Content-Type: application/json" \
  -d "$BODY" "$GATEWAY/api/chat/message" 2>/dev/null || echo "000")
if [ "$CODE" = "200" ] || [ "$CODE" = "201" ]; then ok "POST /api/chat/message" "$CODE"
else fail "POST /api/chat/message" "$CODE" "200 или 201"; fi

# ─── Тигрит: Admin API ───────────────────────────────────────────
echo ""
echo "--- Тигрит: Admin API ---"

# /api/admin/status без ключа → должен вернуть 200 (возвращает db_connected без требования ключа)
CODE=$(curl -s -o /dev/null -w "%{http_code}" -H "Host: $TIGRIT_HOST" "$GATEWAY/api/admin/status" 2>/dev/null || echo "000")
if [ "$CODE" = "200" ]; then ok "GET /api/admin/status (без ключа)" "$CODE"
else fail "GET /api/admin/status (без ключа)" "$CODE" "200"; fi

if [ -n "$ADMIN_KEY" ]; then
  check "GET /api/admin/status (с ключом)" "200" \
    -H "Host: $TIGRIT_HOST" -H "X-Admin-Key: $ADMIN_KEY" "$GATEWAY/api/admin/status"

  # village — 200 или 404 (если нет записи) — не 500
  CODE=$(curl -s -o /dev/null -w "%{http_code}" \
    -H "Host: $TIGRIT_HOST" -H "X-Admin-Key: $ADMIN_KEY" \
    "$GATEWAY/api/admin/village/1" 2>/dev/null || echo "000")
  if [ "$CODE" = "200" ] || [ "$CODE" = "404" ]; then ok "GET /api/admin/village/1 (с ключом)" "$CODE"
  else fail "GET /api/admin/village/1 (с ключом)" "$CODE" "200 или 404"; fi
else
  skip "GET /api/admin/status (с ключом) и /api/admin/village/1"
  echo "       Задайте TIGRIT_ADMIN_API_KEY=... перед запуском скрипта"
fi

# ─── Итог ───────────────────────────────────────────────────────
echo ""
if [ $FAIL -eq 0 ]; then
  echo "✅ Все проверки пройдены."
  exit 0
else
  echo "❌ Часть проверок не пройдена."
  echo "   Логи: docker compose -f deploy/docker-compose.149.yml logs --tail=50 tigrit-api"
  exit 1
fi
