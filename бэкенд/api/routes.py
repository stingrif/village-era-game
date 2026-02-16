import logging
import random
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Header, HTTPException, Request

from config import (
    get_eggs_config,
    get_field_config,
    get_mine_config,
    MIN_ACCOUNT_AGE_DAYS_FOR_PHOENIX_QUEST,
    MIN_BURN_COUNT_FOR_PHOENIX_QUEST,
    PHOEX_TOKEN_ADDRESS,
    PHOENIX_QUEST_REWARD_AMOUNT,
    PHOENIX_QUEST_SUBMIT_RATE_LIMIT_SEC,
    PROJECT_WALLET_ADDRESS,
)
from infrastructure.database import get_setting, get_all_holder_snapshots, get_holder_snapshots_count

# Helpers to read quest settings from DB with fallback to hardcoded defaults
async def _quest_reward_amount():
    return await get_setting("quest.reward_amount", PHOENIX_QUEST_REWARD_AMOUNT)

async def _quest_min_burn():
    return await get_setting("quest.min_burn_count", MIN_BURN_COUNT_FOR_PHOENIX_QUEST)

async def _quest_min_age():
    return await get_setting("quest.min_account_age_days", MIN_ACCOUNT_AGE_DAYS_FOR_PHOENIX_QUEST)

async def _quest_rate_limit():
    return await get_setting("quest.submit_rate_limit_sec", PHOENIX_QUEST_SUBMIT_RATE_LIMIT_SEC)
from core.checkin_mine import do_checkin, do_mine_create, do_mine_dig
from core.craft import craft_merge, craft_reroll, craft_upgrade, craft_furnace_upgrade
from core.game_engine import (
    RUS_ALPHABET,
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
    add_letter_to_user,
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
    get_items_catalog,
    get_item_stats,
    get_shop_offers,
    purchase_shop_offer,
    get_market_orders_open,
    get_mine_session,
    get_phoenix_quest_state,
    get_player_critical,
    get_player_field,
    get_user_id_by_telegram_id,
    get_visit_log,
    perform_attack,
    do_furnace_hatch,
    get_state,
    get_user_balances,
    get_user_inventory,
    get_user_letter_items,
    get_withdraw_eligibility,
    get_leaderboards,
    get_staking_sessions,
    get_pnl_wallet_state,
    list_user_wallet_bindings,
    add_user_wallet_binding,
    delete_user_wallet_binding,
    get_user_wallet_binding_by_code,
    set_wallet_binding_verified,
    update_wallet_binding_address,
    delete_pending_wallet_bindings_by_code,
    MAX_WALLETS_PER_USER,
    phoenix_submit_word,
    set_state,
    demolish_building,
    donate_to_profile,
    place_building,
    record_ad_view,
    unequip_relic,
    upgrade_building,
    get_dev_collections,
    get_dev_nfts_for_user,
    get_dev_profile_stats,
    get_all_dev_nfts,
)
from infrastructure.price import get_rates
from infrastructure.telegram_notify import notify_admin_phoenix_quest
from infrastructure.nft_check import check_user_has_project_nft
from infrastructure.ton_address import raw_to_friendly
from infrastructure.ton_verify import find_verification_tx

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
        try:
            user_id = await ensure_user(telegram_id)
            await add_letter_to_user(user_id, random.choice(RUS_ALPHABET))
        except Exception as e:
            logger.warning("add_letter_to_user on burn: %s", e)
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
            rate_limit = await _quest_rate_limit()
            if now - last < rate_limit:
                raise HTTPException(
                    status_code=429,
                    detail="Rate limit: try again later",
                )
            _phoenix_submit_last[telegram_id] = now
            min_burn = await _quest_min_burn()
            min_age = await _quest_min_age()
            burn_ok = critical["burned_count"] >= min_burn
            age_days = _account_age_days(critical.get("created_at"))
            age_ok = age_days >= min_age
            if not (burn_ok and age_ok):
                raise HTTPException(
                    status_code=403,
                    detail=f"Requires min {min_burn} burns and {min_age} days account age",
                )
            state = apply_phoenix_quest(state)
            reward_amount = await _quest_reward_amount()
            await add_pending_payout(telegram_id, "phoenix_quest", reward_amount)
            await notify_admin_phoenix_quest(
                telegram_id,
                username=username or None,
                first_name=first_name or None,
                reward_amount=reward_amount,
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
    """Публичный конфиг игры: field, mine, eggs — with dynamic overrides from game_settings."""
    mine = dict(get_mine_config())
    # Override from DB settings if present
    grid_size = await get_setting("mine.grid_size")
    if grid_size is not None:
        mine["gridSize"] = grid_size
    dist = await get_setting("mine.prize_cells_distribution")
    if dist is not None:
        mine["prizeCellsDistribution"] = dist
    loot = await get_setting("mine.prize_loot")
    if loot is not None:
        mine["prizeCellLoot"] = loot
    egg_roll = await get_setting("mine.egg_roll")
    if egg_roll is not None:
        mine["eggRoll"] = egg_roll
    return {
        "field": get_field_config(),
        "mine": mine,
        "eggs": get_eggs_config(),
    }


@router.post("/checkin")
async def api_checkin(
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    body: Optional[Dict[str, Any]] = Body(default=None),
):
    """Чекин: app — 3 попытки (из приложения, с рекламой), chat — 2 попытки (команда Голос/vote/checkin в чате)."""
    telegram_id = _get_telegram_id(x_telegram_user_id, x_user_id)
    source = (body or {}).get("source", "app")
    if isinstance(source, str):
        source = source.strip().lower()
    if source not in ("app", "chat"):
        source = "app"
    return await do_checkin(telegram_id, source=source)


@router.get("/checkin-state")
async def api_checkin_state(
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    """Состояние чекина: next_checkin_at, streak, attempts (баланс попыток копания)."""
    telegram_id = _get_telegram_id(x_telegram_user_id, x_user_id)
    user_id = await ensure_user(telegram_id)
    state = await get_checkin_state(user_id)
    attempts = await get_attempts(user_id)
    if state is None:
        return {"next_checkin_at": None, "streak": 0, "attempts": attempts}
    out = dict(state)
    out["attempts"] = attempts
    return out


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


# ——— Квест ФЕНИКС: слово из букв инвентаря, 5 победителей, бейдж «Букварь» ———

@router.get("/phoenix/word")
async def api_phoenix_word():
    """Текущее загаданное слово (подсказка: первая буква), счётчик сдач, макс 5."""
    state = await get_phoenix_quest_state()
    word = state.get("current_word", "ФЕНИКС")
    hint = word[0] + "?" * (len(word) - 1) if word else ""
    return {
        "current_word_hint": hint,
        "word_length": len(word),
        "submissions_count": state.get("submissions_count", 0),
        "max_submissions": state.get("max_submissions", 5),
    }


@router.get("/phoenix/letters")
async def api_phoenix_letters(
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    """Буквы в инвентаре пользователя (item_type=letter)."""
    telegram_id = _get_telegram_id(x_telegram_user_id, x_user_id)
    user_id = await ensure_user(telegram_id)
    items = await get_user_letter_items(user_id)
    return {"letters": items}


@router.post("/phoenix/submit")
async def api_phoenix_submit(
    body: Dict[str, Any],
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    """Сдача слова: word (строка), letter_item_ids (список id user_items в порядке букв). Буквы списываются."""
    telegram_id = _get_telegram_id(x_telegram_user_id, x_user_id)
    user_id = await ensure_user(telegram_id)
    word = body.get("word") or ""
    letter_item_ids = body.get("letter_item_ids")
    if not isinstance(letter_item_ids, list):
        letter_item_ids = []
    letter_item_ids = [int(x) for x in letter_item_ids if isinstance(x, (int, str)) and str(x).isdigit()]
    result = await phoenix_submit_word(user_id, word, letter_item_ids)
    if result.get("badge_granted"):
        reward_amount = await _quest_reward_amount()
        await add_pending_payout(telegram_id, "phoenix_quest", reward_amount)
        await notify_admin_phoenix_quest(
            telegram_id,
            username=None,
            first_name=None,
            reward_amount=reward_amount,
        )
    return result


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


@router.get("/field/{target_telegram_id}")
async def api_field_public(
    target_telegram_id: int,
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    """Поле другого игрока (для визита/атаки): только здания и уровни."""
    target_user_id = await get_user_id_by_telegram_id(target_telegram_id)
    if not target_user_id:
        raise HTTPException(status_code=404, detail="user_not_found")
    return await get_player_field(target_user_id)


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


# ——— Печки и вылупление яиц ———

@router.post("/furnace/hatch")
async def api_furnace_hatch(
    body: Dict[str, Any],
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    """Вылупление: 1 печка + 3 яйца одного цвета или 1 редкое яйцо. body: furnace_user_item_id, egg_ids [id1, id2, id3] или [id1]."""
    telegram_id = _get_telegram_id(x_telegram_user_id, x_user_id)
    user_id = await ensure_user(telegram_id)
    furnace_user_item_id = int(body.get("furnace_user_item_id", 0))
    egg_ids = [int(x) for x in (body.get("egg_ids") or [])]
    result = await do_furnace_hatch(user_id, furnace_user_item_id, egg_ids)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("message", "hatch_failed"))
    return result


# ——— Фаза 3: крафт ———

@router.post("/craft/furnace-upgrade")
async def api_craft_furnace_upgrade(
    body: Dict[str, Any],
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    """Апгрейд печки: 2 печки одного цвета + 1 любой предмет + просмотр рекламы. body: furnace_item_id_1, furnace_item_id_2, extra_item_id, ad_watched (true)."""
    telegram_id = _get_telegram_id(x_telegram_user_id, x_user_id)
    user_id = await ensure_user(telegram_id)
    fid1 = int(body.get("furnace_item_id_1", 0))
    fid2 = int(body.get("furnace_item_id_2", 0))
    extra_id = int(body.get("extra_item_id", 0))
    ad_watched = bool(body.get("ad_watched", False))
    result = await craft_furnace_upgrade(user_id, fid1, fid2, extra_id, ad_watched=ad_watched)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "craft_failed"))
    return result


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


# ——— Каталог предметов (О проекте, маркет) ———

@router.get("/items-catalog")
async def api_items_catalog():
    """Каталог предметов из item_defs (id, key, name, item_type, subtype, rarity, effects)."""
    return await get_items_catalog()


@router.get("/items-stats")
async def api_items_stats():
    """Сводная статистика по предметам: у игроков (inventory/equipped/listed), дроп, сжигание, слияние, продажи."""
    return await get_item_stats()


# ——— Магазин из казны ———

@router.get("/shop/offers")
async def api_shop_offers():
    """Список предложений магазина (покупка за COINS/STARS)."""
    return await get_shop_offers()


@router.post("/shop/purchase")
async def api_shop_purchase(
    body: Dict[str, Any],
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    """Купить предмет в магазине. body: offer_id, quantity (default 1)."""
    telegram_id = _get_telegram_id(x_telegram_user_id, x_user_id)
    user_id = await ensure_user(telegram_id)
    offer_id = int(body.get("offer_id", 0))
    quantity = int(body.get("quantity", 1))
    err = await purchase_shop_offer(user_id, offer_id, quantity)
    if err:
        raise HTTPException(status_code=400, detail=err)
    return {"ok": True, "quantity": quantity}


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


@router.get("/pnl/wallet-state")
async def api_pnl_wallet_state(
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    """Состояние кошелька и стейкингов для экрана PnL: привязка, адреса, список контрактов стейкинга, есть ли активные стейки."""
    telegram_id = _get_telegram_id(x_telegram_user_id, x_user_id)
    user_id = await ensure_user(telegram_id)
    return await get_pnl_wallet_state(user_id)


@router.get("/rates")
async def api_rates(force_refresh: bool = False):
    """Курсы для отображения цен: phxpw_price_ton (цена 1 PHXPW в TON), опционально phxpw_price_usd. Публичный, без авторизации."""
    return await get_rates(force_refresh=force_refresh)


@router.get("/stats")
async def api_game_stats():
    """Публичная статистика: онлайн (WS), всего игроков."""
    from api.main import get_online_count
    from infrastructure.database import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM game_players")
        recent = await conn.fetchval(
            "SELECT COUNT(*) FROM game_players WHERE updated_at > NOW() - INTERVAL '5 minutes'"
        )
    ws_online = get_online_count()
    return {
        "total_players": total or 0,
        "online": max(ws_online, recent or 0),
    }


@router.get("/wallets")
async def api_wallets_list(
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    """Список привязанных кошельков пользователя (до 10). Адреса конвертируются в friendly (UQ…)."""
    telegram_id = _get_telegram_id(x_telegram_user_id, x_user_id)
    user_id = await ensure_user(telegram_id)
    rows = await list_user_wallet_bindings(user_id, telegram_id=telegram_id)
    wallets = []
    for w in rows:
        addr = w.get("wallet_address")
        if addr:
            friendly = await raw_to_friendly(addr)
            masked = friendly[:8] + "…" + friendly[-4:] if len(friendly) > 14 else friendly
        else:
            friendly = None
            masked = "ожидает верификации"
        wallets.append({
            **w,
            "wallet_address_friendly": friendly,
            "wallet_address_masked": masked,
        })
    return {"wallets": wallets, "max_wallets": MAX_WALLETS_PER_USER}


@router.post("/wallet")
async def api_wallet_add(
    body: Dict[str, Any],
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    """Добавить кошелёк: создаётся привязка с verify_comment (verify:telegram_id). Отправить 0.1 TON на project_wallet с этим комментарием, затем проверить привязку."""
    telegram_id = _get_telegram_id(x_telegram_user_id, x_user_id)
    user_id = await ensure_user(telegram_id)
    verify_comment = f"verify:{telegram_id}"
    out = await add_user_wallet_binding(user_id, verify_comment)
    if out is None:
        raise HTTPException(status_code=400, detail=f"max_wallets_reached ({MAX_WALLETS_PER_USER})")
    return {
        "ok": True,
        "binding_id": out["id"],
        "verify_code": out["verify_code"],
        "verify_comment": verify_comment,
        "project_wallet": PROJECT_WALLET_ADDRESS or "",
        "jetton_master": PHOEX_TOKEN_ADDRESS or "",
        "phxpw_amount": 4500,
        "message": "Отправьте 0.1 TON или 4500 PHXPW с комментарием (verify_comment) на адрес проекта с кошелька, который привязываете",
    }


@router.post("/wallet/verify")
async def api_wallet_verify(
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    """Проверить привязку кошелька: ищет входящую tx 0.1 TON или 4500 PHXPW с комментарием verify:telegram_id."""
    telegram_id = _get_telegram_id(x_telegram_user_id, x_user_id)
    user_id = await ensure_user(telegram_id)
    verify_comment = f"verify:{telegram_id}"
    project_wallet = (PROJECT_WALLET_ADDRESS or "").strip()
    if not project_wallet:
        return {"ok": False, "reason": "project_wallet_not_configured"}
    tx = await find_verification_tx(project_wallet, verify_comment)
    if not tx:
        return {"ok": False, "reason": "tx_not_found"}
    binding = await get_user_wallet_binding_by_code(verify_comment)
    if not binding:
        return {"ok": False, "reason": "binding_not_found"}
    wallet_address_raw = (tx.get("sender") or "").strip()
    if not wallet_address_raw:
        return {"ok": False, "reason": "sender_empty"}
    # Конвертируем raw → friendly (UQ…) через Ton Center; при ошибке сохраняем raw
    wallet_address = await raw_to_friendly(wallet_address_raw)
    binding_id = binding["id"]
    await update_wallet_binding_address(binding_id, wallet_address)
    await set_wallet_binding_verified(binding_id)
    await delete_pending_wallet_bindings_by_code(user_id, verify_comment)
    return {
        "ok": True,
        "wallet_address": wallet_address,
        "method": tx.get("method") or "ton",
    }


@router.get("/nft/check")
async def api_nft_check(
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    """Проверить и вернуть список NFT от проекта (сминчены с кошелька разработчика). По привязанным верифицированным кошелькам. items — массив с полями address, name, image, collection_name для отображения в PnL."""
    telegram_id = _get_telegram_id(x_telegram_user_id, x_user_id)
    user_id = await ensure_user(telegram_id)
    rows = await list_user_wallet_bindings(user_id, telegram_id=telegram_id)
    total_count = 0
    has_any = False
    wallets_checked = 0
    all_items: List[Dict[str, Any]] = []
    seen_addresses: set = set()
    for w in rows:
        if not w.get("verified_at") or not w.get("wallet_address"):
            continue
        addr = (w.get("wallet_address") or "").strip()
        if not addr:
            continue
        try:
            out = await check_user_has_project_nft(addr, return_items=True)
        except Exception as e:
            logger.warning("nft/check wallet %s: %s", addr[:16], e)
            continue
        wallets_checked += 1
        if out.get("has_project_nft"):
            has_any = True
        total_count += out.get("count") or 0
        for it in out.get("items") or []:
            a = (it.get("address") or "").strip()
            if a and a not in seen_addresses:
                seen_addresses.add(a)
                all_items.append(it)
    return {
        "has_project_nft": has_any,
        "count": total_count,
        "wallets_checked": wallets_checked,
        "items": all_items,
    }


@router.delete("/wallet/{binding_id}")
async def api_wallet_remove(
    binding_id: int,
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    """Отвязать кошелёк."""
    telegram_id = _get_telegram_id(x_telegram_user_id, x_user_id)
    user_id = await ensure_user(telegram_id)
    ok = await delete_user_wallet_binding(user_id, binding_id)
    if not ok:
        raise HTTPException(status_code=404, detail="wallet_not_found")
    return {"ok": True}


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


@router.get("/visit-log")
async def api_visit_log(
    role: str = "any",
    limit: int = 50,
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    """Лог визитов/атак: role=visitor|target|any."""
    telegram_id = _get_telegram_id(x_telegram_user_id, x_user_id)
    user_id = await ensure_user(telegram_id)
    return await get_visit_log(user_id, role=role, limit=min(limit, 100))


@router.get("/history/logs")
async def api_history_logs(
    limit: int = 50,
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    """Полный лог визитов (для владельцев предмета «история игры» или свой лог). Пока отдаём свой visit_log."""
    telegram_id = _get_telegram_id(x_telegram_user_id, x_user_id)
    user_id = await ensure_user(telegram_id)
    return await get_visit_log(user_id, role="any", limit=min(limit, 200))


@router.post("/attack/{target_telegram_id}")
async def api_attack(
    target_telegram_id: int,
    body: Optional[Dict[str, Any]] = None,
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    """Атака (ограбление до 2 зданий). body: building_slot_indexes [1..9], до 2 слотов. Cooldown 30 мин, на постройку 1ч."""
    telegram_id = _get_telegram_id(x_telegram_user_id, x_user_id)
    attacker_id = await ensure_user(telegram_id)
    if target_telegram_id == telegram_id:
        raise HTTPException(status_code=400, detail="cannot_attack_self")
    target_user_id = await get_user_id_by_telegram_id(target_telegram_id)
    if not target_user_id:
        raise HTTPException(status_code=404, detail="user_not_found")
    slot_indexes = (body or {}).get("building_slot_indexes") or []
    result = await perform_attack(attacker_id, target_user_id, slot_indexes)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("message", "attack_failed"))
    return {"ok": True, "total_stolen": result["total_stolen"], "buildings_robbed": result["buildings_robbed"], "refresh": True}


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


# ——— NFT-каталог разработчика ———

@router.get("/nft/dev-profile")
async def api_nft_dev_profile():
    """Профиль разработчика: кошелёк, количество коллекций/NFT, список коллекций."""
    from config import NFT_DEV_WALLET
    stats = await get_dev_profile_stats()
    collections = await get_dev_collections()
    return {
        "dev_wallet": NFT_DEV_WALLET or "",
        "nickname": "Phoenix Paw",
        **stats,
        "collections": [
            {
                "address": c["collection_address"],
                "name": c["name"],
                "description": c["description"],
                "image": c["image"],
                "items_count": c["items_count"],
            }
            for c in collections
        ],
    }


@router.get("/nft/user-nfts")
async def api_nft_user_nfts(
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    """NFT из коллекций разработчика, принадлежащие текущему пользователю (по его привязанным кошелькам)."""
    telegram_id = _get_telegram_id(x_telegram_user_id, x_user_id)
    user_id = await ensure_user(telegram_id)
    rows = await list_user_wallet_bindings(user_id, telegram_id=telegram_id)
    wallet_addresses = []
    for w in rows:
        if not w.get("verified_at") or not w.get("wallet_address"):
            continue
        addr = (w["wallet_address"] or "").strip()
        if addr:
            friendly = await raw_to_friendly(addr)
            wallet_addresses.append(friendly)
    nfts = await get_dev_nfts_for_user(wallet_addresses)
    items = []
    for n in nfts:
        attrs = n.get("attributes") or []
        if isinstance(attrs, str):
            import json as _json
            try:
                attrs = _json.loads(attrs)
            except Exception:
                attrs = []
        items.append({
            "nft_address": n["nft_address"],
            "collection_address": n["collection_address"],
            "collection_name": n.get("collection_name") or "",
            "name": n["name"],
            "description": n.get("description") or "",
            "image": n["image"],
            "attributes": attrs,
            "nft_index": n.get("nft_index") or 0,
        })
    return {
        "count": len(items),
        "wallets_checked": len(wallet_addresses),
        "items": items,
    }


@router.get("/nft/catalog")
async def api_nft_catalog():
    """Полный каталог NFT из коллекций разработчика (для общего просмотра)."""
    nfts = await get_all_dev_nfts()
    collections = await get_dev_collections()
    coll_map = {c["collection_address"]: c["name"] for c in collections}
    items = []
    for n in nfts:
        attrs = n.get("attributes") or []
        if isinstance(attrs, str):
            import json as _json
            try:
                attrs = _json.loads(attrs)
            except Exception:
                attrs = []
        items.append({
            "nft_address": n["nft_address"],
            "collection_address": n["collection_address"],
            "collection_name": n.get("collection_name") or coll_map.get(n["collection_address"], ""),
            "name": n["name"],
            "description": n.get("description") or "",
            "image": n["image"],
            "owner_address": n.get("owner_address") or "",
            "attributes": attrs,
            "nft_index": n.get("nft_index") or 0,
        })
    return {
        "total": len(items),
        "collections_count": len(collections),
        "items": items,
    }


@router.get("/nft/holders-summary")
async def api_nft_holders_summary():
    """Public: NFT holders count. If holders.show_detailed_public is enabled, includes full list."""
    count = await get_holder_snapshots_count()
    show_detailed = await get_setting("holders.show_detailed_public", False)
    result = {"holders_count": count}
    if show_detailed:
        holders = await get_all_holder_snapshots()
        # Public view: exclude TG links for privacy
        result["holders"] = [
            {
                "address": h["owner_address"][:8] + "..." + h["owner_address"][-6:] if len(h["owner_address"]) > 16 else h["owner_address"],
                "address_full": h["owner_address"],
                "nft_count": h["nft_count"],
                "collections": h["collections"],
                "phxpw_balance": h["phxpw_balance"],
                "total_received": h["total_received"],
                "total_sent": h["total_sent"],
            }
            for h in holders
        ]
    return result


@router.post("/nft/sync")
async def api_nft_sync_trigger(
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    """Ручной запуск синхронизации NFT (только админ)."""
    from config import GAME_ADMIN_TG_ID
    telegram_id = _get_telegram_id(x_telegram_user_id, x_user_id)
    if telegram_id != GAME_ADMIN_TG_ID:
        raise HTTPException(status_code=403, detail="admin_only")
    from infrastructure.nft_sync import run_full_sync
    stats = await run_full_sync()
    return {"ok": True, **stats}
