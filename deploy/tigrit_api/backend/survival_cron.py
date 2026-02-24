"""
Крон-задачи survival-слоя:
- смерть от скуки (72 часа без появления в домашней зоне)
- медленное выравнивание trust
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from tigrit_shared import db

logger = logging.getLogger(__name__)


async def check_boredom_deaths() -> int:
    """
    Если игрок привязан к home_zone, но 72ч не проявлялся в зоне,
    переводим в состояние dead_boredom.
    """
    try:
        pool = await db.get_pool()
        if not pool:
            return 0
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                UPDATE tigrit_user_profile
                SET character_state = 'dead_boredom'
                WHERE character_state = 'alive'
                  AND home_zone_id IS NOT NULL
                  AND home_zone_bound_at IS NOT NULL
                  AND home_zone_first_activity_at IS NULL
                  AND home_zone_bound_at < NOW() - INTERVAL '72 hours'
                RETURNING user_id
                """
            )
            changed = len(rows)
            if changed:
                await conn.execute(
                    """
                    INSERT INTO game_events (user_id, event_type, reason_code, payload, created_at)
                    SELECT user_id, 'survival_state', 'dead_boredom', '{}'::jsonb, NOW()
                    FROM tigrit_user_profile
                    WHERE character_state = 'dead_boredom'
                      AND home_zone_bound_at < NOW() - INTERVAL '72 hours'
                    """
                )
            return changed
    except Exception as e:
        logger.warning("check_boredom_deaths failed: %s", e)
        return 0


async def trust_decay() -> int:
    """
    Медленно тянем trust к нейтральному значению 50:
    - trust > 50 -> -1
    - trust < 50 -> +1
    """
    try:
        pool = await db.get_pool()
        if not pool:
            return 0
        async with pool.acquire() as conn:
            rows_up = await conn.fetch(
                """
                UPDATE tigrit_user_profile
                SET trust_score = trust_score + 1
                WHERE trust_score < 50
                RETURNING user_id
                """
            )
            rows_down = await conn.fetch(
                """
                UPDATE tigrit_user_profile
                SET trust_score = trust_score - 1
                WHERE trust_score > 50
                RETURNING user_id
                """
            )
            return len(rows_up) + len(rows_down)
    except Exception as e:
        logger.warning("trust_decay failed: %s", e)
        return 0


async def run_periodic_jobs(stop_event: asyncio.Event) -> None:
    """
    Фоновый цикл survival-задач.
    - boredom-check: каждые 6 часов
    - trust-decay: 1 раз в сутки
    """
    last_trust_day = None
    while not stop_event.is_set():
        await check_boredom_deaths()

        now = datetime.now(timezone.utc).date()
        if now != last_trust_day:
            await trust_decay()
            last_trust_day = now

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=6 * 60 * 60)
        except asyncio.TimeoutError:
            continue
