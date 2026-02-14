#!/usr/bin/env python3
"""
Проверка связи со всеми базами данных и сервисами из .env.

Использует переменные: DATABASE_URL (PostgreSQL), REDIS_URL (Redis).
Если DATABASE_URL не задан, собирает URL из DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD.

Запуск из корня бэкенда:
    python скрипты/check_db_connections.py
    или: cd бэкенд && python скрипты/check_db_connections.py
"""
import asyncio
import os
import sys
from pathlib import Path
from typing import Optional, Tuple

# Корень бэкенда — родитель папки скрипты
BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
os.chdir(BACKEND_ROOT)

# Загрузка .env до импорта config
try:
    from dotenv import load_dotenv
    load_dotenv(BACKEND_ROOT / ".env")
except ImportError:
    pass


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


def get_database_url() -> Optional[str]:
    url = _env("DATABASE_URL")
    if url:
        return url
    host = _env("DB_HOST")
    port = _env("DB_PORT", "5432")
    name = _env("DB_NAME", "village_era")
    user = _env("DB_USER")
    password = _env("DB_PASSWORD")
    if host and user:
        pw = f":{password}" if password else ""
        return f"postgresql://{user}{pw}@{host}:{port}/{name}"
    return None


def mask_url(url: str) -> str:
    """Скрыть пароль в URL для вывода в консоль."""
    if not url:
        return "(не задан)"
    if "@" in url and "://" in url:
        pre, rest = url.split("://", 1)
        if "@" in rest:
            user_part, host_part = rest.rsplit("@", 1)
            if ":" in user_part:
                user, _ = user_part.split(":", 1)
                user_part = user + ":****"
            return f"{pre}://{user_part}@{host_part}"
    return url


async def check_postgres() -> Tuple[bool, str]:
    """Проверка подключения к PostgreSQL (DATABASE_URL или DB_*)."""
    url = get_database_url()
    if not url:
        return False, "DATABASE_URL и DB_* не заданы в .env"
    try:
        import asyncpg
    except ImportError:
        return False, "модуль asyncpg не установлен (pip install asyncpg)"
    try:
        conn = await asyncio.wait_for(
            asyncpg.connect(url),
            timeout=5.0,
        )
        try:
            v = await conn.fetchval("SELECT 1")
            assert v == 1
            return True, "OK"
        finally:
            await conn.close()
    except asyncio.TimeoutError:
        return False, "таймаут подключения (5 с)"
    except Exception as e:
        return False, str(e)


async def check_redis() -> Tuple[bool, str]:
    """Проверка подключения к Redis (REDIS_URL)."""
    url = _env("REDIS_URL", "redis://localhost:6379/0")
    if not url:
        return False, "REDIS_URL не задан"
    try:
        from redis import asyncio as aioredis
    except ImportError:
        return False, "модуль redis не установлен (pip install redis)"
    try:
        client = aioredis.from_url(url, encoding="utf-8", decode_responses=True)
        try:
            await asyncio.wait_for(client.ping(), timeout=3.0)
            return True, "OK"
        finally:
            await client.aclose()
    except asyncio.TimeoutError:
        return False, "таймаут подключения (3 с)"
    except Exception as e:
        return False, str(e)


async def main() -> int:
    print("Проверка связи с БД и сервисами из .env")
    print("=" * 60)

    # PostgreSQL
    db_url = get_database_url()
    print(f"\nPostgreSQL (DATABASE_URL / DB_*): {mask_url(db_url or '')}")
    ok_pg, msg_pg = await check_postgres()
    if ok_pg:
        print("  ✅", msg_pg)
    else:
        print("  ❌", msg_pg)

    # Redis
    redis_url = _env("REDIS_URL", "redis://localhost:6379/0")
    print(f"\nRedis (REDIS_URL): {mask_url(redis_url)}")
    ok_redis, msg_redis = await check_redis()
    if ok_redis:
        print("  ✅", msg_redis)
    else:
        print("  ❌", msg_redis)

    print("\n" + "=" * 60)
    if ok_pg and ok_redis:
        print("Все проверки пройдены.")
        return 0
    print("Есть ошибки подключения.")
    return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
