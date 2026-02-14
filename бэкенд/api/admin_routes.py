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
    get_all_settings,
    get_setting,
    set_setting,
    get_settings_defaults,
    get_buildings_def,
    get_all_holder_snapshots,
    get_holder_snapshots_count,
    add_withdraw_penalty,
    mark_penalty_notified,
    get_penalties_for_user,
)
from infrastructure.telegram_chat import check_user_in_chat, get_bot_chats
from infrastructure.telegram_notify import notify_user_penalty

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


# ——— Детализация дашборда ———

@router.get("/dashboard/players")
async def admin_dashboard_players(
    filter: str = "all",
    limit: int = 50,
    offset: int = 0,
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    """Список игроков с детализацией. filter: all | online | today | week."""
    _require_admin(_get_telegram_id(x_telegram_user_id, x_user_id))
    pool = await get_pool()
    where = ""
    if filter == "online":
        where = "WHERE updated_at > NOW() - INTERVAL '5 minutes'"
    elif filter == "today":
        where = "WHERE created_at > NOW() - INTERVAL '1 day'"
    elif filter == "week":
        where = "WHERE created_at > NOW() - INTERVAL '7 days'"
    async with pool.acquire() as conn:
        total = await conn.fetchval(f"SELECT COUNT(*) FROM game_players {where}") or 0
        rows = await conn.fetch(f"""
            SELECT telegram_id, username, first_name, points_balance,
                   created_at, updated_at
            FROM game_players {where}
            ORDER BY updated_at DESC
            LIMIT $1 OFFSET $2
        """, limit, offset)
        # checkin streaks for these players (join via users table)
        tg_ids = [r["telegram_id"] for r in rows]
        checkin_map = {}
        if tg_ids:
            crows = await conn.fetch("""
                SELECT u.telegram_id, cs.streak, cs.last_checkin_at,
                       ab.attempts as attempts
                FROM users u
                JOIN checkin_state cs ON cs.user_id = u.id
                LEFT JOIN attempts_balance ab ON ab.user_id = u.id
                WHERE u.telegram_id = ANY($1::bigint[])
            """, tg_ids)
            for cr in crows:
                checkin_map[cr["telegram_id"]] = {
                    "streak": cr["streak"],
                    "last_checkin": cr["last_checkin_at"].isoformat() if cr["last_checkin_at"] else None,
                    "attempts": cr["attempts"] or 0,
                }
    return {
        "total": total,
        "filter": filter,
        "players": [
            {
                "telegram_id": r["telegram_id"],
                "username": r["username"],
                "first_name": r["first_name"],
                "name": r["username"] or r["first_name"] or str(r["telegram_id"]),
                "points": r["points_balance"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                "last_active": r["updated_at"].isoformat() if r["updated_at"] else None,
                "checkin": checkin_map.get(r["telegram_id"]),
            }
            for r in rows
        ],
    }


@router.get("/dashboard/nft-details")
async def admin_dashboard_nft_details(
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    """Детальная разбивка NFT по коллекциям с уникальными владельцами."""
    _require_admin(_get_telegram_id(x_telegram_user_id, x_user_id))
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT c.id, c.name, c.collection_address, c.image, c.synced_at,
                   COUNT(n.id) AS nft_count,
                   COUNT(DISTINCT n.owner_address) FILTER (WHERE n.owner_address != '') AS unique_owners
            FROM dev_collections c
            LEFT JOIN dev_nfts n ON n.collection_id = c.id
            GROUP BY c.id
            ORDER BY nft_count DESC
        """)
        # recent NFTs
        recent = await conn.fetch("""
            SELECT n.name, n.image, n.owner_address, n.nft_address,
                   c.name as collection_name, n.synced_at
            FROM dev_nfts n
            LEFT JOIN dev_collections c ON c.id = n.collection_id
            ORDER BY n.synced_at DESC NULLS LAST
            LIMIT 10
        """)
    return {
        "collections": [
            {
                "id": r["id"],
                "name": r["name"],
                "address": r["collection_address"],
                "image": r["image"],
                "nft_count": r["nft_count"],
                "unique_owners": r["unique_owners"],
                "synced_at": r["synced_at"].isoformat() if r["synced_at"] else None,
            }
            for r in rows
        ],
        "recent_nfts": [
            {
                "name": r["name"],
                "image": r["image"],
                "owner": r["owner_address"],
                "address": r["nft_address"],
                "collection": r["collection_name"],
                "synced_at": r["synced_at"].isoformat() if r["synced_at"] else None,
            }
            for r in recent
        ],
    }


@router.get("/dashboard/checkins")
async def admin_dashboard_checkins(
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    """Детализация чекинов: кто чекинился сегодня, стрики."""
    _require_admin(_get_telegram_id(x_telegram_user_id, x_user_id))
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT u.telegram_id, cs.streak, cs.last_checkin_at,
                   gp.username, gp.first_name,
                   ab.attempts as attempts
            FROM checkin_state cs
            JOIN users u ON u.id = cs.user_id
            JOIN game_players gp ON gp.telegram_id = u.telegram_id
            LEFT JOIN attempts_balance ab ON ab.user_id = u.id
            WHERE cs.last_checkin_at > NOW() - INTERVAL '1 day'
            ORDER BY cs.last_checkin_at DESC
        """)
        max_streak = await conn.fetchval("SELECT MAX(streak) FROM checkin_state") or 0
        avg_streak = await conn.fetchval("SELECT AVG(streak)::int FROM checkin_state WHERE streak > 0") or 0
    return {
        "today": [
            {
                "telegram_id": r["telegram_id"],
                "name": r["username"] or r["first_name"] or str(r["telegram_id"]),
                "streak": r["streak"],
                "attempts": r["attempts"] or 0,
                "last_checkin": r["last_checkin_at"].isoformat() if r["last_checkin_at"] else None,
            }
            for r in rows
        ],
        "max_streak": max_streak,
        "avg_streak": avg_streak,
    }


@router.get("/dashboard/economy")
async def admin_dashboard_economy(
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    """Детализация экономики: потоки валют, последние транзакции."""
    _require_admin(_get_telegram_id(x_telegram_user_id, x_user_id))
    pool = await get_pool()
    async with pool.acquire() as conn:
        # flows by currency and kind
        flows = await conn.fetch("""
            SELECT currency, kind,
                   SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END) AS total_in,
                   SUM(CASE WHEN amount < 0 THEN ABS(amount) ELSE 0 END) AS total_out,
                   COUNT(*) AS tx_count
            FROM economy_ledger
            GROUP BY currency, kind
            ORDER BY currency, total_in DESC
        """)
        # pending payouts
        payouts = await conn.fetch("""
            SELECT pp.id, pp.telegram_id, pp.reward_type, pp.amount, pp.status, pp.created_at,
                   gp.username, gp.first_name
            FROM pending_payouts pp
            LEFT JOIN game_players gp ON gp.telegram_id = pp.telegram_id
            WHERE pp.status = 'pending'
            ORDER BY pp.created_at DESC LIMIT 20
        """)
        # recent ledger entries (join through users to get names)
        recent = await conn.fetch("""
            SELECT el.amount, el.currency, el.kind, el.ref_type, el.created_at,
                   u.telegram_id, gp.username, gp.first_name
            FROM economy_ledger el
            JOIN users u ON u.id = el.user_id
            LEFT JOIN game_players gp ON gp.telegram_id = u.telegram_id
            ORDER BY el.created_at DESC LIMIT 15
        """)
    return {
        "flows": [
            {
                "currency": r["currency"],
                "reason": r["kind"],
                "total_in": float(r["total_in"] or 0),
                "total_out": float(r["total_out"] or 0),
                "tx_count": r["tx_count"],
            }
            for r in flows
        ],
        "pending_payouts": [
            {
                "id": r["id"],
                "telegram_id": r["telegram_id"],
                "name": r["username"] or r["first_name"] or str(r["telegram_id"]),
                "amount": float(r["amount"]),
                "currency": r["reward_type"],
                "status": r["status"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            }
            for r in payouts
        ],
        "recent_transactions": [
            {
                "user": r["username"] or r["first_name"] or str(r.get("telegram_id", "?")),
                "amount": float(r["amount"]),
                "currency": r["currency"],
                "reason": r["kind"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            }
            for r in recent
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




# ——— Game Config CRUD ———

@router.get("/game-config")
async def admin_game_config_get(
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    """Return all game settings grouped by category, with defaults."""
    _require_admin(_get_telegram_id(x_telegram_user_id, x_user_id))
    settings = await get_all_settings()
    defaults = get_settings_defaults()
    # Group by category (part before first dot)
    grouped: Dict[str, list] = {}
    all_keys = set(list(settings.keys()) + list(defaults.keys()))
    for key in sorted(all_keys):
        cat = key.split(".")[0] if "." in key else "general"
        grouped.setdefault(cat, [])
        grouped[cat].append({
            "key": key,
            "value": settings.get(key, defaults.get(key)),
            "default": defaults.get(key),
        })
    return {"settings": grouped, "flat": settings, "defaults": defaults}


@router.put("/game-config")
async def admin_game_config_put(
    body: Dict[str, Any],
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    """Update game settings. Body: {key: value, ...}"""
    _require_admin(_get_telegram_id(x_telegram_user_id, x_user_id))
    updates = body.get("settings") or body  # accept {settings: {k: v}} or flat {k: v}
    if not isinstance(updates, dict):
        raise HTTPException(status_code=400, detail="settings must be a dict")
    updated = []
    for key, value in updates.items():
        if key in ("settings",):
            continue
        await set_setting(key, value)
        updated.append(key)
    return {"ok": True, "updated": updated}


@router.get("/meta")
async def admin_meta(
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    """Return available reward types, currencies, buildings list, task types, channel types, etc."""
    _require_admin(_get_telegram_id(x_telegram_user_id, x_user_id))
    reward_types = [
        {"value": "COINS", "label": "Монеты (COINS)"},
        {"value": "GEMS", "label": "Гемы (GEMS)"},
        {"value": "STARS", "label": "Звёзды (STARS)"},
        {"value": "PHXPW", "label": "Токен проекта (PHXPW)"},
        {"value": "PHOEX", "label": "PHOEX"},
        {"value": "WOOD", "label": "Дерево (WOOD)"},
        {"value": "STONE", "label": "Камень (STONE)"},
        {"value": "ATTEMPTS", "label": "Попытки шахты"},
        {"value": "POINTS", "label": "Очки (POINTS)"},
        {"value": "EGG", "label": "Яйцо (EGG)"},
        {"value": "RELIC", "label": "Реликвия"},
    ]
    currencies = ["COINS", "GEMS", "STARS", "PHXPW", "PHOEX", "WOOD", "STONE", "POINTS"]
    task_types = [
        {"value": "subscribe_channel", "label": "Подписка на канал/чат"},
        {"value": "subscribe_tg", "label": "Подписка на Telegram"},
        {"value": "visit_url", "label": "Посетить ссылку"},
        {"value": "connect_wallet", "label": "Привязать кошелёк"},
        {"value": "buy_nft", "label": "Купить NFT"},
        {"value": "checkin_streak", "label": "Стрик чекинов"},
        {"value": "mine_count", "label": "Копать N раз"},
        {"value": "invite_friend", "label": "Пригласить друга"},
        {"value": "custom", "label": "Своё условие"},
    ]
    channel_types = [
        {"value": "channel", "label": "Канал"},
        {"value": "group", "label": "Группа"},
        {"value": "supergroup", "label": "Супергруппа"},
    ]
    condition_types = [
        {"value": "subscribe_channel", "label": "Подписка на канал"},
        {"value": "hold_nft", "label": "Держать NFT"},
        {"value": "min_balance", "label": "Мин. баланс"},
        {"value": "min_level", "label": "Мин. уровень"},
        {"value": "invite_friends", "label": "Пригласить друзей"},
        {"value": "custom", "label": "Своё условие"},
    ]
    buildings = await get_buildings_def()
    channels = []
    try:
        channels = await admin_get_channels()
    except Exception:
        pass
    return {
        "reward_types": reward_types,
        "currencies": currencies,
        "task_types": task_types,
        "channel_types": channel_types,
        "condition_types": condition_types,
        "buildings": buildings,
        "channels": channels,
    }


# ——— Bot Chats (auto-detect) ———

@router.get("/bot-chats")
async def admin_bot_chats(
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    """Auto-detect chats/channels where bot is a member (cached 5 min)."""
    _require_admin(_get_telegram_id(x_telegram_user_id, x_user_id))
    chats = await get_bot_chats()
    return {"chats": chats}


# ——— NFT Holders ———

@router.get("/nft-holders")
async def admin_nft_holders(
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    """Return full list of NFT holders with analytics and TG links."""
    _require_admin(_get_telegram_id(x_telegram_user_id, x_user_id))
    holders = await get_all_holder_snapshots()
    # Add TG link for each linked user
    for h in holders:
        tg_id = h.get("linked_telegram_id")
        username = h.get("linked_username")
        if username:
            h["tg_link"] = f"https://t.me/{username}"
        elif tg_id:
            h["tg_link"] = f"tg://user?id={tg_id}"
        else:
            h["tg_link"] = None
    return {"holders": holders, "count": len(holders)}


@router.post("/nft-holders/sync")
async def admin_nft_holders_sync(
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    """Trigger manual NFT holders sync."""
    _require_admin(_get_telegram_id(x_telegram_user_id, x_user_id))
    from infrastructure.nft_sync import sync_nft_holders
    stats = await sync_nft_holders()
    return {"ok": True, **stats}


# ——— Участники (для выбора в переводах/штрафах) ———

@router.get("/participants")
async def admin_participants(
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    """Список участников игры для выбора: user_id, telegram_id, username."""
    _require_admin(_get_telegram_id(x_telegram_user_id, x_user_id))
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT u.id AS user_id, u.telegram_id, gp.username
            FROM users u
            JOIN game_players gp ON gp.telegram_id = u.telegram_id
            ORDER BY gp.updated_at DESC NULLS LAST
            LIMIT 500
        """)
    return {
        "participants": [
            {"user_id": r["user_id"], "telegram_id": str(r["telegram_id"]), "username": r["username"] or ""}
            for r in rows
        ],
    }


@router.get("/transfer/currencies")
async def admin_transfer_currencies(
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    """Доступные валюты для перевода и ограничения (если есть)."""
    _require_admin(_get_telegram_id(x_telegram_user_id, x_user_id))
    return {
        "currencies": [{"value": "PHXPW", "label": "PHXPW"}, {"value": "TON", "label": "TON"}],
        "limits_note": "Лимиты и комиссии задаются в iCryptoCheck.",
        "penalty_note": "Штраф удерживается при следующем выводе средств пользователем.",
    }


@router.post("/transfer")
async def admin_transfer(
    body: Dict[str, Any],
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    """Перевод пользователю через iCryptoCheck (награда). body: telegram_id, amount, currency, description."""
    _require_admin(_get_telegram_id(x_telegram_user_id, x_user_id))
    from config import ICRYPTOCHECK_API_KEY, ICRYPTOCHECK_API_URL
    import httpx
    telegram_id_raw = body.get("telegram_id")
    if telegram_id_raw is None:
        raise HTTPException(status_code=400, detail="telegram_id required")
    try:
        telegram_id = str(int(telegram_id_raw))
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="telegram_id must be number")
    amount = body.get("amount")
    if amount is None:
        raise HTTPException(status_code=400, detail="amount required")
    try:
        amount_val = float(amount)
        if amount_val <= 0:
            raise ValueError("must be positive")
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="amount must be positive number")
    currency = (body.get("currency") or "PHXPW").strip().upper() or "PHXPW"
    description = (body.get("description") or "").strip() or "награда"
    if not ICRYPTOCHECK_API_KEY:
        raise HTTPException(status_code=503, detail="iCryptoCheck not configured (ICRYPTOCHECK_API_KEY)")
    payload = {
        "tgUserId": telegram_id,
        "currency": currency,
        "amount": str(int(amount_val)) if amount_val == int(amount_val) else str(amount_val),
        "description": description,
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                f"{ICRYPTOCHECK_API_URL}/app/transfer",
                headers={"iCryptoCheck-Key": ICRYPTOCHECK_API_KEY, "Content-Type": "application/json"},
                json=payload,
            )
    except Exception as e:
        logger.exception("admin transfer request failed: %s", e)
        raise HTTPException(status_code=502, detail=str(e))
    if r.status_code not in (200, 201):
        try:
            err = r.json()
            raise HTTPException(status_code=502, detail=err.get("message", r.text[:200]))
        except Exception:
            raise HTTPException(status_code=502, detail=r.text[:200] or "transfer failed")
    data = r.json()
    if not data.get("success"):
        raise HTTPException(status_code=502, detail=data.get("message", "transfer failed"))
    return {"ok": True, "data": data.get("data"), "message": "Перевод отправлен"}


@router.post("/penalty")
async def admin_penalty(
    body: Dict[str, Any],
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    """Наложить штраф на вывод. body: telegram_id, amount, currency, comment, notify_user (bool). Штраф сработает при выводе."""
    admin_tg_id = _get_telegram_id(x_telegram_user_id, x_user_id)
    _require_admin(admin_tg_id)
    telegram_id_raw = body.get("telegram_id")
    if telegram_id_raw is None:
        raise HTTPException(status_code=400, detail="telegram_id required")
    try:
        telegram_id = int(telegram_id_raw)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="telegram_id must be number")
    amount = body.get("amount")
    if amount is None:
        raise HTTPException(status_code=400, detail="amount required")
    try:
        amount_val = float(amount)
        if amount_val <= 0:
            raise ValueError("must be positive")
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="amount must be positive number")
    currency = (body.get("currency") or "PHXPW").strip().upper() or "PHXPW"
    comment = (body.get("comment") or "").strip()
    notify_user = bool(body.get("notify_user"))
    user_id = await ensure_user(telegram_id)
    penalty_id = await add_withdraw_penalty(
        user_id=user_id,
        amount=amount_val,
        currency=currency,
        reason=comment or None,
        notify_user=notify_user,
        created_by_telegram_id=admin_tg_id,
    )
    if notify_user:
        sent = await notify_user_penalty(telegram_id, amount_val, currency, comment or None)
        if sent:
            await mark_penalty_notified(penalty_id)
    return {"ok": True, "penalty_id": penalty_id, "message": "Штраф наложен. Будет удержан при выводе."}


@router.get("/penalties/{telegram_id}")
async def admin_penalties_for_user(
    telegram_id: int,
    x_telegram_user_id: Optional[str] = Header(None, alias="X-Telegram-User-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    """Список штрафов по пользователю (telegram_id)."""
    _require_admin(_get_telegram_id(x_telegram_user_id, x_user_id))
    user_id = await ensure_user(telegram_id)
    penalties = await get_penalties_for_user(user_id)
    return {"penalties": penalties}


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
