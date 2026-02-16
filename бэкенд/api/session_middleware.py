"""
Middleware: при наличии X-Session-Id и отсутствии X-Telegram-User-Id/X-User-Id
проверяет сессию через сервис Sessions и подставляет X-Telegram-User-Id (telegram_id из БД).
Опционально: если SESSIONS_SERVICE_URL не задан, middleware не выполняет вызов.
"""
import os
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
import httpx
from infrastructure.database import get_telegram_id_by_user_id


SESSIONS_SERVICE_URL = os.environ.get("SESSIONS_SERVICE_URL", "").rstrip("/")


class SessionResolveMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        session_id = request.headers.get("X-Session-Id")
        has_tg = request.headers.get("X-Telegram-User-Id") or request.headers.get("X-User-Id")
        if not SESSIONS_SERVICE_URL or not session_id or has_tg:
            return await call_next(request)
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                r = await client.get(
                    f"{SESSIONS_SERVICE_URL}/session/validate",
                    params={"session_id": session_id.strip()},
                )
            if r.status_code != 200:
                return await call_next(request)
            data = r.json()
            if not data.get("valid") or "user_id" not in data:
                return await call_next(request)
            telegram_id = await get_telegram_id_by_user_id(data["user_id"])
            if telegram_id is None:
                return await call_next(request)
            # Подставляем заголовок для последующих эндпоинтов
            scope = request.scope
            headers = list(scope.get("headers", []))
            headers.append((b"x-telegram-user-id", str(telegram_id).encode()))
            scope["headers"] = headers
        except Exception:
            pass
        return await call_next(request)
