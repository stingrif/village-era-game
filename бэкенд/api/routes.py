import logging
import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, Header, HTTPException, Request

from config import (
    get_eggs_config,
    get_field_config,
    get_mine_config,
    MIN_ACCOUNT_AGE_DAYS_FOR_PHOENIX_QUEST,
    MIN_BURN_COUNT_FOR_PHOENIX_QUEST,
    PHOENIX_QUEST_REWARD_AMOUNT,
    PHOENIX_QUEST_SUBMIT_RATE_LIMIT_SEC,
)
from core.checkin_mine import do_checkin, do_mine_create, do_mine_dig
from core.craft import craft_merge, craft_reroll, craft_upgrade
from core.game_engine import (
    apply_burn,
    apply_buy_diamonds_points,
    apply_collect,
    apply_phoenix_quest,
    apply_sell,
    get_default_state,
    validate_phoenix_sequence,
)
from infrastructure.cache import cache_get, cache_set
from infrastructure.database import (
    accept_trade_offer as db_accept_trade_offer,
    add_pending_payout,
    admin_get_page_texts,
    admin_get_partner_tokens,
    admin_get_tasks,
    cancel_market_order,
    cancel_trade_offer,
    collect_income,
    create_market_order,
    create_trade_offer,
    ensure_user,
    equip_relic,
    fill_market_order_coins,
    get_attempts,
    get_buildings_def,
    get_building_slots,
    get_checkin_state,
    get_market_orders_open,
    get_mine_session,
    get_player_critical,
    get_player_field,
    get_state,
    get_user_balances,
    get_user_inventory,
    get_withdraw_eligibility,
    get_leaderboards,
    get_staking_sessions,
    set_state,
    demolish_building,
    donate_to_profile,
    place_building,
    record_ad_view,
    unequip_relic,
    upgrade_building,
)
from infrastructure.telegram_notify import notify_admin_phoenix_quest

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/game", tags=["game"])

# Rate-limit: last submit time per telegram_id
_phoenix_submit_last: Dict[int, float] = {}


def _get_telegram_id(
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
) -> int:
    tid = x_telegram_user_id or x_user_id
    if not tid:
        raise HTTPException(status_code=401, detail="X-Telegram-User-Id or X-User-Id required")
    try:
        return int(tid)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user id")


def _account_age_days(created_at) -> int:
    if created_at is None:
        return 0
    delta = time.time() - created_at.timestamp()
    return max(0, int(delta / 86400))


@router.get("/state")
async def game_get_state(
    request: Request,
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    telegram_id = _get_telegram_id(x_telegram_user_id, x_user_id)
    cache_key = f"game_state:{telegram_id}"
    state = await cache_get(cache_key)
    if state is None:
        state = await get_state(telegram_id)
    if state is None:
        state = get_default_state()
        await set_state(telegram_id, state)
        await cache_set(cache_key, state)
    return state


@router.post("/action")
async def game_action(
    request: Request,
    body: Dict[str, Any],
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    telegram_id = _get_telegram_id(x_telegram_user_id, x_user_id)
    action = body.get("action")
    params = body.get("params") or {}
    cache_key = f"game_state:{telegram_id}"

    state = await cache_get(cache_key)
    if state is None:
        state = await get_state(telegram_id)
    if state is None:
        state = get_default_state()

    username = params.get("username") or ""
    first_name = params.get("first_name") or ""

    if action == "collect":
        state = apply_collect(state)
    elif action == "burn":
        state = apply_burn(state, params.get("relic_idx", -1))
    elif action == "phoenix_quest_submit":
        # Валидация только на сервере: последовательность букв + условия награды
        letters_sequence = params.get("letters_sequence")
        if not validate_phoenix_sequence(letters_sequence):
            raise HTTPException(status_code=400, detail="Invalid letters sequence")
        critical = await get_player_critical(telegram_id)
        if critical is None:
            critical = {
                "phoenix_quest_completed": state.get("phoenixQuestCompleted", False),
                "burned_count": state.get("burnedCount", 0),
                "created_at": None,
            }
        if critical["phoenix_quest_completed"]:
            pass  # уже выполнен, state не меняем
        else:
            now = time.time()
            last = _phoenix_submit_last.get(telegram_id, 0)
            if now - last < PHOENIX_QUEST_SUBMIT_RATE_LIMIT_SEC:
                raise HTTPException(
                    status_code=429,
                    detail="Rate limit: try again later",
                )
            _phoenix_submit_last[telegram_id] = now
            burn_ok = critical["burned_count"] >= MIN_BURN_COUNT_FOR_PHOENIX_QUEST
            age_days = _account_age_days(critical.get("created_at"))
            age_ok = age_days >= MIN_ACCOUNT_AGE_DAYS_FOR_PHOENIX_QUEST
            if not (burn_ok and age_ok):
                raise HTTPException(
                    status_code=403,
                    detail=f"Requires min {MIN_BURN_COUNT_FOR_PHOENIX_QUEST} burns and {MIN_ACCOUNT_AGE_DAYS_FOR_PHOENIX_QUEST} days account age",
                )
            state = apply_phoenix_quest(state)
            await add_pending_payout(telegram_id, "phoenix_quest", PHOENIX_QUEST_REWARD_AMOUNT)
            await notify_admin_phoenix_quest(
                telegram_id,
                username=username or None,
                first_name=first_name or None,
                reward_amount=PHOENIX_QUEST_REWARD_AMOUNT,
            )
    elif action == "buy_diamonds_points":
        state = apply_buy_diamonds_points(state, params.get("pack_idx", -1))
    elif action == "sell":
        state = apply_sell(state, params.get("relic_idx", -1))
    elif action == "sync":
        client_state = body.get("state")
        if isinstance(client_state, dict):
            critical = await get_player_critical(telegram_id)
            if critical is not None:
                client_state["phoenixQuestCompleted"] = critical["phoenix_quest_completed"]
                client_state["burnedCount"] = critical["burned_count"]
                client_state["points"] = critical["points_balance"]
            state = client_state
    else:
        client_state = body.get("state")
        if isinstance(client_state, dict):
            critical = await get_player_critical(telegram_id)
            if critical is not None:
                client_state["phoenixQuestCompleted"] = critical["phoenix_quest_completed"]
                client_state["burnedCount"] = critical["burned_count"]
                client_state["points"] = critical["points_balance"]
            state = client_state

    await set_state(telegram_id, state, username=username, first_name=first_name)
    await cache_set(cache_key, state)
    return state


# ——— API по 25_Архитектура: конфиг, чекин, шахта ———

@router.get("/config")
async def game_config():
    """Публичный конфиг игры: field, mine, eggs (15_Карта_меню_и_UI, 18_Dev)."""
    return {
        "field": get_field_config(),
        "mine": get_mine_config(),
        "eggs": get_eggs_config(),
    }


@router.post("/checkin")
async def api_checkin(
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    """Чекин: раз в 10 ч даёт 3 попытки шахты (03_Шахта_и_яйца, 18_Dev)."""
    telegram_id = _get_telegram_id(x_telegram_user_id, x_user_id)
    return await do_checkin(telegram_id)


@router.get("/checkin-state")
async def api_checkin_state(
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    """Состояние чекина: next_checkin_at, streak."""
    telegram_id = _get_telegram_id(x_telegram_user_id, x_user_id)
    user_id = await ensure_user(telegram_id)
    state = await get_checkin_state(user_id)
    if state is None:
        return {"next_checkin_at": None, "streak": 0}
    return state


@router.get("/attempts")
async def api_attempts(
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    """Текущий баланс попыток копания."""
    telegram_id = _get_telegram_id(x_telegram_user_id, x_user_id)
    user_id = await ensure_user(telegram_id)
    attempts = await get_attempts(user_id)
    return {"attempts": attempts}


@router.post("/mine/create")
async def api_mine_create(
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    """Создать новую сессию шахты 6×6 с призовыми ячейками."""
    telegram_id = _get_telegram_id(x_telegram_user_id, x_user_id)
    return await do_mine_create(telegram_id)


@router.get("/balances")
async def api_balances(
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    """Балансы по валютам (COINS, STARS, DIAMONDS)."""
    telegram_id = _get_telegram_id(x_telegram_user_id, x_user_id)
    user_id = await ensure_user(telegram_id)
    balances = await get_user_balances(user_id)
    return {"balances": balances}


@router.get("/inventory")
async def api_inventory(
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    """Инвентарь: предметы (реликвии, амулеты и т.д.) и яйца."""
    telegram_id = _get_telegram_id(x_telegram_user_id, x_user_id)
    user_id = await ensure_user(telegram_id)
    return await get_user_inventory(user_id)


@router.post("/mine/dig")
async def api_mine_dig(
    body: Dict[str, Any],
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    """Копать ячейку: mine_id, cell_index (0..35). Опционально: ip_hash, device_hash, vpn_flag."""
    telegram_id = _get_telegram_id(x_telegram_user_id, x_user_id)
    mine_id = body.get("mine_id")
    cell_index = body.get("cell_index", -1)
    if mine_id is None:
        raise HTTPException(status_code=400, detail="mine_id required")
    try:
        mine_id = int(mine_id)
        cell_index = int(cell_index)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="mine_id and cell_index must be integers")
    ip_hash = body.get("ip_hash")
    device_hash = body.get("device_hash")
    vpn_flag = body.get("vpn_flag")
    if isinstance(vpn_flag, str):
        vpn_flag = vpn_flag.lower() in ("true", "1", "yes")
    return await do_mine_dig(
        telegram_id,
        mine_id,
        cell_index,
        ip_hash=ip_hash,
        device_hash=device_hash,
        vpn_flag=vpn_flag if isinstance(vpn_flag, bool) else None,
    )


@router.get("/mine/{mine_id}")
async def api_mine_get(
    mine_id: int,
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    """Получить сессию шахты: grid_size, opened_cells (призовые не раскрываются)."""
    telegram_id = _get_telegram_id(x_telegram_user_id, x_user_id)
    user_id = await ensure_user(telegram_id)
    session = await get_mine_session(mine_id, user_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Mine not found")
    return {
        "id": session["id"],
        "grid_size": session["grid_size"],
        "opened_cells": session["opened_cells"],
        "created_at": session["created_at"],
    }


# ——— Фаза 2: поле и здания ———

@router.get("/field")
async def api_field(
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    """Поле игрока: слоты 1..9 и здания на них."""
    telegram_id = _get_telegram_id(x_telegram_user_id, x_user_id)
    user_id = await ensure_user(telegram_id)
    return await get_player_field(user_id)


@router.get("/buildings/def")
async def api_buildings_def():
    """Справочник зданий (каталог)."""
    return await get_buildings_def()


@router.post("/field/place")
async def api_field_place(
    body: Dict[str, Any],
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    """Поставить здание на слот. body: slot_index (1..9), building_key, cost (optional)."""
    telegram_id = _get_telegram_id(x_telegram_user_id, x_user_id)
    user_id = await ensure_user(telegram_id)
    slot_index = body.get("slot_index")
    building_key = body.get("building_key")
    cost = body.get("cost", 100)
    if slot_index is None or not building_key:
        raise HTTPException(status_code=400, detail="slot_index and building_key required")
    err = await place_building(user_id, int(slot_index), str(building_key), int(cost))
    if err:
        raise HTTPException(status_code=400, detail=err)
    return {"ok": True}


@router.post("/field/demolish")
async def api_field_demolish(
    body: Dict[str, Any],
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    """Снести здание. body: slot_index (1..9). Refund 25%."""
    telegram_id = _get_telegram_id(x_telegram_user_id, x_user_id)
    user_id = await ensure_user(telegram_id)
    slot_index = body.get("slot_index")
    if slot_index is None:
        raise HTTPException(status_code=400, detail="slot_index required")
    err = await demolish_building(user_id, int(slot_index))
    if err:
        raise HTTPException(status_code=400, detail=err)
    return {"ok": True}


@router.post("/field/upgrade")
async def api_field_upgrade(
    body: Dict[str, Any],
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    """Улучшить здание. body: building_key, cost."""
    telegram_id = _get_telegram_id(x_telegram_user_id, x_user_id)
    user_id = await ensure_user(telegram_id)
    building_key = body.get("building_key")
    cost = body.get("cost", 50)
    if not building_key:
        raise HTTPException(status_code=400, detail="building_key required")
    err = await upgrade_building(user_id, str(building_key), int(cost))
    if err:
        raise HTTPException(status_code=400, detail=err)
    return {"ok": True}


@router.get("/field/slots/{building_key}")
async def api_field_slots(
    building_key: str,
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    """Слоты реликвий здания."""
    telegram_id = _get_telegram_id(x_telegram_user_id, x_user_id)
    user_id = await ensure_user(telegram_id)
    return await get_building_slots(user_id, building_key)


@router.post("/field/equip")
async def api_field_equip(
    body: Dict[str, Any],
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    """Поставить реликвию в слот здания. body: building_key, slot_index, user_item_id."""
    telegram_id = _get_telegram_id(x_telegram_user_id, x_user_id)
    user_id = await ensure_user(telegram_id)
    building_key = body.get("building_key")
    slot_index = body.get("slot_index")
    user_item_id = body.get("user_item_id")
    if not building_key or slot_index is None or user_item_id is None:
        raise HTTPException(status_code=400, detail="building_key, slot_index, user_item_id required")
    err = await equip_relic(user_id, str(building_key), int(slot_index), int(user_item_id))
    if err:
        raise HTTPException(status_code=400, detail=err)
    return {"ok": True}


@router.post("/field/unequip")
async def api_field_unequip(
    body: Dict[str, Any],
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    """Снять реликвию со слота. body: building_key, slot_index."""
    telegram_id = _get_telegram_id(x_telegram_user_id, x_user_id)
    user_id = await ensure_user(telegram_id)
    building_key = body.get("building_key")
    slot_index = body.get("slot_index")
    if not building_key or slot_index is None:
        raise HTTPException(status_code=400, detail="building_key, slot_index required")
    err = await unequip_relic(user_id, str(building_key), int(slot_index))
    if err:
        raise HTTPException(status_code=400, detail=err)
    return {"ok": True}


@router.post("/field/collect")
async def api_field_collect(
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    """Собрать доход с поля (оффлайн кап 12 ч)."""
    telegram_id = _get_telegram_id(x_telegram_user_id, x_user_id)
    user_id = await ensure_user(telegram_id)
    return await collect_income(user_id)


# ——— Фаза 3: крафт ———

@router.post("/craft/merge")
async def api_craft_merge(
    body: Dict[str, Any],
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    """Слияние 3 реликвий одного типа. body: item_ids [id1, id2, id3]."""
    telegram_id = _get_telegram_id(x_telegram_user_id, x_user_id)
    user_id = await ensure_user(telegram_id)
    item_ids = body.get("item_ids") or []
    if len(item_ids) != 3:
        raise HTTPException(status_code=400, detail="item_ids must have 3 elements")
    result = await craft_merge(user_id, [int(x) for x in item_ids])
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "craft_failed"))
    return result


@router.post("/craft/upgrade")
async def api_craft_upgrade(
    body: Dict[str, Any],
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    """Улучшение предмета. body: item_id."""
    telegram_id = _get_telegram_id(x_telegram_user_id, x_user_id)
    user_id = await ensure_user(telegram_id)
    item_id = body.get("item_id")
    if item_id is None:
        raise HTTPException(status_code=400, detail="item_id required")
    result = await craft_upgrade(user_id, int(item_id))
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "craft_failed"))
    return result


@router.post("/craft/reroll")
async def api_craft_reroll(
    body: Dict[str, Any],
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    """Перекат эффекта. body: item_id."""
    telegram_id = _get_telegram_id(x_telegram_user_id, x_user_id)
    user_id = await ensure_user(telegram_id)
    item_id = body.get("item_id")
    if item_id is None:
        raise HTTPException(status_code=400, detail="item_id required")
    result = await craft_reroll(user_id, int(item_id))
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "craft_failed"))
    return result


# ——— Фаза 4: рынок и P2P ———

@router.get("/market/orders")
async def api_market_orders(pay_currency: Optional[str] = None):
    """Список открытых ордеров. Опционально pay_currency=COINS|STARS."""
    return await get_market_orders_open(pay_currency)


@router.post("/market/orders")
async def api_market_create_order(
    body: Dict[str, Any],
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    """Создать ордер. body: user_item_ids[], pay_currency, pay_amount, expires_at (optional)."""
    telegram_id = _get_telegram_id(x_telegram_user_id, x_user_id)
    user_id = await ensure_user(telegram_id)
    item_ids = body.get("user_item_ids") or []
    pay_currency = body.get("pay_currency", "COINS")
    pay_amount = int(body.get("pay_amount", 0))
    if not item_ids or pay_amount < 5:
        raise HTTPException(status_code=400, detail="user_item_ids and pay_amount >= 5 required")
    order_id = await create_market_order(user_id, [int(x) for x in item_ids], pay_currency, pay_amount, body.get("expires_at"))
    if order_id is None:
        raise HTTPException(status_code=400, detail="create_failed")
    return {"ok": True, "order_id": order_id}


@router.post("/market/orders/{order_id}/fill")
async def api_market_fill(
    order_id: int,
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    """Купить по ордеру (списание COINS, комиссия 5%)."""
    telegram_id = _get_telegram_id(x_telegram_user_id, x_user_id)
    user_id = await ensure_user(telegram_id)
    err = await fill_market_order_coins(user_id, order_id)
    if err:
        raise HTTPException(status_code=400, detail=err)
    return {"ok": True}


@router.post("/market/orders/{order_id}/cancel")
async def api_market_cancel(
    order_id: int,
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    """Отменить свой ордер."""
    telegram_id = _get_telegram_id(x_telegram_user_id, x_user_id)
    user_id = await ensure_user(telegram_id)
    err = await cancel_market_order(user_id, order_id)
    if err:
        raise HTTPException(status_code=400, detail=err)
    return {"ok": True}


@router.post("/market/trade-offers")
async def api_trade_offer_create(
    body: Dict[str, Any],
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    """Создать оффер обмена. body: maker_item_ids[], taker_item_ids[], taker_id (optional), want_currency, want_amount."""
    telegram_id = _get_telegram_id(x_telegram_user_id, x_user_id)
    user_id = await ensure_user(telegram_id)
    maker_ids = body.get("maker_item_ids") or []
    taker_ids = body.get("taker_item_ids") or []
    if not maker_ids:
        raise HTTPException(status_code=400, detail="maker_item_ids required")
    offer_id = await create_trade_offer(
        user_id,
        [int(x) for x in maker_ids],
        [int(x) for x in taker_ids],
        body.get("taker_id"),
        body.get("want_currency"),
        int(body.get("want_amount", 0)),
        body.get("expires_at"),
    )
    if offer_id is None:
        raise HTTPException(status_code=400, detail="create_failed")
    return {"ok": True, "offer_id": offer_id}


@router.post("/market/trade-offers/{offer_id}/accept")
async def api_trade_offer_accept(
    offer_id: int,
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    """Принять оффер (обмен предметами)."""
    telegram_id = _get_telegram_id(x_telegram_user_id, x_user_id)
    user_id = await ensure_user(telegram_id)
    err = await db_accept_trade_offer(user_id, offer_id)
    if err:
        raise HTTPException(status_code=400, detail=err)
    return {"ok": True}


@router.post("/market/trade-offers/{offer_id}/cancel")
async def api_trade_offer_cancel(
    offer_id: int,
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    """Отменить свой оффер."""
    telegram_id = _get_telegram_id(x_telegram_user_id, x_user_id)
    user_id = await ensure_user(telegram_id)
    err = await cancel_trade_offer(user_id, offer_id)
    if err:
        raise HTTPException(status_code=400, detail=err)
    return {"ok": True}


# ——— Фаза 5: вывод и eligibility ———

@router.get("/withdraw/eligibility")
async def api_withdraw_eligibility(
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    """Проверка возможности вывода (уровень, кошелёк, правило 10%, compliance)."""
    telegram_id = _get_telegram_id(x_telegram_user_id, x_user_id)
    user_id = await ensure_user(telegram_id)
    return await get_withdraw_eligibility(user_id)


@router.post("/withdraw/request")
async def api_withdraw_request(
    body: Dict[str, Any],
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    """Запрос вывода TON. body: amount, to_telegram_id или to_address. Требует iCryptoCheck."""
    telegram_id = _get_telegram_id(x_telegram_user_id, x_user_id)
    user_id = await ensure_user(telegram_id)
    eligibility = await get_withdraw_eligibility(user_id)
    if not eligibility.get("can_withdraw"):
        raise HTTPException(status_code=403, detail="withdraw_not_eligible")
    amount = body.get("amount", 0)
    if amount <= 0:
        raise HTTPException(status_code=400, detail="amount required")
    return {"ok": False, "message": "iCryptoCheck not configured", "status": "pending"}


@router.post("/ads/view")
async def api_ads_view(
    body: Dict[str, Any],
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    """Записать просмотр рекламы. body: ad_kind, provider?, idem_key?."""
    telegram_id = _get_telegram_id(x_telegram_user_id, x_user_id)
    user_id = await ensure_user(telegram_id)
    ad_kind = body.get("ad_kind", "short")
    await record_ad_view(user_id, ad_kind, body.get("provider"), body.get("idem_key"))
    return {"ok": True}


@router.post("/donate")
async def api_donate(
    body: Dict[str, Any],
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    """Вклад в профиль (зачёт в eligibility). body: currency, amount, period_key, donation_points?."""
    telegram_id = _get_telegram_id(x_telegram_user_id, x_user_id)
    user_id = await ensure_user(telegram_id)
    currency = body.get("currency", "STARS")
    amount = int(body.get("amount", 0))
    period_key = body.get("period_key", "")
    points = float(body.get("donation_points", amount))
    if amount <= 0 or not period_key:
        raise HTTPException(status_code=400, detail="currency, amount, period_key required")
    await donate_to_profile(user_id, currency, amount, period_key, points, body.get("idem_key"))
    return {"ok": True}


# ——— Фазы 6–9: стейкинг, лидерборды ———

@router.get("/staking/sessions")
async def api_staking_sessions(
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    """Список стейк-сессий пользователя."""
    telegram_id = _get_telegram_id(x_telegram_user_id, x_user_id)
    user_id = await ensure_user(telegram_id)
    return await get_staking_sessions(user_id)


@router.post("/staking/create")
async def api_staking_create(
    body: Dict[str, Any],
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    """Создать стейк-сессию (адрес депозита через iCryptoCheck). Заглушка."""
    telegram_id = _get_telegram_id(x_telegram_user_id, x_user_id)
    user_id = await ensure_user(telegram_id)
    return {"ok": False, "message": "iCryptoCheck payment-addresses not configured", "payment_address": None}


@router.get("/leaderboards")
async def api_leaderboards(period: str = "weekly", period_key: Optional[str] = None):
    """Лидерборд: period=weekly|monthly|era, опционально period_key."""
    return await get_leaderboards(period, period_key)


# ——— Публичное чтение данных админки (партнёрские токены, задания, тексты страниц) ———

@router.get("/partner-tokens")
async def api_partner_tokens():
    """Список активных партнёрских токенов для оплаты и т.д. (редактирование — в админке)."""
    return await admin_get_partner_tokens(active_only=True)


@router.get("/tasks")
async def api_tasks():
    """Список активных заданий/контрактов (редактирование — в админке)."""
    return await admin_get_tasks(active_only=True)


@router.get("/page-texts/{page_id}")
async def api_page_texts(page_id: str):
    """Тексты для страницы (косметика). page_id: village, mine, profile, about и т.д."""
    return await admin_get_page_texts(page_id=page_id)
