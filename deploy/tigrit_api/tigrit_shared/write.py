"""
Запись данных в БД Тигрит: деревня, профили игроков.
Используется Admin API — все методы без проверки стоимости/ресурсов.
"""
import json
import logging
from typing import Any, Dict, Optional, Tuple

from . import db

logger = logging.getLogger(__name__)


class MissingColumnError(Exception):
    """Колонка отсутствует в таблице — нужна миграция."""


class DatabaseUnavailableError(Exception):
    """БД недоступна (connection error)."""


async def update_village(village_id: int, fields: Dict[str, Any]) -> bool:
    """
    Обновляет поля строки tigrit_village по id.
    Допустимые поля: name, level, xp, activity, population, population_max,
                     build_name, build_progress, resources (dict → JSONB).
    Возвращает True если строка найдена и обновлена.
    """
    ALLOWED = {
        "name", "level", "xp", "activity",
        "population", "population_max",
        "build_name", "build_progress", "resources",
    }
    clean = {k: v for k, v in fields.items() if k in ALLOWED and v is not None}
    if not clean:
        return False

    # resources сериализуем в JSON-строку для JSONB
    if "resources" in clean and isinstance(clean["resources"], dict):
        clean["resources"] = json.dumps(clean["resources"], ensure_ascii=False)

    assignments = []
    values = []
    for i, (col, val) in enumerate(clean.items(), start=1):
        assignments.append(f"{col} = ${i}")
        values.append(val)

    values.append(village_id)
    sql = f"UPDATE tigrit_village SET {', '.join(assignments)} WHERE id = ${len(values)} RETURNING id"
    try:
        result = await db.fetchval(sql, *values)
    except Exception as e:
        err_str = str(e)
        if "column" in err_str and "does not exist" in err_str:
            # Определяем какая именно колонка — возвращаем специальный флаг
            raise MissingColumnError(err_str) from e
        if "connection" in err_str.lower() or "pool" in err_str.lower():
            raise DatabaseUnavailableError(err_str) from e
        raise
    return result is not None


async def update_user_profile(user_id: int, fields: Dict[str, Any]) -> bool:
    """
    Обновляет поля tigrit_user_profile по user_id.
    Допустимые поля: xp, level, race, clazz, job, house (dict → JSONB).
    Возвращает True если строка найдена и обновлена.
    """
    ALLOWED = {"xp", "level", "race", "clazz", "job", "house"}
    clean = {k: v for k, v in fields.items() if k in ALLOWED and v is not None}
    if not clean:
        return False

    if "house" in clean and isinstance(clean["house"], dict):
        clean["house"] = json.dumps(clean["house"], ensure_ascii=False)

    assignments = []
    values = []
    for i, (col, val) in enumerate(clean.items(), start=1):
        assignments.append(f"{col} = ${i}")
        values.append(val)

    values.append(user_id)
    sql = f"UPDATE tigrit_user_profile SET {', '.join(assignments)} WHERE user_id = ${len(values)} RETURNING user_id"
    try:
        result = await db.fetchval(sql, *values)
    except Exception as e:
        err_str = str(e)
        if "column" in err_str and "does not exist" in err_str:
            raise MissingColumnError(err_str) from e
        if "connection" in err_str.lower() or "pool" in err_str.lower():
            raise DatabaseUnavailableError(err_str) from e
        raise
    return result is not None


async def get_village(village_id: int) -> Optional[Dict[str, Any]]:
    """Возвращает полную строку деревни включая name."""
    row = await db.query_one(
        """SELECT id, name, level, xp, activity, resources,
                  population, population_max, build_name, build_progress
           FROM tigrit_village WHERE id = $1""",
        village_id,
    )
    return dict(row) if row else None
