#!/usr/bin/env python3
"""
Проверка доступности внешних API из .env: TON API, TonViewer, DYOR.

Проверяет только связь (доступность хоста и при необходимости ключ).
Не выполняет тяжёлых запросов.

Запуск из папки бэкенд:  python скрипты/check_apis.py
"""
import asyncio
import os
import sys
from pathlib import Path
from typing import Optional, Tuple

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


async def _get(url: str, headers: Optional[dict] = None, timeout: float = 8.0) -> Tuple[bool, str]:
    try:
        import httpx
    except ImportError:
        return False, "модуль httpx не установлен (pip install httpx)"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.get(url, headers=headers or {})
            if r.status_code == 200:
                return True, "OK"
            if r.status_code == 401:
                return False, "401 Unauthorized (проверьте API ключ)"
            return False, f"HTTP {r.status_code}"
    except httpx.TimeoutException:
        return False, "таймаут"
    except Exception as e:
        return False, str(e)


async def _reachable(url: str, headers: Optional[dict] = None, timeout: float = 6.0) -> Tuple[bool, str]:
    """Хост доступен, если получен любой HTTP-ответ (200, 404 и т.д.)."""
    try:
        import httpx
    except ImportError:
        return False, "модуль httpx не установлен"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.get(url, headers=headers or {})
            if r.status_code == 200:
                return True, "OK"
            if r.status_code in (301, 302, 401, 403, 404):
                return True, "доступен (HTTP %s)" % r.status_code
            return False, "HTTP %s" % r.status_code
    except httpx.TimeoutException:
        return False, "таймаут"
    except Exception as e:
        return False, str(e)


async def check_ton_api() -> Tuple[bool, str]:
    """TON API: доступность (GET к базовому URL)."""
    base = _env("TON_API_URL", "https://tonapi.io/v2").rstrip("/")
    key = _env("TON_API_KEY")
    # Эндпоинт статуса или простой запрос
    url = f"{base}/status" if "tonapi" in base else base
    headers = {}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    ok, msg = await _get(url, headers)
    if ok:
        return True, "OK"
    # Иногда /status нет — пробуем главную
    if "404" in msg or "401" in msg:
        ok2, _ = await _get(base, headers)
        if ok2:
            return True, "OK"
    if "401" in msg and key:
        return False, "ключ не принят (401)"
    return ok, msg


async def check_tonviewer() -> Tuple[bool, str]:
    """TonViewer API: хост доступен (базовый URL может отдавать 404)."""
    base = _env("TONVIEWER_API_URL", "https://tonviewer.com/api/v2").rstrip("/")
    return await _reachable(base, timeout=6.0)


async def check_dyor() -> Tuple[bool, str]:
    """DYOR API: хост доступен (базовый URL может отдавать 404)."""
    base = _env("DYOR_API_URL", "https://api.dyor.io").rstrip("/")
    headers = {}
    if _env("DYOR_API_KEY"):
        headers["Authorization"] = "Bearer " + _env("DYOR_API_KEY")
    return await _reachable(base, headers=headers or None, timeout=6.0)


async def main() -> int:
    print("Проверка внешних API из .env")
    print("=" * 60)

    # TON API
    url = _env("TON_API_URL", "https://tonapi.io/v2")
    key = _env("TON_API_KEY")
    print(f"\nTON API (TON_API_URL): {url}")
    print(f"  TON_API_KEY: {'*** задан' if key else '(не задан)'}")
    ok, msg = await check_ton_api()
    if ok:
        print("  ✅", msg)
    else:
        print("  ❌", msg)

    # TonViewer
    tv_url = _env("TONVIEWER_API_URL", "https://tonviewer.com/api/v2")
    print(f"\nTonViewer (TONVIEWER_API_URL): {tv_url}")
    ok2, msg2 = await check_tonviewer()
    if ok2:
        print("  ✅", msg2)
    else:
        print("  ❌", msg2)

    # DYOR
    dyor_url = _env("DYOR_API_URL", "https://api.dyor.io")
    dyor_key = _env("DYOR_API_KEY")
    print(f"\nDYOR (DYOR_API_URL): {dyor_url}")
    print(f"  DYOR_API_KEY: {'*** задан' if dyor_key else '(не задан)'}")
    ok3, msg3 = await check_dyor()
    if ok3:
        print("  ✅", msg3)
    else:
        print("  ❌", msg3)

    print("\n" + "=" * 60)
    if ok and ok2 and ok3:
        print("Все проверки пройдены.")
        return 0
    print("Есть ошибки подключения.")
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
