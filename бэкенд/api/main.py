import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import Set

from fastapi import FastAPI, Request, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.admin_routes import router as admin_router
from api.admin_panel_routes import router as admin_panel_router
from api.internal_routes import router as internal_router
from api.routes import router
from api.session_middleware import SessionResolveMiddleware
from infrastructure.database import init_db, close_db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ——— WebSocket online tracking ———
_online_ws: Set[WebSocket] = set()


async def _broadcast_online_count():
    """Отправить текущее количество онлайн всем подключённым WS-клиентам."""
    count = len(_online_ws)
    msg = json.dumps({"online": count})
    dead: list = []
    for ws in _online_ws:
        try:
            await ws.send_text(msg)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _online_ws.discard(ws)


async def _ws_heartbeat_loop():
    """Фоновая задача: пинг всех WS-клиентов каждые 30 секунд для обнаружения мёртвых."""
    while True:
        await asyncio.sleep(30)
        dead: list = []
        for ws in list(_online_ws):
            try:
                await ws.send_text(json.dumps({"ping": True}))
            except Exception:
                dead.append(ws)
        if dead:
            for ws in dead:
                _online_ws.discard(ws)
            await _broadcast_online_count()

# Интервал фоновой синхронизации NFT (секунды). По умолчанию 30 мин.
NFT_SYNC_INTERVAL = 30 * 60


async def _nft_sync_loop():
    """Фоновая задача: периодическая синхронизация NFT-каталога + холдеров."""
    from infrastructure.nft_sync import run_full_sync, sync_nft_holders
    # Первый запуск через 10 сек после старта (дать БД проинициализироваться)
    await asyncio.sleep(10)
    while True:
        try:
            logger.info("nft_sync_loop: starting periodic sync")
            stats = await run_full_sync()
            logger.info("nft_sync_loop: nft done — %s", stats)
            # Sync holder analytics after NFT sync
            holder_stats = await sync_nft_holders()
            logger.info("nft_sync_loop: holders done — %s", holder_stats)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning("nft_sync_loop error: %s", e)
        await asyncio.sleep(NFT_SYNC_INTERVAL)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    # Запускаем фоновую синхронизацию NFT
    sync_task = asyncio.create_task(_nft_sync_loop())
    heartbeat_task = asyncio.create_task(_ws_heartbeat_loop())
    yield
    sync_task.cancel()
    heartbeat_task.cancel()
    try:
        await sync_task
    except asyncio.CancelledError:
        pass
    try:
        await heartbeat_task
    except asyncio.CancelledError:
        pass
    await close_db()


# При allow_credentials=True нельзя использовать allow_origins=["*"] — браузер требует явный origin
from config import CORS_ORIGINS_EXTRA

CORS_ORIGINS = [
    "http://localhost:8080",
    "http://127.0.0.1:8080",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "https://localhost:8080",
    "https://127.0.0.1:8080",
    "https://web.telegram.org",
    "https://t.me",
] + list(CORS_ORIGINS_EXTRA)

app = FastAPI(
    title="Village Era Game API",
    version="1.0.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)
app.add_middleware(SessionResolveMiddleware)
app.include_router(router)
app.include_router(internal_router)
app.include_router(admin_router)
app.include_router(admin_panel_router)


def _cors_headers_for_request(request: Request) -> dict:
    """Заголовки CORS по Origin запроса (только если origin в разрешённом списке)."""
    origin = request.headers.get("origin")
    if origin and origin in CORS_ORIGINS:
        return {"Access-Control-Allow-Origin": origin}
    return {}


async def exception_handler_500(request: Request, exc: Exception) -> JSONResponse:
    """Глобальный обработчик необработанных исключений: 500 + CORS. HTTPException пробрасываем дальше (обрабатывает FastAPI)."""
    if isinstance(exc, HTTPException):
        raise exc
    logger.exception(exc)
    headers = _cors_headers_for_request(request)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal Server Error"},
        headers=headers,
    )


app.add_exception_handler(Exception, exception_handler_500)


@app.websocket("/ws/online")
async def ws_online(websocket: WebSocket):
    """WebSocket для real-time счётчика онлайн-игроков."""
    await websocket.accept()
    _online_ws.add(websocket)
    await _broadcast_online_count()
    try:
        while True:
            await websocket.receive_text()  # keep-alive
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        _online_ws.discard(websocket)
        await _broadcast_online_count()


def get_online_count() -> int:
    """Текущее количество WS-подключений (для REST fallback)."""
    return len(_online_ws)


@app.get("/health")
def health():
    return {"status": "ok"}
