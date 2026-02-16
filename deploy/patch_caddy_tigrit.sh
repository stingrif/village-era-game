#!/bin/bash
# Вставка блока tigrit.stakingphxpw.com в Caddyfile на сервере 149 (не трогает остальное).
# Запуск на 149: cd /home/kim/stakingphxpw && bash deploy/patch_caddy_tigrit.sh

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_DIR"

for CADDYFILE in /etc/caddy/Caddyfile /etc/Caddyfile; do
  [ -f "$CADDYFILE" ] || continue
  if grep -q "tigrit.stakingphxpw.com" "$CADDYFILE"; then
    echo "В $CADDYFILE блок tigrit уже есть. Ничего не меняем."
    exit 0
  fi
  echo "Добавляем блок tigrit в $CADDYFILE"
  {
    echo ""
    echo "# Поддомен Тигрит (добавлено patch_caddy_tigrit.sh)"
    echo "tigrit.stakingphxpw.com {"
    echo "    reverse_proxy localhost:8081"
    echo "}"
  } | sudo tee -a "$CADDYFILE" > /dev/null
  echo "Готово. Выполните: sudo systemctl reload caddy"
  exit 0
done

echo "Caddyfile не найден. Вставьте вручную блок из deploy/Caddyfile.149.example"
exit 1
