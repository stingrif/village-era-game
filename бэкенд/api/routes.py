import logging
import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, Header, HTTPException, Request

from config import (
    MIN_ACCOUNT_AGE_DAYS_FOR_PHOENIX_QUEST,
    MIN_BURN_COUNT_FOR_PHOENIX_QUEST,
    PHOENIX_QUEST_REWARD_AMOUNT,
    PHOENIX_QUEST_SUBMIT_RATE_LIMIT_SEC,
)
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
    add_pending_payout,
    get_player_critical,
    get_state,
    set_state,
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
