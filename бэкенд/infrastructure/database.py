import json
import logging
from typing import Any, Dict, List, Optional

import asyncpg

from config import DATABASE_URL

logger = logging.getLogger(__name__)
_pool: Optional[asyncpg.Pool] = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=10, command_timeout=60)
    return _pool


async def init_db() -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS game_players (
                telegram_id BIGINT PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                state JSONB NOT NULL DEFAULT '{}',
                phoenix_quest_completed BOOLEAN NOT NULL DEFAULT FALSE,
                burned_count INTEGER NOT NULL DEFAULT 0,
                points_balance INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_game_players_updated
            ON game_players(updated_at)
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS pending_payouts (
                id SERIAL PRIMARY KEY,
                telegram_id BIGINT NOT NULL,
                reward_type TEXT NOT NULL DEFAULT 'phoenix_quest',
                amount INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_pending_payouts_telegram
            ON pending_payouts(telegram_id)
        """)
        for sql in (
            "ALTER TABLE game_players ADD COLUMN IF NOT EXISTS phoenix_quest_completed BOOLEAN NOT NULL DEFAULT FALSE",
            "ALTER TABLE game_players ADD COLUMN IF NOT EXISTS burned_count INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE game_players ADD COLUMN IF NOT EXISTS points_balance INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE game_players ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()",
        ):
            try:
                await conn.execute(sql)
            except Exception as e:
                if "already exists" not in str(e).lower():
                    logger.warning("Migration step: %s", e)
    logger.info("Game DB initialized")


def _row_to_state(row: asyncpg.Record) -> Dict[str, Any]:
    state = dict(row["state"]) if row["state"] else {}
    state["phoenixQuestCompleted"] = row.get("phoenix_quest_completed", False)
    state["burnedCount"] = int(row.get("burned_count", 0))
    state["points"] = int(row.get("points_balance", 0))
    if row.get("created_at"):
        state["createdAt"] = int(row["created_at"].timestamp() * 1000)
    return state


async def get_state(telegram_id: int) -> Optional[Dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT state, phoenix_quest_completed, burned_count, points_balance, created_at
               FROM game_players WHERE telegram_id = $1""",
            telegram_id,
        )
        if row is None:
            return None
        return _row_to_state(row)


async def set_state(
    telegram_id: int,
    state: Dict[str, Any],
    username: str = "",
    first_name: str = "",
) -> None:
    pool = await get_pool()
    phoenix = bool(state.get("phoenixQuestCompleted", False))
    burned = int(state.get("burnedCount", 0))
    points = int(state.get("points", 0))
    state_copy = {k: v for k, v in state.items() if k not in ("phoenixQuestCompleted", "burnedCount", "points")}
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO game_players (
                telegram_id, username, first_name, state,
                phoenix_quest_completed, burned_count, points_balance, updated_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, NOW())
            ON CONFLICT (telegram_id) DO UPDATE SET
                username = COALESCE(EXCLUDED.username, game_players.username),
                first_name = COALESCE(EXCLUDED.first_name, game_players.first_name),
                state = EXCLUDED.state,
                phoenix_quest_completed = EXCLUDED.phoenix_quest_completed,
                burned_count = EXCLUDED.burned_count,
                points_balance = EXCLUDED.points_balance,
                updated_at = NOW()
            """,
            telegram_id,
            username or None,
            first_name or None,
            json.dumps(state_copy, ensure_ascii=False),
            phoenix,
            burned,
            points,
        )


async def get_player_critical(telegram_id: int) -> Optional[Dict[str, Any]]:
    """Только критические поля для валидации квеста."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT phoenix_quest_completed, burned_count, points_balance, created_at
               FROM game_players WHERE telegram_id = $1""",
            telegram_id,
        )
    if row is None:
        return None
    return {
        "phoenix_quest_completed": row["phoenix_quest_completed"],
        "burned_count": int(row["burned_count"]),
        "points_balance": int(row["points_balance"]),
        "created_at": row["created_at"],
    }


async def add_pending_payout(
    telegram_id: int,
    reward_type: str,
    amount: int,
) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO pending_payouts (telegram_id, reward_type, amount, status)
               VALUES ($1, $2, $3, 'pending') RETURNING id""",
            telegram_id,
            reward_type,
            amount,
        )
        return int(row["id"])


async def close_db() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
