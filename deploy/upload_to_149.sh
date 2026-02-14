#!/bin/bash
# Выгрузка проекта Игра на сервер 192.168.1.149
# Запуск с Mac: ./upload_to_149.sh [пользователь]
# По умолчанию пользователь: $USER (текущий). Укажите, если на 149 другой логин: ./upload_to_149.sh root

set -e
SERVER="192.168.1.149"
REMOTE_USER="${1:-$USER}"
REMOTE_DIR="/tmp/igra_upload"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "Проект: $PROJECT_DIR"
echo "Сервер: $REMOTE_USER@$SERVER"
echo "Временная папка на сервере: $REMOTE_DIR"
echo ""

# Проверка доступности сервера
if ! ssh -o ConnectTimeout=5 -o BatchMode=yes "$REMOTE_USER@$SERVER" "echo ok" 2>/dev/null; then
  echo "Ошибка: не удаётся подключиться к $REMOTE_USER@$SERVER по SSH."
  echo "Проверьте: ssh $REMOTE_USER@$SERVER"
  exit 1
fi

# Убедиться, что на сервер попадёт config.js для продакшена
if [ ! -f "$PROJECT_DIR/config.js" ]; then
  printf '%s\n' '// Production' 'window.GAME_API_BASE = "https://stakingphxpw.com/api";' > "$PROJECT_DIR/config.js"
  echo "Создан config.js для продакшена."
fi

echo "Копирование файлов на сервер..."
rsync -avz --progress \
  --exclude 'бэкенд/venv' \
  --exclude 'бэкенд/__pycache__' \
  --exclude 'бэкенд/**/__pycache__' \
  --exclude '.git' \
  --exclude '.DS_Store' \
  --exclude '*.pyc' \
  "$PROJECT_DIR/" "$REMOTE_USER@$SERVER:$REMOTE_DIR/"

echo ""
echo "Готово. Дальше на сервере выполните:"
echo "  ssh $REMOTE_USER@$SERVER"
echo "  sudo bash $REMOTE_DIR/deploy/setup_on_149.sh"
echo ""
echo "Либо одной командой:"
echo "  ssh $REMOTE_USER@$SERVER 'sudo bash -s' < $SCRIPT_DIR/setup_on_149.sh"
echo "  (скрипт ожидает данные в $REMOTE_DIR на сервере)"
