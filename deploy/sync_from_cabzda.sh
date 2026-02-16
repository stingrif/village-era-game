#!/usr/bin/env bash
# Синхронизация кабзда → deploy: фронт и данные API (tiles, buildings, characters, village_map).
# Запуск из корня репозитория, где рядом лежат кабзда/ и Игра/ (или задать CABZDA/DEPLOY вручную).

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY="$(cd "$SCRIPT_DIR" && pwd)"
# Кабзда: на уровень выше deploy, папка кабзда (или env CABZDA)
CABZDA="${CABZDA:-$(cd "$DEPLOY/../.." && pwd)/кабзда}"

if [[ ! -d "$CABZDA" ]]; then
  echo "Папка кабзда не найдена: $CABZDA. Задайте CABZDA=путь" >&2
  exit 1
fi

echo "Кабзда: $CABZDA"
echo "Deploy: $DEPLOY"

# 1) Данные API: backend/data/
SRC_DATA="$CABZDA/tigrit_web/backend/data"
DST_DATA="$DEPLOY/tigrit_api/backend/data"
mkdir -p "$DST_DATA"
for f in tile_data.json building_data.json character_data.json village_map.json; do
  if [[ -f "$SRC_DATA/$f" ]]; then
    cp "$SRC_DATA/$f" "$DST_DATA/$f"
    echo "  data: $f"
  fi
done

# 3) Фронт: исходники (без node_modules и dist)
SRC_FRONT="$CABZDA/tigrit_web/frontend"
DST_FRONT="$DEPLOY/tigrit_web/frontend"
for item in index.html vite.config.js package.json package-lock.json src; do
  if [[ -e "$SRC_FRONT/$item" ]]; then
    rm -rf "$DST_FRONT/$item"
    cp -R "$SRC_FRONT/$item" "$DST_FRONT/$item"
    echo "  frontend: $item"
  fi
done

echo "Готово. В deploy пересоберите образы (docker build) при необходимости."
