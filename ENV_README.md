# Переменные окружения

## Бэкенд (папка `бэкенд`)

1. Скопируйте шаблон в `.env`:
   ```bash
   cd бэкенд
   cp env.example .env
   ```
2. Откройте `.env` и подставьте недостающее:
   - **DATABASE_URL** — строка подключения к PostgreSQL (логин, пароль, хост, порт, база).
   - **GAME_NOTIFY_BOT_TOKEN** — токен бота для уведомлений админу (квест ФЕНИКС).
   - **TON_API_KEY**, **PROJECT_WALLET_ADDRESS** — по необходимости.

## Фронт (папка `Игра`)

1. Скопируйте шаблон в `.env`:
   ```bash
   cp env.example .env
   ```
2. В `.env` укажите **API_BASE** — URL бэкенда:
   - локально: `http://localhost:8000`
   - продакшен: `https://ваш-домен.com`
   - пусто — игра без API (только localStorage).
3. Сгенерируйте `config.js` из `.env` (чтобы игра подхватила API_BASE):
   ```bash
   node generate_config.js
   ```
   Либо отредактируйте **config.js** вручную: задайте `window.GAME_API_BASE = 'http://localhost:8000';`.
