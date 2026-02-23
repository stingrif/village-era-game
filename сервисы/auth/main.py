"""
Сервис авторизации: проверка Telegram initData (или token), возврат user_id.
Секрет для проверки подписи запрашивает у сервиса Secrets.
"""
import hashlib
import json
import hmac
import os
from typing import Any, Dict, Optional
from urllib.parse import parse_qsl, unquote

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="Auth Service", version="0.1.0")

SECRETS_SERVICE_URL = os.environ.get("SECRETS_SERVICE_URL", "http://secrets:8003").rstrip("/")
INTERNAL_TOKEN = os.environ.get("INTERNAL_TOKEN") or os.environ.get("SECRETS_INTERNAL_TOKEN", "")
GAME_API_BASE = os.environ.get("GAME_API_BASE", "http://app:8000").rstrip("/")
INTERNAL_API_SECRET = os.environ.get("INTERNAL_API_SECRET", "")


class VerifyBody(BaseModel):
    init_data: Optional[str] = None
    token: Optional[str] = None


def _get_bot_token() -> str:
    """Запрашивает TELEGRAM_BOT_TOKEN у сервиса секретов."""
    if not INTERNAL_TOKEN:
        return ""
    try:
        r = httpx.get(
            f"{SECRETS_SERVICE_URL}/secret",
            params={"key": "TELEGRAM_BOT_TOKEN"},
            headers={"X-Internal-Token": INTERNAL_TOKEN},
            timeout=5.0,
        )
        if r.status_code != 200:
            return ""
        data = r.json()
        return (data.get("value") or "").strip()
    except Exception:
        return ""


def _get_internal_secret() -> str:
    """Секрет для вызова ensure_user: из env или из Secrets."""
    if INTERNAL_API_SECRET:
        return INTERNAL_API_SECRET
    if not INTERNAL_TOKEN:
        return ""
    try:
        r = httpx.get(
            f"{SECRETS_SERVICE_URL}/secret",
            params={"key": "INTERNAL_API_SECRET"},
            headers={"X-Internal-Token": INTERNAL_TOKEN},
            timeout=5.0,
        )
        if r.status_code != 200:
            return ""
        return (r.json().get("value") or "").strip()
    except Exception:
        return ""


def _validate_telegram_init_data(init_data: str, bot_token: str) -> Dict[str, str]:
    """
    Проверка подписи Telegram Web App initData.
    Возвращает словарь полей (в т.ч. user как JSON-строка) или бросает ValueError.
    """
    if not bot_token or not init_data or not init_data.strip():
        raise ValueError("missing token or init_data")
    pairs = parse_qsl(init_data, keep_blank_values=True)
    received_hash = None
    data_dict = {}
    for k, v in pairs:
        if k == "hash":
            received_hash = v
            continue
        data_dict[k] = unquote(v) if v else ""
    if not received_hash:
        raise ValueError("hash not found")
    data_check_string = "\n".join(f"{k}={data_dict[k]}" for k in sorted(data_dict.keys()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    computed = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if computed != received_hash:
        raise ValueError("invalid signature")
    return data_dict


def _telegram_user_id_from_init_data(parsed: Dict[str, str]) -> Optional[int]:
    """Извлекает telegram user id из поля user (JSON)."""
    user_str = parsed.get("user")
    if not user_str:
        return None
    try:
        user = json.loads(user_str)
        uid = user.get("id")
        return int(uid) if uid is not None else None
    except (json.JSONDecodeError, TypeError, ValueError):
        return None


async def _ensure_user(telegram_id: int) -> Optional[int]:
    """Вызов internal API Игра ensure-user. Возвращает user_id или None."""
    secret = _get_internal_secret()
    if not secret:
        return None
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                f"{GAME_API_BASE}/api/internal/ensure-user",
                json={"telegram_id": telegram_id},
                headers={"X-Internal-Secret": secret},
            )
            if r.status_code != 200:
                return None
            data = r.json()
            return data.get("user_id")
    except Exception:
        return None


@app.post("/verify")
async def verify(body: VerifyBody):
    """
    Проверяет init_data (Telegram Web App). Возвращает {"user_id": int} или 401.
    Поле token принимается, но не поддерживается (авторизация только через Telegram).
    """
    telegram_id = None
    if body.init_data:
        bot_token = _get_bot_token()
        if not bot_token:
            raise HTTPException(status_code=500, detail="secrets unavailable")
        try:
            parsed = _validate_telegram_init_data(body.init_data, bot_token)
            telegram_id = _telegram_user_id_from_init_data(parsed)
        except ValueError:
            raise HTTPException(status_code=401, detail="unauthorized")
        if telegram_id is None:
            raise HTTPException(status_code=401, detail="unauthorized")
    elif body.token:
        # JWT не используется: авторизация только через Telegram init_data
        raise HTTPException(status_code=401, detail="JWT не поддерживается — используйте Telegram init_data")
    else:
        raise HTTPException(status_code=400, detail="init_data or token required")

    user_id = await _ensure_user(telegram_id)
    if user_id is None:
        raise HTTPException(status_code=503, detail="game backend unavailable")
    return {"user_id": user_id}


@app.get("/health")
def health():
    return {"status": "ok"}
