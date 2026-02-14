"""
Админ-панель API: партнёрские токены, задания, тексты страниц.
Доступ только для пользователя с telegram_id == GAME_ADMIN_TG_ID.
"""
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException

from config import GAME_ADMIN_TG_ID
from infrastructure.database import (
    add_currency_credit,
    admin_add_channel,
    admin_add_partner_token,
    admin_add_task,
    admin_delete_channel,
    admin_delete_partner_token,
    admin_delete_task,
    admin_get_activity_log,
    admin_get_activity_stats,
    admin_get_channels,
    admin_get_partner_tokens,
    admin_get_tasks,
    admin_get_page_texts,
    admin_set_page_texts,
    admin_update_task,
    activity_log_record,
    ensure_user,
    get_pool,
    get_dev_collections,
    get_all_dev_nfts,
    get_dev_profile_stats,
)
from infrastructure.telegram_chat import check_user_in_chat

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin", tags=["admin"])


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


def _require_admin(telegram_id: int) -> None:
    if telegram_id != GAME_ADMIN_TG_ID:
        raise HTTPException(status_code=403, detail="Admin only")


# ——— NFT управление (из админки) ———

@router.get("/nft/collections")
async def admin_nft_collections(
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    """Список NFT-коллекций разработчика."""
    _require_admin(_get_telegram_id(x_telegram_user_id, x_user_id))
    return await get_dev_collections()


@router.get("/nft/items")
async def admin_nft_items(
    collection_address: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    """Список NFT из коллекций разработчика."""
    _require_admin(_get_telegram_id(x_telegram_user_id, x_user_id))
    nfts = await get_all_dev_nfts()
    if collection_address:
        nfts = [n for n in nfts if n.get("collection_address") == collection_address]
    return nfts[offset:offset + limit]


@router.post("/nft/sync")
async def admin_nft_sync_trigger(
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    """Ручной запуск синхронизации NFT."""
    _require_admin(_get_telegram_id(x_telegram_user_id, x_user_id))
    from infrastructure.nft_sync import run_full_sync
    stats = await run_full_sync()
    return {"ok": True, "stats": stats}


# ——— Дашборд (аналитика) ———

@router.get("/dashboard")
async def admin_dashboard(
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    """Сводная аналитика проекта для дашборда админки."""
    _require_admin(_get_telegram_id(x_telegram_user_id, x_user_id))
    from infrastructure.database import get_pool, get_dev_profile_stats
    from api.main import get_online_count

    pool = await get_pool()
    async with pool.acquire() as conn:
        total_players = await conn.fetchval("SELECT COUNT(*) FROM game_players") or 0
        new_today = await conn.fetchval(
            "SELECT COUNT(*) FROM game_players WHERE created_at > NOW() - INTERVAL '1 day'"
        ) or 0
        new_week = await conn.fetchval(
            "SELECT COUNT(*) FROM game_players WHERE created_at > NOW() - INTERVAL '7 days'"
        ) or 0
        recent_5m = await conn.fetchval(
            "SELECT COUNT(*) FROM game_players WHERE updated_at > NOW() - INTERVAL '5 minutes'"
        ) or 0
        total_coins = 0
        try:
            total_coins = await conn.fetchval(
                "SELECT COALESCE(SUM(amount), 0) FROM economy_ledger WHERE currency = 'COINS'"
            ) or 0
        except Exception:
            pass
        total_payouts = await conn.fetchval(
            "SELECT COUNT(*) FROM pending_payouts WHERE status = 'pending'"
        ) or 0
        checkins_today = await conn.fetchval(
            "SELECT COUNT(*) FROM checkin_state WHERE last_checkin_at > NOW() - INTERVAL '1 day'"
        ) or 0
        top5 = await conn.fetch(
            """SELECT telegram_id, username, first_name, points_balance
               FROM game_players ORDER BY points_balance DESC LIMIT 5"""
        )

    nft_stats = await get_dev_profile_stats()
    ws_online = get_online_count()

    return {
        "players": {
            "total": total_players,
            "online_ws": ws_online,
            "online_recent": recent_5m,
            "new_today": new_today,
            "new_week": new_week,
        },
        "nft": {
            "collections": nft_stats.get("collections_count", 0),
            "total_nfts": nft_stats.get("nfts_total", 0),
            "last_synced_at": nft_stats.get("last_synced_at"),
        },
        "economy": {
            "total_coins_flow": total_coins,
            "pending_payouts": total_payouts,
        },
        "checkins_today": checkins_today,
        "top5": [
            {
                "telegram_id": r["telegram_id"],
                "name": r["username"] or r["first_name"] or str(r["telegram_id"]),
                "points": r["points_balance"],
            }
            for r in top5
        ],
    }


# ——— Партнёрские токены ———

@router.get("/partner-tokens")
async def admin_list_partner_tokens(
    project_id: int = 1,
    active_only: bool = False,
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    _require_admin(_get_telegram_id(x_telegram_user_id, x_user_id))
    return await admin_get_partner_tokens(project_id=project_id, active_only=active_only)


@router.post("/partner-tokens")
async def admin_create_partner_token(
    body: Dict[str, Any],
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    _require_admin(_get_telegram_id(x_telegram_user_id, x_user_id))
    token_address = body.get("token_address") or body.get("tokenAddress")
    symbol = body.get("symbol", "")
    if not token_address or not symbol:
        raise HTTPException(status_code=400, detail="token_address and symbol required")
    pid = await admin_add_partner_token(
        token_address=str(token_address).strip(),
        symbol=str(symbol).strip(),
        name=body.get("name"),
        usage=body.get("usage", "payment"),
        sort_order=int(body.get("sort_order", body.get("sortOrder", 0))),
        project_id=int(body.get("project_id", body.get("projectId", 1))),
    )
    if pid is None:
        raise HTTPException(status_code=400, detail="Token with this address already exists")
    return {"ok": True, "id": pid}


@router.delete("/partner-tokens/{token_id}")
async def admin_remove_partner_token(
    token_id: int,
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    _require_admin(_get_telegram_id(x_telegram_user_id, x_user_id))
    ok = await admin_delete_partner_token(token_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Token not found")
    return {"ok": True}


# ——— Задания ———

@router.get("/tasks")
async def admin_list_tasks(
    project_id: int = 1,
    active_only: bool = False,
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    _require_admin(_get_telegram_id(x_telegram_user_id, x_user_id))
    return await admin_get_tasks(project_id=project_id, active_only=active_only)


@router.post("/tasks")
async def admin_create_task(
    body: Dict[str, Any],
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    _require_admin(_get_telegram_id(x_telegram_user_id, x_user_id))
    task_key = body.get("task_key") or body.get("taskKey", "")
    title = body.get("title", "")
    if not task_key or not title:
        raise HTTPException(status_code=400, detail="task_key and title required")
    pid = await admin_add_task(
        task_key=str(task_key).strip(),
        title=str(title).strip(),
        description=body.get("description"),
        reward_type=body.get("reward_type") or body.get("rewardType"),
        reward_value=int(body.get("reward_value", body.get("rewardValue", 0))),
        conditions_json=body.get("conditions_json") or body.get("conditionsJson"),
        sort_order=int(body.get("sort_order", body.get("sortOrder", 0))),
        project_id=int(body.get("project_id", body.get("projectId", 1))),
    )
    if pid is None:
        raise HTTPException(status_code=400, detail="Task with this task_key already exists")
    return {"ok": True, "id": pid}


@router.put("/tasks/{task_id}")
async def admin_edit_task(
    task_id: int,
    body: Dict[str, Any],
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    _require_admin(_get_telegram_id(x_telegram_user_id, x_user_id))
    ok = await admin_update_task(
        task_id,
        title=body.get("title"),
        description=body.get("description"),
        reward_type=body.get("reward_type") or body.get("rewardType"),
        reward_value=body.get("reward_value") if "reward_value" in body else body.get("rewardValue"),
        conditions_json=body.get("conditions_json") or body.get("conditionsJson"),
        is_active=body.get("is_active") if "is_active" in body else body.get("isActive"),
        sort_order=body.get("sort_order") if "sort_order" in body else body.get("sortOrder"),
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"ok": True}


@router.delete("/tasks/{task_id}")
async def admin_remove_task(
    task_id: int,
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    _require_admin(_get_telegram_id(x_telegram_user_id, x_user_id))
    ok = await admin_delete_task(task_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"ok": True}


# ——— Тексты страниц (косметика) ———

@router.get("/page-texts")
async def admin_list_all_page_texts(
    project_id: int = 1,
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    _require_admin(_get_telegram_id(x_telegram_user_id, x_user_id))
    return await admin_get_page_texts(page_id=None, project_id=project_id)


@router.get("/page-texts/{page_id}")
async def admin_get_page_texts_route(
    page_id: str,
    project_id: int = 1,
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    _require_admin(_get_telegram_id(x_telegram_user_id, x_user_id))
    return await admin_get_page_texts(page_id=page_id, project_id=project_id)


@router.put("/page-texts/{page_id}")
async def admin_save_page_texts(
    page_id: str,
    body: Dict[str, str],
    project_id: int = 1,
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    """body: { "key1": "value1", "key2": "value2" } — тексты для страницы page_id."""
    _require_admin(_get_telegram_id(x_telegram_user_id, x_user_id))
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Body must be object with text_key: text_value")
    texts = {str(k): str(v) for k, v in body.items()}
    await admin_set_page_texts(page_id.strip(), texts, project_id=project_id)
    return {"ok": True}


# ——— Каналы/чаты ———

@router.get("/channels")
async def admin_list_channels(
    project_id: int = 1,
    active_only: bool = False,
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    _require_admin(_get_telegram_id(x_telegram_user_id, x_user_id))
    return await admin_get_channels(project_id=project_id, active_only=active_only)


@router.post("/channels")
async def admin_create_channel(
    body: Dict[str, Any],
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    _require_admin(_get_telegram_id(x_telegram_user_id, x_user_id))
    chat_id = body.get("chat_id") or body.get("chatId")
    if chat_id is None:
        raise HTTPException(status_code=400, detail="chat_id required")
    pid = await admin_add_channel(
        project_id=int(body.get("project_id", body.get("projectId", 1))),
        chat_id=int(chat_id),
        title=body.get("title"),
        channel_type=body.get("channel_type", body.get("channelType", "channel")),
        sort_order=int(body.get("sort_order", body.get("sortOrder", 0))),
    )
    if pid is None:
        raise HTTPException(status_code=400, detail="Channel with this chat_id already exists in project")
    return {"ok": True, "id": pid}


@router.delete("/channels/{channel_id}")
async def admin_remove_channel(
    channel_id: int,
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    _require_admin(_get_telegram_id(x_telegram_user_id, x_user_id))
    ok = await admin_delete_channel(channel_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Channel not found")
    return {"ok": True}


@router.get("/check-user-in-chat")
async def admin_check_user_in_chat(
    chat_id: int,
    user_id: int,
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    """Проверить, состоит ли пользователь в чате/канале. Бот должен быть админом в чате. BOT_TOKEN в env."""
    _require_admin(_get_telegram_id(x_telegram_user_id, x_user_id))
    in_chat, status = await check_user_in_chat(chat_id, user_id)
    return {"in_chat": in_chat, "status": status}


# ——— Активность (мониторинг: сообщения, реакции, где и когда) ———

@router.post("/activity")
async def admin_record_activity(
    body: Dict[str, Any],
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    """Записать событие активности (вызов от бота или админки). event_type: message_sent, reaction_received, ... event_meta: { reaction_type?, message_id?, ... }."""
    _require_admin(_get_telegram_id(x_telegram_user_id, x_user_id))
    telegram_id = body.get("telegram_id") or body.get("telegramId")
    event_type = body.get("event_type") or body.get("eventType")
    if telegram_id is None or not event_type:
        raise HTTPException(status_code=400, detail="telegram_id and event_type required")
    await activity_log_record(
        project_id=int(body.get("project_id", body.get("projectId", 1))),
        telegram_id=int(telegram_id),
        event_type=str(event_type).strip(),
        channel_id=body.get("channel_id") or body.get("channelId"),
        event_meta=body.get("event_meta") or body.get("eventMeta"),
    )
    return {"ok": True}


@router.get("/activity/log")
async def admin_list_activity_log(
    project_id: int = 1,
    user_id: Optional[int] = None,
    telegram_id: Optional[int] = None,
    limit: int = 100,
    offset: int = 0,
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    _require_admin(_get_telegram_id(x_telegram_user_id, x_user_id))
    return await admin_get_activity_log(project_id=project_id, user_id=user_id, telegram_id=telegram_id, limit=limit, offset=offset)


@router.get("/activity/stats")
async def admin_list_activity_stats(
    project_id: int = 1,
    user_id: Optional[int] = None,
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    """Статистика по пользователям: всего сообщений, реакций, по типам реакций, последняя активность."""
    _require_admin(_get_telegram_id(x_telegram_user_id, x_user_id))
    return await admin_get_activity_stats(project_id=project_id, user_id=user_id)


# ——— Начисление админу и тест выплаты (iCryptoCheck) ———
# Включить после тестов: ADMIN_CREDIT_AND_PAYOUT_ENABLED = True
ADMIN_CREDIT_AND_PAYOUT_ENABLED = False

@router.post("/credit-me")
async def admin_credit_me(
    body: Dict[str, Any],
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    """Начислить себе (только админ) валюту. body: amount (число), currency (по умолчанию PHXPW). Пока отключено — тестируем."""
    if not ADMIN_CREDIT_AND_PAYOUT_ENABLED:
        return {"ok": False, "message": "Отключено: идёт тестирование. Включить: ADMIN_CREDIT_AND_PAYOUT_ENABLED = True в api/admin_routes.py"}
    telegram_id = _get_telegram_id(x_telegram_user_id, x_user_id)
    _require_admin(telegram_id)
    amount = int(body.get("amount", 10000))
    currency = (body.get("currency") or "PHXPW").strip().upper() or "PHXPW"
    if amount <= 0:
        raise HTTPException(status_code=400, detail="amount must be positive")
    user_id = await ensure_user(telegram_id)
    idem_key = body.get("idem_key") or f"admin_credit_me:{telegram_id}:{currency}:once"
    await add_currency_credit(user_id, currency, amount, "admin_credit", str(telegram_id), idem_key=idem_key)
    return {"ok": True, "message": f"Начислено {amount} {currency}", "telegram_id": telegram_id}


@router.post("/test-payout")
async def admin_test_payout(
    body: Dict[str, Any],
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    """Тест отправки токенов с кошелька проекта. Пока отключено — тестируем."""
    if not ADMIN_CREDIT_AND_PAYOUT_ENABLED:
        return {"ok": False, "message": "Отключено: идёт тестирование. Включить: ADMIN_CREDIT_AND_PAYOUT_ENABLED = True в api/admin_routes.py"}
    telegram_id = _get_telegram_id(x_telegram_user_id, x_user_id)
    _require_admin(telegram_id)
    amount = int(body.get("amount", 100))
    user_id = await ensure_user(telegram_id)
    if user_id is None:
        raise HTTPException(status_code=400, detail="User not found by telegram_id")
    logger.info("test-payout: telegram_id=%s user_id=%s amount=%s (iCryptoCheck: отправка по telegram_id/username)", telegram_id, user_id, amount)
    return {
        "ok": True,
        "message": "проверка прошла",
        "telegram_id": telegram_id,
        "user_id": user_id,
        "amount": amount,
        "note": "Отправка токенов на юзернейм/telegram_id по iCryptoCheck выполняется при наличии настроенного API перевода (PROJECT_WALLET_ID и метод transfer).",
    }
