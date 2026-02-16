# Сервис авторизации

POST /verify: тело `{"init_data": "..."}` (Telegram Web App) или `{"token": "..."}` (JWT — заглушка). При успехе — `{"user_id": int}`; при ошибке — 401/503.

Секрет бота для проверки подписи запрашивается у сервиса Secrets (TELEGRAM_BOT_TOKEN). ensure_user вызывается у бэкенда Игра (INTERNAL_API_SECRET из env или из Secrets).

**Env:** SECRETS_SERVICE_URL, INTERNAL_TOKEN (или SECRETS_INTERNAL_TOKEN), GAME_API_BASE, INTERNAL_API_SECRET (опционально), PORT=8001.

**Проверка:** валидный init_data от Mini App или ручной тест с подписанной строкой (см. Telegram Web App docs).
