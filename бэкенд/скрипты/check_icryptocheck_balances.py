#!/usr/bin/env python3
"""
Проверка балансов кошельков проекта в iCryptoCheck.

В iCryptoCheck каждый wallet_id = API-токен приложения.
Для каждого *_WALLET_ID из .env выполняется GET /app/info с заголовком
iCryptoCheck-Key: <wallet_id> и выводятся балансы (TON, токен проекта).

Запуск из папки бэкенд:  python скрипты/check_icryptocheck_balances.py
"""
import asyncio
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
os.chdir(BACKEND_ROOT)

try:
    from dotenv import load_dotenv
    load_dotenv(BACKEND_ROOT / ".env")
except ImportError:
    pass


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


# Список кошельков проекта из env (имя переменной -> человеческое имя)
WALLET_IDS_ENV = [
    ("PROJECT_WALLET_ID", "Project"),
    ("STAKING_POOL_WALLET_ID", "Staking Pool"),
    ("ANIMALS_POOL_WALLET_ID", "Animals Pool"),
    ("USER_PAYOUTS_WALLET_ID", "User Payouts"),
    ("PROJECT_INCOME_WALLET_ID", "Project Income"),
    ("BURN_WALLET_ID", "Burn"),
    ("HOLDERS_REWARDS_WALLET_ID", "Holders Rewards"),
]


async def get_app_info(wallet_id: str, base_url: str) -> Optional[Dict[str, Any]]:
    """
    GET /app/info для приложения. wallet_id используется как API-токен.
    """
    try:
        import httpx
    except ImportError:
        return None
    url = f"{base_url.rstrip('/')}/app/info"
    headers = {
        "iCryptoCheck-Key": wallet_id,
        "Accept": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(url, headers=headers)
            if r.status_code == 200:
                return r.json()
            return None
    except Exception:
        return None


def extract_balances(data: Dict[str, Any]) -> Dict[str, float]:
    """Достаёт балансы из ответа GET /app/info."""
    result = {}
    if not data or not data.get("success"):
        return result
    raw = data.get("data", {})
    balances = raw.get("balances", [])
    if isinstance(balances, dict):
        balances = list(balances.items()) if balances else []
    for item in balances:
        if isinstance(item, dict):
            token = item.get("token", "")
            balance = float(item.get("balance", 0))
            result[token] = balance
        else:
            continue
    return result


async def main() -> int:
    base_url = _env("ICRYPTOCHECK_API_URL", "https://api.icryptocheck.com/api/v1")
    token_symbol = _env("TOKEN_DISPLAY_SYMBOL", "PHXPW")
    ic_token = _env("ICRYPTOCHECK_TOKEN_SYMBOL", token_symbol or "PHXPW")

    print("Проверка балансов iCryptoCheck (кошельки проекта)")
    print("=" * 60)
    print(f"API: {base_url}")
    print("В iCryptoCheck: wallet_id = API-токен приложения")
    print()

    total_ton = 0.0
    total_token = 0.0
    ok_count = 0
    skip_count = 0
    fail_count = 0

    for env_key, label in WALLET_IDS_ENV:
        wallet_id = _env(env_key)
        if not wallet_id:
            print(f"  ⚠️ {label} ({env_key}): не задан в .env")
            skip_count += 1
            continue

        data = await get_app_info(wallet_id, base_url)
        if data is None:
            print(f"  ❌ {label}: ошибка запроса или неверный wallet_id (API-токен)")
            fail_count += 1
            continue

        if not data.get("success"):
            err = data.get("message", data.get("error", "unknown"))
            print(f"  ❌ {label}: {err}")
            fail_count += 1
            continue

        balances = extract_balances(data)
        app_name = data.get("data", {}).get("name", "—")
        ton = balances.get("TON", 0.0)
        tok = (
            balances.get(ic_token)
            or balances.get(token_symbol)
            or balances.get("PHOEX")
            or balances.get("PHXPW")
            or 0.0
        )

        total_ton += ton
        total_token += tok
        ok_count += 1
        print(f"  ✅ {label}: {app_name}")
        print(f"      TON: {ton:,.6f}  |  {token_symbol}: {tok:,.2f}")

        await asyncio.sleep(0.3)

    print()
    print("=" * 60)
    print(f"Проверено: {ok_count}  |  Не заданы: {skip_count}  |  Ошибки: {fail_count}")
    print(f"Итого по кошелькам: TON {total_ton:,.6f}  |  {token_symbol} {total_token:,.2f}")
    print("=" * 60)

    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
