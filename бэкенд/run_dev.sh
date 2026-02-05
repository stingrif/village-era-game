#!/usr/bin/env bash
# Запуск бэкенда в режиме разработки (использует venv, читает .env из текущей папки)
cd "$(dirname "$0")"
if [ ! -d "venv" ]; then
  echo "Создаю venv и устанавливаю зависимости..."
  python3 -m venv venv
  ./venv/bin/pip install -r requirements.txt
fi
if [ ! -f ".env" ]; then
  echo "Файл .env не найден. Скопируйте env.example в .env и задайте DATABASE_URL."
  echo "  cp env.example .env"
  exit 1
fi
exec ./venv/bin/uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
