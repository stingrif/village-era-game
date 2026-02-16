"""
Проверка нахождения пользователя в чате/канале через Telegram Bot API getChatMember.
Бот должен быть добавлен в чат как администратор.
"""
import logging
import time
from typing import Dict, List, Optional, Tuple

from config import BOT_TOKEN

logger = logging.getLogger(__name__)

# Статусы участника: в чате
MEMBER_STATUSES_IN = ("creator", "administrator", "member", "restricted")
# Не в чате
MEMBER_STATUSES_OUT = ("left", "kicked")

# Cache for get_bot_chats (5 minute TTL)
_bot_chats_cache: List[Dict] = []
_bot_chats_cache_ts: float = 0.0
_BOT_CHATS_CACHE_TTL = 300  # seconds


async def check_user_in_chat(chat_id: int, user_id: int) -> Tuple[bool, Optional[str]]:
    """
    Проверить, состоит ли пользователь в чате/канале.
    Возвращает (True, status) если в чате, (False, status или error) если нет или ошибка.
    Требуется BOT_TOKEN; бот должен быть админом в чате.
    """
    if not BOT_TOKEN:
        return False, "BOT_TOKEN not set"
    try:
        import httpx
    except ImportError:
        return False, "httpx not installed"
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getChatMember"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(url, params={"chat_id": chat_id, "user_id": user_id})
            data = r.json()
        if not data.get("ok"):
            return False, data.get("description", "unknown error")
        status = (data.get("result") or {}).get("status", "")
        return status in MEMBER_STATUSES_IN, status
    except Exception as e:
        logger.exception("check_user_in_chat failed")
        return False, str(e)


async def get_bot_chats() -> List[Dict]:
    """
    Discover chats/channels where the bot is a member via getUpdates,
    then getChat for each unique chat_id to get title/type/member_count.
    Results cached for 5 min.
    """
    global _bot_chats_cache, _bot_chats_cache_ts
    if _bot_chats_cache and (time.time() - _bot_chats_cache_ts) < _BOT_CHATS_CACHE_TTL:
        return _bot_chats_cache

    if not BOT_TOKEN:
        return []

    try:
        import httpx
    except ImportError:
        return []

    chats: Dict[int, Dict] = {}
    bot_id = BOT_TOKEN.split(":")[0]

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            # Fetch recent updates to discover chat_ids
            r = await client.get(
                f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates",
                params={"limit": 100, "timeout": 0},
            )
            data = r.json()
            if data.get("ok"):
                for upd in data.get("result", []):
                    # Extract chat_id from messages, member updates, etc.
                    for field in ("message", "edited_message", "channel_post", "my_chat_member", "chat_member"):
                        obj = upd.get(field)
                        if obj:
                            chat = obj.get("chat") or {}
                            cid = chat.get("id")
                            if cid and cid != 0:
                                chats[cid] = {
                                    "chat_id": cid,
                                    "title": chat.get("title") or chat.get("first_name") or str(cid),
                                    "type": chat.get("type", "unknown"),
                                }

            # For each unique chat, call getChat for full info
            result = []
            for cid, info in chats.items():
                try:
                    r2 = await client.get(
                        f"https://api.telegram.org/bot{BOT_TOKEN}/getChat",
                        params={"chat_id": cid},
                    )
                    d2 = r2.json()
                    if d2.get("ok"):
                        chat_info = d2["result"]
                        info["title"] = chat_info.get("title") or chat_info.get("first_name") or str(cid)
                        info["type"] = chat_info.get("type", "unknown")
                        info["username"] = chat_info.get("username")
                        info["description"] = chat_info.get("description", "")

                    # Get member count
                    r3 = await client.get(
                        f"https://api.telegram.org/bot{BOT_TOKEN}/getChatMemberCount",
                        params={"chat_id": cid},
                    )
                    d3 = r3.json()
                    info["member_count"] = d3["result"] if d3.get("ok") else None

                    # Check bot's admin status
                    r4 = await client.get(
                        f"https://api.telegram.org/bot{BOT_TOKEN}/getChatMember",
                        params={"chat_id": cid, "user_id": bot_id},
                    )
                    d4 = r4.json()
                    if d4.get("ok"):
                        bot_status = d4["result"].get("status", "")
                        info["bot_status"] = bot_status
                        info["bot_is_admin"] = bot_status in ("administrator", "creator")
                    else:
                        info["bot_status"] = "unknown"
                        info["bot_is_admin"] = False

                    # Only include groups/channels (not private chats)
                    if info["type"] in ("group", "supergroup", "channel"):
                        result.append(info)
                except Exception as e:
                    logger.warning("get_bot_chats: error fetching chat %s: %s", cid, e)

        _bot_chats_cache = result
        _bot_chats_cache_ts = time.time()
        return result
    except Exception as e:
        logger.exception("get_bot_chats failed")
        return _bot_chats_cache or []
