"""
Проверка транзакций верификации кошелька через TonAPI.
Ищет входящие TonTransfer (0.1 TON) или JettonTransfer (PHXPW) с комментарием verify:{telegram_id}.
"""
import logging
from typing import Any, Dict, Optional

import httpx

from config import PHOEX_TOKEN_ADDRESS, TON_API_KEY, TON_API_URL

logger = logging.getLogger(__name__)

MIN_TON_AMOUNT = 0.09
MIN_PHXPW_AMOUNT = 4400.0
PHXPW_DECIMALS = 9


def _get_sender_from_source(source: Optional[Dict]) -> str:
    """Извлечь адрес отправителя из source/sender в разных форматах TonAPI."""
    if not source:
        return ""
    if isinstance(source, dict):
        return source.get("address") or source.get("account", {}).get("address") or ""
    return ""


def _parse_comment(payload: Optional[Dict]) -> str:
    """Извлечь текстовый комментарий из decoded_body или comment."""
    if not payload:
        return ""
    # decoded_body.text (base64 decoded text)
    decoded = payload.get("decoded_body") or payload
    if isinstance(decoded, dict):
        return decoded.get("text") or decoded.get("comment") or ""
    return payload.get("comment", "")


async def find_verification_tx(
    project_wallet: str,
    verify_comment: str,
    *,
    ton_api_url: Optional[str] = None,
    ton_api_key: Optional[str] = None,
    jetton_master: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Найти транзакцию верификации: 0.1 TON или >= 4400 PHXPW с комментарием verify_comment.

    Запрашивает GET /accounts/{project_wallet}/events?limit=50, перебирает actions,
    ищет TonTransfer с amount >= 0.09 TON и comment == verify_comment
    или JettonTransfer с jetton == PHOEX и amount >= 4400 PHXPW и comment == verify_comment.

    Returns:
        {"sender": str, "amount": float, "tx_hash": str, "method": "ton"|"phxpw"} или None
    """
    if not project_wallet or not verify_comment:
        return None
    base = (ton_api_url or TON_API_URL).rstrip("/")
    key = ton_api_key or TON_API_KEY
    jetton = (jetton_master or PHOEX_TOKEN_ADDRESS or "").strip()
    url = f"{base}/accounts/{project_wallet}/events"
    params = {"limit": 50}
    headers = {}
    if key:
        headers["Authorization"] = f"Bearer {key}"

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(url, params=params, headers=headers or None)
            if r.status_code != 200:
                logger.warning("TonAPI events status %s for %s", r.status_code, url)
                return None
            data = r.json()
    except Exception as e:
        logger.warning("TonAPI request failed: %s", e)
        return None

    events = data.get("events") or []
    for event in events:
        event_id = event.get("event_id") or event.get("hash") or ""
        actions = event.get("actions") or []
        for action in actions:
            atype = action.get("type") or ""
            # TonTransfer: amount в наноTON, comment в decoded_body или comment
            if atype in ("TonTransfer", "ton_transfer"):
                tt = action.get("TonTransfer") or action.get("ton_transfer") or {}
                comment = _parse_comment(tt) or tt.get("comment", "")
                if comment.strip() != verify_comment.strip():
                    continue
                amount_raw = tt.get("amount") or 0
                try:
                    amount_ton = int(amount_raw) / 1e9
                except (TypeError, ValueError):
                    amount_ton = 0.0
                if amount_ton < MIN_TON_AMOUNT:
                    continue
                source = tt.get("source") or tt.get("sender") or {}
                sender = _get_sender_from_source(source)
                if sender:
                    return {
                        "sender": sender,
                        "amount": amount_ton,
                        "tx_hash": event_id,
                        "method": "ton",
                    }
            # JettonTransfer: amount в raw (nanounits для jetton, обычно 9 decimals).
            # Принимаем по comment + amount; в TonAPI jetton может приходить как wallet, не master — не фильтруем по адресу.
            if atype in ("JettonTransfer", "jetton_transfer"):
                jt = action.get("JettonTransfer") or action.get("jetton_transfer") or {}
                comment = _parse_comment(jt) or jt.get("comment", "")
                if comment.strip() != verify_comment.strip():
                    continue
                amount_raw = jt.get("amount") or "0"
                try:
                    amount_human = int(amount_raw) / (10 ** PHXPW_DECIMALS)
                except (TypeError, ValueError):
                    amount_human = 0.0
                if amount_human < MIN_PHXPW_AMOUNT:
                    continue
                source = jt.get("source") or jt.get("sender") or {}
                sender = _get_sender_from_source(source)
                if sender:
                    return {
                        "sender": sender,
                        "amount": amount_human,
                        "tx_hash": event_id,
                        "method": "phxpw",
                    }
    return None
