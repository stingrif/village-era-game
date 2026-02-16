"""
Асинхронный слой БД для Тигрит: PostgreSQL (общая с Игра), таблицы tigrit_*, users только через ensure-user API.
Пул и чтение — через tigrit_shared; здесь только ensure_user, ensure_tigrit_profile и запись в tigrit_*.
"""
import os
import random
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx

# Папка бота для импорта tigrit_shared (tigrit_shared лежит рядом с db_async.py)
_cabzda = Path(__file__).resolve().parents[1]
if str(_cabzda) not in sys.path:
    sys.path.insert(0, str(_cabzda))

from prompts import RACES, CLASSES
from tigrit_shared import db as shared_db
from tigrit_shared.read import get_village_row as shared_get_village_row

get_pool = shared_db.get_pool
close_pool = shared_db.close_pool
query_one = shared_db.query_one
query_all = shared_db.query_all
execute = shared_db.execute
fetchval = shared_db.fetchval
get_village_row = shared_get_village_row

GAME_API_BASE = os.environ.get("GAME_API_BASE", "http://app:8000").rstrip("/")
INTERNAL_API_SECRET = os.environ.get("INTERNAL_API_SECRET", "")


async def get_user_id(telegram_id: int) -> int:
    """Возвращает user_id (users.id) по telegram_id. Вызов ensure-user API Игра."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.post(
            f"{GAME_API_BASE}/internal/ensure-user",
            json={"telegram_id": telegram_id},
            headers={"X-Internal-Secret": INTERNAL_API_SECRET} if INTERNAL_API_SECRET else {},
        )
        r.raise_for_status()
        data = r.json()
        return int(data["user_id"])


async def ensure_tigrit_profile(telegram_id: int, username: Optional[str] = None) -> int:
    """Создаёт/обновляет запись в tigrit_user_profile. Возвращает user_id."""
    user_id = await get_user_id(telegram_id)
    pool = await get_pool()
    username = username or ""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT user_id FROM tigrit_user_profile WHERE user_id = $1", user_id
        )
        if row:
            await conn.execute(
                "UPDATE tigrit_user_profile SET username = $2 WHERE user_id = $1",
                user_id, username,
            )
            return user_id
        race, _ = random.choice(RACES)
        clazz = random.choice(CLASSES)
        await conn.execute(
            """INSERT INTO tigrit_user_profile (user_id, username, race, clazz)
               VALUES ($1, $2, $3, $4)
               ON CONFLICT (user_id) DO UPDATE SET username = EXCLUDED.username""",
            user_id, username, race, clazz,
        )
        await conn.execute(
            "UPDATE tigrit_village SET population = population + 1 WHERE id = 1"
        )
    return user_id


async def get_setting(key: str) -> Optional[str]:
    row = await query_one("SELECT v FROM tigrit_settings WHERE k = $1", key)
    return row["v"] if row and row["v"] is not None else None


async def set_setting(key: str, value: str) -> None:
    await execute(
        """INSERT INTO tigrit_settings (k, v) VALUES ($1, $2)
           ON CONFLICT (k) DO UPDATE SET v = EXCLUDED.v""",
        key, value,
    )


async def upsert_chat(
    chat_id: int,
    type_: str,
    title: Optional[str] = None,
    invite_link: Optional[str] = None,
    owner_user_id: Optional[int] = None,
) -> None:
    await execute(
        """INSERT INTO tigrit_chats (chat_id, type, title, invite_link, owner_user_id)
           VALUES ($1, $2, $3, $4, $5)
           ON CONFLICT (chat_id) DO UPDATE SET
             type = EXCLUDED.type,
             title = COALESCE(NULLIF(EXCLUDED.title, ''), tigrit_chats.title),
             invite_link = COALESCE(EXCLUDED.invite_link, tigrit_chats.invite_link),
             owner_user_id = COALESCE(EXCLUDED.owner_user_id, tigrit_chats.owner_user_id)""",
        chat_id, type_ or "", title or "", invite_link or "", owner_user_id,
    )


async def get_profile(telegram_id: int) -> Optional[Dict[str, Any]]:
    """Профиль из tigrit_user_profile по telegram_id."""
    user_id = await get_user_id(telegram_id)
    row = await query_one(
        """SELECT username, race, clazz, xp, level, house, job, friends,
                  job_name, job_expires_at, job_xp_per_hour
           FROM tigrit_user_profile WHERE user_id = $1""",
        user_id,
    )
    if not row:
        return None
    return {
        "username": row["username"],
        "race": row["race"],
        "clazz": row["clazz"],
        "xp": row["xp"] or 0,
        "level": row["level"] or 0,
        "house": row["house"] or 0,
        "job": row["job"] or 0,
        "friends": row["friends"] or 0,
        "job_name": row["job_name"],
        "job_expires_at": row["job_expires_at"],
        "job_xp_per_hour": row["job_xp_per_hour"],
    }


async def get_feathers_balance(telegram_id: int) -> int:
    """Баланс FEATHERS из user_balances (общая таблица Игра)."""
    user_id = await get_user_id(telegram_id)
    row = await query_one(
        "SELECT balance FROM user_balances WHERE user_id = $1 AND currency = 'FEATHERS'",
        user_id,
    )
    return int(row["balance"]) if row and row["balance"] is not None else 0


XP_COOLDOWN = 4
XP_PER_MSG = 5


async def can_gain_xp(user_id: int) -> bool:
    now = _ts()
    row = await query_one("SELECT last_xp_at FROM tigrit_cooldowns WHERE user_id = $1", user_id)
    last = int(row["last_xp_at"]) if row and row["last_xp_at"] else 0
    if now - last >= XP_COOLDOWN:
        await execute(
            """INSERT INTO tigrit_cooldowns (user_id, last_xp_at) VALUES ($1, $2)
               ON CONFLICT (user_id) DO UPDATE SET last_xp_at = EXCLUDED.last_xp_at""",
            user_id, now,
        )
        return True
    return False


async def gain_xp_and_level(telegram_id: int) -> Optional[Tuple[int, int]]:
    """Начисляет XP за сообщение. Возвращает (new_xp, new_level) или None если кулдаун."""
    import math
    user_id = await get_user_id(telegram_id)
    if not await can_gain_xp(user_id):
        return None
    row = await query_one(
        "SELECT xp, level FROM tigrit_user_profile WHERE user_id = $1", user_id
    )
    old_xp = int(row["xp"]) if row and row["xp"] is not None else 0
    old_level = int(row["level"]) if row and row["level"] is not None else 0
    new_xp = old_xp + XP_PER_MSG
    new_level = int(math.floor(math.sqrt(new_xp / 50)))
    house_inc = 1 if new_level > old_level else 0
    now = _ts()
    await execute(
        """UPDATE tigrit_user_profile SET
               xp = $2, level = $3, house = house + $4,
               last_activity = $5, activity_count = activity_count + 1
           WHERE user_id = $1""",
        user_id, new_xp, new_level, house_inc, now,
    )
    await execute("UPDATE tigrit_village SET activity = activity + 1 WHERE id = 1")
    # Прогресс стройки
    acc_row = await get_setting("build_xp_accum")
    acc = int(acc_row) if acc_row and str(acc_row).isdigit() else 0
    acc += XP_PER_MSG
    inc = acc // 400
    acc = acc % 400
    await set_setting("build_xp_accum", str(acc))
    if inc > 0:
        prog_row = await query_one("SELECT build_progress FROM tigrit_village WHERE id = 1")
        prog = int(prog_row["build_progress"]) if prog_row else 0
        new_prog = min(100, prog + int(inc))
        await execute("UPDATE tigrit_village SET build_progress = $1 WHERE id = 1", new_prog)
    return (new_xp, new_level)


async def top_users(limit: int = 10) -> List[Tuple[str, int]]:
    """Топ игроков по XP. Возвращает [(username, xp), ...]."""
    rows = await query_all(
        "SELECT username, xp FROM tigrit_user_profile ORDER BY xp DESC LIMIT $1",
        limit,
    )
    return [(r["username"] or "", int(r["xp"] or 0)) for r in rows]


def _ts() -> int:
    return int(time.time())


def build_persona(race: str, clazz: str, username: str) -> str:
    from prompts import build_persona as _bp
    return _bp(race, clazz, username)


async def get_persona_prompt(telegram_id: int) -> Optional[str]:
    """Промпт персонажа для LLM по telegram_id."""
    prof = await get_profile(telegram_id)
    if not prof:
        return None
    return build_persona(
        prof["race"] or "",
        prof["clazz"] or "",
        prof["username"] or "",
    )
