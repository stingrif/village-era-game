"""
Веб-API Тигрит: данные из PostgreSQL через tigrit_shared (village, users, events).
Карта и ассеты — из JSON в backend/data/.
"""
import json
import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.util import get_remote_address

logger = logging.getLogger(__name__)

# CORS: в проде задать CORS_ORIGINS (через запятую). Пусто или не задано — ["*"] для разработки.
_CORS = os.environ.get("CORS_ORIGINS", "").strip()
CORS_ORIGINS = [o.strip() for o in _CORS.split(",") if o.strip()] if _CORS else ["*"]

# Ключ редактора карты: в env EDITOR_API_KEY. Пустой — сохранение карты отключено.
EDITOR_API_KEY = os.environ.get("EDITOR_API_KEY", "").strip()

# Rate limit: по IP, лимиты на /api/*
limiter = Limiter(key_func=get_remote_address)
API_RATE_LIMIT = "120/minute"
API_RATE_LIMIT_STRICT = "10/minute"  # для PUT /api/map

# Импорт tigrit_shared из той же папки tigrit_api (deploy)
_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from tigrit_shared import db as shared_db
from tigrit_shared.read import (
    get_village_row,
    get_top_users,
    get_recent_events,
    get_active_events,
)

DATA_DIR = Path(__file__).resolve().parent / "data"

# Схема карты для валидации payload (лимит размера — в эндпоинте).
class MapTilePayload(BaseModel):
    x: int = Field(..., ge=0)
    y: int = Field(..., ge=0)
    type: str = Field(..., min_length=1, max_length=64)
    name: Optional[str] = Field(None, max_length=128)
    owner_id: Optional[int] = None


class MapPayload(BaseModel):
    width: int = Field(..., ge=1, le=128)
    height: int = Field(..., ge=1, le=128)
    tiles: list[MapTilePayload] = Field(..., max_length=2000)


def _load_json(name: str, default: dict):
    """Читает JSON из data/ по фиксированному имени. Не подставлять пользовательский ввод в name; при чтении по query — whitelist имён."""
    p = DATA_DIR / name
    if p.exists():
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    return default


def _save_json(name: str, data: dict) -> None:
    """Атомарная запись JSON в data/. Только фиксированные имена (whitelist)."""
    if name != "village_map.json":
        raise ValueError("Разрешено только village_map.json")
    path = DATA_DIR / name
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


async def verify_editor_key(x_api_key: Optional[str] = Header(None, alias="X-API-Key")) -> None:
    """Проверка ключа редактора для PUT /api/map."""
    if not EDITOR_API_KEY:
        raise HTTPException(status_code=503, detail="Сохранение карты отключено (EDITOR_API_KEY не задан)")
    if not x_api_key or x_api_key.strip() != EDITOR_API_KEY:
        raise HTTPException(status_code=401, detail="Неверный или отсутствующий X-API-Key")


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await shared_db.close_pool()


app = FastAPI(title="Tigrit Village API", lifespan=lifespan)
app.state.limiter = limiter
from slowapi.errors import RateLimitExceeded
app.add_exception_handler(RateLimitExceeded, lambda r, e: JSONResponse(status_code=429, content={"detail": "Слишком много запросов"}))

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """В проде не отдаём stack trace. Ошибки логируем на сервере."""
    logger.exception("Unhandled error: %s", exc)
    if isinstance(exc, HTTPException):
        raise exc
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


@app.get("/api/health")
async def api_health():
    """Проверка живучести сервиса — используется фронтом для индикатора «API»."""
    return {"status": "ok"}


@app.get("/api/village")
@limiter.limit(API_RATE_LIMIT)
async def api_village(request: Request):
    """Информация о деревне из tigrit_village (id=1)."""
    row = await get_village_row()
    if not row:
        raise HTTPException(status_code=404, detail="Village not found")
    return row


@app.get("/api/users")
@limiter.limit(API_RATE_LIMIT)
async def api_users(request: Request, limit: int = 10):
    """Топ игроков по XP из tigrit_user_profile."""
    return await get_top_users(limit=min(limit, 100))


@app.get("/api/events")
@limiter.limit(API_RATE_LIMIT)
async def api_events(request: Request, limit: int = 20):
    """Последние события из tigrit_interactions."""
    return await get_recent_events(limit=min(limit, 100))


@app.get("/api/events/active")
@limiter.limit(API_RATE_LIMIT)
async def api_events_active(request: Request, limit: int = 20):
    """Активные ивенты из tigrit_events (присоединиться в боте)."""
    return await get_active_events(limit=min(limit, 100))


@app.get("/api/map")
@limiter.limit(API_RATE_LIMIT)
async def api_map(request: Request):
    """Карта деревни из village_map.json."""
    data = _load_json("village_map.json", {"width": 32, "height": 32, "tiles": []})
    return data


@app.put("/api/map")
@limiter.limit(API_RATE_LIMIT_STRICT)
async def api_map_put(
    request,
    body: MapPayload,
    _: None = Depends(verify_editor_key),
):
    """Сохранение карты редактором. Требуется заголовок X-API-Key = EDITOR_API_KEY."""
    payload = body.model_dump(exclude_none=True)
    try:
        _save_json("village_map.json", payload)
    except Exception as e:
        logger.exception("Ошибка записи карты: %s", e)
        raise HTTPException(status_code=500, detail="Ошибка записи карты")
    return {"ok": True}


@app.get("/api/assets")
@limiter.limit(API_RATE_LIMIT)
async def api_assets(request: Request):
    """Полные данные ассетов из tile_data, building_data, character_data."""
    tiles_data = _load_json("tile_data.json", {"tiles": []})
    buildings_data = _load_json("building_data.json", {"buildings": []})
    chars_data = _load_json("character_data.json", {"characters": [], "races": [], "classes": []})
    characters = chars_data.get("characters", [])
    if not characters and (chars_data.get("races") or chars_data.get("classes")):
        for r in chars_data.get("races", []):
            characters.append({"id": r["id"], "name": r["name"], "color": r.get("base_color", "#888")})
        for c in chars_data.get("classes", []):
            characters.append({"id": c["id"], "name": c["name"], "color": c.get("color", "#888")})
    return {
        "tiles": tiles_data.get("tiles", []),
        "buildings": buildings_data.get("buildings", []),
        "characters": characters,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
