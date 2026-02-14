#!/bin/bash
# Один раз настроить вход по ключу на kim@192.168.1.149 без пароля.
# Запуск: ./setup_ssh_key_149.sh
# Когда скрипт попросит пароль — введите пароль от пользователя kim на сервере (один раз).
# После этого выгрузка и ssh будут работать без пароля по ключу.

set -e
SERVER="192.168.1.149"
REMOTE_USER="kim"
KEY_PATH="$HOME/.ssh/stakingphxpw_149"
CONFIG_MARKER="# stakingphxpw 149"

echo "=== Настройка входа по ключу на $REMOTE_USER@$SERVER ==="
echo ""

# Ключ без пароля (если уже есть — не перезаписываем)
if [ ! -f "$KEY_PATH" ]; then
  ssh-keygen -t ed25519 -f "$KEY_PATH" -N "" -C "stakingphxpw-149"
  echo "Создан ключ: $KEY_PATH (без пароля)"
else
  echo "Ключ уже есть: $KEY_PATH"
fi

# Копируем публичный ключ на сервер (один раз — пароль или через SSHPASS)
echo ""
if [ -n "$SSHPASS" ]; then
  if command -v sshpass &>/dev/null; then
    sshpass -e ssh-copy-id -i "${KEY_PATH}.pub" -o StrictHostKeyChecking=accept-new "$REMOTE_USER@$SERVER" && echo "Ключ добавлен на сервер."
  else
    echo "Установите sshpass (brew install sshpass) или введите пароль вручную при запросе."
    ssh-copy-id -i "${KEY_PATH}.pub" -o StrictHostKeyChecking=accept-new "$REMOTE_USER@$SERVER" && echo "Ключ добавлен на сервер."
  fi
else
  echo "Сейчас один раз введите пароль от $REMOTE_USER@$SERVER (или задайте SSHPASS=пароль и запустите снова для неинтерактивной настройки):"
  if ssh-copy-id -i "${KEY_PATH}.pub" -o StrictHostKeyChecking=accept-new "$REMOTE_USER@$SERVER" 2>/dev/null; then
    echo "Ключ успешно добавлен на сервер."
  else
    PUB=$(cat "${KEY_PATH}.pub")
    ssh -o StrictHostKeyChecking=accept-new "$REMOTE_USER@$SERVER" "mkdir -p ~/.ssh && chmod 700 ~/.ssh && echo '$PUB' >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"
    echo "Ключ добавлен на сервер."
  fi
fi

# Добавляем в SSH config, чтобы этот хост всегда использовал этот ключ
SSH_CONFIG="$HOME/.ssh/config"
mkdir -p "$(dirname "$KEY_PATH")"
chmod 700 "$(dirname "$KEY_PATH")"
if [ ! -f "$SSH_CONFIG" ]; then
  touch "$SSH_CONFIG"
  chmod 600 "$SSH_CONFIG"
fi
if ! grep -q "$CONFIG_MARKER" "$SSH_CONFIG" 2>/dev/null; then
  echo "" >> "$SSH_CONFIG"
  echo "$CONFIG_MARKER" >> "$SSH_CONFIG"
  echo "Host $SERVER" >> "$SSH_CONFIG"
  echo "  User $REMOTE_USER" >> "$SSH_CONFIG"
  echo "  IdentityFile $KEY_PATH" >> "$SSH_CONFIG"
  echo "  IdentitiesOnly yes" >> "$SSH_CONFIG"
  echo "В ~/.ssh/config добавлен хост $SERVER с ключом $KEY_PATH"
fi

echo ""
echo "Проверка входа без пароля..."
if ssh -o BatchMode=yes -o ConnectTimeout=5 "$REMOTE_USER@$SERVER" "echo OK"; then
  echo "Готово. Дальше можно запускать ./upload_to_149_docker.sh без ввода пароля."
else
  echo "Вход по ключу не сработал. Проверьте пароль и повторите: ./setup_ssh_key_149.sh"
  exit 1
fi
