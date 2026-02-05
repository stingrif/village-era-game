"""
Placeholder for 100k Phoenix payout on PHOENIX quest completion.
Wire to project wallet / jetton transfer (TON API or internal payout service).
"""
import logging
from typing import Optional

from config import PHOENIX_QUEST_REWARD_AMOUNT

logger = logging.getLogger(__name__)


async def schedule_phoenix_quest_payout(
    telegram_id: int,
    username: Optional[str] = None,
    amount: int = PHOENIX_QUEST_REWARD_AMOUNT,
) -> None:
    """
    Schedule or record 100k Phoenix payout for PHOENIX quest.
    Integrate with PROJECT_WALLET_ADDRESS and PHOEX_TOKEN_ADDRESS
    (e.g. TON API jetton transfer or iCryptoCheck transfer to Telegram user).
    """
    logger.info(
        "Phoenix quest payout: telegram_id=%s username=%s amount=%s (wire to jetton/transfer)",
        telegram_id,
        username,
        amount,
    )
    # TODO: enqueue to payout worker or call TON/iCryptoCheck API to send
    # PHOEX_TOKEN_ADDRESS jetton to user (by telegram_id or bound wallet)
