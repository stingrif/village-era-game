"""
Опциональная интеграция с сервисом Auth (Фаза 4).
При наличии X-Telegram-Init-Data и отсутствии X-Telegram-User-Id вызывает Auth POST /verify,
получает user_id, резолвит telegram_id и подставляет X-Telegram-User-Id для эндпоинтов.
Если AUTH_SERVICE_URL не задан — middleware не выполняет вызов.
"""
import os
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
import httpx

from infrastructure.database import get_telegram_id_by_user_id

AUTH_SERVICE_URL = os.environ.get("AUTH_SERVICE_URL", "").rstrip("/")


class AuthInitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not AUTH_SERVICE_URL:
            return await call_next(request)
        if request.headers.get("X-Telegram-User-Id") or request.headers.get("X-User-Id"):
            return await call_next(request)
        # Telegram Web App передаёт initData в заголовке (клиент должен слать X-Telegram-Init-Data или Init-Data)
        init_data = (
            request.headers.get("X-Telegram-Init-Data")
            or request.headers.get("Init-Data")
            or ""
        ).strip()
        if not init_data:
            return await call_next(request)
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.post(
                    f"{AUTH_SERVICE_URL}/verify",
                    json={"init_data": init_data.strip()},
                )
            if r.status_code != 200:
                return await call_next(request)
            data = r.json()
            user_id = data.get("user_id")
            if user_id is None:
                return await call_next(request)
            telegram_id = await get_telegram_id_by_user_id(int(user_id))
            if telegram_id is None:
                return await call_next(request)
            scope = request.scope
            headers = list(scope.get("headers", []))
            headers.append((b"x-telegram-user-id", str(telegram_id).encode()))
            scope["headers"] = headers
        except Exception:
            pass
        return await call_next(request)
