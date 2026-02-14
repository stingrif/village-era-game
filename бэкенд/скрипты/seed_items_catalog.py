#!/usr/bin/env python3
"""Сид каталога предметов в item_defs из Игра/data/items-catalog.json. Запуск из корня репо или из бэкенд."""
import asyncio
import json
import os
import sys
from pathlib import Path

# Добавляем корень бэкенда в path
BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

os.chdir(BACKEND)


async def main():
    from infrastructure.database import init_db, close_db
    await init_db()
    await close_db()
    print("DB init and item defs seed done.")


if __name__ == "__main__":
    asyncio.run(main())
