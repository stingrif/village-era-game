"""
Сервис сессий: создание, продление, инвалидация, проверка.
Хранение в Redis. Ключ подписи (опционально) — из сервиса Secrets.
"""
import json
import os
import time
import uuid
from typing import Optional

import httpx
import redis
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

app = FastAPI(title="Sessions Service", version="0.1.0")

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
SECRETS_SERVICE_URL = os.environ.get("SECRETS_SERVICE_URL", "http://secrets:8003").rstrip("/")
INTERNAL_TOKEN = os.environ.get("INTERNAL_TOKEN") or os.environ.get("SECRETS_INTERNAL_TOKEN", "")
SESSION_TTL_SECONDS = int(os.environ.get("SESSION_TTL_SECONDS", "86400"))  # 24 часа
SESSION_KEY_PREFIX = "session:"
USER_SESSIONS_PREFIX = "user_sessions:"


def _redis() -> redis.Redis:
    """Клиент Redis (синхронный)."""
    return redis.from_url(REDIS_URL, decode_responses=True)


def _get_signing_key() -> str:
    """Опционально: ключ подписи из Secrets (пока не используем в session_id)."""
    if not INTERNAL_TOKEN:
        return ""
    try:
        r = httpx.get(
            f"{SECRETS_SERVICE_URL}/secret",
            params={"key": "SESSION_SIGNING_KEY"},
            headers={"X-Internal-Token": INTERNAL_TOKEN},
            timeout=5.0,
        )
        if r.status_code == 200:
            return (r.json().get("value") or "").strip()
    except Exception:
        pass
    return ""


class CreateBody(BaseModel):
    user_id: int


class RefreshBody(BaseModel):
    session_id: str


class InvalidateBody(BaseModel):
    session_id: Optional[str] = None
    user_id: Optional[int] = None


@app.post("/session")
def create_session(body: CreateBody):
    """Создать сессию для user_id. Возвращает session_id и expires_at (unix)."""
    try:
        r = _redis()
    except Exception as e:
        raise HTTPException(status_code=500, detail="storage unavailable")
    session_id = str(uuid.uuid4())
    expires_at = int(time.time()) + SESSION_TTL_SECONDS
    key = SESSION_KEY_PREFIX + session_id
    value = json.dumps({"user_id": body.user_id, "expires_at": expires_at})
    r.setex(key, SESSION_TTL_SECONDS, value)
    user_key = USER_SESSIONS_PREFIX + str(body.user_id)
    r.sadd(user_key, session_id)
    r.expire(user_key, SESSION_TTL_SECONDS * 2)
    return {"session_id": session_id, "expires_at": expires_at}


@app.post("/session/refresh")
def refresh_session(body: RefreshBody):
    """Продлить TTL сессии. Возвращает новый expires_at."""
    if not body.session_id or not body.session_id.strip():
        raise HTTPException(status_code=400, detail="session_id required")
    try:
        r = _redis()
    except Exception:
        raise HTTPException(status_code=500, detail="storage unavailable")
    key = SESSION_KEY_PREFIX + body.session_id.strip()
    raw = r.get(key)
    if not raw:
        raise HTTPException(status_code=401, detail="session not found or expired")
    data = json.loads(raw)
    expires_at = int(time.time()) + SESSION_TTL_SECONDS
    data["expires_at"] = expires_at
    r.setex(key, SESSION_TTL_SECONDS, json.dumps(data))
    return {"expires_at": expires_at}


@app.post("/session/invalidate")
def invalidate_session(body: InvalidateBody):
    """Инвалидировать сессию по session_id или все сессии по user_id."""
    if body.session_id:
        try:
            r = _redis()
        except Exception:
            raise HTTPException(status_code=500, detail="storage unavailable")
        key = SESSION_KEY_PREFIX + body.session_id.strip()
        raw = r.get(key)
        if raw:
            data = json.loads(raw)
            uid = data.get("user_id")
            r.delete(key)
            if uid is not None:
                r.srem(USER_SESSIONS_PREFIX + str(uid), body.session_id.strip())
        return {"ok": True}
    if body.user_id is not None:
        try:
            r = _redis()
        except Exception:
            raise HTTPException(status_code=500, detail="storage unavailable")
        user_key = USER_SESSIONS_PREFIX + str(body.user_id)
        session_ids = r.smembers(user_key)
        for sid in session_ids or []:
            r.delete(SESSION_KEY_PREFIX + sid)
        r.delete(user_key)
        return {"ok": True}
    raise HTTPException(status_code=400, detail="session_id or user_id required")


@app.get("/session/validate")
def validate_session(session_id: Optional[str] = Query(None)):
    """Проверить сессию. Возвращает {valid: true, user_id: int} или {valid: false}."""
    if not session_id or not session_id.strip():
        raise HTTPException(status_code=400, detail="session_id required")
    try:
        r = _redis()
    except Exception:
        raise HTTPException(status_code=500, detail="storage unavailable")
    key = SESSION_KEY_PREFIX + session_id.strip()
    raw = r.get(key)
    if not raw:
        return {"valid": False}
    data = json.loads(raw)
    expires_at = data.get("expires_at", 0)
    if expires_at < int(time.time()):
        r.delete(key)
        return {"valid": False}
    return {"valid": True, "user_id": data["user_id"]}


@app.get("/health")
def health():
    """Проверка живости и доступности Redis."""
    try:
        _redis().ping()
        return {"status": "ok"}
    except Exception:
        return JSONResponse(status_code=503, content={"status": "error"})
