"""
Пул asyncpg и низкоуровневые запросы к БД Тигрит.
Секреты и пользователи — только через ensure-user API (в боте), здесь только пул и SQL.
"""
import os
from typing import Any, List, Optional

import asyncpg

DATABASE_URL = os.environ.get("DATABASE_URL")
_pool: Optional[asyncpg.Pool] = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None and DATABASE_URL:
        _pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5, command_timeout=30)
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


async def query_one(sql: str, *params: Any) -> Optional[asyncpg.Record]:
    """Одна строка. В SQL — $1, $2."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow(sql, *params)


async def query_all(sql: str, *params: Any) -> List[asyncpg.Record]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetch(sql, *params)


async def execute(sql: str, *params: Any) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(sql, *params)


async def fetchval(sql: str, *params: Any) -> Any:
    """Одно значение (например RETURNING id)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval(sql, *params)
