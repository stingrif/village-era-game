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


async def notify_user_penalty(
    telegram_id: int,
    amount: float,
    currency: str,
    comment: Optional[str] = None,
) -> bool:
    """Отправить пользователю уведомление о наложенном штрафе на вывод."""
    if not GAME_NOTIFY_BOT_TOKEN:
        logger.warning("GAME_NOTIFY_BOT_TOKEN not set, skip penalty notify")
        return False
    text = (
        "⚠️ Вам наложен штраф на вывод.\n\n"
        f"Сумма: {amount} {currency}\n"
    )
    if comment:
        text += f"Причина: {comment}\n"
    text += "\nШтраф будет удержан при следующем выводе средств."
    url = f"https://api.telegram.org/bot{GAME_NOTIFY_BOT_TOKEN}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                url,
                json={"chat_id": telegram_id, "text": text},
            )
            if r.status_code != 200:
                logger.error("Telegram penalty notify failed: %s %s", r.status_code, r.text)
                return False
            return True
    except Exception as e:
        logger.exception("Telegram penalty notify error: %s", e)
        return False
