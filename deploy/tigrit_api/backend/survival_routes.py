"""
Survival MMO API:
- зоны, привязка home_zone, trust
- travel / arrivals
- лут локаций
- базы и кланы
- репорты и модерация
- серверные боевые сессии
"""
from __future__ import annotations

import json
import logging
import math
import os
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field

from tigrit_shared import db as shared_db
from loot_tables import roll_loot

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/survival", tags=["survival"])
admin_router = APIRouter(prefix="/api/admin/survival", tags=["survival-admin"])

ADMIN_KEY = os.environ.get("TIGRIT_ADMIN_API_KEY", "").strip()
BOT_TOKEN = (os.environ.get("TELEGRAM_BOT_TOKEN", "") or os.environ.get("BOT_TOKEN", "")).strip()


def _require_admin(x_admin_key: Optional[str] = Header(None, alias="X-Admin-Key")) -> None:
    if not ADMIN_KEY:
        raise HTTPException(status_code=503, detail="Admin API отключён: TIGRIT_ADMIN_API_KEY не задан")
    if not x_admin_key or x_admin_key.strip() != ADMIN_KEY:
        raise HTTPException(status_code=401, detail="Неверный X-Admin-Key")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _extract_user_id(x_user_id: Optional[str], fallback: Optional[int] = None) -> int:
    if x_user_id:
        try:
            uid = int(x_user_id)
            if uid > 0:
                return uid
        except ValueError:
            pass
    if fallback and fallback > 0:
        return int(fallback)
    raise HTTPException(status_code=401, detail="Нужен X-User-Id или user_id в теле")


async def _ensure_profile_exists(user_id: int) -> None:
    row = await shared_db.query_one("SELECT user_id FROM tigrit_user_profile WHERE user_id = $1", user_id)
    if not row:
        raise HTTPException(
            status_code=404,
            detail="Профиль не найден в tigrit_user_profile. Сначала создайте пользователя через бота.",
        )


async def _write_ledger(user_id: int, kind: str, amount: int = 0, currency: str = "PHOEX", meta: Optional[dict] = None):
    payload = json.dumps(meta or {}, ensure_ascii=False)
    try:
        await shared_db.execute(
            """
            INSERT INTO economy_ledger(user_id, kind, currency, amount, meta, created_at)
            VALUES ($1, $2, $3, $4, $5::jsonb, NOW())
            """,
            user_id,
            kind,
            currency,
            amount,
            payload,
        )
    except Exception:
        # ledger может отсутствовать в некоторых окружениях
        logger.debug("ledger skipped: kind=%s user=%s", kind, user_id)


async def _adjust_trust(user_id: int, delta: int, reason: str) -> int:
    row = await shared_db.query_one(
        """
        UPDATE tigrit_user_profile
        SET trust_score = GREATEST(-100, LEAST(100, COALESCE(trust_score, 50) + $2))
        WHERE user_id = $1
        RETURNING trust_score
        """,
        user_id,
        delta,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    try:
        await shared_db.execute(
            """
            INSERT INTO game_events(user_id, event_type, reason_code, payload, created_at)
            VALUES ($1, 'trust_change', $2, $3::jsonb, NOW())
            """,
            user_id,
            reason,
            json.dumps({"delta": delta, "reason": reason}, ensure_ascii=False),
        )
    except Exception:
        pass
    return int(row["trust_score"])


async def _deduct_phoex(user_id: int, amount: int) -> None:
    if amount <= 0:
        return
    bal = await shared_db.query_one(
        "SELECT balance FROM user_balances WHERE user_id=$1 AND currency='PHOEX'",
        user_id,
    )
    current = int((bal["balance"] if bal else 0) or 0)
    if current < amount:
        raise HTTPException(status_code=400, detail=f"Недостаточно PHOEX: нужно {amount}, доступно {current}")
    await shared_db.execute(
        "UPDATE user_balances SET balance = balance - $2, updated_at = NOW() WHERE user_id = $1 AND currency='PHOEX'",
        user_id,
        amount,
    )
    await _write_ledger(user_id, "survival_spend", -amount, "PHOEX", {"reason": "survival_action"})


async def _check_user_in_chat(chat_id: int, user_id: int) -> tuple[bool, str]:
    """Проверка membership через Telegram getChatMember."""
    if not BOT_TOKEN:
        return False, "BOT_TOKEN не задан"
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getChatMember"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(url, params={"chat_id": chat_id, "user_id": user_id})
            data = r.json()
        if not data.get("ok"):
            return False, data.get("description", "telegram api error")
        status = (data.get("result") or {}).get("status", "")
        return status in {"creator", "administrator", "member", "restricted"}, status
    except Exception as e:
        return False, str(e)


def _allocate_base_position(players_count: int) -> tuple[float, float]:
    """
    Золотой угол + растущий радиус:
    равномерная раскладка баз вокруг центра.
    """
    angle = players_count * 137.5
    radius = 3 * math.sqrt(max(players_count, 1))
    x = 50 + radius * math.cos(math.radians(angle))
    y = 50 + radius * math.sin(math.radians(angle))
    return round(x, 2), round(y, 2)


class ZoneBindPayload(BaseModel):
    zone_id: str = Field(..., min_length=1, max_length=64)
    tg_user_id: Optional[int] = None
    user_id: Optional[int] = None


class ZoneChangePayload(BaseModel):
    zone_id: str = Field(..., min_length=1, max_length=64)
    user_id: Optional[int] = None


class TravelStartPayload(BaseModel):
    to_id: str = Field(..., min_length=1, max_length=128)
    user_id: Optional[int] = None


class ArrivePayload(BaseModel):
    travel_id: int
    user_id: Optional[int] = None


class LocationLootPayload(BaseModel):
    location_id: str
    user_id: Optional[int] = None


class RespawnPayload(BaseModel):
    user_id: Optional[int] = None


class ClanCreatePayload(BaseModel):
    clan_name: str = Field(..., min_length=3, max_length=64)
    zone_id: str
    tg_chat_id: Optional[int] = None
    user_id: Optional[int] = None


class ClanJoinPayload(BaseModel):
    clan_id: int
    user_id: Optional[int] = None
    tg_user_id: Optional[int] = None


class ClanContributePayload(BaseModel):
    clan_id: int
    amount: int = Field(..., ge=1, le=1_000_000)
    user_id: Optional[int] = None


class ClanBetrayPayload(BaseModel):
    clan_id: int
    percent: int = Field(20, ge=1, le=20)
    user_id: Optional[int] = None


class ReportPayload(BaseModel):
    target_id: int
    reason: str = Field(..., min_length=3, max_length=500)
    evidence: Optional[str] = Field(None, max_length=2000)
    user_id: Optional[int] = None


class ReportResolvePayload(BaseModel):
    action: str = Field(..., pattern="^(confirm|dismiss)$")
    moderator_id: Optional[int] = None


class CombatStartPayload(BaseModel):
    defender_id: int
    location_id: Optional[str] = None
    user_id: Optional[int] = None


class CombatActionPayload(BaseModel):
    combat_id: int
    skill_id: str = Field(..., min_length=1, max_length=64)
    user_id: Optional[int] = None


@router.get("/zones")
async def survival_zones():
    rows = await shared_db.query_all(
        """
        SELECT zone_id AS id, tg_chat_id, name, type, xp_multiplier,
               entry_cost_tokens, map_x AS "mapX", map_y AS "mapY",
               active, description, bot_code
        FROM zones
        WHERE active = TRUE
        ORDER BY type, zone_id
        """
    )
    return [dict(r) for r in rows]


@router.get("/locations")
async def survival_locations():
    rows = await shared_db.query_all(
        """
        SELECT location_id, zone_id, type, name, map_x AS "mapX", map_y AS "mapY",
               energy_cost, travel_seconds, loot_table_key, active
        FROM locations
        WHERE active = TRUE
        ORDER BY location_id
        """
    )
    return [dict(r) for r in rows]


@router.post("/zone/bind")
async def survival_zone_bind(
    body: ZoneBindPayload,
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    user_id = _extract_user_id(x_user_id, body.user_id)
    tg_user_id = int(body.tg_user_id or user_id)
    await _ensure_profile_exists(user_id)

    zone = await shared_db.query_one(
        "SELECT zone_id, tg_chat_id FROM zones WHERE zone_id = $1 AND active = TRUE",
        body.zone_id,
    )
    if not zone:
        raise HTTPException(status_code=404, detail="Зона не найдена")

    current = await shared_db.query_one(
        "SELECT home_zone_id FROM tigrit_user_profile WHERE user_id = $1",
        user_id,
    )
    if current and current.get("home_zone_id"):
        raise HTTPException(status_code=409, detail={"error": "home_zone уже установлен", "home_zone_id": current["home_zone_id"]})

    if zone["tg_chat_id"]:
        ok, reason = await _check_user_in_chat(int(zone["tg_chat_id"]), tg_user_id)
        if not ok:
            raise HTTPException(status_code=403, detail={"error": "Пользователь не найден в чате зоны", "reason": reason})

    await shared_db.execute(
        """
        UPDATE tigrit_user_profile
        SET home_zone_id = $2,
            home_zone_bound_at = NOW(),
            home_zone_first_activity_at = NULL
        WHERE user_id = $1
        """,
        user_id,
        body.zone_id,
    )

    # Автовыделение базы при первой привязке
    existing_base = await shared_db.query_one("SELECT user_id FROM player_bases WHERE user_id = $1", user_id)
    if not existing_base:
        cnt = await shared_db.fetchval("SELECT COUNT(*) FROM player_bases")
        x, y = _allocate_base_position(int(cnt or 0) + 1)
        await shared_db.execute(
            "INSERT INTO player_bases (user_id, zone_id, map_x, map_y) VALUES ($1, $2, $3, $4) ON CONFLICT (user_id) DO NOTHING",
            user_id,
            body.zone_id,
            x,
            y,
        )

    await _write_ledger(user_id, "zone_bind", 0, "PHOEX", {"zone_id": body.zone_id})
    return {"ok": True, "home_zone_id": body.zone_id}


@router.post("/zone/change")
async def survival_zone_change(
    body: ZoneChangePayload,
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    user_id = _extract_user_id(x_user_id, body.user_id)
    await _ensure_profile_exists(user_id)
    row = await shared_db.query_one(
        "SELECT home_zone_id, home_zone_change_count FROM tigrit_user_profile WHERE user_id = $1",
        user_id,
    )
    if not row or not row["home_zone_id"]:
        raise HTTPException(status_code=400, detail="Сначала привяжите стартовую зону")
    if row["home_zone_id"] == body.zone_id:
        raise HTTPException(status_code=400, detail="Зона уже выбрана как домашняя")

    zone = await shared_db.query_one("SELECT zone_id FROM zones WHERE zone_id = $1 AND active = TRUE", body.zone_id)
    if not zone:
        raise HTTPException(status_code=404, detail="Зона не найдена")

    change_count = int(row["home_zone_change_count"] or 0)
    price = 100 * (change_count + 1)
    await _deduct_phoex(user_id, price)

    await shared_db.execute(
        """
        UPDATE tigrit_user_profile
        SET home_zone_id = $2,
            home_zone_change_count = COALESCE(home_zone_change_count, 0) + 1,
            home_zone_bound_at = NOW(),
            home_zone_first_activity_at = NULL
        WHERE user_id = $1
        """,
        user_id,
        body.zone_id,
    )
    await _write_ledger(user_id, "zone_change", -price, "PHOEX", {"zone_id": body.zone_id, "price": price})
    return {"ok": True, "home_zone_id": body.zone_id, "price": price}


@router.get("/player/status")
async def survival_player_status(
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    user_id: Optional[int] = Query(None),
):
    uid = _extract_user_id(x_user_id, user_id)
    await _ensure_profile_exists(uid)
    row = await shared_db.query_one(
        """
        SELECT p.user_id, p.home_zone_id, p.home_zone_bound_at, p.home_zone_first_activity_at,
               p.character_state, COALESCE(p.trust_score, 50) AS trust_score,
               p.clan_id, p.betrayal_flag, p.betrayal_expires_at,
               b.map_x AS base_x, b.map_y AS base_y, b.base_level, b.base_name
        FROM tigrit_user_profile p
        LEFT JOIN player_bases b ON b.user_id = p.user_id
        WHERE p.user_id = $1
        """,
        uid,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Профиль не найден")
    return dict(row)


@router.post("/player/respawn")
async def survival_player_respawn(
    body: RespawnPayload,
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    user_id = _extract_user_id(x_user_id, body.user_id)
    await _ensure_profile_exists(user_id)
    await _deduct_phoex(user_id, 50)
    await shared_db.execute(
        """
        UPDATE tigrit_user_profile
        SET character_state = 'alive',
            home_zone_bound_at = NOW(),
            home_zone_first_activity_at = NULL
        WHERE user_id = $1
        """,
        user_id,
    )
    await _write_ledger(user_id, "respawn", -50, "PHOEX", {"reason": "dead_boredom"})
    return {"ok": True, "respawn_price": 50}


@router.post("/travel/start")
async def survival_travel_start(
    body: TravelStartPayload,
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    user_id = _extract_user_id(x_user_id, body.user_id)
    await _ensure_profile_exists(user_id)
    active = await shared_db.query_one(
        "SELECT id FROM travels WHERE user_id = $1 AND status = 'in_progress' ORDER BY id DESC LIMIT 1",
        user_id,
    )
    if active:
        raise HTTPException(status_code=409, detail="У игрока уже есть активное путешествие")

    profile = await shared_db.query_one("SELECT trust_score FROM tigrit_user_profile WHERE user_id=$1", user_id)
    trust_score = int((profile["trust_score"] if profile else 50) or 50)

    loc = await shared_db.query_one(
        """
        SELECT location_id, travel_seconds, energy_cost, type
        FROM locations
        WHERE location_id = $1 AND active = TRUE
        """,
        body.to_id,
    )
    if not loc:
        raise HTTPException(status_code=404, detail="Локация не найдена")
    if loc["type"] == "raid_point" and trust_score < 20:
        raise HTTPException(status_code=403, detail="Недостаточный trust для рейд-локации")

    arrive_ts = _now() + timedelta(seconds=int(loc["travel_seconds"]))
    travel_id = await shared_db.fetchval(
        """
        INSERT INTO travels (user_id, from_id, to_id, start_ts, arrive_ts, status)
        VALUES ($1, COALESCE((SELECT home_zone_id FROM tigrit_user_profile WHERE user_id = $1), 'zone_1'),
                $2, NOW(), $3, 'in_progress')
        RETURNING id
        """,
        user_id,
        body.to_id,
        arrive_ts,
    )
    await _write_ledger(user_id, "travel_start", 0, "PHOEX", {"to_id": body.to_id, "energy_cost": int(loc["energy_cost"])})
    return {"ok": True, "travel_id": travel_id, "arrive_ts": arrive_ts.isoformat()}


@router.get("/travel/current")
async def survival_travel_current(
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    user_id: Optional[int] = Query(None),
):
    uid = _extract_user_id(x_user_id, user_id)
    row = await shared_db.query_one(
        """
        SELECT id, user_id, from_id, to_id, start_ts, arrive_ts, status
        FROM travels
        WHERE user_id = $1 AND status = 'in_progress'
        ORDER BY id DESC
        LIMIT 1
        """,
        uid,
    )
    return dict(row) if row else {"ok": True, "travel": None}


@router.post("/travel/arrive")
async def survival_travel_arrive(
    body: ArrivePayload,
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    user_id = _extract_user_id(x_user_id, body.user_id)
    row = await shared_db.query_one(
        "SELECT id, to_id, arrive_ts, status FROM travels WHERE id = $1 AND user_id = $2",
        body.travel_id,
        user_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Путешествие не найдено")
    if row["status"] != "in_progress":
        raise HTTPException(status_code=400, detail="Путешествие уже завершено")
    if row["arrive_ts"] > _now():
        raise HTTPException(status_code=400, detail="Ещё не время прибытия")

    await shared_db.execute("UPDATE travels SET status='arrived' WHERE id = $1", body.travel_id)
    return {"ok": True, "location_id": row["to_id"], "loot_available": True}


@router.post("/location/loot")
async def survival_location_loot(
    body: LocationLootPayload,
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    user_id = _extract_user_id(x_user_id, body.user_id)
    await _ensure_profile_exists(user_id)

    arrived = await shared_db.query_one(
        """
        SELECT id
        FROM travels
        WHERE user_id = $1
          AND to_id = $2
          AND status = 'arrived'
        ORDER BY id DESC
        LIMIT 1
        """,
        user_id,
        body.location_id,
    )
    if not arrived:
        raise HTTPException(status_code=400, detail="Сначала прибудьте в локацию")

    loc = await shared_db.query_one(
        "SELECT loot_table_key FROM locations WHERE location_id = $1 AND active = TRUE",
        body.location_id,
    )
    if not loc:
        raise HTTPException(status_code=404, detail="Локация не найдена")

    drop = roll_loot(str(loc["loot_table_key"]))
    item_key = drop["item_key"]
    qty = int(drop["qty"])

    # Пробуем записать в user_items, если таблицы item_defs/user_items доступны.
    saved_items = False
    try:
        item_def_id = await shared_db.fetchval("SELECT id FROM item_defs WHERE key = $1 LIMIT 1", item_key)
        if item_def_id:
            for _ in range(qty):
                await shared_db.execute(
                    """
                    INSERT INTO user_items (user_id, item_def_id, state, item_level, meta, acquired_at)
                    VALUES ($1, $2, 'inventory', 1, '{}'::jsonb, NOW())
                    """,
                    user_id,
                    item_def_id,
                )
            saved_items = True
    except Exception:
        saved_items = False

    await _write_ledger(
        user_id,
        "location_loot",
        qty,
        "ITEM",
        {"location_id": body.location_id, "item_key": item_key, "qty": qty},
    )
    return {"ok": True, "item_key": item_key, "qty": qty, "saved_items": saved_items}


@router.get("/bases")
async def survival_bases():
    rows = await shared_db.query_all(
        """
        SELECT b.user_id, b.zone_id, b.map_x, b.map_y, b.base_level, b.base_name,
               p.username
        FROM player_bases b
        LEFT JOIN tigrit_user_profile p ON p.user_id = b.user_id
        ORDER BY b.user_id
        """
    )
    return [dict(r) for r in rows]


@router.post("/clan/create")
async def survival_clan_create(
    body: ClanCreatePayload,
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    user_id = _extract_user_id(x_user_id, body.user_id)
    await _ensure_profile_exists(user_id)
    await _deduct_phoex(user_id, 200)
    clan_id = await shared_db.fetchval(
        """
        INSERT INTO clans (name, tg_chat_id, zone_id, treasury, created_by, created_at)
        VALUES ($1, $2, $3, 0, $4, NOW())
        RETURNING clan_id
        """,
        body.clan_name.strip(),
        body.tg_chat_id,
        body.zone_id,
        user_id,
    )
    await shared_db.execute(
        "INSERT INTO clan_members (clan_id, user_id, role) VALUES ($1, $2, 'leader') ON CONFLICT DO NOTHING",
        clan_id,
        user_id,
    )
    await shared_db.execute("UPDATE tigrit_user_profile SET clan_id=$2 WHERE user_id=$1", user_id, clan_id)
    await _write_ledger(user_id, "clan_create", -200, "PHOEX", {"clan_id": clan_id, "name": body.clan_name})
    return {"ok": True, "clan_id": clan_id}


@router.post("/clan/join")
async def survival_clan_join(
    body: ClanJoinPayload,
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    user_id = _extract_user_id(x_user_id, body.user_id)
    tg_user_id = int(body.tg_user_id or user_id)
    await _ensure_profile_exists(user_id)

    trust = await shared_db.fetchval("SELECT COALESCE(trust_score,50) FROM tigrit_user_profile WHERE user_id=$1", user_id)
    if int(trust or 50) < 0:
        raise HTTPException(status_code=403, detail="С отрицательным trust вступление в клан запрещено")

    clan = await shared_db.query_one("SELECT clan_id, tg_chat_id FROM clans WHERE clan_id = $1", body.clan_id)
    if not clan:
        raise HTTPException(status_code=404, detail="Клан не найден")

    if clan["tg_chat_id"]:
        ok, reason = await _check_user_in_chat(int(clan["tg_chat_id"]), tg_user_id)
        if not ok:
            raise HTTPException(status_code=403, detail={"error": "Пользователь не найден в чате клана", "reason": reason})

    await shared_db.execute(
        "INSERT INTO clan_members (clan_id, user_id, role) VALUES ($1, $2, 'member') ON CONFLICT DO NOTHING",
        body.clan_id,
        user_id,
    )
    await shared_db.execute("UPDATE tigrit_user_profile SET clan_id=$2 WHERE user_id=$1", user_id, body.clan_id)
    return {"ok": True, "clan_id": body.clan_id}


@router.post("/clan/contribute")
async def survival_clan_contribute(
    body: ClanContributePayload,
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    user_id = _extract_user_id(x_user_id, body.user_id)
    await _ensure_profile_exists(user_id)
    await _deduct_phoex(user_id, body.amount)
    await shared_db.execute("UPDATE clans SET treasury = treasury + $2 WHERE clan_id = $1", body.clan_id, body.amount)
    await _write_ledger(user_id, "clan_contribute", -body.amount, "PHOEX", {"clan_id": body.clan_id})
    return {"ok": True, "amount": body.amount}


@router.post("/clan/betray")
async def survival_clan_betray(
    body: ClanBetrayPayload,
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    user_id = _extract_user_id(x_user_id, body.user_id)
    await _ensure_profile_exists(user_id)
    clan = await shared_db.query_one("SELECT clan_id, treasury FROM clans WHERE clan_id=$1", body.clan_id)
    if not clan:
        raise HTTPException(status_code=404, detail="Клан не найден")

    steal = max(1, int(int(clan["treasury"] or 0) * (body.percent / 100.0)))
    await shared_db.execute("UPDATE clans SET treasury = GREATEST(0, treasury - $2) WHERE clan_id = $1", body.clan_id, steal)
    await shared_db.execute(
        """
        UPDATE tigrit_user_profile
        SET betrayal_flag = TRUE,
            betrayal_expires_at = NOW() + INTERVAL '7 days'
        WHERE user_id = $1
        """,
        user_id,
    )
    await _adjust_trust(user_id, -30, "clan_betray")
    await _write_ledger(user_id, "clan_betray", steal, "PHOEX", {"clan_id": body.clan_id, "percent": body.percent})
    return {"ok": True, "stolen": steal}


@router.get("/clan/{clan_id}")
async def survival_clan_info(clan_id: int):
    clan = await shared_db.query_one("SELECT * FROM clans WHERE clan_id = $1", clan_id)
    if not clan:
        raise HTTPException(status_code=404, detail="Клан не найден")
    members = await shared_db.query_all(
        """
        SELECT m.user_id, m.role, m.joined_at, p.username, COALESCE(p.trust_score,50) AS trust_score
        FROM clan_members m
        LEFT JOIN tigrit_user_profile p ON p.user_id = m.user_id
        WHERE m.clan_id = $1
        ORDER BY m.joined_at ASC
        """,
        clan_id,
    )
    return {"clan": dict(clan), "members": [dict(r) for r in members]}


@router.post("/report")
async def survival_report(
    body: ReportPayload,
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    reporter_id = _extract_user_id(x_user_id, body.user_id)
    await _ensure_profile_exists(reporter_id)
    report_id = await shared_db.fetchval(
        """
        INSERT INTO survival_reports (reporter_id, target_id, reason, evidence, status, created_at)
        VALUES ($1, $2, $3, $4, 'pending', NOW())
        RETURNING id
        """,
        reporter_id,
        body.target_id,
        body.reason.strip(),
        (body.evidence or "").strip() or None,
    )
    return {"ok": True, "report_id": report_id}


@admin_router.get("/reports", dependencies=[Depends(_require_admin)])
async def survival_admin_reports(status: str = Query("pending", max_length=32), limit: int = Query(100, ge=1, le=500)):
    rows = await shared_db.query_all(
        """
        SELECT id, reporter_id, target_id, reason, evidence, status, moderator_id, resolved_at, created_at
        FROM survival_reports
        WHERE ($1 = '' OR status = $1)
        ORDER BY created_at DESC
        LIMIT $2
        """,
        status.strip(),
        limit,
    )
    return [dict(r) for r in rows]


@admin_router.patch("/reports/{report_id}", dependencies=[Depends(_require_admin)])
async def survival_admin_report_resolve(report_id: int, body: ReportResolvePayload):
    row = await shared_db.query_one(
        "SELECT id, target_id, status FROM survival_reports WHERE id = $1",
        report_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="report not found")
    if row["status"] != "pending":
        raise HTTPException(status_code=400, detail="report already resolved")

    new_status = "confirmed" if body.action == "confirm" else "dismissed"
    await shared_db.execute(
        """
        UPDATE survival_reports
        SET status=$2, moderator_id=$3, resolved_at=NOW()
        WHERE id=$1
        """,
        report_id,
        new_status,
        body.moderator_id,
    )
    if body.action == "confirm":
        trust = await _adjust_trust(int(row["target_id"]), -20, "report_confirmed")
        return {"ok": True, "status": new_status, "target_trust": trust}
    return {"ok": True, "status": new_status}


@router.post("/combat/start")
async def survival_combat_start(
    body: CombatStartPayload,
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    attacker_id = _extract_user_id(x_user_id, body.user_id)
    await _ensure_profile_exists(attacker_id)
    await _ensure_profile_exists(body.defender_id)
    if attacker_id == body.defender_id:
        raise HTTPException(status_code=400, detail="Нельзя атаковать себя")
    combat_id = await shared_db.fetchval(
        """
        INSERT INTO combat_sessions (attacker_id, defender_id, location_id, attacker_hp, defender_hp, status, started_at)
        VALUES ($1, $2, $3, 100, 100, 'active', NOW())
        RETURNING id
        """,
        attacker_id,
        body.defender_id,
        body.location_id,
    )
    return {"ok": True, "combat_id": combat_id, "attacker_hp": 100, "defender_hp": 100}


@router.post("/combat/action")
async def survival_combat_action(
    body: CombatActionPayload,
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    user_id = _extract_user_id(x_user_id, body.user_id)
    session = await shared_db.query_one(
        """
        SELECT id, attacker_id, defender_id, attacker_hp, defender_hp, status
        FROM combat_sessions
        WHERE id = $1
        """,
        body.combat_id,
    )
    if not session:
        raise HTTPException(status_code=404, detail="Combat session not found")
    if session["status"] != "active":
        raise HTTPException(status_code=400, detail="Combat session already ended")
    if user_id not in (session["attacker_id"], session["defender_id"]):
        raise HTTPException(status_code=403, detail="Доступ к этой боевой сессии запрещён")

    base_damage = {"attack": 14, "dash": 8, "heal": -12}.get(body.skill_id, 10)
    roll = random.uniform(0.9, 1.1)
    delta = int(round(base_damage * roll))

    attacker_hp = int(session["attacker_hp"])
    defender_hp = int(session["defender_hp"])
    actor_is_attacker = user_id == session["attacker_id"]

    if body.skill_id == "heal":
        if actor_is_attacker:
            attacker_hp = min(100, attacker_hp - delta)  # delta отрицательный
        else:
            defender_hp = min(100, defender_hp - delta)
        log_entry = "Лечение"
    else:
        if actor_is_attacker:
            defender_hp = max(0, defender_hp - max(delta, 1))
        else:
            attacker_hp = max(0, attacker_hp - max(delta, 1))
        log_entry = f"Удар {body.skill_id}"

    status = "active"
    ended_at = None
    if attacker_hp <= 0 or defender_hp <= 0:
        status = "finished"
        ended_at = _now()

    await shared_db.execute(
        """
        UPDATE combat_sessions
        SET attacker_hp=$2, defender_hp=$3, status=$4, ended_at=$5
        WHERE id=$1
        """,
        body.combat_id,
        attacker_hp,
        defender_hp,
        status,
        ended_at,
    )
    return {
        "ok": True,
        "attacker_hp": attacker_hp,
        "defender_hp": defender_hp,
        "status": status,
        "log_entry": log_entry,
    }


@router.get("/telegram/health")
async def survival_telegram_health():
    """
    Проверка telegram-инфраструктуры:
    - есть ли BOT_TOKEN
    - бот админ в чатах зон с tg_chat_id
    """
    zones = await shared_db.query_all(
        "SELECT zone_id, name, tg_chat_id FROM zones WHERE active=TRUE ORDER BY zone_id"
    )
    report = []
    for z in zones:
        item = {"zone_id": z["zone_id"], "name": z["name"], "tg_chat_id": z["tg_chat_id"], "ok": None, "reason": None}
        if not z["tg_chat_id"]:
            item["ok"] = None
            item["reason"] = "no_tg_chat_id"
            report.append(item)
            continue
        if not BOT_TOKEN:
            item["ok"] = False
            item["reason"] = "BOT_TOKEN not set"
            report.append(item)
            continue
        try:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/getChatMember"
            bot_id = BOT_TOKEN.split(":")[0]
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(url, params={"chat_id": int(z["tg_chat_id"]), "user_id": int(bot_id)})
                data = r.json()
            if not data.get("ok"):
                item["ok"] = False
                item["reason"] = data.get("description", "telegram api error")
            else:
                status = (data.get("result") or {}).get("status", "")
                item["ok"] = status in {"administrator", "creator"}
                item["reason"] = status
        except Exception as e:
            item["ok"] = False
            item["reason"] = str(e)
        report.append(item)
    return {"ok": True, "bot_token_configured": bool(BOT_TOKEN), "zones": report}
