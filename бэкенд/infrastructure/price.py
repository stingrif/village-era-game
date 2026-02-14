"""
Курсы для конвертации цен: PHXPW/PHOEX в TON и USD, TON в USD.
Используется DYOR API (api.dyor.io) и CoinGecko для TON/USD. Кэш 5 минут.
"""
import logging
import time
from typing import Any, Dict, Optional

import httpx

from config import PHOEX_TOKEN_ADDRESS

logger = logging.getLogger(__name__)

DYOR_JETTON_URL = "https://api.dyor.io/v1/jettons/{token}"
COINGECKO_TON_USD_URL = "https://api.coingecko.com/api/v3/simple/price?ids=ton&vs_currencies=usd"
_CACHE: Dict[str, Any] = {}
_CACHE_TTL_SEC = 300  # 5 минут


def _format_small_decimal(value: float, decimals: int = 8) -> str:
    """Форматирует маленькое число без научной нотации (0.0000240 вместо 2.4e-05)."""
    s = f"{value:.{decimals}f}".rstrip("0").rstrip(".")
    return s if s else "0"


async def get_phxpw_price_ton(force_refresh: bool = False) -> float:
    """
    Цена 1 PHXPW в TON (сколько TON за 1 токен).
    При ошибке возвращает fallback 0.000024 (примерно актуально).
    """
    now = time.monotonic()
    if not force_refresh and _CACHE.get("phxpw_price_ton") is not None:
        if now - (_CACHE.get("_ts") or 0) < _CACHE_TTL_SEC:
            return float(_CACHE["phxpw_price_ton"])
    token = (PHOEX_TOKEN_ADDRESS or "").strip()
    if not token:
        return 0.000024
    try:
        url = DYOR_JETTON_URL.format(token=token)
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(url, headers={"Accept": "application/json"})
        if r.status_code != 200:
            logger.warning("DYOR jetton status %s", r.status_code)
            return _CACHE.get("phxpw_price_ton") or 0.000024
        data = r.json()
        details = data.get("details") or {}
        if isinstance(details, dict):
            p = details.get("price") or {}
            if isinstance(p, dict) and p.get("value") is not None:
                dec = int(p.get("decimals", 9))
                price = int(p["value"]) / (10 ** dec)
                _CACHE["phxpw_price_ton"] = price
                _CACHE["_ts"] = now
                return float(price)
    except Exception as e:
        logger.warning("get_phxpw_price_ton: %s", e)
    return _CACHE.get("phxpw_price_ton") or 0.000024


async def _get_ton_price_usd(force_refresh: bool = False) -> Optional[float]:
    """Цена 1 TON в USD. Кэш общий с get_rates."""
    now = time.monotonic()
    if not force_refresh and _CACHE.get("ton_price_usd") is not None:
        if now - (_CACHE.get("_ts") or 0) < _CACHE_TTL_SEC:
            return float(_CACHE["ton_price_usd"])
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(COINGECKO_TON_USD_URL)
        if r.status_code != 200:
            return _CACHE.get("ton_price_usd")
        data = r.json()
        ton_data = data.get("ton") or data.get("the-open-network") or {}
        if isinstance(ton_data, dict) and ton_data.get("usd") is not None:
            val = float(ton_data["usd"])
            _CACHE["ton_price_usd"] = val
            _CACHE["_ts"] = now
            return val
    except Exception as e:
        logger.warning("_get_ton_price_usd: %s", e)
    return _CACHE.get("ton_price_usd")


async def get_rates(force_refresh: bool = False) -> Dict[str, Any]:
    """
    Возвращает курсы для фронта в читаемом виде (без научной нотации):
    - phxpw_price_ton: строка, например "0.000024" (цена 1 PHXPW в TON)
    - phxpw_price_usd: строка, например "0.0000349" (цена 1 PHXPW в USD)
    - ton_price_usd: число или строка, например 1.46 (цена 1 TON в USD)
    Для расчётов на фронте использовать parseFloat(phxpw_price_ton).
    """
    phxpw_ton = await get_phxpw_price_ton(force_refresh=force_refresh)
    ton_usd = await _get_ton_price_usd(force_refresh=force_refresh)

    result: Dict[str, Any] = {
        "phxpw_price_ton": _format_small_decimal(phxpw_ton),
    }
    if ton_usd is not None:
        result["ton_price_usd"] = round(ton_usd, 2)

    token = (PHOEX_TOKEN_ADDRESS or "").strip()
    if not token:
        return result
    try:
        url = DYOR_JETTON_URL.format(token=token)
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(url, headers={"Accept": "application/json"})
        if r.status_code != 200:
            return result
        data = r.json()
        details = data.get("details") or {}
        if isinstance(details, dict):
            pu = details.get("priceUsd") or {}
            if isinstance(pu, dict) and pu.get("value") is not None:
                dec = int(pu.get("decimals", 7))
                phxpw_usd = int(pu["value"]) / (10 ** dec)
                result["phxpw_price_usd"] = _format_small_decimal(phxpw_usd, 7)
    except Exception:
        pass
    return result
