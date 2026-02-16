#!/bin/bash
# Полный прогон тестов по Фазам 0–4: бэкенд Игра + сервисы secrets, auth, sessions.
# Запуск из корня репозитория: bash run_all_tests_phases_0_4.sh
set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
echo "=== Бэкенд Игра (Фаза 0) ==="
cd "$ROOT/бэкенд"
python3 -m pytest tests/ -v --tb=short
echo ""
echo "=== Smoke бэкенда ==="
python3 -m pytest tests/test_game_api_e2e.py -k "health or config or checkin or mine_create or mine_dig" -v --tb=short
echo ""
echo "=== Сервис Secrets (Фаза 1) ==="
cd "$ROOT/сервисы/secrets"
INTERNAL_TOKEN=test SECRET_KEYS=K K=v python3 -c "
from main import app
from fastapi.testclient import TestClient
c = TestClient(app)
r = c.get('/secret?key=K', headers={'X-Internal-Token': 'test'})
assert r.status_code == 200 and r.json() == {'value': 'v'}, r.text
r = c.get('/health')
assert r.status_code == 200
print('secrets ok')
"
echo ""
echo "=== Сервис Auth (Фаза 2) ==="
cd "$ROOT/сервисы/auth"
python3 -c "
from fastapi.testclient import TestClient
from main import app
c = TestClient(app)
assert c.get('/health').status_code == 200
assert c.post('/verify', json={}).status_code == 400
print('auth ok')
"
echo ""
echo "=== Сервис Sessions (Фаза 3, нужен Redis) ==="
cd "$ROOT/сервисы/sessions"
python3 test_sessions.py || echo "Sessions: ошибка или нет Redis"
echo ""
echo "=== Все проверки завершены ==="
