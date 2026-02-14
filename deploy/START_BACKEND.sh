#!/bin/bash
# Запуск бэкенда игры для раздачи с ПК (stakingphxpw.com)
# Запускайте в отдельном терминале или в фоне: nohup ./START_BACKEND.sh &
cd "$(dirname "$0")/../бэкенд"
./venv/bin/uvicorn api.main:app --host 127.0.0.1 --port 8000
