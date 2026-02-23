"""
Чтение данных для веб-API Тигрит: деревня, топ игроков, последние события.
Без логики бота (ensure_user, ensure_tigrit_profile и т.д.).
"""
from typing import Any, Dict, List, Optional

from . import db


async def get_village_row() -> Optional[Dict[str, Any]]:
    """Строка tigrit_village (id=1). Включает name с COALESCE; fallback если колонки нет."""
    try:
        row = await db.query_one(
            """SELECT COALESCE(name, 'Тигрит') AS name,
                      level, COALESCE(xp, 0) AS xp,
                      activity, resources, population,
                      COALESCE(population_max, 50) AS population_max,
                      build_name, COALESCE(build_progress, 0) AS build_progress
               FROM tigrit_village WHERE id = 1"""
        )
    except Exception:
        # Fallback на SELECT без новых колонок если миграция ещё не выполнена
        row = await db.query_one(
            "SELECT level, activity, resources, population, build_name, build_progress "
            "FROM tigrit_village WHERE id = 1"
        )
    if not row:
        return None
    result = dict(row)
    result.setdefault("name", "Тигрит")
    result.setdefault("xp", 0)
    result.setdefault("population_max", 50)
    return result


async def get_top_users(limit: int = 10) -> List[Dict[str, Any]]:
    """Топ игроков по XP. Поля: user_id, username, race, clazz, xp, level, house, job, friends."""
    rows = await db.query_all(
        """SELECT user_id, username, race, clazz, xp, level, house, job, friends
           FROM tigrit_user_profile ORDER BY xp DESC LIMIT $1""",
        limit,
    )
    return [dict(r) for r in rows]


async def get_recent_events(limit: int = 20) -> List[Dict[str, Any]]:
    """Последние записи из tigrit_interactions (для веб — совместимость с прежним «events»)."""
    rows = await db.query_all(
        "SELECT id, ts, kind, actor_id, target_id, payload FROM tigrit_interactions ORDER BY ts DESC LIMIT $1",
        limit,
    )
    return [dict(r) for r in rows]


async def get_active_events(limit: int = 20) -> List[Dict[str, Any]]:
    """Активные ивенты из tigrit_events (для отображения на вебе)."""
    rows = await db.query_all(
        """SELECT id, title, effect_type, effect_sign, effect_value, chat_id, message_id, start_ts, end_ts, status
           FROM tigrit_events WHERE status = 'active' ORDER BY start_ts DESC LIMIT $1""",
        limit,
    )
    return [dict(r) for r in rows]
