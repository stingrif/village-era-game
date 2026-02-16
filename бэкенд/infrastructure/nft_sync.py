"""
Синхронизация NFT-каталога разработчика из TonAPI v2.

Подход:
1. Получаем все NFT с кошелька разработчика: GET /v2/accounts/{DEV_WALLET}/nfts
2. Для каждого NFT достаём collection.address и collection.owner — оставляем только те коллекции,
   где owner == DEV_WALLET (т.е. разработчик СОЗДАЛ коллекцию, а не просто купил чужой NFT).
3. Для каждой такой коллекции подтягиваем метаданные: GET /v2/nfts/collections/{addr}
4. Сохраняем NFT из этих коллекций в dev_nfts (те, что сейчас на кошельке).
5. Для поиска NFT, уже переданных юзерам, используем search endpoint:
   GET /v2/accounts/{DEV_WALLET}/nfts?collection={coll_addr}&indirect_ownership=true
   или просто GET /v2/nfts/collections/{addr}/items (с fallback если 404).

Запуск:
  - Фоновая задача при старте приложения.
  - Периодически каждые 30 мин.
  - Вручную через POST /api/game/nft/sync (admin).
"""
import asyncio
import logging
from typing import Any, Dict, List, Optional, Set

import httpx

from config import NFT_DEV_COLLECTIONS, NFT_DEV_WALLET, PHOEX_TOKEN_ADDRESS, TON_API_KEY, TON_API_URL
from infrastructure.database import (
    clear_dev_collections,
    get_nft_owners_with_links,
    log_nft_sync,
    upsert_dev_collection,
    upsert_dev_nft,
    upsert_holder_snapshot,
)
from infrastructure.ton_address import raw_to_friendly

logger = logging.getLogger(__name__)

_API_DELAY = 1.0  # секунд между запросами (rate-limit TonAPI)


def _addr(obj: Any) -> str:
    """Извлечь адрес из строки или dict(address=...)."""
    if not obj:
        return ""
    if isinstance(obj, dict):
        return (obj.get("address") or "").strip()
    return str(obj).strip()


def _extract_metadata(item: Dict) -> Dict[str, Any]:
    """Извлечь name, description, image, attributes, metadata_url из NFT item."""
    content = item.get("content") or item.get("metadata") or {}
    previews = item.get("previews") or item.get("preview") or []

    name = ""
    description = ""
    image = ""
    attributes: list = []
    metadata_url = ""

    if isinstance(content, dict):
        name = content.get("name") or content.get("title") or ""
        description = content.get("description") or ""
        image = content.get("image") or ""
        if isinstance(image, dict):
            image = image.get("source") or image.get("url") or ""
        attributes = content.get("attributes") or []
        metadata_url = content.get("external_url") or ""

    # Fallback image из previews
    if not image:
        if isinstance(previews, list):
            for p in previews:
                if isinstance(p, dict):
                    url = p.get("url") or p.get("source") or ""
                    res = p.get("resolution") or ""
                    if url and ("500x500" in res or "100x100" in res or not image):
                        image = url
        elif isinstance(previews, dict):
            image = previews.get("source") or previews.get("image") or previews.get("url") or ""

    if not name:
        name = item.get("name") or ""
    if not image:
        image = item.get("image") or ""
    if isinstance(image, dict):
        image = image.get("source") or image.get("url") or ""
    if not metadata_url:
        metadata_url = item.get("metadata_url") or item.get("content_url") or ""

    return {
        "name": (name or "NFT").strip(),
        "description": (description or "").strip(),
        "image": (image or "").strip(),
        "attributes": attributes if isinstance(attributes, list) else [],
        "metadata_url": (metadata_url or "").strip(),
    }


async def _api_get(client: httpx.AsyncClient, path: str, params: Optional[Dict] = None) -> Optional[Dict]:
    """GET-запрос к TonAPI v2 с авторизацией."""
    base = TON_API_URL.rstrip("/")
    url = f"{base}{path}"
    headers = {}
    if TON_API_KEY:
        headers["Authorization"] = f"Bearer {TON_API_KEY}"
    try:
        r = await client.get(url, headers=headers or None, params=params)
        if r.status_code == 200:
            return r.json()
        if r.status_code != 404:
            logger.warning("TonAPI %s → %s", url, r.status_code)
    except Exception as e:
        logger.warning("TonAPI request error %s: %s", path, e)
    return None


async def _canonical(addr: str) -> str:
    """Привести адрес к каноническому виду (UQ...) для сравнения."""
    if not addr:
        return ""
    return await raw_to_friendly(addr) or addr


async def _get_collection_meta(client: httpx.AsyncClient, coll_addr_raw: str) -> Optional[Dict]:
    """Получить метаданные коллекции: name, description, image, next_item_index, owner."""
    data = await _api_get(client, f"/nfts/collections/{coll_addr_raw}")
    if not data:
        return None
    meta = data.get("metadata") or {}
    owner_raw = _addr(data.get("owner"))
    previews = data.get("previews") or []
    coll_image = (meta.get("image") or "").strip()
    if not coll_image and isinstance(previews, list):
        for p in previews:
            if isinstance(p, dict):
                coll_image = p.get("url") or p.get("source") or ""
                if coll_image:
                    break
    return {
        "name": (meta.get("name") or data.get("name") or "").strip(),
        "description": (meta.get("description") or "").strip(),
        "image": coll_image,
        "items_count": data.get("next_item_index") or 0,
        "owner_raw": owner_raw,
    }


async def run_full_sync() -> Dict[str, Any]:
    """
    Полная синхронизация NFT-каталога разработчика.

    Алгоритм:
    1. GET /accounts/{DEV_WALLET}/nfts → все NFT на кошельке
    2. Из каждого NFT достаём collection.address
    3. Принудительно добавляем коллекции из NFT_DEV_COLLECTIONS (.env)
    4. Автообнаружение: TonCenter v3 /nft/collections?owner_address=DEV_WALLET
       (находит коллекции, у которых все NFT уже переданы юзерам)
    5. Для каждой уникальной коллекции → GET /nfts/collections/{addr} → проверяем owner == DEV_WALLET
    6. Только коллекции, созданные разработчиком, попадают в dev_collections
    7. NFT из этих коллекций → dev_nfts
    """
    stats = {"collections_synced": 0, "nfts_synced": 0, "errors": 0}

    if not NFT_DEV_WALLET:
        logger.info("nft_sync: NFT_DEV_WALLET не задан — пропуск")
        await log_nft_sync("full", 0, 0, 0)
        return stats

    dev_canonical = await _canonical(NFT_DEV_WALLET)
    logger.info("nft_sync: starting, dev_wallet=%s (canonical=%s)", NFT_DEV_WALLET, dev_canonical)

    # Очищаем старые данные перед полным ресинком
    await clear_dev_collections()

    async with httpx.AsyncClient(timeout=20.0) as client:
        # ── Шаг 1: получить все NFT с кошелька разработчика ──
        data = await _api_get(client, f"/accounts/{NFT_DEV_WALLET}/nfts", {"limit": "1000"})
        if not data:
            logger.warning("nft_sync: не удалось получить NFT кошелька разработчика")
            await log_nft_sync("full", 0, 0, 1)
            stats["errors"] = 1
            return stats

        all_wallet_nfts = data.get("nft_items") or data.get("nfts") or []
        logger.info("nft_sync: получено %d NFT с кошелька", len(all_wallet_nfts))

        # ── Шаг 2: собрать уникальные коллекции ──
        # raw_addr → { nft_items: [...], coll_info_from_nft: {...} }
        collections_raw: Dict[str, Dict] = {}
        for item in all_wallet_nfts:
            coll = item.get("collection") or {}
            if isinstance(coll, str):
                coll_addr_raw = coll.strip()
                coll_name = ""
            elif isinstance(coll, dict):
                coll_addr_raw = _addr(coll.get("address"))
                coll_name = (coll.get("name") or "").strip()
            else:
                continue
            if not coll_addr_raw:
                continue
            if coll_addr_raw not in collections_raw:
                collections_raw[coll_addr_raw] = {
                    "name": coll_name,
                    "nft_items": [],
                }
            collections_raw[coll_addr_raw]["nft_items"].append(item)

        logger.info("nft_sync: найдено %d уникальных коллекций на кошельке", len(collections_raw))

        # ── Принудительный список из .env ──
        forced_addrs: Set[str] = set()
        if NFT_DEV_COLLECTIONS:
            for a in NFT_DEV_COLLECTIONS:
                a = a.strip()
                if a:
                    forced_addrs.add(a)
                    if a not in collections_raw:
                        collections_raw[a] = {"name": "", "nft_items": []}

        # ── Автообнаружение коллекций по owner через TonCenter v3 ──
        try:
            tc_url = "https://toncenter.com/api/v3/nft/collections"
            tc_params = {"owner_address": NFT_DEV_WALLET, "limit": "50"}
            r = await client.get(tc_url, params=tc_params)
            if r.status_code == 200:
                tc_data = r.json()
                tc_collections = tc_data.get("nft_collections", [])
                for c in tc_collections:
                    tc_addr = (c.get("address") or "").strip()
                    if tc_addr and tc_addr not in collections_raw:
                        collections_raw[tc_addr] = {"name": "", "nft_items": []}
                        forced_addrs.add(tc_addr)
                        logger.info("nft_sync: автообнаружена коллекция %s (TonCenter)", tc_addr[:20])
                logger.info("nft_sync: TonCenter v3 вернул %d коллекций owner=%s",
                            len(tc_collections), NFT_DEV_WALLET[:20])
            else:
                logger.warning("nft_sync: TonCenter v3 collections → %s", r.status_code)
        except Exception as e:
            logger.warning("nft_sync: TonCenter v3 discovery error: %s", e)

        # ── Шаг 3: для каждой коллекции проверяем owner ──
        dev_coll_ids: Dict[str, int] = {}  # raw_addr → db id

        for coll_addr_raw, coll_data in collections_raw.items():
            try:
                await asyncio.sleep(_API_DELAY)
                meta = await _get_collection_meta(client, coll_addr_raw)

                # Проверяем: разработчик ли владелец?
                is_dev_collection = coll_addr_raw in forced_addrs
                if not is_dev_collection and meta and meta.get("owner_raw"):
                    owner_canonical = await _canonical(meta["owner_raw"])
                    is_dev_collection = (owner_canonical == dev_canonical)

                if not is_dev_collection:
                    continue

                # Это коллекция разработчика — сохраняем
                coll_canonical = await _canonical(coll_addr_raw)
                coll_name = ""
                coll_desc = ""
                coll_image = ""
                items_count = 0
                if meta:
                    coll_name = meta["name"]
                    coll_desc = meta["description"]
                    coll_image = meta["image"]
                    items_count = meta["items_count"]
                if not coll_name:
                    coll_name = coll_data.get("name") or ""

                coll_id = await upsert_dev_collection(
                    collection_address=coll_canonical,
                    name=coll_name,
                    description=coll_desc,
                    image=coll_image,
                    creator_address=dev_canonical,
                    items_count=items_count,
                )
                dev_coll_ids[coll_addr_raw] = coll_id
                stats["collections_synced"] += 1
                logger.info("nft_sync: коллекция «%s» (%s) — %d items", coll_name, coll_canonical[:20], items_count)

            except Exception as e:
                logger.warning("nft_sync: ошибка коллекции %s: %s", coll_addr_raw[:20], e)
                stats["errors"] += 1

        if not dev_coll_ids:
            logger.info("nft_sync: не найдено коллекций разработчика")
            await log_nft_sync("full", 0, 0, stats["errors"])
            return stats

        # ── Шаг 4: сохраняем NFT из коллекций разработчика ──
        # a) NFT, найденные на кошельке разработчика
        for coll_addr_raw, coll_id in dev_coll_ids.items():
            coll_data = collections_raw.get(coll_addr_raw, {})
            coll_canonical = await _canonical(coll_addr_raw)
            for item in coll_data.get("nft_items", []):
                try:
                    nft_addr = _addr(item.get("address"))
                    if not nft_addr:
                        continue
                    owner = _addr(item.get("owner")) or _addr(item.get("owner_address"))
                    if owner:
                        owner = await _canonical(owner)
                    meta = _extract_metadata(item)
                    nft_index = item.get("index") or 0
                    if isinstance(nft_index, str):
                        try:
                            nft_index = int(nft_index)
                        except ValueError:
                            nft_index = 0

                    await upsert_dev_nft(
                        nft_address=nft_addr,
                        collection_id=coll_id,
                        collection_address=coll_canonical,
                        nft_index=nft_index,
                        owner_address=owner or dev_canonical,
                        name=meta["name"],
                        description=meta["description"],
                        image=meta["image"],
                        metadata_url=meta["metadata_url"],
                        attributes=meta["attributes"],
                    )
                    stats["nfts_synced"] += 1
                except Exception as e:
                    logger.warning("nft_sync: ошибка NFT %s: %s", _addr(item.get("address"))[:20], e)
                    stats["errors"] += 1

        # b) Попытка загрузить ВСЕ NFT каждой коллекции (включая переданные юзерам)
        for coll_addr_raw, coll_id in dev_coll_ids.items():
            try:
                await asyncio.sleep(_API_DELAY)
                coll_canonical = await _canonical(coll_addr_raw)
                # Пробуем /nfts/collections/{addr}/items
                items_data = await _api_get(
                    client,
                    f"/nfts/collections/{coll_addr_raw}/items",
                    {"limit": "1000", "offset": "0"},
                )
                if not items_data:
                    # Fallback: пробуем без /items (некоторые версии API)
                    continue
                items = items_data.get("nft_items") or items_data.get("nfts") or []
                for item in items:
                    try:
                        nft_addr = _addr(item.get("address"))
                        if not nft_addr:
                            continue
                        owner = _addr(item.get("owner")) or _addr(item.get("owner_address"))
                        if owner:
                            owner = await _canonical(owner)
                        meta = _extract_metadata(item)
                        nft_index = item.get("index") or 0
                        if isinstance(nft_index, str):
                            try:
                                nft_index = int(nft_index)
                            except ValueError:
                                nft_index = 0
                        await upsert_dev_nft(
                            nft_address=nft_addr,
                            collection_id=coll_id,
                            collection_address=coll_canonical,
                            nft_index=nft_index,
                            owner_address=owner,
                            name=meta["name"],
                            description=meta["description"],
                            image=meta["image"],
                            metadata_url=meta["metadata_url"],
                            attributes=meta["attributes"],
                        )
                        stats["nfts_synced"] += 1
                    except Exception as e:
                        stats["errors"] += 1
            except Exception as e:
                logger.warning("nft_sync: items fetch error %s: %s", coll_addr_raw[:20], e)

    await log_nft_sync("full", stats["collections_synced"], stats["nfts_synced"], stats["errors"])
    logger.info(
        "nft_sync complete: %d collections, %d nfts, %d errors",
        stats["collections_synced"], stats["nfts_synced"], stats["errors"],
    )
    return stats


# ===================== NFT Holders Sync =====================

async def sync_nft_holders() -> Dict[str, Any]:
    """
    Sync NFT holder analytics:
    1. Get unique owners from dev_nfts
    2. For each owner, fetch PHXPW balance and transfer history from TonAPI
    3. Cross-reference with wallet bindings for linked TG users
    4. Upsert into nft_holder_snapshots
    """
    stats = {"holders_synced": 0, "errors": 0}
    owners = await get_nft_owners_with_links()
    if not owners:
        logger.info("sync_nft_holders: no NFT owners found")
        return stats

    jetton_master = PHOEX_TOKEN_ADDRESS or ""
    headers = {}
    if TON_API_KEY:
        headers["Authorization"] = f"Bearer {TON_API_KEY}"

    try:
        async with httpx.AsyncClient(timeout=15.0, headers=headers) as client:
            for owner_row in owners:
                addr = owner_row["owner_address"]
                if not addr:
                    continue
                nft_count = owner_row["nft_count"]
                coll_names = owner_row.get("collection_names") or []
                coll_addrs = owner_row.get("collection_addresses") or []
                collections = [
                    {"name": n, "address": a}
                    for n, a in zip(coll_names, coll_addrs)
                ] if coll_names else []
                linked_tg_id = owner_row.get("linked_telegram_id")
                linked_username = owner_row.get("linked_username")

                phxpw_balance = 0.0
                total_received = 0.0
                total_sent = 0.0

                # Fetch PHXPW balance from TonAPI
                if jetton_master:
                    try:
                        await asyncio.sleep(1.2)  # rate limit
                        r = await client.get(
                            f"{TON_API_URL}/accounts/{addr}/jettons/{jetton_master}"
                        )
                        if r.status_code == 200:
                            data = r.json()
                            raw_balance = data.get("balance") or "0"
                            # PHXPW has 9 decimals
                            try:
                                phxpw_balance = int(raw_balance) / 1_000_000_000
                            except (ValueError, TypeError):
                                phxpw_balance = 0.0
                    except Exception as e:
                        logger.warning("sync_holders: balance fetch %s: %s", addr[:16], e)

                    # Fetch jetton transfer history
                    try:
                        await asyncio.sleep(1.2)
                        r = await client.get(
                            f"{TON_API_URL}/accounts/{addr}/jettons/{jetton_master}/history",
                            params={"limit": 100},
                        )
                        if r.status_code == 200:
                            events = r.json().get("events") or []
                            for ev in events:
                                for action in ev.get("actions") or []:
                                    jt = action.get("JettonTransfer") or {}
                                    amount_raw = jt.get("amount") or "0"
                                    try:
                                        amount = int(amount_raw) / 1_000_000_000
                                    except (ValueError, TypeError):
                                        amount = 0.0
                                    sender = _addr(jt.get("sender")) or ""
                                    recipient = _addr(jt.get("recipient")) or ""
                                    # Normalize addresses for comparison
                                    if sender and sender.lower() == addr.lower():
                                        total_sent += amount
                                    elif recipient and recipient.lower() == addr.lower():
                                        total_received += amount
                    except Exception as e:
                        logger.warning("sync_holders: history fetch %s: %s", addr[:16], e)

                try:
                    await upsert_holder_snapshot(
                        owner_address=addr,
                        nft_count=nft_count,
                        collections=collections,
                        phxpw_balance=phxpw_balance,
                        total_received=total_received,
                        total_sent=total_sent,
                        staking_rewards=0,  # TODO: integrate with staking system
                        linked_telegram_id=linked_tg_id,
                        linked_username=linked_username,
                    )
                    stats["holders_synced"] += 1
                except Exception as e:
                    logger.warning("sync_holders: upsert error %s: %s", addr[:16], e)
                    stats["errors"] += 1

    except Exception as e:
        logger.exception("sync_nft_holders failed: %s", e)

    logger.info("sync_nft_holders complete: %d holders, %d errors", stats["holders_synced"], stats["errors"])
    return stats
