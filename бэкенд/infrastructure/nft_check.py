"""
Проверка наличия у пользователя NFT, созданных/переданных с кошелька разработчика проекта.
Все NFT проекта сминчены строго с кошелька разработчика (NFT_DEV_WALLET).
Используется TonAPI v2: accounts/{address}/nfts, при необходимости nft/collections.
"""
import logging
from typing import Any, Dict, List, Optional

import httpx

from config import NFT_DEV_COLLECTIONS, NFT_DEV_WALLET, TON_API_KEY, TON_API_URL
from infrastructure.ton_address import raw_to_friendly

logger = logging.getLogger(__name__)


def _normalize_address(addr: Any) -> str:
    """Извлечь строку адреса из поля API (может быть строка или dict с ключом address)."""
    if not addr:
        return ""
    if isinstance(addr, dict):
        return (addr.get("address") or "").strip()
    return str(addr).strip()


async def _get_collection_owner(
    collection_address: str,
    *,
    ton_api_url: str,
    ton_api_key: str,
) -> str:
    """Получить owner коллекции через TonAPI v2 nft/collections."""
    if not collection_address:
        return ""
    url = f"{ton_api_url.rstrip('/')}/nfts/collections/{collection_address}"
    headers = {}
    if ton_api_key:
        headers["Authorization"] = f"Bearer {ton_api_key}"
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(url, headers=headers or None)
        if r.status_code != 200:
            return ""
        data = r.json()
        owner = data.get("owner") or data.get("collection", {}).get("owner")
        return _normalize_address(owner)
    except Exception as e:
        logger.warning("nft_check _get_collection_owner %s: %s", collection_address, e)
    return ""


def _nft_item_display(item: Dict, collection_name: str = "") -> Dict[str, Any]:
    """Собрать отображаемые поля NFT для ответа API (address, name, image, collection_name)."""
    addr = _normalize_address(item.get("address")) or _normalize_address(item.get("item_id"))
    content = item.get("content") or item.get("metadata") or {}
    name = ""
    image = ""
    if isinstance(content, dict):
        name = content.get("name") or content.get("title") or ""
        image = content.get("image") or ""
        if isinstance(image, dict):
            image = image.get("source") or image.get("url") or ""
        if not image and isinstance(content.get("preview"), dict):
            image = content["preview"].get("source") or content["preview"].get("image") or ""
    preview = item.get("preview") or {}
    if not image and isinstance(preview, dict):
        image = preview.get("source") or preview.get("image") or ""
    if isinstance(image, dict):
        image = image.get("source") or image.get("url") or ""
    if not name:
        name = item.get("name") or ""
    if not image:
        image = item.get("image") or (preview.get("source") if isinstance(preview, dict) else "") or ""
    collection = item.get("collection") or {}
    coll_name = collection_name or (collection.get("name") if isinstance(collection, dict) else "") or ""
    coll_addr = _normalize_address(collection.get("address")) if isinstance(collection, dict) else _normalize_address(item.get("collection_address")) or _normalize_address(item.get("collection_id"))
    return {
        "address": addr,
        "name": (name or "NFT").strip(),
        "image": (image or "").strip(),
        "collection_name": (coll_name or "").strip(),
        "collection_address": coll_addr,
    }


async def check_user_has_project_nft(
    wallet_address: str,
    *,
    ton_api_url: Optional[str] = None,
    ton_api_key: Optional[str] = None,
    return_items: bool = False,
) -> Dict[str, Any]:
    """
    Проверить, есть ли у владельца кошелька NFT, созданные с кошелька разработчика (NFT_DEV_WALLET).

    Возвращает: { "has_project_nft": bool, "count": int, "error": str | None, "items": list (если return_items=True) }.
    """
    result: Dict[str, Any] = {"has_project_nft": False, "count": 0, "error": None}
    if return_items:
        result["items"] = []
    if not NFT_DEV_WALLET:
        return result
    if not wallet_address or not isinstance(wallet_address, str):
        result["error"] = "wallet_required"
        return result

    base = (ton_api_url or TON_API_URL).rstrip("/")
    key = ton_api_key or TON_API_KEY
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    account_id = wallet_address.strip()
    url = f"{base}/accounts/{account_id}/nfts?limit=1000"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(url, headers=headers or None)
    except Exception as e:
        logger.warning("nft_check request failed: %s", e)
        result["error"] = "request_failed"
        return result

    if r.status_code != 200:
        logger.warning("nft_check api %s for %s body %s", r.status_code, account_id[:20], (r.text or "")[:200])
        result["error"] = f"api_{r.status_code}"
        return result

    try:
        data = r.json()
    except Exception as e:
        result["error"] = "parse_error"
        return result

    nft_items: List[Dict] = data.get("nft_items") or data.get("nfts") or []
    dev_canonical = await raw_to_friendly(NFT_DEV_WALLET) or NFT_DEV_WALLET
    dev_collections_canonical: set = set()
    for a in NFT_DEV_COLLECTIONS:
        try:
            canon = await raw_to_friendly(a) or a
            if canon:
                dev_collections_canonical.add(canon)
        except Exception:
            dev_collections_canonical.add(a.strip())

    count = 0
    seen_collections: Dict[str, bool] = {}
    items_out: List[Dict[str, Any]] = result.get("items", [])

    for item in nft_items:
        collection = item.get("collection") or {}
        if isinstance(collection, str):
            coll_addr = collection
            owner_raw = ""
            coll_name = ""
        else:
            coll_addr = _normalize_address(collection.get("address"))
            owner_raw = _normalize_address(collection.get("owner"))
            coll_name = (collection.get("name") or "").strip()

        if not coll_addr:
            continue
        if coll_addr in seen_collections:
            if seen_collections[coll_addr]:
                count += 1
                if return_items:
                    items_out.append(_nft_item_display(item, coll_name))
            continue

        coll_canonical = await raw_to_friendly(coll_addr) or coll_addr
        if dev_collections_canonical and coll_canonical in dev_collections_canonical:
            is_dev = True
        else:
            owner_friendly = ""
            if owner_raw:
                owner_friendly = await raw_to_friendly(owner_raw) or owner_raw
            else:
                owner_friendly = await _get_collection_owner(coll_addr, ton_api_url=base, ton_api_key=key)
                if owner_friendly:
                    owner_friendly = await raw_to_friendly(owner_friendly) or owner_friendly
            owner_canonical = await raw_to_friendly(owner_friendly) or owner_friendly if owner_friendly else ""
            is_dev = bool(owner_canonical and owner_canonical == dev_canonical)
        seen_collections[coll_addr] = is_dev
        if is_dev:
            count += 1
            if return_items:
                items_out.append(_nft_item_display(item, coll_name))

    if nft_items and count == 0 and dev_collections_canonical:
        logger.info("nft_check: wallet has %s nfts, 0 in dev collections %s", len(nft_items), list(dev_collections_canonical)[:2])
    elif nft_items and count == 0:
        logger.info("nft_check: wallet has %s nfts, 0 project (dev_canonical=%s)", len(nft_items), dev_canonical[:20])

    result["has_project_nft"] = count > 0
    result["count"] = count
    if return_items:
        result["items"] = items_out
    return result
