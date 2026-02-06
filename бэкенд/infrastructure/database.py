import json
import logging
import random
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
        # Legacy: game_players (state JSONB) — обратная совместимость
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
        # Архитектура 25: users (user_id для связей)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                telegram_id BIGINT UNIQUE NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_users_telegram ON users(telegram_id)")
        # user_profile — 18_Dev
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_profile (
                user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                ads_enabled BOOLEAN NOT NULL DEFAULT TRUE,
                checkin_cd_bonus_minutes INTEGER NOT NULL DEFAULT 0,
                checkin_cd_bonus_cap_minutes INTEGER NOT NULL DEFAULT 60,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        # user_balances — COINS, STARS, DIAMONDS
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_balances (
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                currency TEXT NOT NULL,
                balance BIGINT NOT NULL DEFAULT 0,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (user_id, currency)
            )
        """)
        # checkin_state, checkin_log — 03_Шахта_и_яйца, 18_Dev
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS checkin_state (
                user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                last_checkin_at TIMESTAMPTZ,
                next_checkin_at TIMESTAMPTZ,
                streak INTEGER NOT NULL DEFAULT 0,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS checkin_log (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                granted_attempts INTEGER NOT NULL,
                base_cd_minutes INTEGER NOT NULL,
                bonus_minutes_used INTEGER NOT NULL DEFAULT 0,
                effective_cd_minutes INTEGER NOT NULL,
                next_checkin_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_checkin_log_user ON checkin_log(user_id)")
        # attempts_balance — попытки копания
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS attempts_balance (
                user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                attempts INTEGER NOT NULL DEFAULT 0,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        # mine_sessions — 6×6, призовые ячейки
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS mine_sessions (
                id BIGSERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                grid_size INTEGER NOT NULL DEFAULT 36,
                prize_cells INTEGER[] NOT NULL,
                prize_cells_seed BIGINT NOT NULL DEFAULT 0,
                opened_cells INTEGER[] NOT NULL DEFAULT '{}',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_mine_sessions_user ON mine_sessions(user_id)")
        # dig_log — лог копок (антибот: ip_hash, device_hash, vpn_flag опционально)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS dig_log (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                mine_id BIGINT NOT NULL REFERENCES mine_sessions(id) ON DELETE CASCADE,
                cell_index INTEGER NOT NULL,
                used_attempt_source TEXT NOT NULL DEFAULT 'checkin',
                prize_hit BOOLEAN NOT NULL DEFAULT FALSE,
                coins_drop INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_dig_log_user ON dig_log(user_id)")
        # economy_ledger — движения по валютам, idem_key для идемпотентности
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS economy_ledger (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                kind TEXT NOT NULL,
                currency TEXT NOT NULL,
                amount BIGINT NOT NULL,
                ref_type TEXT NOT NULL,
                ref_id TEXT,
                meta JSONB,
                idem_key TEXT UNIQUE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_economy_ledger_user ON economy_ledger(user_id)")
        await conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_economy_ledger_idem ON economy_ledger(idem_key) WHERE idem_key IS NOT NULL")

        # Фаза 1: предметы и инвентарь (18_Dev)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS item_defs (
                id SERIAL PRIMARY KEY,
                key TEXT UNIQUE NOT NULL,
                item_type TEXT NOT NULL,
                subtype TEXT NOT NULL,
                name TEXT NOT NULL,
                rarity TEXT NOT NULL,
                allowed_buildings JSONB NOT NULL DEFAULT '[]',
                effects_json JSONB NOT NULL DEFAULT '{}',
                limits_json JSONB NOT NULL DEFAULT '{}',
                is_deep_pool BOOLEAN NOT NULL DEFAULT FALSE,
                base_level INTEGER NOT NULL DEFAULT 1,
                craftable BOOLEAN NOT NULL DEFAULT TRUE
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_item_defs_rarity ON item_defs(rarity)")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_items (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                item_def_id INTEGER NOT NULL REFERENCES item_defs(id) ON DELETE RESTRICT,
                state TEXT NOT NULL DEFAULT 'inventory',
                item_level INTEGER NOT NULL DEFAULT 1,
                meta JSONB NOT NULL DEFAULT '{}',
                acquired_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                cooldown_until TIMESTAMPTZ
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_user_items_user ON user_items(user_id)")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS eggs_def (
                color TEXT PRIMARY KEY,
                rarity TEXT NOT NULL,
                weight INTEGER NOT NULL DEFAULT 1
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS player_eggs (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                color TEXT NOT NULL REFERENCES eggs_def(color) ON DELETE RESTRICT,
                acquired_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                meta JSONB NOT NULL DEFAULT '{}'
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_player_eggs_user ON player_eggs(user_id)")

        # Фаза 2: деревня и здания (18_Dev, 01)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS buildings_def (
                key TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                category TEXT NOT NULL,
                kind TEXT NOT NULL DEFAULT 'income',
                stack_limit INTEGER NOT NULL DEFAULT 1,
                short_reason TEXT,
                config JSONB NOT NULL DEFAULT '{}'
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS player_field (
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                slot_index INTEGER NOT NULL CHECK (slot_index >= 1 AND slot_index <= 9),
                building_key TEXT NOT NULL REFERENCES buildings_def(key) ON DELETE RESTRICT,
                placed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (user_id, slot_index)
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_player_field_user ON player_field(user_id)")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_buildings (
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                building_key TEXT NOT NULL REFERENCES buildings_def(key) ON DELETE RESTRICT,
                level INTEGER NOT NULL DEFAULT 1 CHECK (level >= 1 AND level <= 10),
                invested_cost BIGINT NOT NULL DEFAULT 0,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (user_id, building_key)
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS building_slots (
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                building_key TEXT NOT NULL,
                slot_index INTEGER NOT NULL,
                user_item_id INTEGER REFERENCES user_items(id) ON DELETE SET NULL,
                equipped_at TIMESTAMPTZ,
                PRIMARY KEY (user_id, building_key, slot_index),
                FOREIGN KEY (user_id, building_key) REFERENCES user_buildings(user_id, building_key) ON DELETE CASCADE
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS demolish_log (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                building_key TEXT NOT NULL,
                refunded_amount BIGINT NOT NULL,
                refund_rate NUMERIC NOT NULL DEFAULT 0.25,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_demolish_log_user ON demolish_log(user_id)")

        # Фаза 3: крафт (18_Dev)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS crafting_log (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                action TEXT NOT NULL,
                input_item_ids INTEGER[] NOT NULL DEFAULT '{}',
                output_item_id INTEGER REFERENCES user_items(id),
                dust_spent BIGINT NOT NULL DEFAULT 0,
                result_json JSONB NOT NULL DEFAULT '{}',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_crafting_log_user ON crafting_log(user_id)")

        # Фаза 4: рынок и P2P (18_Dev, 11)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS market_orders (
                id SERIAL PRIMARY KEY,
                seller_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                status TEXT NOT NULL DEFAULT 'open',
                pay_currency TEXT NOT NULL DEFAULT 'COINS',
                pay_amount BIGINT NOT NULL,
                expires_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_market_orders_seller ON market_orders(seller_id)")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS market_order_items (
                order_id INTEGER NOT NULL REFERENCES market_orders(id) ON DELETE CASCADE,
                user_item_id INTEGER NOT NULL REFERENCES user_items(id) ON DELETE CASCADE,
                PRIMARY KEY (order_id, user_item_id)
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS escrow_items (
                user_item_id INTEGER PRIMARY KEY REFERENCES user_items(id) ON DELETE CASCADE,
                owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                lock_type TEXT NOT NULL,
                lock_id TEXT NOT NULL
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS trade_offers (
                id SERIAL PRIMARY KEY,
                maker_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                status TEXT NOT NULL DEFAULT 'open',
                taker_id INTEGER REFERENCES users(id),
                want_currency TEXT,
                want_amount BIGINT NOT NULL DEFAULT 0,
                expires_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS trade_offer_items (
                offer_id INTEGER NOT NULL REFERENCES trade_offers(id) ON DELETE CASCADE,
                side TEXT NOT NULL,
                user_item_id INTEGER NOT NULL REFERENCES user_items(id) ON DELETE CASCADE,
                PRIMARY KEY (offer_id, side, user_item_id)
            )
        """)

        # Фаза 5: вывод и eligibility (18_Dev, 08)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_wallets (
                user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                wallet_address TEXT NOT NULL UNIQUE,
                verified_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS withdraw_gating (
                user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                required_action_value_ton NUMERIC NOT NULL DEFAULT 0,
                completed_action_value_ton NUMERIC NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'open'
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS token_compliance (
                user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                status TEXT NOT NULL DEFAULT 'ok',
                reason TEXT,
                detected_at TIMESTAMPTZ,
                deadline_at TIMESTAMPTZ,
                resolved_at TIMESTAMPTZ
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS donations (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                currency TEXT NOT NULL,
                amount BIGINT NOT NULL,
                donation_points NUMERIC NOT NULL DEFAULT 0,
                period_key TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS ad_log (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                ad_kind TEXT NOT NULL,
                provider TEXT,
                idem_key TEXT UNIQUE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)

        # Фазы 6–7: стейкинг и блокчейн
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS staking_sessions (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                staked_amount NUMERIC NOT NULL DEFAULT 0,
                accrued_rewards NUMERIC NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'PENDING',
                lock_until TIMESTAMPTZ,
                plan_id TEXT,
                payment_address TEXT,
                lock_requested_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS staking_reward_history (
                id SERIAL PRIMARY KEY,
                session_id INTEGER NOT NULL REFERENCES staking_sessions(id) ON DELETE CASCADE,
                reward_amount NUMERIC NOT NULL,
                calculated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS token_transactions (
                id SERIAL PRIMARY KEY,
                tx_hash TEXT NOT NULL,
                user_id INTEGER REFERENCES users(id),
                wallet_address TEXT NOT NULL,
                amount NUMERIC NOT NULL,
                direction TEXT NOT NULL,
                block_timestamp TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        await conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_token_tx_hash ON token_transactions(tx_hash)")

        # Фазы 8–9: события и лидерборды
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS game_events (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                event_type TEXT NOT NULL,
                reason_code TEXT,
                payload JSONB NOT NULL DEFAULT '{}',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_game_events_user ON game_events(user_id)")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS leaderboards (
                period TEXT NOT NULL,
                period_key TEXT NOT NULL,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                points BIGINT NOT NULL DEFAULT 0,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (period, period_key, user_id)
            )
        """)

        # Фаза 10: админ и риск
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS risk_profile (
                user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                risk_score INTEGER NOT NULL DEFAULT 0,
                vpn_hits INTEGER NOT NULL DEFAULT 0,
                multi_account_hits INTEGER NOT NULL DEFAULT 0,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_sanctions (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                sanction_type TEXT NOT NULL,
                started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                deadline_at TIMESTAMPTZ,
                meta JSONB NOT NULL DEFAULT '{}'
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS projects (
                id SERIAL PRIMARY KEY,
                code TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        await conn.execute("""
            INSERT INTO projects (id, code, name) VALUES (1, 'village_era', 'Village Era')
            ON CONFLICT (code) DO NOTHING
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS admin_users (
                user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                role TEXT NOT NULL DEFAULT 'admin',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS admin_partner_tokens (
                id SERIAL PRIMARY KEY,
                project_id INTEGER NOT NULL DEFAULT 1 REFERENCES projects(id) ON DELETE CASCADE,
                token_address TEXT NOT NULL,
                symbol TEXT NOT NULL,
                name TEXT,
                usage TEXT NOT NULL DEFAULT 'payment',
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE(project_id, token_address)
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS admin_tasks (
                id SERIAL PRIMARY KEY,
                project_id INTEGER NOT NULL DEFAULT 1 REFERENCES projects(id) ON DELETE CASCADE,
                task_key TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT,
                reward_type TEXT,
                reward_value INTEGER NOT NULL DEFAULT 0,
                conditions_json JSONB NOT NULL DEFAULT '{}',
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE(project_id, task_key)
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS admin_page_texts (
                id SERIAL PRIMARY KEY,
                project_id INTEGER NOT NULL DEFAULT 1 REFERENCES projects(id) ON DELETE CASCADE,
                page_id TEXT NOT NULL,
                text_key TEXT NOT NULL,
                text_value TEXT NOT NULL DEFAULT '',
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE(project_id, page_id, text_key)
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS admin_channels (
                id SERIAL PRIMARY KEY,
                project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                chat_id BIGINT NOT NULL,
                title TEXT,
                channel_type TEXT NOT NULL DEFAULT 'channel',
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE(project_id, chat_id)
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS activity_log (
                id BIGSERIAL PRIMARY KEY,
                project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
                telegram_id BIGINT NOT NULL,
                channel_id BIGINT,
                event_type TEXT NOT NULL,
                event_meta JSONB NOT NULL DEFAULT '{}',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_activity_log_project_user ON activity_log(project_id, user_id)
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_activity_log_created ON activity_log(created_at)
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_activity_stats (
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                total_messages_sent INTEGER NOT NULL DEFAULT 0,
                total_reactions_received INTEGER NOT NULL DEFAULT 0,
                reactions_by_type JSONB NOT NULL DEFAULT '{}',
                last_activity_at TIMESTAMPTZ,
                PRIMARY KEY (user_id, project_id)
            )
        """)

        for sql in (
            "ALTER TABLE admin_partner_tokens ADD COLUMN IF NOT EXISTS project_id INTEGER DEFAULT 1 REFERENCES projects(id)",
            "ALTER TABLE admin_tasks ADD COLUMN IF NOT EXISTS project_id INTEGER DEFAULT 1 REFERENCES projects(id)",
            "ALTER TABLE admin_page_texts ADD COLUMN IF NOT EXISTS project_id INTEGER DEFAULT 1 REFERENCES projects(id)",
            "ALTER TABLE game_players ADD COLUMN IF NOT EXISTS phoenix_quest_completed BOOLEAN NOT NULL DEFAULT FALSE",
            "ALTER TABLE game_players ADD COLUMN IF NOT EXISTS burned_count INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE game_players ADD COLUMN IF NOT EXISTS points_balance INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE game_players ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()",
            "ALTER TABLE dig_log ADD COLUMN IF NOT EXISTS drop_item_def_id INTEGER REFERENCES item_defs(id)",
            "ALTER TABLE dig_log ADD COLUMN IF NOT EXISTS drop_rarity TEXT",
            "ALTER TABLE dig_log ADD COLUMN IF NOT EXISTS egg_hit BOOLEAN NOT NULL DEFAULT FALSE",
            "ALTER TABLE dig_log ADD COLUMN IF NOT EXISTS ip_hash TEXT",
            "ALTER TABLE dig_log ADD COLUMN IF NOT EXISTS device_hash TEXT",
            "ALTER TABLE dig_log ADD COLUMN IF NOT EXISTS vpn_flag BOOLEAN",
        ):
            try:
                await conn.execute(sql)
            except Exception as e:
                if "already exists" not in str(e).lower() and "duplicate" not in str(e).lower():
                    logger.warning("Migration step: %s", e)
        await _seed_item_defs_and_eggs(conn)
        await _seed_buildings_def(conn)
    logger.info("Game DB initialized")


async def _seed_item_defs_and_eggs(conn: asyncpg.Connection) -> None:
    """Сид item_defs (реликвии по 19) и eggs_def (по конфигу)."""
    # eggs_def из game config
    from config import get_eggs_config
    eggs_cfg = get_eggs_config()
    for c in eggs_cfg.get("colors", []):
        await conn.execute(
            """INSERT INTO eggs_def (color, rarity, weight)
               VALUES ($1, $2, $3) ON CONFLICT (color) DO NOTHING""",
            c.get("color", ""), c.get("rarity", "common"), c.get("weight", 1),
        )
    # item_defs: реликвии FIRE, YIN, YAN, TSY, MAGIC, EPIC (19_Список_предметов)
    relics = [
        *[("fire_%02d" % i, "relic_slot", "FIRE", "Реликвия FIRE %d" % i) for i in range(1, 9)],
        *[("yin_%02d" % i, "relic_slot", "YIN", "Реликвия YIN %d" % i) for i in range(1, 9)],
        *[("yan_%02d" % i, "relic_slot", "YAN", "Реликвия YAN %d" % i) for i in range(1, 9)],
        *[("tsy_%02d" % i, "relic_slot", "TSY", "Реликвия TSY %d" % i) for i in range(1, 9)],
        *[("magic_%02d" % i, "relic_slot", "MAGIC", "Реликвия MAGIC %d" % i) for i in range(1, 7)],
        *[("epic_%02d" % i, "relic_slot", "EPIC", "Реликвия EPIC %d" % i) for i in range(1, 5)],
    ]
    for key, item_type, rarity, name in relics:
        await conn.execute(
            """INSERT INTO item_defs (key, item_type, subtype, name, rarity, allowed_buildings, effects_json)
               VALUES ($1, $2, $3, $4, $5, '[]', '{}') ON CONFLICT (key) DO NOTHING""",
            key, item_type, rarity, name, rarity,
        )
    # амулеты по редкости (один на редкость для дропа)
    amulets = [("amulet_fire", "amulet", "FIRE", "Амулет огня"), ("amulet_yin", "amulet", "YIN", "Амулет инь"),
               ("amulet_yan", "amulet", "YAN", "Амулет янь"), ("amulet_tsy", "amulet", "TSY", "Амулет цы"),
               ("amulet_magic", "amulet", "MAGIC", "Амулет магии"), ("amulet_epic", "amulet", "EPIC", "Амулет эпик")]
    for key, item_type, rarity, name in amulets:
        await conn.execute(
            """INSERT INTO item_defs (key, item_type, subtype, name, rarity, allowed_buildings, effects_json)
               VALUES ($1, $2, $3, $4, $5, '[]', '{}') ON CONFLICT (key) DO NOTHING""",
            key, item_type, rarity, name, rarity,
        )


# Здания по 01_Здания_и_задания: key, name, category, stack_limit, config (incomePerHour, slotsByLevel)
_BUILDINGS_SEED = [
    ("townhall", "Ратуша", "progress", 1, [4, 5, 7, 9, 12, 16, 20, 25, 31, 38], [1, 2, 3, 3]),
    ("houses", "Дома", "income", 3, [8, 11, 15, 20, 27, 36, 48, 63, 82, 106], [1, 2, 3, 3]),
    ("farm", "Ферма", "income", 3, [10, 14, 19, 25, 33, 44, 58, 76, 99, 128], [1, 2, 3, 3]),
    ("market", "Рынок", "trade", 1, [6, 8, 11, 15, 20, 26, 34, 44, 56, 71], [1, 2, 2, 3]),
    ("warehouse", "Склад", "service", 3, [0] * 10, [1, 1, 2, 2]),
    ("lumbermill", "Лесопилка", "resource", 1, [6, 8, 11, 15, 20, 26, 33, 41, 50, 60], [1, 1, 2, 2]),
    ("quarry", "Каменоломня", "resource", 1, [4, 6, 8, 11, 15, 20, 26, 33, 41, 50], [1, 1, 2, 2]),
    ("mine_office", "Шахтный офис", "progress", 1, [1, 1, 2, 2, 3, 3, 4, 5, 6, 7], [1, 1, 2, 2]),
    ("forge", "Кузница", "pvp", 1, [2, 3, 4, 6, 8, 11, 15, 20, 26, 33], [1, 2, 2, 3]),
    ("temple", "Храм", "progress", 1, [1, 2, 3, 4, 6, 8, 11, 15, 20, 26], [1, 1, 2, 3]),
    ("guard_post", "Страж-пост", "defense", 1, [0, 0, 0, 1, 1, 2, 2, 3, 3, 4], [1, 1, 2, 2]),
    ("watchtower", "Башня наблюдения", "defense", 1, [0, 0, 1, 1, 2, 2, 3, 3, 4, 5], [1, 1, 2, 2]),
    ("infirmary", "Лазарет", "defense", 1, [0, 0, 0, 1, 1, 2, 2, 3, 3, 4], [1, 1, 2, 2]),
    ("academy", "Академия", "progress", 1, [2, 2, 3, 3, 4, 5, 6, 7, 8, 10], [1, 1, 2, 2]),
    ("workshop", "Мастерская", "service", 1, [1, 1, 2, 2, 3, 3, 4, 4, 5, 6], [1, 1, 2, 2]),
    ("alchemy", "Алхимическая", "service", 1, [1, 1, 2, 2, 3, 4, 5, 6, 7, 9], [1, 1, 2, 2]),
    ("post_office", "Почта", "service", 1, [0, 0, 0, 1, 1, 1, 2, 2, 3, 3], [1, 1, 2, 2]),
    ("portal", "Портал", "progress", 1, [0, 0, 1, 1, 2, 2, 3, 3, 4, 5], [1, 1, 1, 2]),
    ("treasury", "Казна", "defense", 1, [1, 1, 2, 2, 3, 3, 4, 5, 6, 8], [1, 1, 2, 2]),
    ("firebrigade", "Пожарная", "defense", 1, [0, 0, 0, 1, 1, 2, 2, 3, 3, 4], [1, 1, 2, 2]),
    ("well", "Колодец", "defense", 1, [0, 0, 0, 1, 1, 2, 2, 2, 3, 3], [1, 1, 2, 2]),
    ("trade_guild", "Торговая гильдия", "trade", 1, [2, 3, 4, 6, 8, 10, 13, 16, 20, 25], [1, 1, 2, 2]),
    ("auction_house", "Аукционный дом", "trade", 1, [2, 3, 5, 7, 9, 12, 15, 19, 24, 30], [1, 1, 2, 2]),
    ("caravan", "Караван-сарай", "trade", 1, [1, 2, 3, 4, 6, 8, 10, 12, 15, 19], [1, 1, 2, 2]),
    ("arena", "Арена", "pvp", 1, [2, 3, 4, 6, 8, 11, 14, 18, 23, 29], [1, 1, 2, 2]),
    ("contracts_board", "Доска контрактов", "progress", 1, [1, 2, 3, 4, 6, 8, 10, 12, 15, 18], [1, 1, 2, 2]),
    ("egg_shrine", "Святилище яиц", "progress", 1, [0, 0, 1, 1, 2, 2, 3, 3, 4, 4], [1, 1, 1, 2]),
    ("incubator", "Инкубатор", "progress", 1, [0, 0, 1, 1, 2, 2, 3, 4, 5, 6], [1, 1, 1, 2]),
    ("ad_totem", "Рекламный тотем", "service", 1, [0, 0, 0, 1, 1, 1, 2, 2, 2, 3], [1, 1, 2, 2]),
    ("era_monument", "Памятник эры", "progress", 1, [1, 2, 3, 4, 6, 8, 10, 13, 16, 20], [1, 1, 2, 2]),
    ("silence_chapel", "Часовня тишины", "defense", 1, [0, 0, 0, 1, 1, 1, 2, 2, 3, 3], [1, 1, 2, 2]),
    ("blacklist_office", "Канцелярия запретов", "pvp", 1, [0, 0, 1, 1, 2, 2, 3, 3, 4, 5], [1, 1, 2, 2]),
]


async def _seed_buildings_def(conn: asyncpg.Connection) -> None:
    for key, name, category, stack_limit, income_per_hour, slots_by_level in _BUILDINGS_SEED:
        config = json.dumps({"incomePerHour": income_per_hour, "slotsByLevel": slots_by_level})
        await conn.execute(
            """INSERT INTO buildings_def (key, name, category, kind, stack_limit, config)
               VALUES ($1, $2, $3, 'income', $4, $5::jsonb) ON CONFLICT (key) DO UPDATE SET config = EXCLUDED.config""",
            key, name, category, stack_limit, config,
        )


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


# ——— Архитектура: users, checkin, mine (18_Dev, 25) ———

async def ensure_user(telegram_id: int) -> int:
    """Возвращает user_id (users.id). Создаёт пользователя при первом обращении."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT id FROM users WHERE telegram_id = $1", telegram_id)
        if row:
            return int(row["id"])
        row = await conn.fetchrow(
            """INSERT INTO users (telegram_id) VALUES ($1) RETURNING id""",
            telegram_id,
        )
        user_id = int(row["id"])
        await conn.execute(
            """INSERT INTO user_profile (user_id) VALUES ($1)
               ON CONFLICT (user_id) DO NOTHING""",
            user_id,
        )
        await conn.execute(
            """INSERT INTO attempts_balance (user_id, attempts) VALUES ($1, 0)
               ON CONFLICT (user_id) DO NOTHING""",
            user_id,
        )
        await conn.execute(
            """INSERT INTO checkin_state (user_id) VALUES ($1)
               ON CONFLICT (user_id) DO NOTHING""",
            user_id,
        )
        return user_id


async def ensure_balance_row(user_id: int, currency: str) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO user_balances (user_id, currency, balance)
               VALUES ($1, $2, 0) ON CONFLICT (user_id, currency) DO NOTHING""",
            user_id, currency,
        )


async def get_checkin_state(user_id: int) -> Optional[Dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT last_checkin_at, next_checkin_at, streak, updated_at
               FROM checkin_state WHERE user_id = $1""",
            user_id,
        )
    if row is None:
        return None
    return {
        "last_checkin_at": row["last_checkin_at"].isoformat() if row["last_checkin_at"] else None,
        "next_checkin_at": row["next_checkin_at"].isoformat() if row["next_checkin_at"] else None,
        "streak": int(row["streak"]),
        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
    }


async def get_attempts(user_id: int) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT attempts FROM attempts_balance WHERE user_id = $1""",
            user_id,
        )
    return int(row["attempts"]) if row else 0


async def add_attempts(user_id: int, delta: int) -> int:
    """Добавляет попытки, возвращает новый баланс."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """UPDATE attempts_balance SET attempts = attempts + $2, updated_at = NOW()
               WHERE user_id = $1 RETURNING attempts""",
            user_id, delta,
        )
        if not row:
            await conn.execute(
                """INSERT INTO attempts_balance (user_id, attempts) VALUES ($1, $2)
                   ON CONFLICT (user_id) DO UPDATE SET attempts = attempts_balance.attempts + $2, updated_at = NOW()""",
                user_id, delta,
            )
            row = await conn.fetchrow("SELECT attempts FROM attempts_balance WHERE user_id = $1", user_id)
    return int(row["attempts"]) if row else max(0, delta)


async def consume_attempt(user_id: int) -> bool:
    """Списывает одну попытку. Возвращает True если попытка была."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """UPDATE attempts_balance SET attempts = attempts - 1, updated_at = NOW()
               WHERE user_id = $1 AND attempts > 0 RETURNING attempts""",
            user_id,
        )
    return row is not None


async def create_mine_session(user_id: int, prize_cells: List[int], seed: int) -> int:
    """Создаёт сессию шахты 6×6 с заданными призовыми ячейками. Возвращает mine_id."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO mine_sessions (user_id, grid_size, prize_cells, prize_cells_seed, opened_cells)
               VALUES ($1, 36, $2, $3, '{}') RETURNING id""",
            user_id, prize_cells, seed,
        )
    return int(row["id"])


async def get_mine_session(mine_id: int, user_id: int) -> Optional[Dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT id, user_id, grid_size, prize_cells, prize_cells_seed, opened_cells, created_at
               FROM mine_sessions WHERE id = $1 AND user_id = $2""",
            mine_id, user_id,
        )
    if row is None:
        return None
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "grid_size": row["grid_size"],
        "prize_cells": list(row["prize_cells"]) if row["prize_cells"] else [],
        "prize_cells_seed": row["prize_cells_seed"],
        "opened_cells": list(row["opened_cells"]) if row["opened_cells"] else [],
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
    }


async def mark_cell_opened(mine_id: int, user_id: int, cell_index: int) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """UPDATE mine_sessions SET opened_cells = array_append(opened_cells, $3)
               WHERE id = $1 AND user_id = $2""",
            mine_id, user_id, cell_index,
        )


async def record_dig_log(
    user_id: int,
    mine_id: int,
    cell_index: int,
    used_attempt_source: str,
    prize_hit: bool,
    coins_drop: int,
    drop_item_def_id: Optional[int] = None,
    drop_rarity: Optional[str] = None,
    egg_hit: bool = False,
    ip_hash: Optional[str] = None,
    device_hash: Optional[str] = None,
    vpn_flag: Optional[bool] = None,
) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO dig_log (user_id, mine_id, cell_index, used_attempt_source, prize_hit, coins_drop,
               drop_item_def_id, drop_rarity, egg_hit, ip_hash, device_hash, vpn_flag)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)""",
            user_id,
            mine_id,
            cell_index,
            used_attempt_source,
            prize_hit,
            coins_drop,
            drop_item_def_id,
            drop_rarity,
            egg_hit,
            ip_hash,
            device_hash,
            vpn_flag,
        )


async def add_coins_ledger(
    user_id: int, amount: int, ref_type: str, ref_id: Optional[str] = None,
    idem_key: Optional[str] = None,
) -> None:
    """Начисляет монеты через economy_ledger и user_balances."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        if idem_key:
            existing = await conn.fetchrow(
                "SELECT id FROM economy_ledger WHERE idem_key = $1", idem_key
            )
            if existing:
                return
        await conn.execute(
            """INSERT INTO economy_ledger (user_id, kind, currency, amount, ref_type, ref_id, idem_key)
               VALUES ($1, 'credit', 'COINS', $2, $3, $4, $5)""",
            user_id, amount, ref_type, ref_id or "", idem_key,
        )
        await conn.execute(
            """INSERT INTO user_balances (user_id, currency, balance, updated_at)
               VALUES ($1, 'COINS', $2, NOW())
               ON CONFLICT (user_id, currency) DO UPDATE SET
                 balance = user_balances.balance + $2, updated_at = NOW()""",
            user_id, amount,
        )


async def get_item_def_ids_by_rarity(rarity: str) -> List[int]:
    """Возвращает список id item_defs заданной редкости (FIRE, YIN, YAN, TSY, MAGIC, EPIC)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id FROM item_defs WHERE rarity = $1 AND item_type IN ('relic_slot', 'amulet')",
            rarity,
        )
    return [int(r["id"]) for r in rows]


async def add_user_item(user_id: int, item_def_id: int, item_level: int = 1) -> int:
    """Добавляет предмет в инвентарь. Возвращает user_items.id."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO user_items (user_id, item_def_id, state, item_level)
               VALUES ($1, $2, 'inventory', $3) RETURNING id""",
            user_id, item_def_id, item_level,
        )
    return int(row["id"])


async def add_player_egg(user_id: int, color: str) -> int:
    """Добавляет яйцо игроку. Возвращает player_eggs.id."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO player_eggs (user_id, color) VALUES ($1, $2) RETURNING id""",
            user_id, color,
        )
    return int(row["id"])


async def get_user_balances(user_id: int) -> Dict[str, int]:
    """Балансы по валютам (COINS, STARS, DIAMONDS и т.д.)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT currency, balance FROM user_balances WHERE user_id = $1",
            user_id,
        )
    return {r["currency"]: int(r["balance"]) for r in rows}


async def get_user_inventory(user_id: int) -> Dict[str, Any]:
    """Инвентарь: user_items с item_defs + player_eggs."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT ui.id, ui.item_def_id, ui.state, ui.item_level, ui.meta, ui.acquired_at,
                      id.key as item_key, id.item_type, id.subtype, id.name, id.rarity
               FROM user_items ui
               JOIN item_defs id ON id.id = ui.item_def_id
               WHERE ui.user_id = $1 ORDER BY ui.acquired_at DESC""",
            user_id,
        )
        eggs = await conn.fetch(
            "SELECT id, color, acquired_at, meta FROM player_eggs WHERE user_id = $1 ORDER BY acquired_at DESC",
            user_id,
        )
    items = []
    for r in rows:
        items.append({
            "id": r["id"],
            "item_def_id": r["item_def_id"],
            "item_key": r["item_key"],
            "item_type": r["item_type"],
            "subtype": r["subtype"],
            "name": r["name"],
            "rarity": r["rarity"],
            "state": r["state"],
            "item_level": r["item_level"],
            "meta": dict(r["meta"]) if r["meta"] else {},
            "acquired_at": r["acquired_at"].isoformat() if r["acquired_at"] else None,
        })
    eggs_list = [
        {
            "id": r["id"],
            "color": r["color"],
            "acquired_at": r["acquired_at"].isoformat() if r["acquired_at"] else None,
            "meta": dict(r["meta"]) if r["meta"] else {},
        }
        for r in eggs
    ]
    return {"items": items, "eggs": eggs_list}


async def pick_egg_color_by_weight() -> Optional[str]:
    """Выбирает цвет яйца по весам из eggs_def. Возвращает color или None."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT color, weight FROM eggs_def")
    if not rows:
        return None
    total = sum(int(r["weight"]) for r in rows)
    r = random.randint(1, max(1, total))
    for row in rows:
        r -= int(row["weight"])
        if r <= 0:
            return row["color"]
    return rows[-1]["color"]


async def deduct_coins_ledger(
    user_id: int, amount: int, ref_type: str, ref_id: Optional[str] = None,
    idem_key: Optional[str] = None,
) -> bool:
    """Списывает монеты. Возвращает True если баланса хватило."""
    if amount <= 0:
        return True
    pool = await get_pool()
    async with pool.acquire() as conn:
        if idem_key:
            existing = await conn.fetchrow(
                "SELECT id FROM economy_ledger WHERE idem_key = $1", idem_key
            )
            if existing:
                return True
        row = await conn.fetchrow(
            "SELECT balance FROM user_balances WHERE user_id = $1 AND currency = 'COINS'",
            user_id,
        )
        balance = int(row["balance"]) if row else 0
        if balance < amount:
            return False
        await conn.execute(
            """INSERT INTO economy_ledger (user_id, kind, currency, amount, ref_type, ref_id, idem_key)
               VALUES ($1, 'debit', 'COINS', $2, $3, $4, $5)""",
            user_id, -amount, ref_type, ref_id or "", idem_key,
        )
        await conn.execute(
            """UPDATE user_balances SET balance = balance - $2, updated_at = NOW()
               WHERE user_id = $1 AND currency = 'COINS'""",
            user_id, amount,
        )
    return True


async def deduct_balance(user_id: int, currency: str, amount: int) -> bool:
    """Списывает валюту (COINS, STARS, DIAMONDS). Возвращает True если хватило."""
    if amount <= 0:
        return True
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT balance FROM user_balances WHERE user_id = $1 AND currency = $2",
            user_id, currency,
        )
        balance = int(row["balance"]) if row else 0
        if balance < amount:
            return False
        await conn.execute(
            """UPDATE user_balances SET balance = balance - $2, updated_at = NOW()
               WHERE user_id = $1 AND currency = $3""",
            user_id, amount, currency,
        )
    return True


# ——— Фаза 2: деревня и здания ———

async def get_buildings_def() -> List[Dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT key, name, category, kind, stack_limit, config FROM buildings_def ORDER BY key")
    return [
        {
            "key": r["key"],
            "name": r["name"],
            "category": r["category"],
            "kind": r["kind"],
            "stack_limit": r["stack_limit"],
            "config": dict(r["config"]) if r["config"] else {},
        }
        for r in rows
    ]


async def get_player_field(user_id: int) -> List[Dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT pf.slot_index, pf.building_key, pf.placed_at, ub.level, ub.invested_cost
               FROM player_field pf
               JOIN user_buildings ub ON ub.user_id = pf.user_id AND ub.building_key = pf.building_key
               WHERE pf.user_id = $1 ORDER BY pf.slot_index""",
            user_id,
        )
    return [
        {
            "slot_index": r["slot_index"],
            "building_key": r["building_key"],
            "level": r["level"],
            "invested_cost": int(r["invested_cost"]),
            "placed_at": r["placed_at"].isoformat() if r["placed_at"] else None,
        }
        for r in rows
    ]


async def get_user_buildings(user_id: int) -> Dict[str, Dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT building_key, level, invested_cost, updated_at FROM user_buildings WHERE user_id = $1",
            user_id,
        )
    return {
        r["building_key"]: {
            "level": r["level"],
            "invested_cost": int(r["invested_cost"]),
            "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
        }
        for r in rows
    }


async def place_building(
    user_id: int, slot_index: int, building_key: str, cost: int = 100
) -> Optional[str]:
    """Размещает здание на слот. Возвращает None при успехе, иначе строку ошибки."""
    if slot_index < 1 or slot_index > 9:
        return "invalid_slot"
    pool = await get_pool()
    async with pool.acquire() as conn:
        def_row = await conn.fetchrow("SELECT key, stack_limit FROM buildings_def WHERE key = $1", building_key)
        if not def_row:
            return "unknown_building"
        stack_limit = def_row["stack_limit"]
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM player_field WHERE user_id = $1 AND building_key = $2",
            user_id, building_key,
        )
        if count >= stack_limit:
            return "stack_limit"
        occupied = await conn.fetchrow(
            "SELECT 1 FROM player_field WHERE user_id = $1 AND slot_index = $2",
            user_id, slot_index,
        )
        if occupied:
            return "slot_occupied"
        balance_row = await conn.fetchrow(
            "SELECT balance FROM user_balances WHERE user_id = $1 AND currency = 'COINS'",
            user_id,
        )
        balance = int(balance_row["balance"]) if balance_row else 0
        if balance < cost:
            return "insufficient_coins"
        await conn.execute(
            "UPDATE user_balances SET balance = balance - $2, updated_at = NOW() WHERE user_id = $1 AND currency = 'COINS'",
            user_id, cost,
        )
        await conn.execute(
            """INSERT INTO economy_ledger (user_id, kind, currency, amount, ref_type, ref_id)
               VALUES ($1, 'debit', 'COINS', $2, 'field_place', $3)""",
            user_id, -cost, building_key,
        )
        await conn.execute(
            "INSERT INTO player_field (user_id, slot_index, building_key) VALUES ($1, $2, $3)",
            user_id, slot_index, building_key,
        )
        await conn.execute(
            """INSERT INTO user_buildings (user_id, building_key, level, invested_cost)
               VALUES ($1, $2, 1, $3) ON CONFLICT (user_id, building_key) DO UPDATE SET invested_cost = user_buildings.invested_cost + $3""",
            user_id, building_key, cost,
        )
    return None


async def demolish_building(user_id: int, slot_index: int) -> Optional[str]:
    """Сносит здание. Возвращает None при успехе, иначе строку ошибки. Refund 25%."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT building_key FROM player_field WHERE user_id = $1 AND slot_index = $2",
            user_id, slot_index,
        )
        if not row:
            return "no_building"
        building_key = row["building_key"]
        ub = await conn.fetchrow(
            "SELECT invested_cost FROM user_buildings WHERE user_id = $1 AND building_key = $2",
            user_id, building_key,
        )
        invested = int(ub["invested_cost"]) if ub else 0
        refund = int(invested * 0.25)
        await conn.execute("DELETE FROM building_slots WHERE user_id = $1 AND building_key = $2", user_id, building_key)
        await conn.execute("DELETE FROM player_field WHERE user_id = $1 AND slot_index = $2", user_id, slot_index)
        await conn.execute("DELETE FROM user_buildings WHERE user_id = $1 AND building_key = $2", user_id, building_key)
        if refund > 0:
            await conn.execute(
                "UPDATE user_balances SET balance = balance + $2, updated_at = NOW() WHERE user_id = $1 AND currency = 'COINS'",
                user_id, refund,
            )
            await conn.execute(
                """INSERT INTO economy_ledger (user_id, kind, currency, amount, ref_type, ref_id)
                   VALUES ($1, 'credit', 'COINS', $2, 'field_demolish', $3)""",
                user_id, refund, building_key,
            )
        await conn.execute(
            """INSERT INTO demolish_log (user_id, building_key, refunded_amount, refund_rate)
               VALUES ($1, $2, $3, 0.25)""",
            user_id, building_key, refund,
        )
    return None


async def upgrade_building(user_id: int, building_key: str, cost: int) -> Optional[str]:
    """Улучшает здание на 1 уровень (макс 10). Возвращает None при успехе."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT level FROM user_buildings WHERE user_id = $1 AND building_key = $2",
            user_id, building_key,
        )
        if not row:
            return "no_building"
        level = int(row["level"])
        if level >= 10:
            return "max_level"
        balance_row = await conn.fetchrow(
            "SELECT balance FROM user_balances WHERE user_id = $1 AND currency = 'COINS'",
            user_id,
        )
        balance = int(balance_row["balance"]) if balance_row else 0
        if balance < cost:
            return "insufficient_coins"
        await conn.execute(
            "UPDATE user_balances SET balance = balance - $2, updated_at = NOW() WHERE user_id = $1 AND currency = 'COINS'",
            user_id, cost,
        )
        await conn.execute(
            """INSERT INTO economy_ledger (user_id, kind, currency, amount, ref_type, ref_id)
               VALUES ($1, 'debit', 'COINS', $2, 'field_upgrade', $3)""",
            user_id, -cost, building_key,
        )
        await conn.execute(
            """UPDATE user_buildings SET level = level + 1, invested_cost = invested_cost + $3, updated_at = NOW()
               WHERE user_id = $1 AND building_key = $2""",
            user_id, building_key, cost,
        )
    return None


async def get_building_slots(user_id: int, building_key: str) -> List[Dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT slot_index, user_item_id, equipped_at FROM building_slots
               WHERE user_id = $1 AND building_key = $2 ORDER BY slot_index""",
            user_id, building_key,
        )
    return [
        {"slot_index": r["slot_index"], "user_item_id": r["user_item_id"], "equipped_at": r["equipped_at"].isoformat() if r["equipped_at"] else None}
        for r in rows
    ]


async def equip_relic(
    user_id: int, building_key: str, slot_index: int, user_item_id: int
) -> Optional[str]:
    """Ставит реликвию в слот здания. Возвращает None при успехе."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        item = await conn.fetchrow(
            "SELECT id FROM user_items WHERE user_id = $1 AND id = $2 AND state = 'inventory'",
            user_id, user_item_id,
        )
        if not item:
            return "item_not_found"
        await conn.execute(
            """INSERT INTO building_slots (user_id, building_key, slot_index, user_item_id, equipped_at)
               VALUES ($1, $2, $3, $4, NOW())
               ON CONFLICT (user_id, building_key, slot_index) DO UPDATE SET user_item_id = $4, equipped_at = NOW()""",
            user_id, building_key, slot_index, user_item_id,
        )
        await conn.execute("UPDATE user_items SET state = 'equipped' WHERE id = $1", user_item_id)
    return None


async def unequip_relic(user_id: int, building_key: str, slot_index: int) -> Optional[str]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT user_item_id FROM building_slots WHERE user_id = $1 AND building_key = $2 AND slot_index = $3",
            user_id, building_key, slot_index,
        )
        if not row or not row["user_item_id"]:
            return "no_relic"
        await conn.execute(
            "DELETE FROM building_slots WHERE user_id = $1 AND building_key = $2 AND slot_index = $3",
            user_id, building_key, slot_index,
        )
        await conn.execute("UPDATE user_items SET state = 'inventory' WHERE id = $1", row["user_item_id"])
    return None


async def lock_item_to_escrow(owner_id: int, user_item_id: int, lock_type: str, lock_id: str) -> bool:
    """Переводит предмет в escrow. Возвращает True если успешно."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id FROM user_items WHERE user_id = $1 AND id = $2 AND state = 'inventory'",
            owner_id, user_item_id,
        )
        if not row:
            return False
        await conn.execute(
            "INSERT INTO escrow_items (user_item_id, owner_id, lock_type, lock_id) VALUES ($1, $2, $3, $4)",
            user_item_id, owner_id, lock_type, lock_id,
        )
        await conn.execute("UPDATE user_items SET state = 'listed' WHERE id = $1", user_item_id)
    return True


async def unlock_escrow_items(lock_type: str, lock_id: str) -> int:
    """Разблокирует все предметы по lock_type и lock_id. Возвращает количество."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT user_item_id FROM escrow_items WHERE lock_type = $1 AND lock_id = $2",
            lock_type, lock_id,
        )
        for r in rows:
            await conn.execute("UPDATE user_items SET state = 'inventory' WHERE id = $1", r["user_item_id"])
            await conn.execute("DELETE FROM escrow_items WHERE user_item_id = $1", r["user_item_id"])
    return len(rows) if rows else 0


async def create_market_order(
    seller_id: int,
    user_item_ids: List[int],
    pay_currency: str,
    pay_amount: int,
    expires_at: Optional[Any] = None,
) -> Optional[int]:
    """Создаёт ордер на продажу. Предметы уходят в escrow. Возвращает order_id или None."""
    if pay_amount < 5:
        return None
    pool = await get_pool()
    async with pool.acquire() as conn:
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM market_orders WHERE seller_id = $1 AND status = 'open'",
            seller_id,
        )
        if count and int(count) >= 20:
            return None
        row = await conn.fetchrow(
            """INSERT INTO market_orders (seller_id, status, pay_currency, pay_amount, expires_at)
               VALUES ($1, 'open', $2, $3, $4) RETURNING id""",
            seller_id, pay_currency, pay_amount, expires_at,
        )
        order_id = int(row["id"])
        for iid in user_item_ids:
            ok = await lock_item_to_escrow(seller_id, iid, "market_order", str(order_id))
            if not ok:
                await unlock_escrow_items("market_order", str(order_id))
                await conn.execute("UPDATE market_orders SET status = 'canceled' WHERE id = $1", order_id)
                return None
            await conn.execute(
                "INSERT INTO market_order_items (order_id, user_item_id) VALUES ($1, $2)",
                order_id, iid,
            )
    return order_id


async def fill_market_order_coins(
    buyer_id: int, order_id: int, fee_pct: float = 5.0, idem_key: Optional[str] = None
) -> Optional[str]:
    """Покупатель платит COINS, продавец получает за вычетом комиссии. Предметы переходят покупателю. Ошибка = строка."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        order = await conn.fetchrow(
            "SELECT id, seller_id, pay_amount, pay_currency, status FROM market_orders WHERE id = $1",
            order_id,
        )
        if not order or order["status"] != "open":
            return "order_not_found"
        seller_id = order["seller_id"]
        amount = int(order["pay_amount"])
        if buyer_id == seller_id:
            return "cannot_buy_own"
        balance_row = await conn.fetchrow(
            "SELECT balance FROM user_balances WHERE user_id = $1 AND currency = 'COINS'",
            buyer_id,
        )
        balance = int(balance_row["balance"]) if balance_row else 0
        if balance < amount:
            return "insufficient_balance"
        fee = max(1, int(amount * fee_pct / 100))
        seller_get = amount - fee
        await conn.execute(
            "UPDATE user_balances SET balance = balance - $2, updated_at = NOW() WHERE user_id = $1 AND currency = 'COINS'",
            buyer_id, amount,
        )
        await conn.execute(
            """INSERT INTO user_balances (user_id, currency, balance, updated_at)
               VALUES ($1, 'COINS', $2, NOW())
               ON CONFLICT (user_id, currency) DO UPDATE SET balance = user_balances.balance + EXCLUDED.balance, updated_at = NOW()""",
            seller_id, seller_get,
        )
        await conn.execute("UPDATE market_orders SET status = 'filled' WHERE id = $1", order_id)
        item_rows = await conn.fetch(
            "SELECT user_item_id FROM market_order_items WHERE order_id = $1",
            order_id,
        )
        for r in item_rows:
            await conn.execute("UPDATE user_items SET user_id = $2, state = 'inventory' WHERE id = $1", r["user_item_id"], buyer_id)
            await conn.execute("DELETE FROM escrow_items WHERE user_item_id = $1", r["user_item_id"])
    return None


async def cancel_market_order(seller_id: int, order_id: int) -> Optional[str]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        order = await conn.fetchrow(
            "SELECT seller_id, status FROM market_orders WHERE id = $1",
            order_id,
        )
        if not order or order["seller_id"] != seller_id:
            return "not_found"
        if order["status"] != "open":
            return "not_open"
        await conn.execute("UPDATE market_orders SET status = 'canceled' WHERE id = $1", order_id)
    n = await unlock_escrow_items("market_order", str(order_id))
    return None


async def create_trade_offer(
    maker_id: int,
    maker_item_ids: List[int],
    taker_item_ids: List[int],
    taker_id: Optional[int] = None,
    want_currency: Optional[str] = None,
    want_amount: int = 0,
    expires_at: Optional[Any] = None,
) -> Optional[int]:
    """Создаёт оффер обмена. Предметы макера уходят в escrow. Возвращает offer_id или None."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM trade_offers WHERE maker_id = $1 AND status = 'open'",
            maker_id,
        )
        if count and int(count) >= 10:
            return None
        row = await conn.fetchrow(
            """INSERT INTO trade_offers (maker_id, status, taker_id, want_currency, want_amount, expires_at)
               VALUES ($1, 'open', $2, $3, $4, $5) RETURNING id""",
            maker_id, taker_id, want_currency or "", want_amount, expires_at,
        )
        offer_id = int(row["id"])
        for iid in maker_item_ids:
            ok = await lock_item_to_escrow(maker_id, iid, "trade_offer", str(offer_id))
            if not ok:
                await unlock_escrow_items("trade_offer", str(offer_id))
                await conn.execute("UPDATE trade_offers SET status = 'canceled' WHERE id = $1", offer_id)
                return None
            await conn.execute(
                "INSERT INTO trade_offer_items (offer_id, side, user_item_id) VALUES ($1, 'maker', $2)",
                offer_id, iid,
            )
        for iid in taker_item_ids:
            await conn.execute(
                "INSERT INTO trade_offer_items (offer_id, side, user_item_id) VALUES ($1, 'taker', $2)",
                offer_id, iid,
            )
    return offer_id


async def accept_trade_offer(taker_id: int, offer_id: int) -> Optional[str]:
    """Принять оффер: обмен предметами. Ошибка = строка."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        offer = await conn.fetchrow(
            "SELECT maker_id, status, want_currency, want_amount FROM trade_offers WHERE id = $1",
            offer_id,
        )
        if not offer or offer["status"] != "open":
            return "offer_not_found"
        maker_id = offer["maker_id"]
        if maker_id == taker_id:
            return "cannot_trade_self"
        want_amount = int(offer["want_amount"]) or 0
        want_cur = offer["want_currency"] or "COINS"
        if want_amount > 0:
            row = await conn.fetchrow(
                "SELECT balance FROM user_balances WHERE user_id = $1 AND currency = $2",
                taker_id, want_cur,
            )
            if not row or int(row["balance"]) < want_amount:
                return "insufficient_balance"
            await deduct_balance(taker_id, want_cur, want_amount)
            if want_cur == "COINS":
                await add_coins_ledger(maker_id, want_amount, "trade_offer", ref_id=str(offer_id))
            else:
                await conn.execute(
                    """INSERT INTO user_balances (user_id, currency, balance, updated_at)
                       VALUES ($1, $2, $3, NOW())
                       ON CONFLICT (user_id, currency) DO UPDATE SET balance = user_balances.balance + EXCLUDED.balance, updated_at = NOW()""",
                    maker_id, want_cur, want_amount,
                )
        maker_items = await conn.fetch(
            "SELECT user_item_id FROM trade_offer_items WHERE offer_id = $1 AND side = 'maker'",
            offer_id,
        )
        taker_items = await conn.fetch(
            "SELECT user_item_id FROM trade_offer_items WHERE offer_id = $1 AND side = 'taker'",
            offer_id,
        )
        for r in maker_items:
            await conn.execute("UPDATE user_items SET user_id = $2, state = 'inventory' WHERE id = $1", r["user_item_id"], taker_id)
            await conn.execute("DELETE FROM escrow_items WHERE user_item_id = $1", r["user_item_id"])
        for r in taker_items:
            it = await conn.fetchrow("SELECT user_id FROM user_items WHERE id = $1", r["user_item_id"])
            if it and it["user_id"] == taker_id:
                await conn.execute("UPDATE user_items SET user_id = $2 WHERE id = $1", r["user_item_id"], maker_id)
        await conn.execute("UPDATE trade_offers SET status = 'filled', taker_id = $2 WHERE id = $1", offer_id, taker_id)
    return None


async def cancel_trade_offer(maker_id: int, offer_id: int) -> Optional[str]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        offer = await conn.fetchrow(
            "SELECT maker_id, status FROM trade_offers WHERE id = $1",
            offer_id,
        )
        if not offer or offer["maker_id"] != maker_id:
            return "not_found"
        if offer["status"] != "open":
            return "not_open"
        await conn.execute("UPDATE trade_offers SET status = 'canceled' WHERE id = $1", offer_id)
    await unlock_escrow_items("trade_offer", str(offer_id))
    return None


async def get_staking_sessions(user_id: int) -> List[Dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT id, staked_amount, accrued_rewards, status, lock_until, payment_address, created_at
               FROM staking_sessions WHERE user_id = $1 ORDER BY created_at DESC""",
            user_id,
        )
    return [
        {
            "id": r["id"],
            "staked_amount": float(r["staked_amount"]),
            "accrued_rewards": float(r["accrued_rewards"]),
            "status": r["status"],
            "lock_until": r["lock_until"].isoformat() if r["lock_until"] else None,
            "payment_address": r["payment_address"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        }
        for r in rows
    ]


async def get_leaderboards(period: str, period_key: Optional[str] = None) -> List[Dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        if period_key:
            rows = await conn.fetch(
                "SELECT user_id, points, updated_at FROM leaderboards WHERE period = $1 AND period_key = $2 ORDER BY points DESC LIMIT 100",
                period, period_key,
            )
        else:
            rows = await conn.fetch(
                "SELECT period_key, user_id, points, updated_at FROM leaderboards WHERE period = $1 ORDER BY period_key DESC, points DESC LIMIT 500",
                period,
            )
    return [
        {
            "period_key": r.get("period_key"),
            "user_id": r["user_id"],
            "points": int(r["points"]),
            "updated_at": r["updated_at"].isoformat() if r.get("updated_at") else None,
        }
        for r in rows
    ]


async def get_withdraw_eligibility(user_id: int) -> Dict[str, Any]:
    """Проверка возможности вывода: уровень, кошелёк, gating, compliance."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        wallet = await conn.fetchrow("SELECT wallet_address FROM user_wallets WHERE user_id = $1", user_id)
        gating = await conn.fetchrow(
            "SELECT required_action_value_ton, completed_action_value_ton, status FROM withdraw_gating WHERE user_id = $1",
            user_id,
        )
        compliance = await conn.fetchrow("SELECT status FROM token_compliance WHERE user_id = $1", user_id)
    level_ok = True  # TODO: compute from exp/level table
    wallet_bound = wallet is not None
    required = float(gating["required_action_value_ton"]) if gating else 0
    completed = float(gating["completed_action_value_ton"]) if gating else 0
    rule_10_ok = completed >= required if required else True
    compliance_ok = compliance is None or compliance["status"] == "ok"
    can_withdraw = level_ok and wallet_bound and rule_10_ok and compliance_ok
    return {
        "can_withdraw": can_withdraw,
        "level_ok": level_ok,
        "wallet_bound": wallet_bound,
        "rule_10_ok": rule_10_ok,
        "required_action_value_ton": required,
        "completed_action_value_ton": completed,
        "compliance_ok": compliance_ok,
    }


async def record_ad_view(user_id: int, ad_kind: str, provider: Optional[str] = None, idem_key: Optional[str] = None) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        if idem_key:
            ex = await conn.fetchrow("SELECT id FROM ad_log WHERE idem_key = $1", idem_key)
            if ex:
                return True
        await conn.execute(
            "INSERT INTO ad_log (user_id, ad_kind, provider, idem_key) VALUES ($1, $2, $3, $4)",
            user_id, ad_kind, provider or "", idem_key,
        )
    return True


async def donate_to_profile(
    user_id: int, currency: str, amount: int, period_key: str,
    donation_points: float = 0, idem_key: Optional[str] = None,
) -> bool:
    credit = donation_points * 0.0001  # TON-equivalent for rule 10%
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO donations (user_id, currency, amount, donation_points, period_key) VALUES ($1, $2, $3, $4, $5)",
            user_id, currency, amount, donation_points, period_key,
        )
        await conn.execute(
            """INSERT INTO withdraw_gating (user_id, completed_action_value_ton, status)
               VALUES ($1, $2, 'open')
               ON CONFLICT (user_id) DO UPDATE SET
                 completed_action_value_ton = withdraw_gating.completed_action_value_ton + $2""",
            user_id, credit,
        )
    return True


async def get_market_orders_open(pay_currency: Optional[str] = None) -> List[Dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        if pay_currency:
            rows = await conn.fetch(
                """SELECT id, seller_id, pay_currency, pay_amount, expires_at, created_at
                   FROM market_orders WHERE status = 'open' AND pay_currency = $1 ORDER BY created_at DESC""",
                pay_currency,
            )
        else:
            rows = await conn.fetch(
                """SELECT id, seller_id, pay_currency, pay_amount, expires_at, created_at
                   FROM market_orders WHERE status = 'open' ORDER BY created_at DESC"""
            )
    return [
        {
            "id": r["id"],
            "seller_id": r["seller_id"],
            "pay_currency": r["pay_currency"],
            "pay_amount": int(r["pay_amount"]),
            "expires_at": r["expires_at"].isoformat() if r["expires_at"] else None,
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        }
        for r in rows
    ]


async def collect_income(user_id: int) -> Dict[str, Any]:
    """Начисляет доход с поля за оффлайн (кап 12 ч). Возвращает { earned, hours_used }."""
    from datetime import datetime, timezone
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT pf.slot_index, pf.building_key, ub.level, bd.config
               FROM player_field pf
               JOIN user_buildings ub ON ub.user_id = pf.user_id AND ub.building_key = pf.building_key
               JOIN buildings_def bd ON bd.key = pf.building_key
               WHERE pf.user_id = $1""",
            user_id,
        )
        profile = await conn.fetchrow(
            "SELECT ads_enabled FROM user_profile WHERE user_id = $1",
            user_id,
        )
    ads_mult = 1.0 if (profile and profile["ads_enabled"]) else 0.5
    total_per_hour = 0
    for r in rows:
        config = dict(r["config"]) if r["config"] else {}
        income_arr = config.get("incomePerHour") or [0] * 10
        level = min(int(r["level"]), 10)
        base = income_arr[level - 1] if level <= len(income_arr) else 0
        total_per_hour += base * ads_mult
    cap_hours = 12
    # Упрощение: считаем что последний сбор был при placed_at или сейчас - 12ч
    hours_used = min(cap_hours, 12.0)
    earned = int(total_per_hour * hours_used)
    if earned > 0:
        await add_coins_ledger(user_id, earned, "field_income", ref_id="collect")
    return {"earned": earned, "hours_used": hours_used}


async def update_checkin_state(
    user_id: int,
    granted_attempts: int,
    next_checkin_at,
    base_cd_minutes: int,
    bonus_minutes_used: int = 0,
    effective_cd_minutes: int = 600,
) -> None:
    """Обновляет checkin_state и пишет checkin_log после успешного чекина."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """UPDATE checkin_state SET
                 last_checkin_at = NOW(),
                 next_checkin_at = $2,
                 streak = streak + 1,
                 updated_at = NOW()
               WHERE user_id = $1""",
            user_id, next_checkin_at,
        )
        await conn.execute(
            """INSERT INTO checkin_log (user_id, granted_attempts, base_cd_minutes, bonus_minutes_used, effective_cd_minutes, next_checkin_at)
               VALUES ($1, $2, $3, $4, $5, $6)""",
            user_id, granted_attempts, base_cd_minutes, bonus_minutes_used, effective_cd_minutes, next_checkin_at,
        )
        await conn.execute(
            """UPDATE attempts_balance SET attempts = attempts + $2, updated_at = NOW()
               WHERE user_id = $1""",
            user_id, granted_attempts,
        )


# ——— Админ-панель: партнёрские токены, задания, тексты страниц ———

async def admin_get_partner_tokens(project_id: int = 1, active_only: bool = False) -> List[Dict[str, Any]]:
    """Список партнёрских токенов (для оплаты и т.д.)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        where = "WHERE project_id = $1 AND is_active = TRUE" if active_only else "WHERE project_id = $1"
        params = (project_id,) if active_only else (project_id,)
        rows = await conn.fetch(
            f"""SELECT id, project_id, token_address, symbol, name, usage, is_active, sort_order, created_at
               FROM admin_partner_tokens {where} ORDER BY sort_order, id""",
            *params,
        )
    return [dict(r) for r in rows]


async def admin_add_partner_token(
    token_address: str,
    symbol: str,
    name: Optional[str] = None,
    usage: str = "payment",
    sort_order: int = 0,
    project_id: int = 1,
) -> Optional[int]:
    """Добавить партнёрский токен. Возвращает id или None при дубликате."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            row = await conn.fetchrow(
                """INSERT INTO admin_partner_tokens (project_id, token_address, symbol, name, usage, sort_order)
                   VALUES ($1, $2, $3, $4, $5, $6) RETURNING id""",
                project_id, token_address.strip(), symbol.strip(), (name or "").strip(), usage.strip(), sort_order,
            )
            return row["id"] if row else None
        except asyncpg.UniqueViolationError:
            return None


async def admin_delete_partner_token(token_id: int) -> bool:
    """Удалить партнёрский токен по id."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        n = await conn.execute("DELETE FROM admin_partner_tokens WHERE id = $1", token_id)
    return n == "DELETE 1"


async def admin_get_tasks(project_id: int = 1, active_only: bool = False) -> List[Dict[str, Any]]:
    """Список заданий (контрактов)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        where = "WHERE project_id = $1 AND is_active = TRUE" if active_only else "WHERE project_id = $1"
        rows = await conn.fetch(
            f"""SELECT id, project_id, task_key, title, description, reward_type, reward_value,
                      conditions_json, is_active, sort_order, created_at, updated_at
               FROM admin_tasks {where} ORDER BY sort_order, id""",
            project_id,
        )
    return [dict(r) for r in rows]


async def admin_add_task(
    task_key: str,
    title: str,
    description: Optional[str] = None,
    reward_type: Optional[str] = None,
    reward_value: int = 0,
    conditions_json: Optional[Dict] = None,
    sort_order: int = 0,
    project_id: int = 1,
) -> Optional[int]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            row = await conn.fetchrow(
                """INSERT INTO admin_tasks (project_id, task_key, title, description, reward_type, reward_value, conditions_json, sort_order)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8) RETURNING id""",
                project_id, task_key.strip(), title.strip(), (description or "").strip(), reward_type or "", reward_value,
                json.dumps(conditions_json or {}), sort_order,
            )
            return row["id"] if row else None
        except asyncpg.UniqueViolationError:
            return None


async def admin_update_task(
    task_id: int,
    title: Optional[str] = None,
    description: Optional[str] = None,
    reward_type: Optional[str] = None,
    reward_value: Optional[int] = None,
    conditions_json: Optional[Dict] = None,
    is_active: Optional[bool] = None,
    sort_order: Optional[int] = None,
) -> bool:
    pool = await get_pool()
    updates = []
    values = []
    i = 1
    if title is not None:
        updates.append(f"title = ${i}")
        values.append(title)
        i += 1
    if description is not None:
        updates.append(f"description = ${i}")
        values.append(description)
        i += 1
    if reward_type is not None:
        updates.append(f"reward_type = ${i}")
        values.append(reward_type)
        i += 1
    if reward_value is not None:
        updates.append(f"reward_value = ${i}")
        values.append(reward_value)
        i += 1
    if conditions_json is not None:
        updates.append(f"conditions_json = ${i}")
        values.append(json.dumps(conditions_json))
        i += 1
    if is_active is not None:
        updates.append(f"is_active = ${i}")
        values.append(is_active)
        i += 1
    if sort_order is not None:
        updates.append(f"sort_order = ${i}")
        values.append(sort_order)
        i += 1
    if not updates:
        return True
    updates.append("updated_at = NOW()")
    values.append(task_id)
    async with pool.acquire() as conn:
        n = await conn.execute(
            f"UPDATE admin_tasks SET {', '.join(updates)} WHERE id = ${i}",
            *values,
        )
    return n == "UPDATE 1"


async def admin_delete_task(task_id: int) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        n = await conn.execute("DELETE FROM admin_tasks WHERE id = $1", task_id)
    return n == "DELETE 1"


async def admin_get_page_texts(page_id: Optional[str] = None, project_id: int = 1) -> Dict[str, Any]:
    """Тексты для страниц. Если page_id задан — словарь { text_key: text_value }; иначе { page_id: { key: value } }."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        if page_id:
            rows = await conn.fetch(
                "SELECT text_key, text_value FROM admin_page_texts WHERE project_id = $1 AND page_id = $2",
                project_id, page_id,
            )
            return {r["text_key"]: r["text_value"] for r in rows}
        rows = await conn.fetch(
            "SELECT page_id, text_key, text_value FROM admin_page_texts WHERE project_id = $1 ORDER BY page_id, text_key",
            project_id,
        )
        out = {}
        for r in rows:
            pid = r["page_id"]
            if pid not in out:
                out[pid] = {}
            out[pid][r["text_key"]] = r["text_value"]
        return out


async def admin_set_page_texts(page_id: str, texts: Dict[str, str], project_id: int = 1) -> None:
    """Записать/обновить тексты страницы. texts = { key: value }."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        for k, v in texts.items():
            await conn.execute(
                """INSERT INTO admin_page_texts (project_id, page_id, text_key, text_value, updated_at)
                   VALUES ($1, $2, $3, $4, NOW())
                   ON CONFLICT (project_id, page_id, text_key) DO UPDATE SET text_value = $4, updated_at = NOW()""",
                project_id, page_id.strip(), k.strip(), (v or "").strip(),
            )


# ——— Каналы/чаты проекта ———

async def admin_get_channels(project_id: int = 1, active_only: bool = False) -> List[Dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        where = "WHERE project_id = $1 AND is_active = TRUE" if active_only else "WHERE project_id = $1"
        rows = await conn.fetch(
            f"""SELECT id, project_id, chat_id, title, channel_type, is_active, sort_order, created_at
               FROM admin_channels {where} ORDER BY sort_order, id""",
            project_id,
        )
    return [dict(r) for r in rows]


async def admin_add_channel(
    project_id: int,
    chat_id: int,
    title: Optional[str] = None,
    channel_type: str = "channel",
    sort_order: int = 0,
) -> Optional[int]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            row = await conn.fetchrow(
                """INSERT INTO admin_channels (project_id, chat_id, title, channel_type, sort_order)
                   VALUES ($1, $2, $3, $4, $5) RETURNING id""",
                project_id, chat_id, (title or "").strip(), channel_type.strip(), sort_order,
            )
            return row["id"] if row else None
        except asyncpg.UniqueViolationError:
            return None


async def admin_delete_channel(channel_id: int) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        n = await conn.execute("DELETE FROM admin_channels WHERE id = $1", channel_id)
    return n == "DELETE 1"


# ——— Лог активности и статистика (мониторинг пользователя в проекте) ———

async def activity_log_record(
    project_id: int,
    telegram_id: int,
    event_type: str,
    channel_id: Optional[int] = None,
    event_meta: Optional[Dict] = None,
    user_id: Optional[int] = None,
) -> None:
    """Записать событие активности. Обновляет user_activity_stats."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        if user_id is None:
            u = await conn.fetchrow("SELECT id FROM users WHERE telegram_id = $1", telegram_id)
            user_id = u["id"] if u else None
        await conn.execute(
            """INSERT INTO activity_log (project_id, user_id, telegram_id, channel_id, event_type, event_meta)
               VALUES ($1, $2, $3, $4, $5, $6)""",
            project_id, user_id, telegram_id, channel_id, event_type, json.dumps(event_meta or {}),
        )
        if user_id:
            if event_type == "message_sent":
                await conn.execute(
                    """INSERT INTO user_activity_stats (user_id, project_id, total_messages_sent, last_activity_at)
                       VALUES ($1, $2, 1, NOW())
                       ON CONFLICT (user_id, project_id) DO UPDATE SET
                         total_messages_sent = user_activity_stats.total_messages_sent + 1,
                         last_activity_at = NOW()""",
                    user_id, project_id,
                )
            elif event_type == "reaction_received":
                meta = event_meta or {}
                rtype = meta.get("reaction_type", "unknown")
                await conn.execute(
                    """INSERT INTO user_activity_stats (user_id, project_id, total_reactions_received, reactions_by_type, last_activity_at)
                       VALUES ($1, $2, 1, jsonb_build_object($3, 1), NOW())
                       ON CONFLICT (user_id, project_id) DO UPDATE SET
                         total_reactions_received = user_activity_stats.total_reactions_received + 1,
                         reactions_by_type = COALESCE(user_activity_stats.reactions_by_type, '{}') || jsonb_build_object($3, COALESCE((user_activity_stats.reactions_by_type->>$3)::int, 0) + 1),
                         last_activity_at = NOW()""",
                    user_id, project_id, rtype,
                )
            else:
                await conn.execute(
                    """INSERT INTO user_activity_stats (user_id, project_id, last_activity_at)
                       VALUES ($1, $2, NOW())
                       ON CONFLICT (user_id, project_id) DO UPDATE SET last_activity_at = NOW()""",
                    user_id, project_id,
                )


async def admin_get_activity_log(
    project_id: int = 1,
    user_id: Optional[int] = None,
    telegram_id: Optional[int] = None,
    limit: int = 100,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        if user_id is not None:
            rows = await conn.fetch(
                """SELECT id, project_id, user_id, telegram_id, channel_id, event_type, event_meta, created_at
                   FROM activity_log WHERE project_id = $1 AND user_id = $2 ORDER BY created_at DESC LIMIT $3 OFFSET $4""",
                project_id, user_id, limit, offset,
            )
        elif telegram_id is not None:
            rows = await conn.fetch(
                """SELECT id, project_id, user_id, telegram_id, channel_id, event_type, event_meta, created_at
                   FROM activity_log WHERE project_id = $1 AND telegram_id = $2 ORDER BY created_at DESC LIMIT $3 OFFSET $4""",
                project_id, telegram_id, limit, offset,
            )
        else:
            rows = await conn.fetch(
                """SELECT id, project_id, user_id, telegram_id, channel_id, event_type, event_meta, created_at
                   FROM activity_log WHERE project_id = $1 ORDER BY created_at DESC LIMIT $2 OFFSET $3""",
                project_id, limit, offset,
            )
    return [dict(r) for r in rows]


async def admin_get_activity_stats(project_id: int = 1, user_id: Optional[int] = None) -> List[Dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        if user_id is not None:
            rows = await conn.fetch(
                """SELECT uas.*, u.telegram_id FROM user_activity_stats uas
                   JOIN users u ON u.id = uas.user_id
                   WHERE uas.project_id = $1 AND uas.user_id = $2""",
                project_id, user_id,
            )
        else:
            rows = await conn.fetch(
                """SELECT uas.*, u.telegram_id FROM user_activity_stats uas
                   JOIN users u ON u.id = uas.user_id
                   WHERE uas.project_id = $1 ORDER BY uas.last_activity_at DESC NULLS LAST""",
                project_id,
            )
    return [dict(r) for r in rows]
