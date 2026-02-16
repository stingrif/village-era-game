"""
Чекин и шахта по 03_Шахта_и_яйца.md, 18_Dev, 25_Архитектура.
- checkin: раз в 10 ч → 3 попытки.
- mine_create: сессия 6×6, 2–6 призовых ячеек по распределению.
- mine_dig: списание попытки, открытие ячейки, дроп (монеты/приз).
"""
import random
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

from config import CHECKIN_RULES, get_mine_config
from infrastructure.database import (
    add_coins_ledger,
    add_currency_credit,
    add_player_egg,
    add_user_item,
    consume_attempt,
    create_mine_session,
    ensure_user,
    get_and_consume_furnace_bonus,
    get_attempts,
    get_checkin_state,
    get_item_def_id_by_key,
    get_item_def_ids_by_rarity,
    get_mine_session,
    get_setting,
    mark_cell_opened,
    pick_egg_color_by_weight,
    record_dig_log,
    record_item_event,
    update_checkin_state,
)


def _next_checkin_at(base_cd_minutes: int, min_cd_minutes: int, bonus_minutes: int = 0) -> datetime:
    effective = max(min_cd_minutes, base_cd_minutes - bonus_minutes)
    return datetime.now(timezone.utc) + timedelta(minutes=effective)


async def do_checkin(telegram_id: int, source: str = "app") -> Dict[str, Any]:
    """
    Выполняет чекин: если cooldown прошёл — начисляет попытки, обновляет next_checkin_at.
    source: "app" — чекин из приложения (с рекламой) → 3 попытки; "chat" — по команде модератора (Голос/ vote/ checkin) → 2 попытки.
    """
    user_id = await ensure_user(telegram_id)
    state = await get_checkin_state(user_id)
    cooldown_hours = await get_setting("checkin.cooldown_hours", CHECKIN_RULES.get("baseCdMinutes", 600) / 60)
    base_cd = int(float(cooldown_hours) * 60)
    min_cd = int(base_cd * 0.9)
    if source == "chat":
        granted = await get_setting("checkin.attempts_per_claim_chat", 2)
    else:
        granted = await get_setting("checkin.attempts_per_claim", CHECKIN_RULES.get("grantedAttempts", 3))

    now = datetime.now(timezone.utc)
    next_at = None
    if state and state.get("next_checkin_at"):
        try:
            next_at = datetime.fromisoformat(state["next_checkin_at"].replace("Z", "+00:00"))
        except Exception:
            pass

    if next_at and now < next_at:
        return {
            "ok": False,
            "granted_attempts": 0,
            "next_checkin_at": state["next_checkin_at"],
            "attempts_balance": await get_attempts(user_id),
            "message": "cooldown",
        }

    bonus = 0  # TODO: из user_profile.checkin_cd_bonus_minutes и рекламы
    effective_cd = max(min_cd, base_cd - bonus)
    next_checkin = _next_checkin_at(base_cd, min_cd, bonus)

    await update_checkin_state(
        user_id,
        granted_attempts=granted,
        next_checkin_at=next_checkin,
        base_cd_minutes=base_cd,
        bonus_minutes_used=bonus,
        effective_cd_minutes=effective_cd,
    )
    balance = await get_attempts(user_id)

    return {
        "ok": True,
        "granted_attempts": granted,
        "next_checkin_at": next_checkin.isoformat(),
        "attempts_balance": balance,
        "message": "ok",
    }


def _pick_prize_cells_count(dist: List[Dict[str, Any]]) -> int:
    """Выбирает количество призовых ячеек по prizeCellsDistribution."""
    if not dist:
        return random.randint(2, 6)
    r = random.random() * 100
    for entry in dist:
        r -= entry.get("chancePct", 0)
        if r <= 0:
            return entry.get("cells", 3)
    return dist[-1].get("cells", 4)


def _build_prize_cells(grid_size: int, count: int, seed: Optional[int] = None) -> List[int]:
    if seed is not None:
        random.seed(seed)
    indices = list(range(grid_size))
    random.shuffle(indices)
    return sorted(indices[:count])


async def do_mine_create(telegram_id: int) -> Dict[str, Any]:
    """
    Создаёт новую сессию шахты с призовыми ячейками по конфигу.
    Uses runtime settings from game_settings table, falls back to game_config.json.
    """
    user_id = await ensure_user(telegram_id)
    grid_size = await get_setting("mine.grid_size", get_mine_config().get("gridSize", 36))
    dist = await get_setting("mine.prize_cells_distribution", get_mine_config().get("prizeCellsDistribution", []))
    prize_count = _pick_prize_cells_count(dist)
    seed = int(time.time() * 1000) + telegram_id
    prize_cells = _build_prize_cells(grid_size, prize_count, seed)
    mine_id = await create_mine_session(user_id, prize_cells, seed)
    return {
        "ok": True,
        "mine_id": mine_id,
        "grid_size": grid_size,
        "prize_count": len(prize_cells),
    }


def _roll_prize_loot(loot_cfg: Dict[str, float]) -> str:
    """Возвращает тип дропа: relic, amulet, coins, egg, project_tokens, furnace (по prizeCellLoot)."""
    cfg = loot_cfg or {}
    pairs = [
        ("relic", cfg.get("relicPct", 65)),
        ("amulet", cfg.get("amuletPct", 14)),
        ("coins", cfg.get("coinsPct", 10)),
        ("egg", cfg.get("eggPct", 0.8)),
        ("project_tokens", cfg.get("projectTokensPct", 5)),
        ("furnace", cfg.get("furnacePct", 5.2)),
    ]
    r = random.random() * 100
    for k, pct in pairs:
        r -= float(pct)
        if r <= 0:
            return k
    return "coins"


def _tokens_amount_roll() -> int:
    """Количество STARS за дроп: 1–5000, крупные реже."""
    r = random.random() * 100
    if r < 50:
        return random.randint(1, 10)
    if r < 80:
        return random.randint(11, 100)
    if r < 95:
        return random.randint(101, 500)
    if r < 99:
        return random.randint(501, 1500)
    return random.randint(1501, 5000)


FURNACE_COLORS = ["red", "green", "blue", "yellow", "purple", "black"]


def _coins_by_rarity() -> int:
    """Монеты за призовую ячейку (упрощённо по редкости)."""
    return random.randint(10, 50)


# Редкости в призовой ячейке по 03: Fire 50%, Yin 26%, Yan 15%, Tsy 8%, Magic 1%, Epic 0.1%
RARITY_WEIGHTS: List[Tuple[str, float]] = [
    ("FIRE", 50.0),
    ("YIN", 26.0),
    ("YAN", 15.0),
    ("TSY", 8.0),
    ("MAGIC", 1.0),
    ("EPIC", 0.1),
]


def _roll_relic_rarity() -> str:
    r = random.random() * 100
    for rarity, pct in RARITY_WEIGHTS:
        r -= pct
        if r <= 0:
            return rarity
    return "FIRE"


async def do_mine_dig(
    telegram_id: int,
    mine_id: int,
    cell_index: int,
    attempt_source: str = "checkin",
    ip_hash: Optional[str] = None,
    device_hash: Optional[str] = None,
    vpn_flag: Optional[bool] = None,
) -> Dict[str, Any]:
    """
    Копает ячейку: списывает попытку, открывает ячейку.
    Если призовая — дроп по prizeCellLoot (relic/amulet/coins/egg); иначе пусто.
    Возвращает { "ok": bool, "prize_hit": bool, "drop_type": str, "coins_drop": int, "message": str }.
    """
    user_id = await ensure_user(telegram_id)
    session = await get_mine_session(mine_id, user_id)
    if not session:
        return {"ok": False, "prize_hit": False, "drop_type": "none", "coins_drop": 0, "message": "mine_not_found", "opened_cells": []}

    if cell_index < 0 or cell_index >= session["grid_size"]:
        return {"ok": False, "prize_hit": False, "drop_type": "none", "coins_drop": 0, "message": "invalid_cell", "opened_cells": list(session["opened_cells"])}

    if cell_index in session["opened_cells"]:
        return {"ok": False, "prize_hit": False, "drop_type": "none", "coins_drop": 0, "message": "already_opened", "opened_cells": list(session["opened_cells"])}

    consumed = await consume_attempt(user_id)
    if not consumed:
        return {"ok": False, "prize_hit": False, "drop_type": "none", "coins_drop": 0, "message": "no_attempts", "opened_cells": list(session["opened_cells"])}

    prize_cells = session["prize_cells"]
    prize_hit = cell_index in prize_cells
    drop_type = "none"
    coins_drop = 0
    stars_drop = 0
    furnace_key: Optional[str] = None
    drop_item_def_id: Optional[int] = None
    drop_rarity: Optional[str] = None
    egg_hit = False

    if prize_hit:
        loot_cfg = await get_setting("mine.prize_loot") or get_mine_config().get("prizeCellLoot") or {"relicPct": 72, "amuletPct": 15, "coinsPct": 12.1, "eggPct": 0.9}
        drop_type = _roll_prize_loot(loot_cfg)
        if drop_type == "coins":
            coins_drop = _coins_by_rarity()
            await add_coins_ledger(user_id, coins_drop, "mine_dig", ref_id=str(mine_id))
        elif drop_type == "relic" or drop_type == "amulet":
            rarity = _roll_relic_rarity()
            ids = await get_item_def_ids_by_rarity(rarity)
            if ids:
                item_def_id = random.choice(ids)
                await add_user_item(user_id, item_def_id, item_level=1)
                await record_item_event(item_def_id, "drop", user_id, 1, ref_type="mine_dig", ref_id=mine_id)
                drop_item_def_id = item_def_id
                drop_rarity = rarity
        elif drop_type == "egg":
            color = await pick_egg_color_by_weight()
            if color:
                await add_player_egg(user_id, color)
                egg_hit = True
        elif drop_type == "project_tokens":
            stars_amount = _tokens_amount_roll()
            stars_drop = stars_amount
            await add_currency_credit(user_id, "STARS", stars_amount, "mine_dig", str(mine_id))
        elif drop_type == "furnace":
            color = random.choice(FURNACE_COLORS)
            furnace_key = f"furnace_{color}"
            furnace_def_id = await get_item_def_id_by_key(furnace_key)
            if furnace_def_id:
                improved = await get_and_consume_furnace_bonus(user_id)
                meta = {"improved": True} if improved else None
                await add_user_item(user_id, furnace_def_id, item_level=1, meta=meta)
                await record_item_event(furnace_def_id, "drop", user_id, 1, ref_type="mine_dig", ref_id=mine_id)
                drop_item_def_id = furnace_def_id
                drop_rarity = "common"

    await mark_cell_opened(mine_id, user_id, cell_index)
    await record_dig_log(
        user_id,
        mine_id,
        cell_index,
        attempt_source,
        prize_hit,
        coins_drop,
        drop_item_def_id=drop_item_def_id,
        drop_rarity=drop_rarity,
        egg_hit=egg_hit,
        ip_hash=ip_hash,
        device_hash=device_hash,
        vpn_flag=vpn_flag,
    )

    balance = await get_attempts(user_id)
    opened_cells = list(session["opened_cells"]) + [cell_index]
    return {
        "ok": True,
        "prize_hit": prize_hit,
        "drop_type": drop_type,
        "coins_drop": coins_drop,
        "stars_drop": stars_drop,
        "furnace_key": furnace_key,
        "drop_item_def_id": drop_item_def_id,
        "drop_rarity": drop_rarity,
        "egg_hit": egg_hit,
        "attempts_balance": balance,
        "message": "ok",
        "opened_cells": opened_cells,
    }
