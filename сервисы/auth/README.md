# Сервис авторизации

POST /verify: тело `{"init_data": "..."}` (Telegram Web App). При успехе — `{"user_id": int}`; при ошибке — 401/503.

Поле `token` принимается в теле, но возвращает 401 — авторизация только через Telegram init_data.
JWT не реализован: в текущей архитектуре используется исключительно Telegram Mini App Web App данные.

Секрет бота для проверки подписи запрашивается у сервиса Secrets (TELEGRAM_BOT_TOKEN). ensure_user вызывается у бэкенда Игра (INTERNAL_API_SECRET из env или из Secrets).

**Env:** SECRETS_SERVICE_URL, INTERNAL_TOKEN (или SECRETS_INTERNAL_TOKEN), GAME_API_BASE, INTERNAL_API_SECRET (опционально), PORT=8001.

**Проверка:** валидный init_data от Mini App или ручной тест с подписанной строкой (см. Telegram Web App docs).
