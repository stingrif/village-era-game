"""
Админ-панель: отдельный вход по логину/паролю (не в основном приложении).
Первый вход — создание учётной записи; в настройках — смена логина/пароля.
Управление списком адресов стейкинг-контрактов (добавление/удаление).
"""
import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Header

from config import ADMIN_PANEL_PASSWORD_SALT
from infrastructure.database import (
    admin_panel_create,
    admin_panel_get_by_login,
    admin_panel_get_by_token,
    admin_panel_has_any,
    admin_panel_set_token,
    admin_panel_update_login,
    admin_panel_update_password,
    staking_contract_add,
    staking_contract_delete,
    staking_contracts_list,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin-panel", tags=["admin-panel"])

TOKEN_EXPIRE_DAYS = 7


def _hash_password(password: str) -> str:
    return hashlib.sha256((password + ADMIN_PANEL_PASSWORD_SALT).encode()).hexdigest()


def _check_password(password: str, password_hash: str) -> bool:
    return _hash_password(password) == password_hash


async def _get_admin_from_bearer(
    authorization: Optional[str] = Header(None),
) -> Dict[str, Any]:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authorization Bearer required")
    token = authorization[7:].strip()
    admin = await admin_panel_get_by_token(token)
    if not admin:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return admin


# ——— Первый вход / логин ———

@router.get("/setup/status")
async def setup_status() -> Dict[str, Any]:
    """Проверить, создан ли уже админ (есть ли учётные записи). Если нет — фронт показывает форму создания."""
    has_any = await admin_panel_has_any()
    return {"admin_exists": has_any}


@router.post("/setup")
async def setup_create_admin(body: Dict[str, Any]) -> Dict[str, Any]:
    """Первый вход: создать единственную учётную запись админа. Только если записей ещё нет."""
    if await admin_panel_has_any():
        raise HTTPException(status_code=403, detail="Admin already exists, use login")
    login = (body.get("login") or "").strip()
    password = body.get("password") or ""
    if not login or len(login) < 2:
        raise HTTPException(status_code=400, detail="login required (min 2 chars)")
    if not password or len(password) < 6:
        raise HTTPException(status_code=400, detail="password required (min 6 chars)")
    password_hash = _hash_password(password)
    await admin_panel_create(login, password_hash)
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(days=TOKEN_EXPIRE_DAYS)
    admin = await admin_panel_get_by_login(login)
    await admin_panel_set_token(admin["id"], token, expires)
    return {
        "ok": True,
        "token": token,
        "expires_at": expires.isoformat(),
        "login": login,
    }


@router.post("/login")
async def login(body: Dict[str, Any]) -> Dict[str, Any]:
    """Вход по логину и паролю. Возвращает token для заголовка Authorization: Bearer <token>."""
    login_str = (body.get("login") or "").strip()
    password = body.get("password") or ""
    if not login_str or not password:
        raise HTTPException(status_code=400, detail="login and password required")
    admin = await admin_panel_get_by_login(login_str)
    if not admin or not _check_password(password, admin["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid login or password")
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(days=TOKEN_EXPIRE_DAYS)
    await admin_panel_set_token(admin["id"], token, expires)
    return {
        "ok": True,
        "token": token,
        "expires_at": expires.isoformat(),
        "login": admin["login"],
    }


@router.get("/me")
async def me(admin: Dict[str, Any] = Depends(_get_admin_from_bearer)) -> Dict[str, Any]:
    """Текущий админ (по токену)."""
    return {"login": admin["login"], "id": admin["id"]}


@router.put("/settings")
async def settings(
    body: Dict[str, Any],
    admin: Dict[str, Any] = Depends(_get_admin_from_bearer),
) -> Dict[str, Any]:
    """Смена логина и/или пароля. Требуется текущий пароль при смене пароля."""
    new_login = (body.get("new_login") or body.get("login") or "").strip()
    new_password = body.get("new_password") or body.get("password") or ""
    current_password = body.get("current_password") or body.get("password") or ""

    if new_login and new_login != admin["login"]:
        if len(new_login) < 2:
            raise HTTPException(status_code=400, detail="new_login min 2 chars")
        await admin_panel_update_login(admin["id"], new_login)

    if new_password:
        if len(new_password) < 6:
            raise HTTPException(status_code=400, detail="new_password min 6 chars")
        # Проверка текущего пароля перед сменой
        full_admin = await admin_panel_get_by_login(admin["login"])
        if not full_admin or not _check_password(current_password, full_admin["password_hash"]):
            raise HTTPException(status_code=401, detail="Current password is wrong")
        await admin_panel_update_password(admin["id"], _hash_password(new_password))

    return {"ok": True}


# ——— Стейкинг-контракты (адреса смарт-контрактов стейкинга) ———

@router.get("/staking-contracts")
async def list_staking_contracts(
    admin: Dict[str, Any] = Depends(_get_admin_from_bearer),
) -> List[Dict[str, Any]]:
    """Список адресов стейкинг-контрактов (для отображения в PnL и проверок)."""
    return await staking_contracts_list()


@router.post("/staking-contracts")
async def add_staking_contract(
    body: Dict[str, Any],
    admin: Dict[str, Any] = Depends(_get_admin_from_bearer),
) -> Dict[str, Any]:
    """Добавить адрес стейкинг-контракта. contract_address обязателен, label опционален."""
    address = (body.get("contract_address") or body.get("address") or "").strip()
    if not address:
        raise HTTPException(status_code=400, detail="contract_address required")
    label = (body.get("label") or "").strip() or None
    sort_order = int(body.get("sort_order", body.get("sortOrder", 0)))
    pid = await staking_contract_add(address, label=label, sort_order=sort_order)
    if pid is None:
        raise HTTPException(status_code=400, detail="Contract address already exists")
    return {"ok": True, "id": pid}


@router.delete("/staking-contracts/{contract_id}")
async def remove_staking_contract(
    contract_id: int,
    admin: Dict[str, Any] = Depends(_get_admin_from_bearer),
) -> Dict[str, Any]:
    """Удалить адрес стейкинг-контракта из списка."""
    ok = await staking_contract_delete(contract_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Contract not found")
    return {"ok": True}
