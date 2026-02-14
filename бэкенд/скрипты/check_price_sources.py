#!/usr/bin/env python3
"""
Диагностика источников цены токена для проекта Игра.
Проверяет: конфиг, TonAPI, DYOR (api.dyor.io/v1/jettons/...).
Запуск из папки бэкенд:  python скрипты/check_price_sources.py
"""
import asyncio
import logging
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(BACKEND_ROOT / ".env")
except ImportError:
    pass

import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def check_price_sources():
    """Проверка конфигурации и API источников цены."""
    print("=" * 60)
    print("🔍 ДИАГНОСТИКА ИСТОЧНИКОВ ЦЕНЫ (Игра)")
    print("=" * 60)

    # 1. Конфигурация
    print("\n1️⃣ КОНФИГУРАЦИЯ")
    print("-" * 60)
    token = getattr(config, "PHOEX_TOKEN_ADDRESS", "") or getattr(config, "PHXPW_TOKEN_ADDRESS", "")
    ton_url = getattr(config, "TON_API_URL", "https://tonapi.io/v2")
    ton_key = getattr(config, "TON_API_KEY", "")
    print(f"  PHOEX_TOKEN_ADDRESS: {token[:20]}..." if token else "  PHOEX_TOKEN_ADDRESS: не задан")
    print(f"  TON_API_URL: {ton_url}")
    print(f"  TON_API_KEY: {'*** задан' if ton_key else '(не задан)'}")

    # 2. TonAPI
    print("\n2️⃣ TON API")
    print("-" * 60)
    try:
        import httpx
        base = ton_url.rstrip("/")
        url = f"{base}/status" if "tonapi" in base else base
        headers = {}
        if ton_key:
            headers["Authorization"] = f"Bearer {ton_key}"
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(url, headers=headers or None)
            if r.status_code == 200:
                print("  ✅ TonAPI доступен")
            elif r.status_code in (401, 404):
                r2 = await client.get(base, headers=headers or None)
                print("  ✅ TonAPI доступен (по базовому URL)" if r2.status_code == 200 else f"  ❌ HTTP {r2.status_code}")
            else:
                print(f"  ❌ HTTP {r.status_code}")
    except Exception as e:
        print(f"  ❌ Ошибка: {e}")

    # 3. DYOR (цена токена)
    print("\n3️⃣ DYOR.IO (цена PHOEX/PHXPW)")
    print("-" * 60)
    if not token:
        print("  ⚠️ Пропуск: не задан PHOEX_TOKEN_ADDRESS")
    else:
        try:
            import httpx
            url = f"https://api.dyor.io/v1/jettons/{token}"
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(url, headers={"Accept": "application/json"})
            if r.status_code == 200:
                data = r.json()
                price_ton = None
                price_usd = None
                details = data.get("details") or {}
                if isinstance(details, dict):
                    p = details.get("price") or {}
                    if isinstance(p, dict) and p.get("value") is not None:
                        dec = int(p.get("decimals", 9))
                        price_ton = int(p["value"]) / (10 ** dec)
                    pu = details.get("priceUsd") or {}
                    if isinstance(pu, dict) and pu.get("value") is not None:
                        dec = int(pu.get("decimals", 7))
                        price_usd = int(pu["value"]) / (10 ** dec)
                if price_ton is not None and price_ton > 0:
                    print(f"  ✅ Цена: {price_ton:.8f} TON" + (f" (${price_usd:.6f})" if price_usd else ""))
                else:
                    print("  ⚠️ Цена в ответе не найдена")
            elif r.status_code == 404:
                print("  ⚠️ Токен не найден в DYOR")
            elif r.status_code == 429:
                print("  ⚠️ Rate limit, попробуйте позже")
            else:
                print(f"  ❌ HTTP {r.status_code}")
        except Exception as e:
            print(f"  ❌ Ошибка: {e}")

    print("\n" + "=" * 60)
    print("Проверка завершена.")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(check_price_sources())
