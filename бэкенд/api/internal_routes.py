"""
Внутренние эндпоинты для микросервисов экосистемы (например Тигрит).
Доступ по заголовку X-Internal-Secret (INTERNAL_API_SECRET).
"""
import os
from typing import Any, Dict, Optional

from fastapi import APIRouter, Header, HTTPException

from infrastructure.database import ensure_user

INTERNAL_SECRET = os.environ.get("INTERNAL_API_SECRET", "")

router = APIRouter(prefix="/internal", tags=["internal"])


def _check_internal(x_internal_secret: Optional[str]) -> None:
    if not INTERNAL_SECRET or x_internal_secret != INTERNAL_SECRET:
        raise HTTPException(status_code=403, detail="Forbidden")


@router.post("/ensure-user")
async def internal_ensure_user(
    body: Dict[str, Any],
    x_internal_secret: Optional[str] = Header(None, alias="X-Internal-Secret"),
):
    """
    Возвращает user_id (users.id) по telegram_id. Создаёт пользователя при первом обращении.
    Для микросервисов (Тигрит и др.). Body: {"telegram_id": 123456789}.
    """
    _check_internal(x_internal_secret)
    telegram_id = body.get("telegram_id")
    if telegram_id is None:
        raise HTTPException(status_code=400, detail="telegram_id required")
    try:
        telegram_id = int(telegram_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="telegram_id must be integer")
    user_id = await ensure_user(telegram_id)
    return {"user_id": user_id, "telegram_id": telegram_id}
