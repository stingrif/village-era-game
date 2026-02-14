"""
Крафт: merge, upgrade, reroll по 05_Крафт_и_слияние (схема B: COINS + STARS).
"""
import json
import random
from typing import Any, Dict, List, Optional

from infrastructure.database import (
    add_user_item,
    deduct_balance,
    ensure_balance_row,
    get_item_def_id_by_key,
    get_item_def_ids_by_rarity,
    get_user_buildings,
    get_user_balances,
    record_item_event,
)


# Схема B: стоимость и шансы
MERGE3_COINS = 900
MERGE3_STARS = 1800
MERGE3_NORMAL = 0.80
MERGE3_UP = 0.17
MERGE3_BREAK = 0.03

UPGRADE_COINS = 1200
UPGRADE_STARS = 2500
UPGRADE_SUCCESS = 0.75
UPGRADE_SAME = 0.20
UPGRADE_BREAK = 0.05

REROLL_COINS = 500
REROLL_STARS = 500
REROLL_SUCCESS = 0.85
REROLL_BREAK = 0.15


async def _get_item(user_id: int, item_id: int) -> Optional[Dict[str, Any]]:
    from infrastructure.database import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT ui.id, ui.user_id, ui.item_def_id, ui.state, ui.item_level, ui.meta,
                      id.rarity, id.item_type, id.key AS item_key, id.subtype
               FROM user_items ui JOIN item_defs id ON id.id = ui.item_def_id
               WHERE ui.user_id = $1 AND ui.id = $2 AND ui.state = 'inventory'""",
            user_id, item_id,
        )
    if not row:
        return None
    return dict(row)


async def _delete_item(item_id: int) -> None:
    from infrastructure.database import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM user_items WHERE id = $1", item_id)


async def _log_craft(
    user_id: int, action: str, input_ids: List[int],
    output_item_id: Optional[int], dust_spent: int, result: Dict[str, Any],
) -> None:
    from infrastructure.database import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO crafting_log (user_id, action, input_item_ids, output_item_id, dust_spent, result_json)
               VALUES ($1, $2, $3, $4, $5, $6)""",
            user_id, action, input_ids, output_item_id, dust_spent, json.dumps(result),
        )


async def craft_merge(user_id: int, item_ids: List[int]) -> Dict[str, Any]:
    """
    Merge 3 реликвий одного типа. Стоимость 900 COINS + 1800 STARS.
    Результат: 80% обычный, 17% +1 уровень, 3% слом.
    """
    if len(item_ids) != 3:
        return {"ok": False, "error": "need_3_items"}
    await ensure_balance_row(user_id, "COINS")
    await ensure_balance_row(user_id, "STARS")
    balances = await get_user_balances(user_id)
    if balances.get("COINS", 0) < MERGE3_COINS or balances.get("STARS", 0) < MERGE3_STARS:
        return {"ok": False, "error": "insufficient_balance"}
    items = [await _get_item(user_id, iid) for iid in item_ids]
    if any(x is None for x in items):
        return {"ok": False, "error": "item_not_found"}
    rarities = [x["rarity"] for x in items]
    if len(set(rarities)) != 1:
        return {"ok": False, "error": "same_type_required"}
    rarity = rarities[0]
    avg_level = sum(x["item_level"] for x in items) // 3
    await deduct_balance(user_id, "COINS", MERGE3_COINS)
    await deduct_balance(user_id, "STARS", MERGE3_STARS)
    for it in items:
        await record_item_event(it["item_def_id"], "merge_input", user_id, 1, ref_type="craft", ref_id=it["id"])
    for iid in item_ids:
        await _delete_item(iid)
    r = random.random()
    if r < MERGE3_BREAK:
        for it in items:
            await record_item_event(it["item_def_id"], "merge_break", user_id, 1)
        await _log_craft(user_id, "merge", item_ids, None, MERGE3_COINS + MERGE3_STARS, {"result": "break"})
        return {"ok": True, "result": "break", "output_item_id": None}
    new_level = avg_level if r < MERGE3_NORMAL else min(5, avg_level + 1)
    if r >= MERGE3_NORMAL + MERGE3_UP:
        new_level = min(5, avg_level + 2)
    def_ids = await get_item_def_ids_by_rarity(rarity)
    if not def_ids:
        for it in items:
            await record_item_event(it["item_def_id"], "merge_break", user_id, 1)
        await _log_craft(user_id, "merge", item_ids, None, MERGE3_COINS + MERGE3_STARS, {"result": "break"})
        return {"ok": True, "result": "break", "output_item_id": None}
    new_item_def_id = random.choice(def_ids)
    new_id = await add_user_item(user_id, new_item_def_id, item_level=new_level)
    await record_item_event(new_item_def_id, "merge_output", user_id, 1, ref_type="craft", ref_id=new_id)
    await _log_craft(user_id, "merge", item_ids, new_id, MERGE3_COINS + MERGE3_STARS, {"result": "ok", "level": new_level})
    return {"ok": True, "result": "ok", "output_item_id": new_id, "level": new_level}


async def craft_upgrade(user_id: int, item_id: int) -> Dict[str, Any]:
    """Upgrade 1 предмет. Стоимость 1200 COINS + 2500 STARS. 75% +1, 20% без изменений, 5% слом."""
    await ensure_balance_row(user_id, "COINS")
    await ensure_balance_row(user_id, "STARS")
    balances = await get_user_balances(user_id)
    if balances.get("COINS", 0) < UPGRADE_COINS or balances.get("STARS", 0) < UPGRADE_STARS:
        return {"ok": False, "error": "insufficient_balance"}
    item = await _get_item(user_id, item_id)
    if not item:
        return {"ok": False, "error": "item_not_found"}
    level = item["item_level"]
    if level >= 5:
        return {"ok": False, "error": "max_level"}
    await deduct_balance(user_id, "COINS", UPGRADE_COINS)
    await deduct_balance(user_id, "STARS", UPGRADE_STARS)
    await record_item_event(item["item_def_id"], "upgrade_input", user_id, 1, ref_type="craft", ref_id=item_id)
    r = random.random()
    if r < UPGRADE_BREAK:
        await _delete_item(item_id)
        await record_item_event(item["item_def_id"], "upgrade_break", user_id, 1)
        await _log_craft(user_id, "upgrade", [item_id], None, UPGRADE_COINS + UPGRADE_STARS, {"result": "break"})
        return {"ok": True, "result": "break", "output_item_id": None}
    if r < UPGRADE_SUCCESS + UPGRADE_BREAK:
        from infrastructure.database import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE user_items SET item_level = item_level + 1 WHERE id = $1",
                item_id,
            )
        await record_item_event(item["item_def_id"], "upgrade_ok", user_id, 1)
        await _log_craft(user_id, "upgrade", [item_id], item_id, UPGRADE_COINS + UPGRADE_STARS, {"result": "ok", "level": level + 1})
        return {"ok": True, "result": "ok", "output_item_id": item_id, "level": level + 1}
    await _log_craft(user_id, "upgrade", [item_id], item_id, UPGRADE_COINS + UPGRADE_STARS, {"result": "same"})
    return {"ok": True, "result": "same", "output_item_id": item_id, "level": level}


async def craft_reroll(user_id: int, item_id: int) -> Dict[str, Any]:
    """Reroll: новый эффект 85%, поломка 15%. Стоимость 500 COINS + 500 STARS."""
    await ensure_balance_row(user_id, "COINS")
    await ensure_balance_row(user_id, "STARS")
    balances = await get_user_balances(user_id)
    if balances.get("COINS", 0) < REROLL_COINS or balances.get("STARS", 0) < REROLL_STARS:
        return {"ok": False, "error": "insufficient_balance"}
    item = await _get_item(user_id, item_id)
    if not item:
        return {"ok": False, "error": "item_not_found"}
    await deduct_balance(user_id, "COINS", REROLL_COINS)
    await deduct_balance(user_id, "STARS", REROLL_STARS)
    await record_item_event(item["item_def_id"], "reroll_input", user_id, 1, ref_type="craft", ref_id=item_id)
    r = random.random()
    if r < REROLL_BREAK:
        await _delete_item(item_id)
        await record_item_event(item["item_def_id"], "reroll_break", user_id, 1)
        await _log_craft(user_id, "reroll", [item_id], None, REROLL_COINS + REROLL_STARS, {"result": "break"})
        return {"ok": True, "result": "break", "output_item_id": None}
    await record_item_event(item["item_def_id"], "reroll_ok", user_id, 1)
    await _log_craft(user_id, "reroll", [item_id], item_id, REROLL_COINS + REROLL_STARS, {"result": "ok"})
    return {"ok": True, "result": "ok", "output_item_id": item_id}


async def craft_furnace_upgrade(
    user_id: int,
    furnace_item_id_1: int,
    furnace_item_id_2: int,
    extra_item_id: int,
    ad_watched: bool = False,
) -> Dict[str, Any]:
    """
    Апгрейд печки в мастерской: 2 печки одного цвета + 1 любой предмет + просмотр рекламы.
    Результат: 1 печка того же цвета с улучшенным шансом (meta improved).
    """
    buildings = await get_user_buildings(user_id)
    if "workshop" not in buildings:
        return {"ok": False, "error": "workshop_required"}
    if not ad_watched:
        return {"ok": False, "error": "ad_watched_required"}
    f1 = await _get_item(user_id, furnace_item_id_1)
    f2 = await _get_item(user_id, furnace_item_id_2)
    extra = await _get_item(user_id, extra_item_id)
    if not f1 or not f2 or not extra:
        return {"ok": False, "error": "item_not_found"}
    if f1["item_type"] != "furnace" or f2["item_type"] != "furnace":
        return {"ok": False, "error": "need_two_furnaces"}
    if f1["item_def_id"] != f2["item_def_id"]:
        return {"ok": False, "error": "same_furnace_color_required"}
    color = f1.get("subtype") or (f1.get("item_key") or "").replace("furnace_", "")
    for iid in (furnace_item_id_1, furnace_item_id_2, extra_item_id):
        await _delete_item(iid)
    meta = {"improved": True}
    new_id = await add_user_item(user_id, f1["item_def_id"], item_level=1, meta=meta)
    await _log_craft(
        user_id, "furnace_upgrade",
        [furnace_item_id_1, furnace_item_id_2, extra_item_id],
        new_id, 0, {"color": color, "improved": True},
    )
    return {"ok": True, "result": "ok", "output_item_id": new_id, "furnace_color": color}
