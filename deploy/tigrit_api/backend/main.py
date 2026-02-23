"""
Веб-API Тигрит: данные из PostgreSQL через tigrit_shared (village, users, events).
Карта и ассеты — из JSON в backend/data/.
"""
import datetime
import json
import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
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

# Импорт tigrit_shared и backend-модулей: добавляем оба пути в sys.path
_root    = Path(__file__).resolve().parents[1]   # /app
_backend = Path(__file__).resolve().parent        # /app/backend
for _p in (_root, _backend):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from tigrit_shared import db as shared_db
from tigrit_shared.read import (
    get_village_row,
    get_top_users,
    get_recent_events,
    get_active_events,
)
from admin_routes import router as admin_router

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


# Статические зоны — fallback если tigrit_interactions пустой или недоступен
STATIC_ZONES: List[Dict[str, Any]] = [
    {"id":"zone_1","name":"Деревня Тигрит","type":"starter","players_online":0,"total_players":0,
     "xp_multiplier":1.0,"description":"Главная стартовая зона проекта Phoenix","active":True,
     "bot_code":"zone_1","mapX":50,"mapY":35},
    {"id":"zone_2","name":"Торговые ряды","type":"starter","players_online":0,"total_players":0,
     "xp_multiplier":1.2,"description":"Зона торговли. Бонус к XP","active":True,
     "bot_code":"zone_2","mapX":30,"mapY":25},
    {"id":"zone_3","name":"Военный лагерь","type":"starter","players_online":0,"total_players":0,
     "xp_multiplier":1.5,"description":"Зона боя и рейдов. XP ×1.5","active":True,
     "bot_code":"zone_3","mapX":70,"mapY":22},
    {"id":"zone_4","name":"Гильдия Северного Ветра","type":"community","players_online":0,"total_players":0,
     "xp_multiplier":1.0,"description":"Сообщество игроков","active":True,
     "bot_code":"zone_4","mapX":20,"mapY":55},
    {"id":"zone_5","name":"Клан Железного Кулака","type":"community","players_online":0,"total_players":0,
     "xp_multiplier":1.0,"description":"Новая зона","active":True,
     "bot_code":"zone_5","mapX":75,"mapY":60},
    {"id":"zone_6","name":"Академия Магии","type":"community","players_online":0,"total_players":0,
     "xp_multiplier":1.2,"description":"Чат магов и алхимиков","active":True,
     "bot_code":"zone_6","mapX":45,"mapY":70},
]


class ChatMessagePayload(BaseModel):
    text:    str = Field(..., min_length=1, max_length=2000)
    xp:      int = Field(0, ge=0, le=100)
    zone_id: str = Field("zone_1", max_length=64)

    @field_validator("zone_id")
    @classmethod
    def zone_id_safe(cls, v: str) -> str:
        """Только буквы/цифры/подчёркивание — защита от инъекций."""
        import re
        if not re.match(r'^[\w\-]+$', v):
            raise ValueError("zone_id содержит недопустимые символы")
        return v


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Запускает миграции при старте, закрывает пул при остановке."""
    try:
        from run_migrations import run_migrations
        await run_migrations()
    except ImportError:
        logger.warning("run_migrations.py не найден — миграции пропущены")
    except Exception as e:
        logger.error("Ошибка миграций при старте: %s", e)
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

# Подключаем Admin API
app.include_router(admin_router)


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


@app.get("/api/items-catalog")
@limiter.limit(API_RATE_LIMIT)
async def api_items_catalog(request: Request):
    """Единый каталог предметов (реликвии, бафы, проклятия, артефакты, яйца).
    Используется Tigrit-web и Village Era. Каждый предмет содержит поле stat с числовыми значениями."""
    data = _load_json("items-catalog.json", {"items": []})
    return data.get("items", [])


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


@app.get("/api/zones")
@limiter.limit(API_RATE_LIMIT)
async def api_zones(request: Request):
    """Список игровых зон. Попытка читать из tigrit_interactions, fallback к статике."""
    import copy
    zones = copy.deepcopy(STATIC_ZONES)
    try:
        rows = await shared_db.query_all(
            "SELECT actor_id, COUNT(*) as msgs FROM tigrit_interactions "
            "WHERE kind = 'msg' GROUP BY actor_id ORDER BY msgs DESC LIMIT 6"
        )
        if rows:
            for i, row in enumerate(rows):
                if i < len(zones):
                    zones[i]["players_online"] = int(row["msgs"])
    except Exception as e:
        logger.warning("api_zones: БД недоступна, возвращаем статику: %s", e)
    return zones


@app.post("/api/chat/message", status_code=201)
@limiter.limit("30/minute")
async def api_chat_message(request: Request, body: ChatMessagePayload):
    """Записать сообщение чата в tigrit_interactions. Graceful fallback при ошибке БД."""
    import asyncpg
    payload_json = json.dumps(
        {"text": body.text, "xp": body.xp, "zone_id": body.zone_id},
        ensure_ascii=False,
    )
    try:
        inserted_id = await shared_db.fetchval(
            "INSERT INTO tigrit_interactions (ts, kind, actor_id, payload) "
            "VALUES (now(), 'msg', 0, $1) RETURNING id",
            payload_json,
        )
        return {"ok": True, "saved": True, "id": inserted_id}
    except asyncpg.UndefinedTableError:
        logger.warning("api_chat_message: таблица tigrit_interactions не существует")
        return {"ok": True, "saved": False, "reason": "table_missing",
                "hint": "Выполните миграцию 002_tigrit_interactions_ensure.sql"}
    except Exception as e:
        logger.warning("api_chat_message: ошибка БД: %s", e)
        return {"ok": True, "saved": False, "reason": "db_error"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
