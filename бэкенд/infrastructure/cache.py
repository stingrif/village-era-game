import json
import logging
from typing import Any, Optional

from config import REDIS_URL

logger = logging.getLogger(__name__)
_redis = None


def _get_redis():
    global _redis
    if _redis is None:
        try:
            from redis import asyncio as aioredis
            _redis = aioredis.from_url(REDIS_URL, encoding="utf-8", decode_responses=True)
        except Exception as e:
            logger.warning("Redis unavailable: %s", e)
    return _redis


async def cache_get(key: str) -> Optional[Any]:
    r = _get_redis()
    if r is None:
        return None
    try:
        s = await r.get(key)
        if s is None:
            return None
        return json.loads(s)
    except Exception:
        return None


async def cache_set(key: str, value: Any, ttl_sec: int = 300) -> None:
    r = _get_redis()
    if r is None:
        return
    try:
        await r.setex(key, ttl_sec, json.dumps(value, ensure_ascii=False))
    except Exception as e:
        logger.warning("Cache set failed: %s", e)


async def cache_delete(key: str) -> None:
    r = _get_redis()
    if r is None:
        return
    try:
        await r.delete(key)
    except Exception:
        pass
