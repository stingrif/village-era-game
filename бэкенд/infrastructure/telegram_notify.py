import logging
from typing import Optional

import httpx

from config import GAME_ADMIN_TG_ID, GAME_NOTIFY_BOT_TOKEN

logger = logging.getLogger(__name__)


async def notify_admin_phoenix_quest(
    telegram_id: int,
    username: Optional[str] = None,
    first_name: Optional[str] = None,
    reward_amount: int = 100000,
) -> bool:
    if not GAME_NOTIFY_BOT_TOKEN:
        logger.warning("GAME_NOTIFY_BOT_TOKEN not set, skip admin notify")
        return False
    text = (
        "🔥 Скрытый квест ФЕНИКС выполнен!\n"
        f"user_id / telegram_id: {telegram_id}\n"
        f"username: {username or '-'}\n"
        f"first_name: {first_name or '-'}\n"
        f"Начислено: {reward_amount} Phoenix."
    )
    url = f"https://api.telegram.org/bot{GAME_NOTIFY_BOT_TOKEN}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                url,
                json={"chat_id": GAME_ADMIN_TG_ID, "text": text},
            )
            if r.status_code != 200:
                logger.error("Telegram notify failed: %s %s", r.status_code, r.text)
                return False
            return True
    except Exception as e:
        logger.exception("Telegram notify error: %s", e)
        return False
