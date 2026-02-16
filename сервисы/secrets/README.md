# Микросервис секретов

Выдаёт значения секретов по ключу (GET /secret?key=...) при валидном заголовке X-Internal-Token.

**Env:** `PORT` (по умолчанию 8003), `INTERNAL_TOKEN` (если задан — обязателен в запросе). Секреты: переменные из `SECRET_KEYS` (список через запятую) или все `SECRET_*`; либо файл `SECRETS_FILE` (JSON: `{"KEY": "value"}`).

**Деплой:** в `deploy/docker-compose.149.yml` сервис читает `deploy/.env.secrets`. Создайте файл (не коммитить): `INTERNAL_TOKEN=...`, `SECRET_KEYS=KEY1,KEY2`, `KEY1=...`, `KEY2=...`.

**Проверка:** `curl -H "X-Internal-Token: YOUR_TOKEN" "http://localhost:8003/secret?key=KEY1"` → `{"value":"..."}`.
