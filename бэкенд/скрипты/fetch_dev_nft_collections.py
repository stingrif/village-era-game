#!/usr/bin/env python3
"""
Получить адреса коллекций NFT кошелька разработчика (TonAPI) для заполнения NFT_DEV_COLLECTIONS.
Запуск из папки бэкенд:  python скрипты/fetch_dev_nft_collections.py
Вывод: список адресов через запятую — вставьте в .env как NFT_DEV_COLLECTIONS=...
"""
import asyncio
import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
os.chdir(BACKEND_ROOT)

try:
    from dotenv import load_dotenv
    load_dotenv(BACKEND_ROOT / ".env")
except ImportError:
    pass

from config import NFT_DEV_WALLET, TON_API_KEY, TON_API_URL


def _norm_addr(addr) -> str:
    if not addr:
        return ""
    if isinstance(addr, dict):
        return (addr.get("address") or "").strip()
    return str(addr).strip()


async def main() -> int:
    if not NFT_DEV_WALLET:
        print("Задайте NFT_DEV_WALLET в .env")
        return 1
    try:
        import httpx
    except ImportError:
        print("Установите httpx: pip install httpx")
        return 1
    base = TON_API_URL.rstrip("/")
    url = f"{base}/accounts/{NFT_DEV_WALLET}/nfts?limit=1000"
    headers = {"Authorization": f"Bearer {TON_API_KEY}"} if TON_API_KEY else {}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(url, headers=headers or None)
    except Exception as e:
        print("Ошибка запроса:", e)
        return 1
    if r.status_code != 200:
        print(f"TonAPI вернул {r.status_code}. Проверьте TON_API_KEY в .env")
        return 1
    data = r.json()
    items = data.get("nft_items") or data.get("nfts") or []
    seen: set = set()
    for it in items:
        col = it.get("collection") or {}
        if isinstance(col, str):
            addr = col.strip()
        else:
            addr = _norm_addr(col.get("address")) or _norm_addr(it.get("collection_address")) or _norm_addr(it.get("collection_id"))
        if addr and addr not in seen:
            seen.add(addr)
    if not seen:
        print("У кошелька разработчика не найдено NFT по TonAPI (или формат ответа изменился).")
        return 0
    line = ",".join(sorted(seen))
    print("Вставьте в .env строку:")
    print("NFT_DEV_COLLECTIONS=" + line)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
