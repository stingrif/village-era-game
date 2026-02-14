#!/bin/bash
# Выгрузка проекта Игра на kim@192.168.1.149 для развёртывания в Docker
# Запуск с Mac: ./upload_to_149_docker.sh
# Один раз перед первой выгрузкой: ./setup_ssh_key_149.sh (ввести пароль) — дальше вход по ключу без пароля.

set -e
SERVER="192.168.1.149"
REMOTE_USER="kim"
REMOTE_DIR="/home/kim/stakingphxpw"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
KEY_PATH="$HOME/.ssh/stakingphxpw_149"

echo "Проект: $PROJECT_DIR"
echo "Сервер: $REMOTE_USER@$SERVER"
echo "Папка на сервере: $REMOTE_DIR"
echo ""

# Используем ключ для 149, если он настроен
SSH_OPTS=(-o ConnectTimeout=5 -o BatchMode=yes)
[ -f "$KEY_PATH" ] && SSH_OPTS=(-o ConnectTimeout=5 -o BatchMode=yes -i "$KEY_PATH")

if ! ssh "${SSH_OPTS[@]}" "$REMOTE_USER@$SERVER" "echo ok" 2>/dev/null; then
  echo "Ошибка: не удаётся подключиться к $REMOTE_USER@$SERVER по SSH."
  echo "Один раз настройте вход по ключу (пароль больше не будет нужен):"
  echo "  ./setup_ssh_key_149.sh"
  echo "Затем снова запустите этот скрипт."
  exit 1
fi

# config.js для продакшена
if [ ! -f "$PROJECT_DIR/config.js" ]; then
  printf '%s\n' '// Production' 'window.GAME_API_BASE = "https://stakingphxpw.com";' > "$PROJECT_DIR/config.js"
  echo "Создан config.js для продакшена."
fi

echo "Копирование файлов на сервер..."
RSYNC_SSH="ssh"
[ -f "$KEY_PATH" ] && RSYNC_SSH="ssh -i $KEY_PATH"
ssh "${SSH_OPTS[@]}" "$REMOTE_USER@$SERVER" "mkdir -p $REMOTE_DIR"
rsync -avz --progress -e "$RSYNC_SSH" \
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
echo "  cd $REMOTE_DIR && bash deploy/deploy_docker_on_149.sh"
echo ""
echo "Или одной командой с этого Mac:"
echo "  ssh $REMOTE_USER@$SERVER 'cd $REMOTE_DIR && bash deploy/deploy_docker_on_149.sh'"
echo ""
