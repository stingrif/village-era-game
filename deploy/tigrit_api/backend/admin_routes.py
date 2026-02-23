"""
Admin API для Тигрит-веба.
Авторизация: заголовок X-Admin-Key == env TIGRIT_ADMIN_API_KEY.
Все PATCH-эндпоинты меняют данные без проверки стоимости ресурсов.
"""
import datetime
import logging
import os
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin", tags=["admin-tigrit"])

ADMIN_KEY = os.environ.get("TIGRIT_ADMIN_API_KEY", "").strip()

# Допустимые action для /activate
ACTIVATE_ACTIONS = {
    "build_complete", "build_reset", "resources_fill",
    "level_up", "activity_reset",
}
RESOURCES_FULL = {"wood": 9999, "stone": 9999, "gold": 9999, "food": 9999, "influence": 999}


def _require_admin(x_admin_key: Optional[str] = Header(None, alias="X-Admin-Key")) -> None:
    """Проверяет X-Admin-Key. При незаданном ADMIN_KEY — 503."""
    if not ADMIN_KEY:
        raise HTTPException(
            status_code=503,
            detail="Admin API отключён: задайте TIGRIT_ADMIN_API_KEY в env и перезапустите контейнер",
        )
    if not x_admin_key or x_admin_key.strip() != ADMIN_KEY:
        raise HTTPException(status_code=401, detail="Неверный или отсутствующий X-Admin-Key")


# ─── СТАТУС ────────────────────────────────────────────────────────

@router.get("/status")
async def admin_status(x_admin_key: Optional[str] = Header(None, alias="X-Admin-Key")):
    """Проверка Admin API: db_connected, village_exists, server_time. Не требует ключа для db_connected."""
    db_connected = False
    village_exists = False

    try:
        from tigrit_shared import db
        pool = await db.get_pool()
        if pool:
            async with pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            db_connected = True
            village_exists_val = await db.fetchval(
                "SELECT EXISTS(SELECT 1 FROM tigrit_village WHERE id = 1)"
            )
            village_exists = bool(village_exists_val)
    except Exception as e:
        logger.warning("admin_status: БД недоступна: %s", e)

    key_ok = bool(ADMIN_KEY) and bool(x_admin_key) and x_admin_key.strip() == ADMIN_KEY

    return {
        "ok": True,
        "admin_key_configured": bool(ADMIN_KEY),
        "key_valid": key_ok,
        "db_connected": db_connected,
        "village_exists": village_exists,
        "server_time": datetime.datetime.utcnow().isoformat() + "Z",
    }


# ─── ДЕРЕВНЯ ───────────────────────────────────────────────────────

@router.get("/village/{village_id}", dependencies=[Depends(_require_admin)])
async def admin_get_village(village_id: int):
    """Полные данные деревни с COALESCE для опциональных полей."""
    from tigrit_shared import db
    try:
        row = await db.query_one(
            """SELECT id,
                      COALESCE(name, 'Тигрит')      AS name,
                      level,
                      COALESCE(xp, 0)               AS xp,
                      activity,
                      resources,
                      population,
                      COALESCE(population_max, 50)  AS population_max,
                      build_name,
                      COALESCE(build_progress, 0)   AS build_progress
               FROM tigrit_village WHERE id = $1""",
            village_id,
        )
    except Exception as e:
        err = str(e)
        if "column" in err and "does not exist" in err:
            raise HTTPException(
                status_code=422,
                detail={"error": "Колонка отсутствует в таблице",
                        "hint": "Выполните миграцию: docker exec <tigrit-api> python3 backend/run_migrations.py",
                        "pg_error": err},
            )
        raise HTTPException(status_code=503, detail={"error": "БД недоступна", "detail": err})

    if not row:
        raise HTTPException(
            status_code=404,
            detail={"error": f"Деревня id={village_id} не найдена",
                    "hint": "Вставьте первую строку: INSERT INTO tigrit_village(id) VALUES(1)"},
        )
    return dict(row)


@router.patch("/village/{village_id}", dependencies=[Depends(_require_admin)])
async def admin_patch_village(village_id: int, body: Dict[str, Any]):
    """Обновляет поля деревни. Возвращает полные данные деревни после UPDATE."""
    from tigrit_shared.write import update_village, MissingColumnError, DatabaseUnavailableError
    from tigrit_shared.write import get_village

    if not body:
        raise HTTPException(status_code=400, detail="Тело запроса пустое")

    try:
        ok = await update_village(village_id, body)
    except MissingColumnError as e:
        raise HTTPException(
            status_code=422,
            detail={"error": "Колонка отсутствует в таблице tigrit_village",
                    "hint": "Выполните миграцию: docker exec <tigrit-api> python3 backend/run_migrations.py",
                    "pg_error": str(e)},
        )
    except DatabaseUnavailableError as e:
        raise HTTPException(status_code=503, detail={"error": "БД недоступна", "detail": str(e)})

    if not ok:
        raise HTTPException(
            status_code=404,
            detail={"error": f"Деревня id={village_id} не найдена или нет допустимых полей",
                    "allowed_fields": ["name","level","xp","activity","population",
                                       "population_max","build_name","build_progress","resources"]},
        )

    village = await get_village(village_id)
    logger.info("admin_patch_village: id=%s fields=%s", village_id, list(body.keys()))
    return {"ok": True, "updated_fields": list(body.keys()), "village": village}


@router.post("/village/{village_id}/activate", dependencies=[Depends(_require_admin)])
async def admin_activate_village(village_id: int, body: Dict[str, Any]):
    """
    Быстрые активации деревни.
    body: {"action": "build_complete"} — одно из build_complete, build_reset,
    resources_fill, level_up, activity_reset.
    """
    import json as _json
    from tigrit_shared import db
    from tigrit_shared.write import get_village

    action = body.get("action", "")
    if not action or action not in ACTIVATE_ACTIONS:
        raise HTTPException(
            status_code=400,
            detail={"error": f"Неизвестное действие: '{action}'",
                    "allowed": sorted(ACTIVATE_ACTIONS)},
        )

    sql_map = {
        "build_complete": "UPDATE tigrit_village SET build_progress = 100 WHERE id = $1",
        "build_reset":    "UPDATE tigrit_village SET build_progress = 0   WHERE id = $1",
        "resources_fill": f"UPDATE tigrit_village SET resources = '{_json.dumps(RESOURCES_FULL)}'::jsonb WHERE id = $1",
        "level_up":       "UPDATE tigrit_village SET level = level + 1, xp = 0 WHERE id = $1",
        "activity_reset": "UPDATE tigrit_village SET activity = 0          WHERE id = $1",
    }

    try:
        await db.execute(sql_map[action], village_id)
    except Exception as e:
        raise HTTPException(status_code=503, detail={"error": "БД недоступна", "detail": str(e)})

    village = await get_village(village_id)
    logger.info("admin_activate_village: id=%s action=%s", village_id, action)
    return {"ok": True, "action": action, "village": village}


# ─── ИГРОКИ ────────────────────────────────────────────────────────

@router.get("/users", dependencies=[Depends(_require_admin)])
async def admin_list_users(
    search: str = Query("", max_length=100),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """Список игроков с поиском по username (ILIKE). При пустой таблице — hint."""
    from tigrit_shared import db

    if search.strip():
        pattern = f"%{search.strip()}%"
        rows = await db.query_all(
            """SELECT user_id, username, race, clazz, xp, level
               FROM tigrit_user_profile
               WHERE username ILIKE $1
               ORDER BY xp DESC LIMIT $2 OFFSET $3""",
            pattern, limit, offset,
        )
    else:
        rows = await db.query_all(
            """SELECT user_id, username, race, clazz, xp, level
               FROM tigrit_user_profile
               ORDER BY xp DESC LIMIT $1 OFFSET $2""",
            limit, offset,
        )

    players = [dict(r) for r in rows]
    result = {"total": len(players), "players": players}
    if not players:
        result["hint"] = "Нет игроков в tigrit_user_profile" if not search else f"Игрок '{search}' не найден"
    return result


@router.get("/user/{user_id}", dependencies=[Depends(_require_admin)])
async def admin_get_user(user_id: int):
    """Профиль игрока из tigrit_user_profile."""
    from tigrit_shared import db
    if user_id <= 0:
        raise HTTPException(status_code=400, detail="user_id должен быть положительным числом")
    row = await db.query_one(
        """SELECT user_id, username, race, clazz, xp, level, house, job, friends
           FROM tigrit_user_profile WHERE user_id = $1""",
        user_id,
    )
    if not row:
        raise HTTPException(
            status_code=404,
            detail={"error": f"Игрок user_id={user_id} не найден в tigrit_user_profile",
                    "hint": "Используйте GET /api/admin/users для поиска по username"},
        )
    return dict(row)


@router.patch("/user/{user_id}", dependencies=[Depends(_require_admin)])
async def admin_patch_user(user_id: int, body: Dict[str, Any]):
    """
    Прокачка игрока без проверки ресурсов.
    Возвращает обновлённые данные после PATCH.
    """
    from tigrit_shared.write import update_user_profile, MissingColumnError, DatabaseUnavailableError
    from tigrit_shared import db

    if user_id <= 0:
        raise HTTPException(status_code=400, detail="user_id должен быть положительным числом")
    if not body:
        raise HTTPException(status_code=400, detail="Тело запроса пустое")

    # Валидация диапазонов
    if "level" in body and body["level"] < 1:
        raise HTTPException(status_code=422, detail={"field": "level", "error": "level должен быть >= 1"})
    if "xp" in body and body["xp"] < 0:
        raise HTTPException(status_code=422, detail={"field": "xp", "error": "xp должен быть >= 0"})

    try:
        ok = await update_user_profile(user_id, body)
    except MissingColumnError as e:
        raise HTTPException(
            status_code=422,
            detail={"error": "Колонка отсутствует в tigrit_user_profile", "pg_error": str(e)},
        )
    except DatabaseUnavailableError as e:
        raise HTTPException(status_code=503, detail={"error": "БД недоступна", "detail": str(e)})

    if not ok:
        # Проверяем — может пользователь не существует
        exists = await db.fetchval(
            "SELECT EXISTS(SELECT 1 FROM tigrit_user_profile WHERE user_id=$1)", user_id
        )
        if not exists:
            raise HTTPException(
                status_code=404,
                detail={"error": f"Игрок user_id={user_id} не найден",
                        "hint": "Используйте GET /api/admin/users для поиска"},
            )
        raise HTTPException(
            status_code=422,
            detail={"error": "Нет допустимых полей для обновления",
                    "allowed": ["xp", "level", "race", "clazz", "job"]},
        )

    # Возвращаем актуальные данные игрока после UPDATE
    row = await db.query_one(
        "SELECT user_id, username, race, clazz, xp, level FROM tigrit_user_profile WHERE user_id=$1",
        user_id,
    )
    logger.info("admin_patch_user: user_id=%s fields=%s", user_id, list(body.keys()))
    return {"ok": True, "updated_fields": list(body.keys()), "user": dict(row) if row else None}
