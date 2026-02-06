"""
Проверка нахождения пользователя в чате/канале через Telegram Bot API getChatMember.
Бот должен быть добавлен в чат как администратор.
"""
import logging
from typing import Optional, Tuple

from config import BOT_TOKEN

logger = logging.getLogger(__name__)

# Статусы участника: в чате
MEMBER_STATUSES_IN = ("creator", "administrator", "member", "restricted")
# Не в чате
MEMBER_STATUSES_OUT = ("left", "kicked")


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
