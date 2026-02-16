import json
import logging
import random
from datetime import datetime, timezone, timedelta
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
        # users: telegram_id — ID из Telegram; id — наш внутренний ID для связей (FK во всех таблицах)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                telegram_id BIGINT UNIQUE NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_users_telegram ON users(telegram_id)")
        # Подстройка под существующую БД: если users уже был без id (только telegram_id), добавляем id для связей
        try:
            await conn.execute(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS id SERIAL UNIQUE NOT NULL"
            )
        except Exception as e:
            if "already exists" not in str(e).lower():
                logger.warning("users.id migration: %s", e)
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

        # Статистика по предметам: события (дроп, сжигание, слияние, продажа и т.д.)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS item_events (
                id SERIAL PRIMARY KEY,
                item_def_id INTEGER REFERENCES item_defs(id) ON DELETE SET NULL,
                event_type TEXT NOT NULL,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                quantity INTEGER NOT NULL DEFAULT 1,
                ref_type TEXT,
                ref_id BIGINT,
                meta JSONB NOT NULL DEFAULT '{}',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_item_events_item_def ON item_events(item_def_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_item_events_type ON item_events(event_type)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_item_events_user ON item_events(user_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_item_events_created ON item_events(created_at)")

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

        # Магазин из казны (фиксированные предложения)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS shop_offers (
                id SERIAL PRIMARY KEY,
                item_def_id INTEGER NOT NULL UNIQUE REFERENCES item_defs(id) ON DELETE RESTRICT,
                pay_currency TEXT NOT NULL DEFAULT 'COINS',
                pay_amount BIGINT NOT NULL,
                stock_type TEXT NOT NULL DEFAULT 'unlimited',
                max_per_user_per_era INTEGER,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_shop_offers_item ON shop_offers(item_def_id)")

        # Визиты и атаки (ограбление построек)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS visit_log (
                id SERIAL PRIMARY KEY,
                visitor_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                target_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                visited_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                attack_performed BOOLEAN NOT NULL DEFAULT FALSE,
                buildings_robbed JSONB NOT NULL DEFAULT '{}',
                total_stolen BIGINT NOT NULL DEFAULT 0
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_visit_log_visitor ON visit_log(visitor_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_visit_log_target ON visit_log(target_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_visit_log_visited_at ON visit_log(visited_at)")

        # Накопленные монеты по зданию (до сбора)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS building_pending_income (
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                slot_index INTEGER NOT NULL CHECK (slot_index >= 1 AND slot_index <= 9),
                pending_coins BIGINT NOT NULL DEFAULT 0,
                last_updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (user_id, slot_index)
            )
        """)

        # Кулдаун ограбления: атакующий–цель–слот, раз в час
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS rob_cooldown (
                attacker_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                target_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                slot_index INTEGER NOT NULL CHECK (slot_index >= 1 AND slot_index <= 9),
                last_robbed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (attacker_id, target_id, slot_index)
            )
        """)

        # Фамильяры (определения)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS familiars_def (
                id SERIAL PRIMARY KEY,
                key TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                passive_buff_json JSONB NOT NULL DEFAULT '{}',
                extra_abilities JSONB NOT NULL DEFAULT '[]',
                rarity TEXT NOT NULL DEFAULT 'common'
            )
        """)

        # Фамильяры у игрока
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_familiars (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                familiar_def_id INTEGER NOT NULL REFERENCES familiars_def(id) ON DELETE RESTRICT,
                equipped BOOLEAN NOT NULL DEFAULT TRUE,
                acquired_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_user_familiars_user ON user_familiars(user_id)")

        # Пул результатов вылупления яиц (color, rarity -> тип и веса)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS egg_hatch_pool (
                id SERIAL PRIMARY KEY,
                egg_color TEXT NOT NULL REFERENCES eggs_def(color) ON DELETE CASCADE,
                egg_rarity TEXT NOT NULL DEFAULT 'common',
                outcome_type TEXT NOT NULL,
                weight INTEGER NOT NULL DEFAULT 1,
                UNIQUE(egg_color, egg_rarity, outcome_type)
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_egg_hatch_pool_color ON egg_hatch_pool(egg_color)")

        # Фаза 5: вывод и eligibility (18_Dev, 08)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_wallets (
                user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                wallet_address TEXT NOT NULL UNIQUE,
                verified_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        # До 10 кошельков на юзера: привязки с отдельным verify_code на каждую
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_wallet_bindings (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                wallet_address TEXT UNIQUE,
                verify_code TEXT,
                verified_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_user_wallet_bindings_user ON user_wallet_bindings(user_id)")
        # Миграция: скопировать из user_wallets в user_wallet_bindings (один раз)
        await conn.execute("""
            INSERT INTO user_wallet_bindings (user_id, wallet_address, verified_at, created_at)
            SELECT user_id, wallet_address, verified_at, created_at FROM user_wallets
            ON CONFLICT (wallet_address) DO NOTHING
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
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS withdraw_penalties (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                amount NUMERIC NOT NULL DEFAULT 0,
                currency TEXT NOT NULL DEFAULT 'PHXPW',
                reason TEXT,
                notify_user BOOLEAN NOT NULL DEFAULT FALSE,
                notified_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                created_by_telegram_id BIGINT
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
            CREATE TABLE IF NOT EXISTS user_task_claims (
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                task_key TEXT NOT NULL,
                claimed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (user_id, task_key)
            )
        """)

        # Квест ФЕНИКС: текущее слово, счётчик сдач (макс 5), смена слова после 5
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS phoenix_quest_state (
                id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
                current_word TEXT NOT NULL DEFAULT 'ФЕНИКС',
                submissions_count INTEGER NOT NULL DEFAULT 0,
                word_index INTEGER NOT NULL DEFAULT 0,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        await conn.execute("""
            INSERT INTO phoenix_quest_state (id, current_word, submissions_count, word_index)
            VALUES (1, 'ФЕНИКС', 0, 0) ON CONFLICT (id) DO NOTHING
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

        # Админ-панель (отдельный вход по логину/паролю, не в основном приложении)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS admin_panel_credentials (
                id SERIAL PRIMARY KEY,
                login TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                token TEXT,
                token_expires_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS staking_contract_addresses (
                id SERIAL PRIMARY KEY,
                contract_address TEXT NOT NULL UNIQUE,
                label TEXT,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)

        # NFT-каталог разработчика: коллекции и отдельные NFT
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS dev_collections (
                id SERIAL PRIMARY KEY,
                collection_address TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                image TEXT NOT NULL DEFAULT '',
                creator_address TEXT NOT NULL DEFAULT '',
                items_count INTEGER NOT NULL DEFAULT 0,
                synced_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS dev_nfts (
                id SERIAL PRIMARY KEY,
                nft_address TEXT NOT NULL UNIQUE,
                collection_id INTEGER REFERENCES dev_collections(id) ON DELETE CASCADE,
                collection_address TEXT NOT NULL DEFAULT '',
                nft_index INTEGER NOT NULL DEFAULT 0,
                owner_address TEXT NOT NULL DEFAULT '',
                name TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                image TEXT NOT NULL DEFAULT '',
                metadata_url TEXT NOT NULL DEFAULT '',
                attributes JSONB NOT NULL DEFAULT '[]',
                mint_timestamp TIMESTAMPTZ,
                synced_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_dev_nfts_collection ON dev_nfts(collection_address)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_dev_nfts_owner ON dev_nfts(owner_address)")
        # Лог синхронизации NFT (когда последний раз запускали полный/инкрементальный синк)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS nft_sync_log (
                id SERIAL PRIMARY KEY,
                sync_type TEXT NOT NULL DEFAULT 'full',
                collections_synced INTEGER NOT NULL DEFAULT 0,
                nfts_synced INTEGER NOT NULL DEFAULT 0,
                errors INTEGER NOT NULL DEFAULT 0,
                started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                finished_at TIMESTAMPTZ
            )
        """)

        # ——— nft_holder_snapshots: cached NFT holder analytics ———
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS nft_holder_snapshots (
                id SERIAL PRIMARY KEY,
                owner_address TEXT NOT NULL,
                nft_count INTEGER NOT NULL DEFAULT 0,
                collections JSONB NOT NULL DEFAULT '[]',
                phxpw_balance NUMERIC NOT NULL DEFAULT 0,
                total_received NUMERIC NOT NULL DEFAULT 0,
                total_sent NUMERIC NOT NULL DEFAULT 0,
                staking_rewards NUMERIC NOT NULL DEFAULT 0,
                linked_telegram_id BIGINT,
                linked_username TEXT,
                synced_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE(owner_address)
            )
        """)

        # ——— game_settings: runtime-editable config (key-value) ———
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS game_settings (
                key TEXT PRIMARY KEY,
                value JSONB NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)

        # ——— referrals: общая реферальная система для экосистемы ———
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS referrals (
                referrer_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                referred_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE(referred_user_id)
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_referrals_referrer ON referrals(referrer_user_id)")

        # ——— tigrit_*: микросервис Деревня Тигрит (общий users.id) ———
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS tigrit_user_profile (
                user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                username TEXT,
                race TEXT,
                clazz TEXT,
                xp INTEGER NOT NULL DEFAULT 0,
                level INTEGER NOT NULL DEFAULT 0,
                house INTEGER NOT NULL DEFAULT 0,
                job INTEGER NOT NULL DEFAULT 0,
                friends INTEGER NOT NULL DEFAULT 0,
                last_activity BIGINT DEFAULT 0,
                activity_count INTEGER NOT NULL DEFAULT 0,
                tax_applied INTEGER NOT NULL DEFAULT 0,
                job_name TEXT,
                job_expires_at BIGINT DEFAULT 0,
                job_xp_per_hour INTEGER DEFAULT 0,
                job_msg_chat_id BIGINT DEFAULT 0,
                job_msg_id BIGINT DEFAULT 0,
                personal_resources INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS tigrit_cooldowns (
                user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                last_xp_at BIGINT DEFAULT 0
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS tigrit_village (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                level INTEGER NOT NULL DEFAULT 0,
                activity INTEGER NOT NULL DEFAULT 0,
                resources INTEGER NOT NULL DEFAULT 0,
                population INTEGER NOT NULL DEFAULT 0,
                build_stage INTEGER NOT NULL DEFAULT 0,
                build_name TEXT NOT NULL DEFAULT 'Площадь',
                build_progress INTEGER NOT NULL DEFAULT 0,
                last_tick BIGINT DEFAULT 0,
                last_tax_check BIGINT DEFAULT 0,
                last_event_time BIGINT DEFAULT 0
            )
        """)
        await conn.execute("INSERT INTO tigrit_village (id) VALUES (1) ON CONFLICT (id) DO NOTHING")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS tigrit_chats (
                chat_id BIGINT PRIMARY KEY,
                type TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL DEFAULT '',
                invite_link TEXT,
                owner_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS tigrit_settings (
                k TEXT PRIMARY KEY,
                v TEXT
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS tigrit_interactions (
                id SERIAL PRIMARY KEY,
                ts BIGINT DEFAULT 0,
                kind TEXT,
                actor_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
                target_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
                payload TEXT
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS tigrit_last_messages (
                chat_id BIGINT NOT NULL,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                kind TEXT NOT NULL DEFAULT '',
                message_id BIGINT NOT NULL DEFAULT 0,
                updated_at BIGINT DEFAULT 0,
                PRIMARY KEY (chat_id, user_id, kind)
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS tigrit_events (
                id SERIAL PRIMARY KEY,
                title TEXT,
                effect_type TEXT,
                effect_sign INTEGER DEFAULT 0,
                effect_value INTEGER DEFAULT 0,
                chat_id BIGINT,
                message_id BIGINT,
                start_ts BIGINT DEFAULT 0,
                end_ts BIGINT DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'active'
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS tigrit_event_participants (
                event_id INTEGER NOT NULL REFERENCES tigrit_events(id) ON DELETE CASCADE,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                decision TEXT NOT NULL DEFAULT '',
                ts BIGINT DEFAULT 0,
                PRIMARY KEY (event_id, user_id)
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
            "ALTER TABLE user_profile ADD COLUMN IF NOT EXISTS badges JSONB NOT NULL DEFAULT '[]'",
            "ALTER TABLE user_profile ADD COLUMN IF NOT EXISTS last_collected_at TIMESTAMPTZ",
            "ALTER TABLE user_profile ADD COLUMN IF NOT EXISTS furnace_bonus_until TIMESTAMPTZ",
            "ALTER TABLE dev_collections ADD COLUMN IF NOT EXISTS project_id INTEGER DEFAULT 1",
            "ALTER TABLE dev_nfts ADD COLUMN IF NOT EXISTS project_id INTEGER DEFAULT 1",
        ):
            try:
                await conn.execute(sql)
            except Exception as e:
                if "already exists" not in str(e).lower() and "duplicate" not in str(e).lower():
                    logger.warning("Migration step: %s", e)
        await _seed_item_defs_and_eggs(conn)
        await _seed_buildings_def(conn)
        await _seed_familiars_def(conn)
        await _seed_egg_hatch_pool(conn)
        await _seed_shop_offers(conn)
    await seed_game_settings()
    logger.info("Game DB initialized")


# allowed_buildings для реликвий (02_Реликвии_и_эффекты)
RELIC_ALLOWED_BUILDINGS = {
    "fire_01": ["houses"], "fire_02": ["farm"], "fire_03": ["market", "trade_guild", "auction_house"],
    "fire_04": ["lumbermill", "quarry", "caravan"], "fire_05": ["market", "trade_guild", "auction_house"],
    "fire_06": ["workshop", "alchemy"], "fire_07": ["post_office", "ad_totem"], "fire_08": ["warehouse", "treasury"],
    "yin_01": ["houses", "firebrigade"], "yin_02": ["guard_post", "watchtower", "infirmary"],
    "yin_03": ["townhall"], "yin_04": ["treasury", "well"], "yin_05": ["houses", "guard_post"],
    "yin_06": ["farm", "infirmary"], "yin_07": ["market", "trade_guild"], "yin_08": ["well", "firebrigade"],
    "yan_01": ["forge", "arena"], "yan_02": ["forge", "blacklist_office"], "yan_03": ["forge", "arena"],
    "yan_04": ["forge", "arena"], "yan_05": ["market", "blacklist_office"], "yan_06": ["forge"],
    "yan_07": ["forge", "arena"], "yan_08": ["era_monument"],
}


async def _seed_item_defs_and_eggs(conn: asyncpg.Connection) -> None:
    """Сид item_defs из каталога (все категории с описанием) и eggs_def (по конфигу)."""
    from pathlib import Path
    # eggs_def из game config
    from config import get_eggs_config
    eggs_cfg = get_eggs_config()
    for c in eggs_cfg.get("colors", []):
        await conn.execute(
            """INSERT INTO eggs_def (color, rarity, weight)
               VALUES ($1, $2, $3) ON CONFLICT (color) DO NOTHING""",
            c.get("color", ""), c.get("rarity", "common"), c.get("weight", 1),
        )
    # Каталог: сначала Игра/data/items-catalog.json, иначе бэкенд/data/items_defs_seed.json
    base = Path(__file__).resolve().parent.parent
    catalog_path = base.parent / "data" / "items-catalog.json"
    if not catalog_path.exists():
        catalog_path = base / "data" / "items_defs_seed.json"
    catalog = []
    if catalog_path.exists():
        try:
            with open(catalog_path, "r", encoding="utf-8") as f:
                catalog = json.load(f)
        except Exception as e:
            logger.warning("Could not load items catalog from %s: %s", catalog_path, e)
    # Если каталог загружен — upsert все предметы с эффектом и описанием
    for it in catalog:
        key = it.get("key") or it.get("id")
        if not key:
            continue
        item_type = it.get("slot_type") or it.get("item_type", "")
        subtype = it.get("type") or it.get("subtype") or item_type
        name = it.get("name", key)
        rarity = it.get("rarity", "common")
        effect = it.get("effect", "")
        description = it.get("description", effect)
        effects_json = json.dumps({"effect": effect, "description": description})
        allowed = it.get("allowed_buildings")
        if allowed is None:
            allowed = RELIC_ALLOWED_BUILDINGS.get(key, [])
        allowed_json = json.dumps(allowed if isinstance(allowed, list) else [])
        await conn.execute(
            """INSERT INTO item_defs (key, item_type, subtype, name, rarity, allowed_buildings, effects_json)
               VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb)
               ON CONFLICT (key) DO UPDATE SET
                 item_type = EXCLUDED.item_type, subtype = EXCLUDED.subtype, name = EXCLUDED.name,
                 rarity = EXCLUDED.rarity, allowed_buildings = EXCLUDED.allowed_buildings,
                 effects_json = EXCLUDED.effects_json""",
            key, item_type, subtype, name, rarity, allowed_json, effects_json,
        )
    # Если каталог пуст — минимальный сид реликвий и буквы (fallback)
    if not catalog:
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
    # Буквы для квеста ФЕНИКС
    await conn.execute(
        """INSERT INTO item_defs (key, item_type, subtype, name, rarity, allowed_buildings, effects_json)
           VALUES ('letter', 'letter', 'letter', 'Буква', 'common', '[]', '{}') ON CONFLICT (key) DO NOTHING"""
    )
    # Печки (ключ по цвету): 6 видов
    for color, name in [
        ("red", "Печка красная"), ("green", "Печка зелёная"), ("blue", "Печка синяя"),
        ("yellow", "Печка жёлтая"), ("purple", "Печка фиолетовая"), ("black", "Печка чёрная"),
    ]:
        await conn.execute(
            """INSERT INTO item_defs (key, item_type, subtype, name, rarity, allowed_buildings, effects_json)
               VALUES ($1, 'furnace', $2, $3, 'common', '[]', '{"effect":"открыть 3 обычных или 1 крутое яйцо"}')
               ON CONFLICT (key) DO UPDATE SET name = EXCLUDED.name, effects_json = EXCLUDED.effects_json""",
            f"furnace_{color}", color, name,
        )
    # Предмет доступа к полной истории (логи визитов/атак)
    await conn.execute(
        """INSERT INTO item_defs (key, item_type, subtype, name, rarity, allowed_buildings, effects_json)
           VALUES ('full_history_access', 'special', 'utility', 'Доступ к логам игры', 'rare', '[]',
                   '{"effect":"просмотр полной истории: кто к кому ходил, что делал"}')
           ON CONFLICT (key) DO UPDATE SET name = EXCLUDED.name, effects_json = EXCLUDED.effects_json"""
    )
    # Предмет эры: защита от воров (−50% удачи ворам, +50% владельцу)
    await conn.execute(
        """INSERT INTO item_defs (key, item_type, subtype, name, rarity, allowed_buildings, effects_json)
           VALUES ('thief_protection_era', 'amulet', 'ERA', 'Страж племени', 'rare', '[]',
                   '{"effect":"−50% удачи ворам, +50% удачи владельцу при ограблении"}')
           ON CONFLICT (key) DO UPDATE SET name = EXCLUDED.name, effects_json = EXCLUDED.effects_json"""
    )
    # Артефакт сокращения кулдауна атаки
    await conn.execute(
        """INSERT INTO item_defs (key, item_type, subtype, name, rarity, allowed_buildings, effects_json)
           VALUES ('attack_cd_reduce', 'artifact_relic', 'ATTACK', 'Песочные часы атаки', 'rare', '[]',
                   '{"effect":"−15 мин к кулдауну атаки при активации"}')
           ON CONFLICT (key) DO UPDATE SET name = EXCLUDED.name, effects_json = EXCLUDED.effects_json"""
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


async def _seed_familiars_def(conn: asyncpg.Connection) -> None:
    """Сид определений фамильяров (пассивные бафы, возможности)."""
    familiars = [
        ("fam_guard", "Страж", '{"incomePct": 2}', "[]", "common"),
        ("fam_luck", "Талисман удачи", '{"dropChancePct": 1}', "[]", "rare"),
        ("fam_shield", "Щитник", '{"theftResistPct": 5}', "[]", "rare"),
        ("fam_coin", "Монетник", '{"incomePct": 5}', "[]", "epic"),
    ]
    for key, name, passive_buff_json, extra_abilities, rarity in familiars:
        await conn.execute(
            """INSERT INTO familiars_def (key, name, passive_buff_json, extra_abilities, rarity)
               VALUES ($1, $2, $3::jsonb, $4::jsonb, $5) ON CONFLICT (key) DO UPDATE SET
                 name = EXCLUDED.name, passive_buff_json = EXCLUDED.passive_buff_json,
                 extra_abilities = EXCLUDED.extra_abilities, rarity = EXCLUDED.rarity""",
            key, name, passive_buff_json, extra_abilities, rarity,
        )


async def _seed_egg_hatch_pool(conn: asyncpg.Connection) -> None:
    """Пул результатов вылупления: по цвету/редкости — resource, relic, familiar."""
    from config import get_eggs_config
    eggs_cfg = get_eggs_config()
    colors = [c.get("color") for c in eggs_cfg.get("colors", []) if c.get("color")]
    if not colors:
        colors = ["red", "green", "blue", "yellow", "purple", "black"]
    for color in colors:
        for rarity, outcomes in [
            ("common", [("resource", 60), ("relic", 30), ("familiar", 10)]),
            ("rare", [("resource", 40), ("relic", 40), ("familiar", 20)]),
            ("epic", [("resource", 20), ("relic", 40), ("familiar", 40)]),
            ("legendary", [("resource", 10), ("relic", 30), ("familiar", 60)]),
        ]:
            for outcome_type, weight in outcomes:
                await conn.execute(
                    """INSERT INTO egg_hatch_pool (egg_color, egg_rarity, outcome_type, weight)
                       VALUES ($1, $2, $3, $4)
                       ON CONFLICT (egg_color, egg_rarity, outcome_type) DO UPDATE SET weight = EXCLUDED.weight""",
                    color, rarity, outcome_type, weight,
                )


async def _seed_shop_offers(conn: asyncpg.Connection) -> None:
    """Сид предложений магазина из казны (item_def_id по key). Гарантирует наличие item_defs перед вставкой в shop_offers."""
    # Гарантированно создать в item_defs печки и спецпредметы (на случай старой БД без них)
    for color, name in [
        ("red", "Печка красная"), ("green", "Печка зелёная"), ("blue", "Печка синяя"),
        ("yellow", "Печка жёлтая"), ("purple", "Печка фиолетовая"), ("black", "Печка чёрная"),
    ]:
        await conn.execute(
            """INSERT INTO item_defs (key, item_type, subtype, name, rarity, allowed_buildings, effects_json)
               VALUES ($1, 'furnace', $2, $3, 'common', '[]', '{"effect":"открыть 3 обычных или 1 крутое яйцо"}')
               ON CONFLICT (key) DO UPDATE SET name = EXCLUDED.name, effects_json = EXCLUDED.effects_json""",
            f"furnace_{color}", color, name,
        )
    await conn.execute(
        """INSERT INTO item_defs (key, item_type, subtype, name, rarity, allowed_buildings, effects_json)
           VALUES ('full_history_access', 'special', 'utility', 'Доступ к логам игры', 'rare', '[]',
                   '{"effect":"просмотр полной истории: кто к кому ходил, что делал"}')
           ON CONFLICT (key) DO UPDATE SET name = EXCLUDED.name, effects_json = EXCLUDED.effects_json"""
    )
    await conn.execute(
        """INSERT INTO item_defs (key, item_type, subtype, name, rarity, allowed_buildings, effects_json)
           VALUES ('thief_protection_era', 'amulet', 'ERA', 'Страж племени', 'rare', '[]',
                   '{"effect":"−50% удачи ворам, +50% удачи владельцу при ограблении"}')
           ON CONFLICT (key) DO UPDATE SET name = EXCLUDED.name, effects_json = EXCLUDED.effects_json"""
    )
    await conn.execute(
        """INSERT INTO item_defs (key, item_type, subtype, name, rarity, allowed_buildings, effects_json)
           VALUES ('attack_cd_reduce', 'artifact_relic', 'ATTACK', 'Песочные часы атаки', 'rare', '[]',
                   '{"effect":"−15 мин к кулдауну атаки при активации"}')
           ON CONFLICT (key) DO UPDATE SET name = EXCLUDED.name, effects_json = EXCLUDED.effects_json"""
    )
    rows = await conn.fetch(
        """SELECT id, key FROM item_defs WHERE key IN (
           'full_history_access', 'thief_protection_era', 'attack_cd_reduce',
           'furnace_red', 'furnace_green', 'furnace_blue', 'furnace_yellow', 'furnace_purple', 'furnace_black'
           )"""
    )
    by_key = {r["key"]: r["id"] for r in rows}
    logger.info("Shop offers seed: %d item_defs found, inserting offers", len(by_key))
    offers = [
        # --- За звёзды ---
        ("full_history_access", "STARS", 5000, 0),
        ("thief_protection_era", "STARS", 3000, 1),
        ("attack_cd_reduce", "STARS", 800, 2),
        # Премиум-амулеты
        ("amu_06", "STARS", 1500, 3),    # Удача ×2
        ("amu_07", "STARS", 2000, 4),    # Доход ×3
        ("amu_08", "STARS", 2500, 5),    # Анти-Skyfall
        ("amu_09", "STARS", 3500, 6),    # Сейф вывода
        ("amu_04", "STARS", 1200, 7),    # Заморозка порчи
        ("amu_05", "STARS", 1000, 8),    # Очищение
        # --- За монеты ---
        # Амулеты стихий
        ("amulet_fire", "COINS", 800, 20),
        ("amulet_yin", "COINS", 800, 21),
        ("amulet_yan", "COINS", 800, 22),
        ("amulet_tsy", "COINS", 800, 23),
        ("amulet_magic", "COINS", 1200, 24),
        # Артефакты защиты
        ("ward_01", "COINS", 600, 30),   # Щит Тумана
        ("ward_02", "COINS", 600, 31),   # Пластина Холода
        # Хроно-артефакты
        ("chrono_01", "COINS", 400, 35), # Песок Минут
        ("chrono_02", "COINS", 500, 36), # Маятник Сдвига
        ("chrono_03", "COINS", 400, 37), # Малая Пружина
    ]
    # Добавляем все из списка (для тех, что есть в item_defs)
    all_shop_keys = set()
    for key, currency, amount, sort_order in offers:
        item_id = by_key.get(key)
        if not item_id:
            # Попробуем найти в БД напрямую
            row = await conn.fetchrow("SELECT id FROM item_defs WHERE key = $1", key)
            if row:
                item_id = row["id"]
        if not item_id:
            continue
        all_shop_keys.add(key)
        await conn.execute(
            """INSERT INTO shop_offers (item_def_id, pay_currency, pay_amount, stock_type, sort_order)
               VALUES ($1, $2, $3, 'unlimited', $4)
               ON CONFLICT (item_def_id) DO UPDATE SET pay_currency = EXCLUDED.pay_currency,
                 pay_amount = EXCLUDED.pay_amount, sort_order = EXCLUDED.sort_order""",
            item_id, currency, amount, sort_order,
        )
    for i, color in enumerate(["red", "green", "blue", "yellow", "purple", "black"]):
        key = f"furnace_{color}"
        item_id = by_key.get(key)
        if item_id:
            await conn.execute(
                """INSERT INTO shop_offers (item_def_id, pay_currency, pay_amount, stock_type, sort_order)
                   VALUES ($1, 'COINS', 500, 'unlimited', $2)
                   ON CONFLICT (item_def_id) DO UPDATE SET pay_amount = EXCLUDED.pay_amount, sort_order = EXCLUDED.sort_order""",
                item_id, 50 + i,
            )


def _row_to_state(row: asyncpg.Record) -> Dict[str, Any]:
    raw = row["state"]
    if raw is None:
        state = {}
    elif isinstance(raw, dict):
        state = dict(raw)
    elif isinstance(raw, str):
        state = json.loads(raw) if raw else {}
    else:
        state = dict(raw)
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
    """Добавить выплату в очередь. Для наград типа phoenix_quest — не дублируем: если уже есть запись по (telegram_id, reward_type), возвращаем её id."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        single_claim_types = ("phoenix_quest",)
        if reward_type in single_claim_types:
            existing = await conn.fetchrow(
                """SELECT id FROM pending_payouts WHERE telegram_id = $1 AND reward_type = $2 LIMIT 1""",
                telegram_id, reward_type,
            )
            if existing:
                return int(existing["id"])
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
    """Возвращает баланс попыток; обнуляет его, если прошло больше N дней с последнего изменения (не пользовались)."""
    expiry_days = await get_setting("checkin.attempts_expiry_days", 2)
    expiry_days = int(float(expiry_days))
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT attempts, updated_at FROM attempts_balance WHERE user_id = $1""",
            user_id,
        )
        if not row:
            return 0
        now = datetime.now(timezone.utc)
        updated_at = row["updated_at"]
        if updated_at is not None and expiry_days > 0:
            if (now - (updated_at.replace(tzinfo=timezone.utc) if updated_at.tzinfo is None else updated_at)) > timedelta(days=expiry_days):
                await conn.execute(
                    """UPDATE attempts_balance SET attempts = 0, updated_at = NOW() WHERE user_id = $1""",
                    user_id,
                )
                return 0
        return int(row["attempts"])


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
    await add_currency_credit(user_id, "COINS", amount, ref_type, ref_id, idem_key)


async def add_currency_credit(
    user_id: int, currency: str, amount: int, ref_type: str, ref_id: Optional[str] = None,
    idem_key: Optional[str] = None,
) -> None:
    """Начисляет валюту (COINS, STARS, DIAMONDS) через economy_ledger и user_balances."""
    if amount <= 0:
        return
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
               VALUES ($1, 'credit', $2, $3, $4, $5, $6)""",
            user_id, currency, amount, ref_type, ref_id or "", idem_key,
        )
        await conn.execute(
            """INSERT INTO user_balances (user_id, currency, balance, updated_at)
               VALUES ($1, $2, $3, NOW())
               ON CONFLICT (user_id, currency) DO UPDATE SET
                 balance = user_balances.balance + $3, updated_at = NOW()""",
            user_id, currency, amount,
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


async def get_item_def_id_by_key(key: str) -> Optional[int]:
    """Возвращает id item_def по key или None."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT id FROM item_defs WHERE key = $1", key)
    return int(row["id"]) if row else None


async def add_user_item(user_id: int, item_def_id: int, item_level: int = 1, meta: Optional[Dict] = None) -> int:
    """Добавляет предмет в инвентарь. Возвращает user_items.id."""
    pool = await get_pool()
    meta = meta or {}
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO user_items (user_id, item_def_id, state, item_level, meta)
               VALUES ($1, $2, 'inventory', $3, $4::jsonb) RETURNING id""",
            user_id, item_def_id, item_level, json.dumps(meta),
        )
    return int(row["id"])


async def get_letter_item_def_id() -> Optional[int]:
    """ID item_def для типа letter (квест ФЕНИКС)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT id FROM item_defs WHERE key = 'letter' AND item_type = 'letter'")
    return int(row["id"]) if row else None


async def add_letter_to_user(user_id: int, symbol: str) -> int:
    """Добавляет букву в инвентарь (meta.symbol). Возвращает user_items.id."""
    letter_def_id = await get_letter_item_def_id()
    if not letter_def_id:
        raise ValueError("Letter item_def not found")
    return await add_user_item(user_id, letter_def_id, item_level=1, meta={"symbol": symbol.upper()})


async def get_phoenix_quest_state() -> Dict[str, Any]:
    """Текущее загаданное слово и счётчик сдач (макс 5)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT current_word, submissions_count, word_index, updated_at FROM phoenix_quest_state WHERE id = 1")
    if not row:
        return {"current_word": "ФЕНИКС", "submissions_count": 0, "word_index": 0, "max_submissions": 5}
    return {
        "current_word": row["current_word"],
        "submissions_count": row["submissions_count"],
        "word_index": row["word_index"],
        "max_submissions": 5,
        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
    }


PHOENIX_WORDS_LIST = ["ФЕНИКС", "СЛОВО", "ОГОНЬ", "ПОБЕДА", "МЕДАЛЬ", "ТОКЕН", "ИГРОК", "ЭРА"]


async def advance_phoenix_word() -> str:
    """После 5 сдач переключает на следующее слово. Возвращает новое current_word."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT word_index FROM phoenix_quest_state WHERE id = 1")
        idx = int(row["word_index"]) if row else 0
        next_idx = (idx + 1) % len(PHOENIX_WORDS_LIST)
        next_word = PHOENIX_WORDS_LIST[next_idx]
        await conn.execute(
            """UPDATE phoenix_quest_state SET current_word = $1, submissions_count = 0, word_index = $2, updated_at = NOW() WHERE id = 1""",
            next_word, next_idx,
        )
    return next_word


async def get_user_letter_items(user_id: int) -> List[Dict[str, Any]]:
    """Список букв в инвентаре (user_items с item_type=letter, state=inventory)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT ui.id, ui.meta
               FROM user_items ui
               JOIN item_defs id ON id.id = ui.item_def_id
               WHERE ui.user_id = $1 AND id.item_type = 'letter' AND ui.state = 'inventory'
               ORDER BY ui.id""",
            user_id,
        )
    return [{"id": r["id"], "symbol": (r["meta"] or {}).get("symbol", "?")} for r in rows]


async def consume_letter_items(user_id: int, item_ids: List[int], word: str) -> bool:
    """
    Списывает буквы по id. word — ожидаемое слово; для каждого символа должен быть ровно один id.
    Возвращает True если списание прошло.
    """
    word_upper = word.strip().upper()
    if len(word_upper) != len(item_ids) or len(set(item_ids)) != len(item_ids):
        return False
    pool = await get_pool()
    async with pool.acquire() as conn:
        for i, char in enumerate(word_upper):
            item_id = item_ids[i]
            row = await conn.fetchrow(
                """SELECT ui.id FROM user_items ui
                   JOIN item_defs id ON id.id = ui.item_def_id
                   WHERE ui.user_id = $1 AND ui.id = $2 AND id.item_type = 'letter' AND ui.state = 'inventory'""",
                user_id, item_id,
            )
            if not row:
                return False
            meta = await conn.fetchrow("SELECT meta FROM user_items WHERE id = $1", item_id)
            sym = (meta["meta"] or {}).get("symbol", "")
            if sym.upper() != char:
                return False
        for item_id in item_ids:
            await conn.execute("DELETE FROM user_items WHERE id = $1 AND user_id = $2", item_id, user_id)
    return True


async def add_user_badge(user_id: int, badge_key: str) -> None:
    """Добавляет бейдж в user_profile.badges (например 'букварь')."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT badges FROM user_profile WHERE user_id = $1", user_id)
        badges = list(row["badges"]) if row and row["badges"] else []
        if badge_key not in badges:
            badges.append(badge_key)
            await conn.execute(
                "UPDATE user_profile SET badges = $1::jsonb, updated_at = NOW() WHERE user_id = $2",
                json.dumps(badges), user_id,
            )


async def has_user_badge(user_id: int, badge_key: str) -> bool:
    """Проверяет наличие бейджа у пользователя."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT badges FROM user_profile WHERE user_id = $1", user_id)
    badges = list(row["badges"]) if row and row.get("badges") else []
    return badge_key in badges


async def phoenix_submit_word(
    user_id: int,
    word: str,
    letter_item_ids: List[int],
) -> Dict[str, Any]:
    """
    Сдача слова: списание букв, проверка совпадения с текущим словом, топ-5 приз + бейдж «Букварь».
    Возвращает: success, place (1-5 или 0), badge_granted, message, next_word (если слово сменилось).
    """
    state = await get_phoenix_quest_state()
    current = (state["current_word"] or "").strip().upper()
    word_upper = word.strip().upper()
    if not current or not word_upper:
        return {"success": False, "place": 0, "badge_granted": False, "message": "Пустое слово"}
    if len(word_upper) != len(letter_item_ids):
        return {"success": False, "place": 0, "badge_granted": False, "message": "Количество букв не совпадает со словом"}
    consumed = await consume_letter_items(user_id, letter_item_ids, word_upper)
    if not consumed:
        return {"success": False, "place": 0, "badge_granted": False, "message": "Не удалось списать буквы (нет в инвентаре или не совпадают)"}
    if word_upper != current:
        return {"success": True, "place": 0, "badge_granted": False, "message": "Слово принято, но это не загаданное слово"}
    count = state["submissions_count"]
    if count >= 5:
        return {"success": True, "place": 0, "badge_granted": False, "message": "Загаданное слово уже отгадано 5 раз"}
    pool = await get_pool()
    place = count + 1
    next_word = None
    async with pool.acquire() as conn:
        await conn.execute(
            """UPDATE phoenix_quest_state SET submissions_count = submissions_count + 1, updated_at = NOW() WHERE id = 1"""
        )
        new_row = await conn.fetchrow("SELECT submissions_count FROM phoenix_quest_state WHERE id = 1")
        new_count = int(new_row["submissions_count"]) if new_row else 0
    if place <= 5:
        await add_user_badge(user_id, "букварь")
    if new_count >= 5:
        next_word = await advance_phoenix_word()
    return {
        "success": True,
        "place": place,
        "badge_granted": place <= 5,
        "message": f"Правильно! Вы #{place} из 5. Бейдж «Букварь» выдан." if place <= 5 else "Правильно, но призы уже разыграны.",
        "next_word": next_word,
    }


async def add_player_egg(user_id: int, color: str) -> int:
    """Добавляет яйцо игроку. Возвращает player_eggs.id."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO player_eggs (user_id, color) VALUES ($1, $2) RETURNING id""",
            user_id, color,
        )
    return int(row["id"])


async def get_egg_hatch_pool(egg_color: str, egg_rarity: str) -> List[tuple]:
    """Возвращает список (outcome_type, weight) для вылупления по цвету и редкости яйца."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT outcome_type, weight FROM egg_hatch_pool WHERE egg_color = $1 AND egg_rarity = $2",
            egg_color, egg_rarity,
        )
    return [(r["outcome_type"], int(r["weight"])) for r in rows] if rows else [("resource", 100)]


async def get_eggs_def_rarity(color: str) -> str:
    """Редкость яйца по цвету из eggs_def."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT rarity FROM eggs_def WHERE color = $1", color)
    return row["rarity"] if row else "common"


async def consume_player_eggs(user_id: int, egg_ids: List[int]) -> bool:
    """Удаляет яйца по id. Возвращает True если все id принадлежат юзеру и удалены."""
    if not egg_ids:
        return False
    pool = await get_pool()
    async with pool.acquire() as conn:
        for eid in egg_ids:
            await conn.execute("DELETE FROM player_eggs WHERE id = $1 AND user_id = $2", eid, user_id)
    return True


async def add_user_familiar(user_id: int, familiar_def_id: int) -> int:
    """Добавляет фамильяра игроку. Возвращает user_familiars.id."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO user_familiars (user_id, familiar_def_id, equipped) VALUES ($1, $2, TRUE) RETURNING id""",
            user_id, familiar_def_id,
        )
    return int(row["id"])


async def get_familiar_defs_random_one() -> Optional[int]:
    """Случайный familiars_def.id по весу редкости (упрощённо: равновероятно)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT id FROM familiars_def")
    if not rows:
        return None
    return random.choice([int(r["id"]) for r in rows])


async def do_furnace_hatch(
    user_id: int,
    furnace_user_item_id: int,
    egg_ids: List[int],
) -> Dict[str, Any]:
    """
    Вылупление: 1 печка + 3 яйца одного цвета (или 1 редкое яйцо). Consume furnace and eggs, roll outcome (resource/relic/familiar).
    Возвращает { ok, outcome_type, coins_granted?, item_def_id?, familiar_def_id?, message }.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        furnace = await conn.fetchrow(
            """SELECT ui.id, ui.item_def_id, id.key AS item_key
               FROM user_items ui JOIN item_defs id ON id.id = ui.item_def_id
               WHERE ui.id = $1 AND ui.user_id = $2 AND ui.state = 'inventory' AND id.item_type = 'furnace'""",
            furnace_user_item_id, user_id,
        )
        if not furnace:
            return {"ok": False, "outcome_type": None, "message": "furnace_not_found"}
        color = furnace["item_key"].replace("furnace_", "") if furnace["item_key"] else ""
        if not color or len(egg_ids) not in (1, 3):
            return {"ok": False, "outcome_type": None, "message": "need_3_eggs_or_1_rare"}
        eggs = await conn.fetch(
            "SELECT id, color FROM player_eggs WHERE user_id = $1 AND id = ANY($2::int[])",
            user_id, egg_ids,
        )
        if len(eggs) != len(egg_ids):
            return {"ok": False, "outcome_type": None, "message": "eggs_not_found"}
        if any(e["color"] != color for e in eggs):
            return {"ok": False, "outcome_type": None, "message": "eggs_color_mismatch"}
        egg_rarity = await get_eggs_def_rarity(color)
        if len(egg_ids) == 1 and egg_rarity == "common":
            return {"ok": False, "outcome_type": None, "message": "need_3_common_or_1_rare"}
        pool_outcomes = await get_egg_hatch_pool(color, egg_rarity)
        total_w = sum(w for _, w in pool_outcomes)
        r = random.randint(1, max(1, total_w))
        outcome_type = "resource"
        for ot, w in pool_outcomes:
            r -= w
            if r <= 0:
                outcome_type = ot
                break
        await conn.execute("DELETE FROM user_items WHERE id = $1 AND user_id = $2", furnace_user_item_id, user_id)
        for eid in egg_ids:
            await conn.execute("DELETE FROM player_eggs WHERE id = $1 AND user_id = $2", eid, user_id)
    coins_granted = 0
    item_def_id = None
    familiar_def_id = None
    if outcome_type == "resource":
        coins_granted = random.randint(50, 200)
        await add_coins_ledger(user_id, coins_granted, "furnace_hatch", ref_id="")
    elif outcome_type == "relic":
        ids = await get_item_def_ids_by_rarity("FIRE")
        if ids:
            item_def_id = random.choice(ids)
            await add_user_item(user_id, item_def_id, item_level=1)
            await record_item_event(item_def_id, "drop", user_id, 1, ref_type="furnace_hatch", ref_id=None)
    elif outcome_type == "familiar":
        fid = await get_familiar_defs_random_one()
        if fid:
            await add_user_familiar(user_id, fid)
            familiar_def_id = fid
    return {"ok": True, "outcome_type": outcome_type, "coins_granted": coins_granted, "item_def_id": item_def_id, "familiar_def_id": familiar_def_id, "message": "ok"}


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
    def _safe_meta(v: Any) -> dict:
        if v is None:
            return {}
        if isinstance(v, dict):
            return v
        try:
            return dict(v)
        except Exception:
            return {}

    def _safe_iso(v: Any) -> Optional[str]:
        if v is None:
            return None
        if hasattr(v, "isoformat"):
            return v.isoformat()
        return str(v)

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
            "meta": _safe_meta(r.get("meta")),
            "acquired_at": _safe_iso(r.get("acquired_at")),
        })
    eggs_list = [
        {
            "id": r["id"],
            "color": r["color"],
            "acquired_at": _safe_iso(r.get("acquired_at")),
            "meta": _safe_meta(r.get("meta")),
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
            "config": (r["config"] if isinstance(r["config"], dict) else json.loads(r["config"]) if r["config"] else {}),
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


async def _sync_coins_from_state(conn, user_id: int) -> int:
    """Если user_balances не содержит COINS, инициализирует из game_players.state.coins. Возвращает баланс."""
    balance_row = await conn.fetchrow(
        "SELECT balance FROM user_balances WHERE user_id = $1 AND currency = 'COINS'",
        user_id,
    )
    if balance_row is not None:
        return int(balance_row["balance"])
    # Берём coins из game_players.state
    tg_row = await conn.fetchrow("SELECT telegram_id FROM users WHERE id = $1", user_id)
    coins = 0
    if tg_row:
        state_row = await conn.fetchrow(
            "SELECT state FROM game_players WHERE telegram_id = $1",
            tg_row["telegram_id"],
        )
        if state_row and state_row["state"]:
            raw = state_row["state"]
            st = json.loads(raw) if isinstance(raw, str) else (raw if isinstance(raw, dict) else {})
            coins = int(st.get("coins", 0))
    await conn.execute(
        """INSERT INTO user_balances (user_id, currency, balance)
           VALUES ($1, 'COINS', $2)
           ON CONFLICT (user_id, currency) DO NOTHING""",
        user_id, coins,
    )
    logger.info("_sync_coins_from_state: user_id=%s, synced coins=%s", user_id, coins)
    return coins


async def _update_state_coins(conn, user_id: int, new_coins: int) -> None:
    """Обновляет coins внутри game_players.state JSON."""
    tg_row = await conn.fetchrow("SELECT telegram_id FROM users WHERE id = $1", user_id)
    if not tg_row:
        return
    state_row = await conn.fetchrow(
        "SELECT state FROM game_players WHERE telegram_id = $1",
        tg_row["telegram_id"],
    )
    if not state_row or not state_row["state"]:
        return
    raw = state_row["state"]
    st = json.loads(raw) if isinstance(raw, str) else (dict(raw) if isinstance(raw, dict) else {})
    st["coins"] = new_coins
    await conn.execute(
        "UPDATE game_players SET state = $2::jsonb, updated_at = NOW() WHERE telegram_id = $1",
        tg_row["telegram_id"], json.dumps(st),
    )


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
        # Синхронизируем баланс из game_players.state если user_balances пуст
        balance = await _sync_coins_from_state(conn, user_id)
        if balance < cost:
            return "insufficient_coins"
        new_balance = balance - cost
        await conn.execute(
            """INSERT INTO user_balances (user_id, currency, balance, updated_at)
               VALUES ($1, 'COINS', $2, NOW())
               ON CONFLICT (user_id, currency) DO UPDATE SET balance = $2, updated_at = NOW()""",
            user_id, new_balance,
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
        # Обновляем coins в game_players.state
        await _update_state_coins(conn, user_id, new_balance)
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
            # Синхронизируем баланс перед начислением
            cur_balance = await _sync_coins_from_state(conn, user_id)
            new_balance = cur_balance + refund
            await conn.execute(
                """INSERT INTO user_balances (user_id, currency, balance, updated_at)
                   VALUES ($1, 'COINS', $2, NOW())
                   ON CONFLICT (user_id, currency) DO UPDATE SET balance = $2, updated_at = NOW()""",
                user_id, new_balance,
            )
            await conn.execute(
                """INSERT INTO economy_ledger (user_id, kind, currency, amount, ref_type, ref_id)
                   VALUES ($1, 'credit', 'COINS', $2, 'field_demolish', $3)""",
                user_id, refund, building_key,
            )
            await _update_state_coins(conn, user_id, new_balance)
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
        # Синхронизируем баланс из game_players.state если user_balances пуст
        balance = await _sync_coins_from_state(conn, user_id)
        if balance < cost:
            return "insufficient_coins"
        new_balance = balance - cost
        await conn.execute(
            """INSERT INTO user_balances (user_id, currency, balance, updated_at)
               VALUES ($1, 'COINS', $2, NOW())
               ON CONFLICT (user_id, currency) DO UPDATE SET balance = $2, updated_at = NOW()""",
            user_id, new_balance,
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
        # Обновляем coins в game_players.state
        await _update_state_coins(conn, user_id, new_balance)
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
            """SELECT moi.user_item_id, ui.item_def_id
               FROM market_order_items moi
               JOIN user_items ui ON ui.id = moi.user_item_id
               WHERE moi.order_id = $1""",
            order_id,
        )
        for r in item_rows:
            await conn.execute("UPDATE user_items SET user_id = $2, state = 'inventory' WHERE id = $1", r["user_item_id"], buyer_id)
            await conn.execute("DELETE FROM escrow_items WHERE user_item_id = $1", r["user_item_id"])
        for r in item_rows:
            await record_item_event(r["item_def_id"], "sold", seller_id, 1, ref_type="market_order", ref_id=order_id)
            await record_item_event(r["item_def_id"], "bought", buyer_id, 1, ref_type="market_order", ref_id=order_id)
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
                """SELECT lb.user_id, lb.points, lb.updated_at, u.telegram_id,
                          COALESCE(gp.first_name, gp.username, '') AS display_name
                   FROM leaderboards lb
                   JOIN users u ON u.id = lb.user_id
                   LEFT JOIN game_players gp ON gp.telegram_id = u.telegram_id
                   WHERE lb.period = $1 AND lb.period_key = $2 ORDER BY lb.points DESC LIMIT 100""",
                period, period_key,
            )
        else:
            rows = await conn.fetch(
                """SELECT lb.period_key, lb.user_id, lb.points, lb.updated_at, u.telegram_id,
                          COALESCE(gp.first_name, gp.username, '') AS display_name
                   FROM leaderboards lb
                   JOIN users u ON u.id = lb.user_id
                   LEFT JOIN game_players gp ON gp.telegram_id = u.telegram_id
                   WHERE lb.period = $1 ORDER BY lb.period_key DESC, lb.points DESC LIMIT 500""",
                period,
            )
    if rows:
        return [
            {
                "period_key": r.get("period_key"),
                "user_id": r["user_id"],
                "id": int(r["telegram_id"]) if r.get("telegram_id") is not None else r["user_id"],
                "telegram_id": int(r["telegram_id"]) if r.get("telegram_id") is not None else None,
                "points": int(r["points"]),
                "name": (r.get("display_name") or "").strip() or f"Игрок {r.get('telegram_id') or r['user_id']}",
                "updated_at": r["updated_at"].isoformat() if r.get("updated_at") else None,
            }
            for r in rows
        ]
    # Fallback: таблица leaderboards пуста — рейтинг по очкам из game_players (текущая эра/глобально)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT gp.telegram_id, gp.points_balance AS points,
                      COALESCE(gp.first_name, gp.username, '') AS display_name
               FROM game_players gp
               WHERE gp.points_balance > 0
               ORDER BY gp.points_balance DESC LIMIT 200"""
        )
    return [
        {
            "period_key": period_key,
            "user_id": 0,
            "id": int(r["telegram_id"]) if r.get("telegram_id") is not None else 0,
            "telegram_id": int(r["telegram_id"]) if r.get("telegram_id") is not None else None,
            "points": int(r["points"]),
            "name": (r.get("display_name") or "").strip() or f"Игрок {r.get('telegram_id') or ''}",
            "updated_at": None,
        }
        for r in rows
    ]


MAX_WALLETS_PER_USER = 10


async def _cleanup_duplicate_pending_bindings(conn, user_id: int) -> None:
    """Оставить по одной непроверенной привязке на каждый verify_code, остальные удалить."""
    await conn.execute(
        """DELETE FROM user_wallet_bindings a
           WHERE a.user_id = $1 AND a.verified_at IS NULL
           AND EXISTS (
             SELECT 1 FROM user_wallet_bindings b
             WHERE b.user_id = a.user_id AND b.verify_code = a.verify_code
               AND b.verified_at IS NULL AND b.id < a.id
           )""",
        user_id,
    )


async def list_user_wallet_bindings(
    user_id: int,
    telegram_id: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Список привязанных кошельков пользователя (до 10). Удаляются дубликаты и лишняя «ожидает верификации», если уже есть верифицированный кошелёк."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await _cleanup_duplicate_pending_bindings(conn, user_id)
        if telegram_id is not None:
            has_verified = await conn.fetchval(
                "SELECT 1 FROM user_wallet_bindings WHERE user_id = $1 AND verified_at IS NOT NULL LIMIT 1",
                user_id,
            )
            if has_verified:
                await conn.execute(
                    "DELETE FROM user_wallet_bindings WHERE user_id = $1 AND verify_code = $2 AND verified_at IS NULL",
                    user_id,
                    f"verify:{telegram_id}",
                )
        rows = await conn.fetch(
            "SELECT id, wallet_address, verified_at, created_at FROM user_wallet_bindings WHERE user_id = $1 ORDER BY verified_at NULLS LAST, created_at",
            user_id,
        )
    return [
        {
            "id": r["id"],
            "wallet_address": r["wallet_address"],
            "verified_at": r["verified_at"].isoformat() if r["verified_at"] else None,
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        }
        for r in rows
    ]


async def add_user_wallet_binding(user_id: int, verify_code: str, wallet_address: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Создать привязку или вернуть существующую непроверенную с тем же verify_code (чтобы не плодить дубли «ожидает верификации»). Не более MAX_WALLETS_PER_USER. Возвращает { id, verify_code } или None."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        existing = await conn.fetchrow(
            """SELECT id, verify_code FROM user_wallet_bindings
               WHERE user_id = $1 AND verify_code = $2 AND verified_at IS NULL LIMIT 1""",
            user_id, verify_code,
        )
        if existing:
            return {"id": existing["id"], "verify_code": existing["verify_code"]}
        n = await conn.fetchval("SELECT COUNT(*) FROM user_wallet_bindings WHERE user_id = $1", user_id)
        if n >= MAX_WALLETS_PER_USER:
            return None
        addr = wallet_address.strip() if wallet_address else None
        try:
            row = await conn.fetchrow(
                """INSERT INTO user_wallet_bindings (user_id, wallet_address, verify_code, created_at)
                   VALUES ($1, $2, $3, NOW()) RETURNING id, verify_code""",
                user_id, addr, verify_code,
            )
            return {"id": row["id"], "verify_code": row["verify_code"]} if row else None
        except Exception:
            return None


async def delete_user_wallet_binding(user_id: int, binding_id: int) -> bool:
    """Отвязать кошелёк (только свой)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        r = await conn.execute(
            "DELETE FROM user_wallet_bindings WHERE id = $1 AND user_id = $2", binding_id, user_id
        )
    return r == "DELETE 1"


async def get_user_wallet_binding_by_code(verify_code: str):
    """Найти привязку по коду верификации (для обработки входящего tx)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            "SELECT id, user_id, wallet_address FROM user_wallet_bindings WHERE verify_code = $1", verify_code
        )


async def set_wallet_binding_verified(binding_id: int) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE user_wallet_bindings SET verified_at = NOW(), verify_code = NULL WHERE id = $1", binding_id
        )


async def delete_pending_wallet_bindings_by_code(user_id: int, verify_code: str) -> None:
    """Удалить все непроверенные привязки с данным verify_code (дубликаты после повторных «Добавить кошелёк»)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM user_wallet_bindings WHERE user_id = $1 AND verify_code = $2 AND verified_at IS NULL",
            user_id, verify_code,
        )


async def update_wallet_binding_address(binding_id: int, wallet_address: str) -> None:
    """Установить адрес кошелька по привязке (перед верификацией по tx)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE user_wallet_bindings SET wallet_address = $1 WHERE id = $2",
            wallet_address.strip(),
            binding_id,
        )


# ——— withdraw_penalties (штрафы на вывод, срабатывают при выводе) ———

async def get_pending_penalty_total(user_id: int) -> float:
    """Сумма неприменённых штрафов по user_id (вычитается при выводе)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT COALESCE(SUM(amount), 0)::numeric AS total FROM withdraw_penalties WHERE user_id = $1",
            user_id,
        )
        return float(row["total"]) if row else 0.0


async def add_withdraw_penalty(
    user_id: int,
    amount: float,
    currency: str = "PHXPW",
    reason: Optional[str] = None,
    notify_user: bool = False,
    created_by_telegram_id: Optional[int] = None,
) -> int:
    """Добавить штраф на вывод. Возвращает id записи."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO withdraw_penalties (user_id, amount, currency, reason, notify_user, created_by_telegram_id)
               VALUES ($1, $2, $3, $4, $5, $6) RETURNING id""",
            user_id, amount, currency or "PHXPW", reason, notify_user, created_by_telegram_id,
        )
        return row["id"]


async def mark_penalty_notified(penalty_id: int) -> None:
    """Отметить, что пользователю отправлено уведомление о штрафе."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE withdraw_penalties SET notified_at = NOW() WHERE id = $1",
            penalty_id,
        )


async def get_penalties_for_user(user_id: int) -> List[Dict[str, Any]]:
    """Список штрафов пользователя для админки."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, amount, currency, reason, notify_user, notified_at, created_at FROM withdraw_penalties WHERE user_id = $1 ORDER BY created_at DESC",
            user_id,
        )
        return [
            {
                "id": r["id"],
                "amount": float(r["amount"]),
                "currency": r["currency"],
                "reason": r["reason"],
                "notify_user": r["notify_user"],
                "notified_at": r["notified_at"].isoformat() if r.get("notified_at") else None,
                "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
            }
            for r in rows
        ]


async def get_withdraw_eligibility(user_id: int) -> Dict[str, Any]:
    """Проверка возможности вывода: уровень, кошелёк, gating, compliance."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        wallet = await conn.fetchrow("SELECT 1 FROM user_wallet_bindings WHERE user_id = $1 AND verified_at IS NOT NULL LIMIT 1", user_id)
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
    penalty_total = await get_pending_penalty_total(user_id)
    can_withdraw = level_ok and wallet_bound and rule_10_ok and compliance_ok
    return {
        "can_withdraw": can_withdraw,
        "level_ok": level_ok,
        "wallet_bound": wallet_bound,
        "rule_10_ok": rule_10_ok,
        "required_action_value_ton": required,
        "completed_action_value_ton": completed,
        "compliance_ok": compliance_ok,
        "pending_penalty_total": float(penalty_total),
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
        await conn.execute(
            """UPDATE user_profile SET furnace_bonus_until = NOW() + INTERVAL '24 hours', updated_at = NOW() WHERE user_id = $1""",
            user_id,
        )
    return True


async def get_and_consume_furnace_bonus(user_id: int) -> bool:
    """Если у пользователя активен бонус доната (furnace_bonus_until > now), сбрасывает его и возвращает True. Иначе False."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT furnace_bonus_until FROM user_profile WHERE user_id = $1", user_id,
        )
        if not row or not row["furnace_bonus_until"]:
            return False
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        if now < row["furnace_bonus_until"]:
            await conn.execute(
                "UPDATE user_profile SET furnace_bonus_until = NULL, updated_at = NOW() WHERE user_id = $1",
                user_id,
            )
            return True
    return False


async def get_items_catalog() -> List[Dict[str, Any]]:
    """Возвращает каталог предметов из item_defs для «О проекте» и маркета. slot_type и effect для фронта."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT id, key, item_type, subtype, name, rarity, effects_json
               FROM item_defs ORDER BY item_type, subtype, key"""
        )
    out = []
    for r in rows:
        raw = r["effects_json"]
        if isinstance(raw, dict):
            effects = raw
        elif isinstance(raw, str) and raw:
            try:
                effects = json.loads(raw)
            except (TypeError, ValueError):
                effects = {}
        else:
            effects = {}
        effect_str = effects.get("effect", "") if isinstance(effects, dict) else ""
        out.append({
            "id": r["id"],
            "key": r["key"],
            "item_type": r["item_type"],
            "slot_type": r["item_type"],
            "subtype": r["subtype"],
            "name": r["name"],
            "rarity": r["rarity"],
            "effect": effect_str,
            "effects": effects,
        })
    return out


async def get_shop_offers() -> List[Dict[str, Any]]:
    """Список предложений магазина из казны (покупка за COINS/STARS)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT so.id, so.item_def_id, so.pay_currency, so.pay_amount, so.stock_type,
                      so.max_per_user_per_era, so.sort_order,
                      id.key AS item_key, id.name AS item_name, id.rarity, id.effects_json
               FROM shop_offers so
               JOIN item_defs id ON id.id = so.item_def_id
               ORDER BY so.sort_order, so.id"""
        )
    return [
        {
            "id": r["id"],
            "item_def_id": r["item_def_id"],
            "item_key": r["item_key"],
            "item_name": r["item_name"],
            "rarity": r["rarity"],
            "pay_currency": r["pay_currency"],
            "pay_amount": int(r["pay_amount"]),
            "stock_type": r["stock_type"],
            "max_per_user_per_era": r["max_per_user_per_era"],
            "effects": (r["effects_json"] if isinstance(r["effects_json"], dict) else json.loads(r["effects_json"])) if r["effects_json"] else {},
        }
        for r in rows
    ]


async def purchase_shop_offer(user_id: int, offer_id: int, quantity: int = 1) -> Optional[str]:
    """
    Покупка в магазине за казну. Списывает COINS/STARS, выдаёт предмет в user_items.
    Возвращает None при успехе, иначе строку ошибки.
    """
    if quantity < 1 or quantity > 99:
        return "invalid_quantity"
    pool = await get_pool()
    async with pool.acquire() as conn:
        offer = await conn.fetchrow(
            """SELECT so.id, so.item_def_id, so.pay_currency, so.pay_amount, so.stock_type, so.max_per_user_per_era
               FROM shop_offers so WHERE so.id = $1""",
            offer_id,
        )
        if not offer:
            return "offer_not_found"
        currency = offer["pay_currency"]
        amount = offer["pay_amount"] * quantity
        balance_row = await conn.fetchrow(
            "SELECT balance FROM user_balances WHERE user_id = $1 AND currency = $2",
            user_id, currency,
        )
        balance = int(balance_row["balance"]) if balance_row else 0
        if balance < amount:
            return "insufficient_balance"
        await conn.execute(
            """UPDATE user_balances SET balance = balance - $2, updated_at = NOW()
               WHERE user_id = $1 AND currency = $3""",
            user_id, amount, currency,
        )
        await conn.execute(
            """INSERT INTO economy_ledger (user_id, kind, currency, amount, ref_type, ref_id)
               VALUES ($1, 'debit', $2, $3, 'shop_purchase', $4)""",
            user_id, -amount, currency, offer_id,
        )
        item_def_id = offer["item_def_id"]
        for _ in range(quantity):
            await conn.execute(
                """INSERT INTO user_items (user_id, item_def_id, state, item_level)
                   VALUES ($1, $2, 'inventory', 1)""",
                user_id, item_def_id,
            )
    await record_item_event(item_def_id, "bought", user_id, quantity, ref_type="shop_offer", ref_id=offer_id)
    return None


async def record_item_event(
    item_def_id: Optional[int],
    event_type: str,
    user_id: int,
    quantity: int = 1,
    ref_type: Optional[str] = None,
    ref_id: Optional[int] = None,
    meta: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Пишет событие по предмету для статистики.
    event_type: drop, burn, merge_input, merge_break, merge_output,
                upgrade_input, upgrade_break, upgrade_ok, reroll_input, reroll_break, reroll_ok, sold, bought.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO item_events (item_def_id, event_type, user_id, quantity, ref_type, ref_id, meta)
               VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb)""",
            item_def_id, event_type, user_id, quantity, ref_type, ref_id, json.dumps(meta or {}),
        )


async def get_item_stats() -> List[Dict[str, Any]]:
    """
    Сводная статистика по каждому предмету (item_def_id):
    сколько у игроков (inventory, equipped, listed), сколько выпало, сожгли, ушло в слияние/слом и т.д.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        defs = await conn.fetch("SELECT id, key, name, item_type, subtype, rarity FROM item_defs ORDER BY id")
        result = []
        for d in defs:
            item_def_id = d["id"]
            inv = await conn.fetchrow(
                """SELECT
                    COUNT(*) FILTER (WHERE state = 'inventory') AS total_inventory,
                    COUNT(*) FILTER (WHERE state = 'equipped') AS total_equipped,
                    COUNT(*) FILTER (WHERE state = 'listed') AS total_listed
                   FROM user_items WHERE item_def_id = $1""",
                item_def_id,
            )
            events = await conn.fetchrow(
                """SELECT
                    COALESCE(SUM(quantity) FILTER (WHERE event_type = 'drop'), 0) AS total_dropped,
                    COALESCE(SUM(quantity) FILTER (WHERE event_type = 'burn'), 0) AS total_burned,
                    COALESCE(SUM(quantity) FILTER (WHERE event_type = 'merge_input'), 0) AS total_merge_input,
                    COALESCE(SUM(quantity) FILTER (WHERE event_type = 'merge_break'), 0) AS total_merge_break,
                    COALESCE(SUM(quantity) FILTER (WHERE event_type = 'merge_output'), 0) AS total_merge_output,
                    COALESCE(SUM(quantity) FILTER (WHERE event_type = 'upgrade_input'), 0) AS total_upgrade_input,
                    COALESCE(SUM(quantity) FILTER (WHERE event_type = 'upgrade_break'), 0) AS total_upgrade_break,
                    COALESCE(SUM(quantity) FILTER (WHERE event_type = 'upgrade_ok'), 0) AS total_upgrade_ok,
                    COALESCE(SUM(quantity) FILTER (WHERE event_type = 'reroll_input'), 0) AS total_reroll_input,
                    COALESCE(SUM(quantity) FILTER (WHERE event_type = 'reroll_break'), 0) AS total_reroll_break,
                    COALESCE(SUM(quantity) FILTER (WHERE event_type = 'reroll_ok'), 0) AS total_reroll_ok,
                    COALESCE(SUM(quantity) FILTER (WHERE event_type = 'sold'), 0) AS total_sold,
                    COALESCE(SUM(quantity) FILTER (WHERE event_type = 'bought'), 0) AS total_bought
                   FROM item_events WHERE item_def_id = $1""",
                item_def_id,
            )
            result.append({
                "item_def_id": item_def_id,
                "key": d["key"],
                "name": d["name"],
                "item_type": d["item_type"],
                "subtype": d["subtype"],
                "rarity": d["rarity"],
                "total_inventory": int(inv["total_inventory"] or 0),
                "total_equipped": int(inv["total_equipped"] or 0),
                "total_listed": int(inv["total_listed"] or 0),
                "total_dropped": int(events["total_dropped"] or 0),
                "total_burned": int(events["total_burned"] or 0),
                "total_merge_input": int(events["total_merge_input"] or 0),
                "total_merge_break": int(events["total_merge_break"] or 0),
                "total_merge_output": int(events["total_merge_output"] or 0),
                "total_upgrade_input": int(events["total_upgrade_input"] or 0),
                "total_upgrade_break": int(events["total_upgrade_break"] or 0),
                "total_upgrade_ok": int(events["total_upgrade_ok"] or 0),
                "total_reroll_input": int(events["total_reroll_input"] or 0),
                "total_reroll_break": int(events["total_reroll_break"] or 0),
                "total_reroll_ok": int(events["total_reroll_ok"] or 0),
                "total_sold": int(events["total_sold"] or 0),
                "total_bought": int(events["total_bought"] or 0),
            })
    return result


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
        order_ids = [r["id"] for r in rows]
        items_by_order: Dict[int, List[Dict[str, Any]]] = {oid: [] for oid in order_ids}
        if order_ids:
            item_rows = await conn.fetch(
                """SELECT moi.order_id, id.key AS item_key, id.name AS item_name, id.rarity
                   FROM market_order_items moi
                   JOIN user_items ui ON ui.id = moi.user_item_id
                   JOIN item_defs id ON id.id = ui.item_def_id
                   WHERE moi.order_id = ANY($1::int[])""",
                order_ids,
            )
            for ir in item_rows:
                items_by_order[ir["order_id"]].append({
                    "key": ir["item_key"],
                    "name": ir["item_name"],
                    "rarity": ir["rarity"] or "fire",
                })
    return [
        {
            "id": r["id"],
            "seller_id": r["seller_id"],
            "pay_currency": r["pay_currency"],
            "pay_amount": int(r["pay_amount"]),
            "expires_at": r["expires_at"].isoformat() if r["expires_at"] else None,
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            "items": items_by_order.get(r["id"], []),
        }
        for r in rows
    ]


async def get_building_pending_income(user_id: int) -> Dict[int, int]:
    """Возвращает накопленные монеты по слотам (slot_index -> pending_coins). Обновляет building_pending_income из last_collected_at."""
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
            "SELECT ads_enabled, last_collected_at FROM user_profile WHERE user_id = $1",
            user_id,
        )
        ads_mult = 1.0 if (profile and profile["ads_enabled"]) else 0.5
        now = datetime.now(timezone.utc)
        last_at = profile.get("last_collected_at") if profile else None
        cap_hours = 12.0
        if last_at:
            hours_used = min(cap_hours, (now - last_at).total_seconds() / 3600.0)
        else:
            hours_used = cap_hours
        pending_by_slot: Dict[int, int] = {}
        for r in rows:
            config = dict(r["config"]) if r["config"] else {}
            income_arr = config.get("incomePerHour") or [0] * 10
            level = min(int(r["level"]), 10)
            base = income_arr[level - 1] if level <= len(income_arr) else 0
            pending_by_slot[r["slot_index"]] = int(base * ads_mult * hours_used)
        for slot_index, pending in pending_by_slot.items():
            await conn.execute(
                """INSERT INTO building_pending_income (user_id, slot_index, pending_coins, last_updated_at)
                   VALUES ($1, $2, $3, NOW())
                   ON CONFLICT (user_id, slot_index) DO UPDATE SET
                     pending_coins = EXCLUDED.pending_coins, last_updated_at = NOW()""",
                user_id, slot_index, pending,
            )
    return pending_by_slot


async def get_user_id_by_telegram_id(telegram_id: int) -> Optional[int]:
    """Возвращает user_id по telegram_id или None."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT id FROM users WHERE telegram_id = $1", telegram_id)
    return int(row["id"]) if row else None


async def get_telegram_id_by_user_id(user_id: int) -> Optional[int]:
    """Возвращает telegram_id по user_id (users.id) или None."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT telegram_id FROM users WHERE id = $1", user_id)
    return int(row["telegram_id"]) if row else None


async def perform_attack(
    attacker_id: int,
    target_id: int,
    building_slot_indexes: List[int],
) -> Dict[str, Any]:
    """
    Атака (ограбление до 2 зданий). Проверяет cooldown 30 мин и 1ч на постройку.
    50% шанс на каждое здание; забирает 20% накопленных в слоте. Возвращает { ok, total_stolen, buildings_robbed, message }.
    """
    from datetime import datetime, timezone, timedelta
    if len(building_slot_indexes) > 2:
        return {"ok": False, "total_stolen": 0, "buildings_robbed": {}, "message": "invalid_slots"}
    for s in building_slot_indexes:
        if s < 1 or s > 9:
            return {"ok": False, "total_stolen": 0, "buildings_robbed": {}, "message": "invalid_slot_index"}
    pool = await get_pool()
    now = datetime.now(timezone.utc)
    pending_by_slot = await get_building_pending_income(target_id)
    buildings_robbed: Dict[int, int] = {}
    total_stolen = 0
    rob_pct = 0.20
    async with pool.acquire() as conn:
        last_attack = await conn.fetchrow(
            """SELECT visited_at FROM visit_log
               WHERE visitor_id = $1 AND target_id = $2 AND attack_performed = TRUE
               ORDER BY visited_at DESC LIMIT 1""",
            attacker_id, target_id,
        )
        if last_attack:
            next_at = last_attack["visited_at"] + timedelta(minutes=30)
            if now < next_at:
                return {"ok": False, "total_stolen": 0, "buildings_robbed": {}, "message": "attack_cooldown", "next_attack_at": next_at.isoformat()}
        for slot_index in building_slot_indexes:
            if slot_index not in pending_by_slot or pending_by_slot[slot_index] <= 0:
                continue
            cooldown_row = await conn.fetchrow(
                """SELECT last_robbed_at FROM rob_cooldown
                   WHERE attacker_id = $1 AND target_id = $2 AND slot_index = $3""",
                attacker_id, target_id, slot_index,
            )
            if cooldown_row and (cooldown_row["last_robbed_at"] + timedelta(hours=1)) > now:
                continue
            if random.random() > 0.5:
                continue
            steal = max(1, int(pending_by_slot[slot_index] * rob_pct))
            await conn.execute(
                """INSERT INTO building_pending_income (user_id, slot_index, pending_coins, last_updated_at)
                   VALUES ($1, $2, 0, NOW())
                   ON CONFLICT (user_id, slot_index) DO UPDATE SET
                     pending_coins = GREATEST(0, building_pending_income.pending_coins - $3), last_updated_at = NOW()""",
                target_id, slot_index, steal,
            )
            buildings_robbed[slot_index] = steal
            total_stolen += steal
            await conn.execute(
                """INSERT INTO rob_cooldown (attacker_id, target_id, slot_index, last_robbed_at)
                   VALUES ($1, $2, $3, NOW())
                   ON CONFLICT (attacker_id, target_id, slot_index) DO UPDATE SET last_robbed_at = NOW()""",
                attacker_id, target_id, slot_index,
            )
        buildings_robbed_json = json.dumps({str(k): v for k, v in buildings_robbed.items()})
        visit_id = await conn.fetchval(
            """INSERT INTO visit_log (visitor_id, target_id, visited_at, attack_performed, buildings_robbed, total_stolen)
               VALUES ($1, $2, NOW(), TRUE, $3::jsonb, $4) RETURNING id""",
            attacker_id, target_id, buildings_robbed_json, total_stolen,
        )
    if total_stolen > 0:
        await add_coins_ledger(attacker_id, total_stolen, "attack_rob", ref_id=visit_id)
    return {"ok": True, "total_stolen": total_stolen, "buildings_robbed": buildings_robbed, "message": "ok", "visit_id": visit_id}


async def get_visit_log(user_id: int, role: str = "any", limit: int = 50) -> List[Dict[str, Any]]:
    """Лог визитов/атак: role=visitor (где я гость), target (где я цель), any (оба)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        if role == "visitor":
            rows = await conn.fetch(
                """SELECT vl.id, vl.visitor_id, vl.target_id, vl.visited_at, vl.attack_performed, vl.buildings_robbed, vl.total_stolen
                   FROM visit_log vl WHERE vl.visitor_id = $1 ORDER BY vl.visited_at DESC LIMIT $2""",
                user_id, limit,
            )
        elif role == "target":
            rows = await conn.fetch(
                """SELECT vl.id, vl.visitor_id, vl.target_id, vl.visited_at, vl.attack_performed, vl.buildings_robbed, vl.total_stolen
                   FROM visit_log vl WHERE vl.target_id = $1 ORDER BY vl.visited_at DESC LIMIT $2""",
                user_id, limit,
            )
        else:
            rows = await conn.fetch(
                """SELECT vl.id, vl.visitor_id, vl.target_id, vl.visited_at, vl.attack_performed, vl.buildings_robbed, vl.total_stolen
                   FROM visit_log vl WHERE vl.visitor_id = $1 OR vl.target_id = $1 ORDER BY vl.visited_at DESC LIMIT $2""",
                user_id, limit,
            )
    return [
        {
            "id": r["id"],
            "visitor_id": r["visitor_id"],
            "target_id": r["target_id"],
            "visited_at": r["visited_at"].isoformat() if r["visited_at"] else None,
            "attack_performed": r["attack_performed"],
            "buildings_robbed": dict(r["buildings_robbed"]) if r["buildings_robbed"] else {},
            "total_stolen": int(r["total_stolen"]),
        }
        for r in rows
    ]


async def collect_income(user_id: int) -> Dict[str, Any]:
    """Начисляет доход с поля: считает pending по слотам, зачисляет в казну, обнуляет pending и last_collected_at. Кап 12 ч."""
    pool = await get_pool()
    pending_by_slot = await get_building_pending_income(user_id)
    total_earned = sum(pending_by_slot.values())
    if total_earned > 0:
        await add_coins_ledger(user_id, total_earned, "field_income", ref_id="collect")
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM building_pending_income WHERE user_id = $1", user_id)
        await conn.execute(
            "UPDATE user_profile SET last_collected_at = NOW(), updated_at = NOW() WHERE user_id = $1",
            user_id,
        )
    cap_hours = 12.0
    return {"earned": total_earned, "hours_used": cap_hours, "pending_by_slot": pending_by_slot}


async def update_checkin_state(
    user_id: int,
    granted_attempts: int,
    next_checkin_at,
    base_cd_minutes: int,
    bonus_minutes_used: int = 0,
    effective_cd_minutes: int = 600,
) -> None:
    """Обновляет checkin_state и пишет checkin_log после успешного чекина. Upsert для надёжности — строки создаются если их нет."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        # Upsert checkin_state: создаёт строку если нет, обновляет если есть
        await conn.execute(
            """INSERT INTO checkin_state (user_id, last_checkin_at, next_checkin_at, streak, updated_at)
               VALUES ($1, NOW(), $2, 1, NOW())
               ON CONFLICT (user_id) DO UPDATE SET
                 last_checkin_at = NOW(),
                 next_checkin_at = $2,
                 streak = checkin_state.streak + 1,
                 updated_at = NOW()""",
            user_id, next_checkin_at,
        )
        await conn.execute(
            """INSERT INTO checkin_log (user_id, granted_attempts, base_cd_minutes, bonus_minutes_used, effective_cd_minutes, next_checkin_at)
               VALUES ($1, $2, $3, $4, $5, $6)""",
            user_id, granted_attempts, base_cd_minutes, bonus_minutes_used, effective_cd_minutes, next_checkin_at,
        )
        # Upsert attempts_balance: создаёт строку если нет, прибавляет если есть
        await conn.execute(
            """INSERT INTO attempts_balance (user_id, attempts) VALUES ($1, $2)
               ON CONFLICT (user_id) DO UPDATE SET
                 attempts = attempts_balance.attempts + EXCLUDED.attempts,
                 updated_at = NOW()""",
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


async def try_claim_task_reward(user_id: int, task_key: str) -> bool:
    """Закрепить выдачу награды за задание (один раз на пользователя и task_key). Возвращает True если это первое получение, False если уже получал."""
    pool = await get_pool()
    key = task_key.strip()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO user_task_claims (user_id, task_key) VALUES ($1, $2)
               ON CONFLICT (user_id, task_key) DO NOTHING RETURNING user_id""",
            user_id, key,
        )
    return row is not None


async def has_claimed_task(user_id: int, task_key: str) -> bool:
    """Проверить, получал ли пользователь уже награду за задание."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT 1 FROM user_task_claims WHERE user_id = $1 AND task_key = $2",
            user_id, task_key.strip(),
        )
    return row is not None


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


# ——— Админ-панель (логин/пароль, отдельно от приложения) ———

async def admin_panel_has_any() -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        r = await conn.fetchval("SELECT 1 FROM admin_panel_credentials LIMIT 1")
    return r is not None


async def admin_panel_create(login: str, password_hash: str) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO admin_panel_credentials (login, password_hash, updated_at)
               VALUES ($1, $2, NOW()) RETURNING id""",
            login.strip(), password_hash,
        )
    return row["id"]


async def admin_panel_get_by_login(login: str) -> Optional[Dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, login, password_hash FROM admin_panel_credentials WHERE login = $1",
            login.strip(),
        )
    return dict(row) if row else None


async def admin_panel_get_by_token(token: str) -> Optional[Dict[str, Any]]:
    if not token:
        return None
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT id, login FROM admin_panel_credentials
               WHERE token = $1 AND token_expires_at > NOW()""",
            token,
        )
    return dict(row) if row else None


async def admin_panel_set_token(admin_id: int, token: str, expires_at) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """UPDATE admin_panel_credentials SET token = $1, token_expires_at = $2, updated_at = NOW() WHERE id = $3""",
            token, expires_at, admin_id,
        )


async def admin_panel_update_password(admin_id: int, password_hash: str) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE admin_panel_credentials SET password_hash = $1, token = NULL, token_expires_at = NULL, updated_at = NOW() WHERE id = $2",
            password_hash, admin_id,
        )


async def admin_panel_update_login(admin_id: int, login: str) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE admin_panel_credentials SET login = $1, updated_at = NOW() WHERE id = $2",
            login.strip(), admin_id,
        )


async def staking_contracts_list() -> List[Dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, contract_address, label, sort_order, created_at FROM staking_contract_addresses ORDER BY sort_order, id"
        )
    return [
        {
            "id": r["id"],
            "contract_address": r["contract_address"],
            "label": r["label"] or "",
            "sort_order": r["sort_order"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        }
        for r in rows
    ]


async def staking_contract_add(contract_address: str, label: Optional[str] = None, sort_order: int = 0) -> Optional[int]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            row = await conn.fetchrow(
                """INSERT INTO staking_contract_addresses (contract_address, label, sort_order) VALUES ($1, $2, $3) RETURNING id""",
                contract_address.strip(), (label or "").strip() or None, sort_order,
            )
            return row["id"]
        except Exception:
            return None


async def staking_contract_delete(contract_id: int) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        r = await conn.execute("DELETE FROM staking_contract_addresses WHERE id = $1", contract_id)
    return r == "DELETE 1"


async def get_pnl_wallet_state(user_id: int) -> Dict[str, Any]:
    """Состояние кошелька и стейкингов для экрана PnL: привязка, список кошельков (сокращённые), общая статистика, контракты стейкинга."""
    from infrastructure.ton_address import raw_to_friendly

    pool = await get_pool()
    async with pool.acquire() as conn:
        wallets = await conn.fetch(
            "SELECT id, wallet_address FROM user_wallet_bindings WHERE user_id = $1 AND verified_at IS NOT NULL ORDER BY created_at",
            user_id,
        )
        sessions = await conn.fetch(
            "SELECT id, status FROM staking_sessions WHERE user_id = $1 AND status IN ('PENDING', 'ACCUMULATING', 'LOCKED')",
            user_id,
        )
        contracts = await conn.fetch(
            "SELECT id, contract_address, label FROM staking_contract_addresses ORDER BY sort_order, id"
        )
    # Конвертируем raw → friendly (UQ…) через Ton Center API
    wallet_list = []
    first_friendly = None
    for r in wallets:
        addr = r["wallet_address"] or ""
        friendly = await raw_to_friendly(addr)
        masked = friendly[:8] + "…" + friendly[-4:] if len(friendly) > 14 else friendly
        wallet_list.append({"id": r["id"], "wallet_address_masked": masked, "wallet_address_friendly": friendly})
        if first_friendly is None:
            first_friendly = friendly
    first_masked = first_friendly[:8] + "…" + first_friendly[-4:] if first_friendly and len(first_friendly) > 14 else (first_friendly or "")
    return {
        "wallet_bound": len(wallets) > 0,
        "wallets_count": len(wallets),
        "wallets": wallet_list,
        "wallet_address_masked": first_masked,
        "wallet_address_full": first_friendly or "",
        "has_active_staking": len(sessions) > 0,
        "active_staking_count": len(sessions),
        "staking_contracts": [
            {"id": r["id"], "contract_address": r["contract_address"], "label": r["label"] or ""}
            for r in contracts
        ],
    }


# ──────────────────────────────────────────────────────────────
# Dev NFT collections & items (каталог NFT от разработчика)
# ──────────────────────────────────────────────────────────────

async def upsert_dev_collection(
    collection_address: str,
    name: str = "",
    description: str = "",
    image: str = "",
    creator_address: str = "",
    items_count: int = 0,
) -> int:
    """Upsert коллекции разработчика. Возвращает id."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO dev_collections (collection_address, name, description, image, creator_address, items_count, synced_at)
               VALUES ($1, $2, $3, $4, $5, $6, NOW())
               ON CONFLICT (collection_address) DO UPDATE SET
                 name = EXCLUDED.name,
                 description = EXCLUDED.description,
                 image = EXCLUDED.image,
                 creator_address = EXCLUDED.creator_address,
                 items_count = EXCLUDED.items_count,
                 synced_at = NOW()
               RETURNING id""",
            collection_address, name, description, image, creator_address, items_count,
        )
        return row["id"]


async def upsert_dev_nft(
    nft_address: str,
    collection_id: int,
    collection_address: str = "",
    nft_index: int = 0,
    owner_address: str = "",
    name: str = "",
    description: str = "",
    image: str = "",
    metadata_url: str = "",
    attributes: Any = None,
    mint_timestamp: Any = None,
) -> int:
    """Upsert NFT из коллекции разработчика. Возвращает id."""
    pool = await get_pool()
    attrs = json.dumps(attributes or [])
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO dev_nfts (nft_address, collection_id, collection_address, nft_index, owner_address, name, description, image, metadata_url, attributes, mint_timestamp, synced_at)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10::jsonb, $11, NOW())
               ON CONFLICT (nft_address) DO UPDATE SET
                 collection_id = EXCLUDED.collection_id,
                 collection_address = EXCLUDED.collection_address,
                 owner_address = EXCLUDED.owner_address,
                 name = EXCLUDED.name,
                 description = EXCLUDED.description,
                 image = EXCLUDED.image,
                 metadata_url = EXCLUDED.metadata_url,
                 attributes = EXCLUDED.attributes,
                 mint_timestamp = EXCLUDED.mint_timestamp,
                 synced_at = NOW()
               RETURNING id""",
            nft_address, collection_id, collection_address, nft_index,
            owner_address, name, description, image, metadata_url,
            attrs, mint_timestamp,
        )
        return row["id"]


async def get_dev_collections() -> List[Dict[str, Any]]:
    """Все коллекции разработчика (items_count = реальное кол-во NFT в dev_nfts)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT c.*,
                   COALESCE(n.cnt, 0) AS real_items_count
            FROM dev_collections c
            LEFT JOIN (
                SELECT collection_id, COUNT(*) AS cnt
                FROM dev_nfts
                GROUP BY collection_id
            ) n ON n.collection_id = c.id
            ORDER BY c.created_at
        """)
    result = []
    for r in rows:
        d = dict(r)
        d["items_count"] = d.pop("real_items_count")
        result.append(d)
    return result


async def get_dev_nfts_for_user(user_wallet_addresses: List[str]) -> List[Dict[str, Any]]:
    """NFT из коллекций разработчика, принадлежащие юзеру (по списку его кошельков)."""
    if not user_wallet_addresses:
        return []
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT n.*, c.name AS collection_name, c.image AS collection_image
               FROM dev_nfts n
               JOIN dev_collections c ON c.id = n.collection_id
               WHERE n.owner_address = ANY($1::text[])
               ORDER BY c.name, n.nft_index""",
            user_wallet_addresses,
        )
    return [dict(r) for r in rows]


async def get_dev_nfts_by_collection(collection_address: str) -> List[Dict[str, Any]]:
    """Все NFT из конкретной коллекции."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM dev_nfts WHERE collection_address = $1 ORDER BY nft_index",
            collection_address,
        )
    return [dict(r) for r in rows]


async def get_all_dev_nfts() -> List[Dict[str, Any]]:
    """Все NFT из всех коллекций разработчика."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT n.*, c.name AS collection_name
               FROM dev_nfts n
               JOIN dev_collections c ON c.id = n.collection_id
               ORDER BY c.name, n.nft_index"""
        )
    return [dict(r) for r in rows]


async def get_dev_profile_stats() -> Dict[str, Any]:
    """Статистика профиля разработчика: количество коллекций и NFT."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        coll_count = await conn.fetchval("SELECT COUNT(*) FROM dev_collections")
        nft_count = await conn.fetchval("SELECT COUNT(*) FROM dev_nfts")
        last_sync = await conn.fetchval(
            "SELECT finished_at FROM nft_sync_log WHERE finished_at IS NOT NULL ORDER BY finished_at DESC LIMIT 1"
        )
    return {
        "collections_count": coll_count or 0,
        "nfts_total": nft_count or 0,
        "last_synced_at": last_sync.isoformat() if last_sync else None,
    }


async def log_nft_sync(sync_type: str, collections_synced: int, nfts_synced: int, errors: int) -> None:
    """Записать результат синхронизации NFT."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO nft_sync_log (sync_type, collections_synced, nfts_synced, errors, finished_at)
               VALUES ($1, $2, $3, $4, NOW())""",
            sync_type, collections_synced, nfts_synced, errors,
        )


async def clear_dev_collections() -> None:
    """Удалить все записи из dev_collections и dev_nfts (перед полным ресинком)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM dev_nfts")
        await conn.execute("DELETE FROM dev_collections")


# ===================== game_settings (runtime config) =====================

# Default values seeded on first run
_GAME_SETTINGS_DEFAULTS: Dict[str, Any] = {
    "checkin.cooldown_hours": 10,
    "checkin.attempts_per_claim": 3,
    "checkin.attempts_per_claim_chat": 2,
    "checkin.attempts_expiry_days": 2,
    "mine.grid_size": 36,
    "mine.prize_cells_distribution": [
        {"cells": 2, "chancePct": 10}, {"cells": 3, "chancePct": 20},
        {"cells": 4, "chancePct": 30}, {"cells": 5, "chancePct": 25},
        {"cells": 6, "chancePct": 15},
    ],
    "mine.prize_loot": {
        "relicPct": 65, "amuletPct": 14, "coinsPct": 10,
        "eggPct": 0.8, "projectTokensPct": 5, "furnacePct": 5.2,
    },
    "mine.egg_roll": {"targetEggPerClick": 0.001, "derivedEggGivenPrizeCellPct": 0.909},
    "eggs.colors": [
        {"color": "red", "rarity": "common", "weight": 22},
        {"color": "green", "rarity": "common", "weight": 22},
        {"color": "blue", "rarity": "common", "weight": 22},
        {"color": "yellow", "rarity": "common", "weight": 18},
        {"color": "purple", "rarity": "rare", "weight": 10},
        {"color": "black", "rarity": "epic", "weight": 5},
        {"color": "white", "rarity": "legendary", "weight": 1},
    ],
    "field.max_buildings": 9,
    "field.demolish_refund_rate": 0.25,
    "prize_pool.entry_phxpw": 30000,
    "prize_pool.phxpw_price_ton": 0.00002412,
    "fees.transaction_percent": 6.0,
    "fees.early_unstake": 10.0,
    "fees.express_withdrawal": 60.0,
    "fees.nft_holders": 2.0,
    "fees.project": 2.0,
    "fees.burn": 1.0,
    "fees.charity": 1.0,
    "staking.enabled": True,
    "staking.base_apy": 0.15,
    "staking.reward_period_sec": 3600,
    "staking.min_stake": 100.0,
    "staking.max_stake": 1000000000.0,
    "staking.auto_compound": False,
    "quest.reward_amount": 100000,
    "quest.min_burn_count": 5,
    "quest.min_account_age_days": 3,
    "quest.submit_rate_limit_sec": 5,
    "quest.burn_diminishing_after": 50,
    "holders.show_detailed_public": False,
}


async def seed_game_settings() -> None:
    """Insert default settings where missing (does NOT overwrite existing)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        for key, val in _GAME_SETTINGS_DEFAULTS.items():
            await conn.execute(
                """INSERT INTO game_settings (key, value)
                   VALUES ($1, $2::jsonb)
                   ON CONFLICT (key) DO NOTHING""",
                key, json.dumps(val),
            )


async def get_setting(key: str, default=None):
    """Read a single setting from game_settings, fall back to default."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchval(
            "SELECT value FROM game_settings WHERE key = $1", key
        )
    if row is not None:
        return json.loads(row) if isinstance(row, str) else row
    return default if default is not None else _GAME_SETTINGS_DEFAULTS.get(key)


async def set_setting(key: str, value: Any) -> None:
    """Upsert a single setting."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO game_settings (key, value, updated_at)
               VALUES ($1, $2::jsonb, NOW())
               ON CONFLICT (key) DO UPDATE SET value = $2::jsonb, updated_at = NOW()""",
            key, json.dumps(value),
        )


async def get_all_settings() -> Dict[str, Any]:
    """Return all game_settings as a flat dict."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT key, value FROM game_settings ORDER BY key")
    result = {}
    for r in rows:
        v = r["value"]
        result[r["key"]] = json.loads(v) if isinstance(v, str) else v
    return result


def get_settings_defaults() -> Dict[str, Any]:
    """Return the hardcoded defaults dict (for display in admin panel)."""
    return dict(_GAME_SETTINGS_DEFAULTS)


# ===================== nft_holder_snapshots =====================

async def upsert_holder_snapshot(
    owner_address: str,
    nft_count: int = 0,
    collections: Any = None,
    phxpw_balance: float = 0,
    total_received: float = 0,
    total_sent: float = 0,
    staking_rewards: float = 0,
    linked_telegram_id: Optional[int] = None,
    linked_username: Optional[str] = None,
) -> None:
    """Insert or update a holder snapshot."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO nft_holder_snapshots
                   (owner_address, nft_count, collections, phxpw_balance,
                    total_received, total_sent, staking_rewards,
                    linked_telegram_id, linked_username, synced_at)
               VALUES ($1, $2, $3::jsonb, $4, $5, $6, $7, $8, $9, NOW())
               ON CONFLICT (owner_address) DO UPDATE SET
                   nft_count = $2, collections = $3::jsonb, phxpw_balance = $4,
                   total_received = $5, total_sent = $6, staking_rewards = $7,
                   linked_telegram_id = $8, linked_username = $9, synced_at = NOW()""",
            owner_address,
            nft_count,
            json.dumps(collections or []),
            phxpw_balance,
            total_received,
            total_sent,
            staking_rewards,
            linked_telegram_id,
            linked_username,
        )


async def get_all_holder_snapshots() -> List[Dict[str, Any]]:
    """Return all NFT holder snapshots, ordered by nft_count desc."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM nft_holder_snapshots ORDER BY nft_count DESC, phxpw_balance DESC"
        )
    result = []
    for r in rows:
        d = dict(r)
        colls = d.get("collections")
        d["collections"] = json.loads(colls) if isinstance(colls, str) else (colls or [])
        d["phxpw_balance"] = float(d.get("phxpw_balance") or 0)
        d["total_received"] = float(d.get("total_received") or 0)
        d["total_sent"] = float(d.get("total_sent") or 0)
        d["staking_rewards"] = float(d.get("staking_rewards") or 0)
        if d.get("synced_at"):
            d["synced_at"] = d["synced_at"].isoformat()
        result.append(d)
    return result


async def get_holder_snapshots_count() -> int:
    """Return count of unique NFT holders."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval("SELECT COUNT(*) FROM nft_holder_snapshots WHERE nft_count > 0") or 0


async def get_nft_owners_with_links() -> List[Dict[str, Any]]:
    """Get unique NFT owners from dev_nfts joined with wallet bindings to find linked TG users."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT
                n.owner_address,
                COUNT(*) AS nft_count,
                ARRAY_AGG(DISTINCT c.name) FILTER (WHERE c.name IS NOT NULL) AS collection_names,
                ARRAY_AGG(DISTINCT c.collection_address) FILTER (WHERE c.collection_address IS NOT NULL) AS collection_addresses,
                wb.user_id AS linked_user_id,
                u.telegram_id AS linked_telegram_id,
                gp.username AS linked_username
            FROM dev_nfts n
            JOIN dev_collections c ON c.id = n.collection_id
            LEFT JOIN user_wallet_bindings wb ON wb.wallet_address = n.owner_address AND wb.verified_at IS NOT NULL
            LEFT JOIN users u ON u.id = wb.user_id
            LEFT JOIN game_players gp ON gp.telegram_id = u.telegram_id
            WHERE n.owner_address != '' AND n.owner_address IS NOT NULL
            GROUP BY n.owner_address, wb.user_id, u.telegram_id, gp.username
            ORDER BY COUNT(*) DESC
        """)
    return [dict(r) for r in rows]
