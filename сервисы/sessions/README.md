# Сервис сессий

Создание, продление, инвалидация и проверка сессий. Хранение в Redis. SESSION_SIGNING_KEY запрашивается у Secrets (опционально, для будущего подписанного session_id).

**Эндпоинты:** POST /session, POST /session/refresh, POST /session/invalidate, GET /session/validate?session_id=...

**Env:** REDIS_URL, SECRETS_SERVICE_URL, INTERNAL_TOKEN, SESSION_TTL_SECONDS (по умолчанию 86400), PORT=8002.
