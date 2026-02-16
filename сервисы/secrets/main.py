"""
Микросервис секретов: выдача значений по ключу доверенным вызывающим.
Контракт: GET /secret?key=... с заголовком X-Internal-Token.
"""
import json
import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Header, Query
from fastapi.responses import JSONResponse

app = FastAPI(title="Secrets Service", version="0.1.0")

# Кэш секретов: ключ -> значение (не логировать)
_secrets_cache: Optional[dict] = None


def _load_secrets() -> dict:
    """Читает секреты из env и опционально из SECRETS_FILE. Не логирует значения."""
    global _secrets_cache
    if _secrets_cache is not None:
        return _secrets_cache
    out = {}
    # Из env: только переменные, перечисленные в SECRET_KEYS (через запятую), или все с префиксом SECRET_
    secret_keys_env = os.environ.get("SECRET_KEYS", "")
    if secret_keys_env:
        for k in (s.strip() for s in secret_keys_env.split(",") if s.strip()):
            v = os.environ.get(k)
            if v is not None:
                out[k] = v
    else:
        # По умолчанию — все env с префиксом SECRET_
        for k, v in os.environ.items():
            if k.startswith("SECRET_") and v:
                out[k] = v
    path = os.environ.get("SECRETS_FILE")
    if path and Path(path).exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                for k, v in data.items():
                    if isinstance(v, str):
                        out[k] = v
        except (json.JSONDecodeError, OSError):
            pass
    _secrets_cache = out
    return out


def _check_token(x_internal_token: Optional[str]) -> bool:
    """Проверяет внутренний токен. Если INTERNAL_TOKEN не задан — доступ только по сети (токен не проверяем строго)."""
    expected = os.environ.get("INTERNAL_TOKEN")
    if not expected:
        return True
    return x_internal_token is not None and x_internal_token.strip() == expected


@app.get("/secret")
def get_secret(
    key: Optional[str] = Query(None, description="Имя ключа секрета"),
    x_internal_token: Optional[str] = Header(None, alias="X-Internal-Token"),
):
    """
    Возвращает значение секрета по ключу. Требуется заголовок X-Internal-Token при заданном INTERNAL_TOKEN.
    """
    if not key or not key.strip():
        return JSONResponse(
            status_code=400,
            content={"detail": "key is required"},
        )
    key = key.strip()
    if not _check_token(x_internal_token):
        return JSONResponse(
            status_code=403,
            content={"detail": "invalid or missing token"},
        )
    secrets = _load_secrets()
    if key not in secrets:
        return JSONResponse(
            status_code=404,
            content={"detail": "key not found"},
        )
    return {"value": secrets[key]}


@app.get("/health")
def health():
    """Проверка живости сервиса."""
    return {"status": "ok"}
