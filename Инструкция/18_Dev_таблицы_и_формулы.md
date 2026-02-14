# Dev: таблицы и формулы

## Ключевые таблицы (PostgreSQL)

- **users** — user_id, created_at; + ads_enabled (или в user_profile)
- **user_profile** — user_id, ads_enabled, checkin_cd_bonus_minutes, checkin_cd_bonus_cap_minutes, last_collected_at, furnace_bonus_until
- **user_balances** — user_id, currency, balance, updated_at
- **buildings_def** — key, name, category, kind, stack_limit, short_reason, config (JSONB)
- **player_field** — user_id, slot_index (1..9), building_key, placed_at
- **user_buildings** — user_id, building_key, level, invested_cost, updated_at
- **demolish_log** — user_id, building_key, refunded_amount, refund_rate, created_at
- **item_defs** — id, item_type, subtype, name, rarity, allowed_buildings[], effects_json, limits_json, is_deep_pool, base_level, craftable
- **user_items** — id, user_id, item_def_id, state, item_level, meta, acquired_at, cooldown_until
- **eggs_def** — color, rarity, weight
- **player_eggs** — user_id, color, acquired_at, meta
- **building_slots** — user_id, building_key, slot_index, user_item_id, equipped_at
- **mine_sessions** — id, user_id, grid_size, prize_cells, prize_cells_seed, opened_cells, created_at
- **dig_log** — user_id, mine_id, cell_index, used_attempt_source, egg_hit, prize_hit, drop_item_def_id, drop_rarity, coins_drop, ip_hash, device_hash, vpn_flag, created_at
- **attempts_balance** — user_id, attempts, updated_at
- **checkin_state** — user_id, last_checkin_at, next_checkin_at, streak, updated_at
- **checkin_log** — user_id, granted_attempts, base_cd_minutes, bonus_minutes_used, effective_cd_minutes, next_checkin_at, ip_hash, device_hash, vpn_flag, risk_note, created_at
- **economy_ledger** — user_id, kind, currency, amount, ref_type, ref_id, meta, idem_key, created_at
- **shop_offers** — id, item_def_id, pay_currency (COINS|STARS), pay_amount, stock_type (unlimited|limited), max_per_user_per_era, sort_order. Магазин из казны: [11_Рынок_и_P2P.md](11_Рынок_и_P2P.md).
- **visit_log** — id, visitor_id, target_id, visited_at, attack_performed, buildings_robbed (JSONB), total_stolen. Визиты и атаки: [26_Визиты_и_атаки.md](26_Визиты_и_атаки.md).
- **building_pending_income** — user_id, slot_index, pending_coins, last_updated_at. Накопление по зданиям до сбора.
- **rob_cooldown** — attacker_id, target_id, slot_index, next_rob_at. Кулдаун ограбления «раз в час на постройку».
- **familiars_def** — id, key, name, passive_buff_json, extra_abilities. Определения фамильяров: [27_Печки_и_фамильяры.md](27_Печки_и_фамильяры.md).
- **user_familiars** — user_id, familiar_def_id, equipped, acquired_at.
- **egg_hatch_pool** — egg_color, egg_rarity, outcome_type (resource|relic|familiar), weight. Пул исходов вылупления по цвету/редкости: [03_Шахта_и_яйца.md](03_Шахта_и_яйца.md), [27_Печки_и_фамильяры.md](27_Печки_и_фамильяры.md).
- **market_orders**, **market_order_items**, **escrow_items**, **trade_offers**, **trade_offer_items**
- **curse_log** — attacker_id, target_id, source_item_def_id, class (weak|strong|severe), effects_json, started_at, ends_at, blocked, cleanse_used
- **user_effects** — user_id, effect_group, effect_value, tier, source, applied_at, expires_at
- **user_sanctions** — user_id, sanction_type, started_at, deadline_at, meta
- **token_compliance** — user_id, status, reason, detected_at, deadline_at, required_tokens_json, snapshot_json, resolved_at
- **withdraw_gating** — user_id, required_action_value_ton, completed_action_value_ton, status
- **donations** — user_id, currency, amount, donation_points, period_key, created_at
- **donation_leaderboard_cache** — period_key, user_id, donation_points, updated_at
- **ad_log** — user_id, ad_kind, provider, reward_json, ip_hash, device_hash, vpn_flag, idem_key, created_at
- **admin_users**, **access_policy**, **user_identities**, **account_links**, **risk_profile**, **user_flags**
- **currencies**, **exchange_rates**
- **staking_sessions** — user_id, staked_amount, accrued_rewards, status (ACCUMULATING/LOCKED/UNSTAKED), lock_until, payment_address, lock_requested_at
- **staking_reward_history** — session_id, reward_amount, calculated_at
- **token_transactions** — tx_hash, user_id, wallet_address, amount, direction, block_timestamp
- **crafting_log** — user_id, action (merge|upgrade|reroll), input_item_ids, output_item_id, dust_spent, result_json, created_at
- **item_events** — item_def_id (nullable), event_type, user_id, quantity, ref_type, ref_id, meta (JSONB), created_at. События: drop, burn, merge_input, merge_break, merge_output, upgrade_*, reroll_*, sold, bought. Для сводной статистики по предметам.
- **game_events** — id, user_id, event_type, reason_code, payload (JSONB), created_at
- **leaderboards** — period, period_key, user_id, points, updated_at (PK: period, period_key, user_id)
- **effect_defs** — id, effect_type, group_key (relic|buff|curse|amulet), name, value, duration_minutes, meta (JSONB)

### game_events: типы событий

checkin_granted, mine_click, loot_drop, craft_result, curse_applied, curse_expired, sanction_started, sanction_cleared, withdraw_requested, withdraw_approved, withdraw_rejected, skyfall_tick

### leaderboards: period

weekly, monthly, era. period_key: 2026-W06, 2026-02, S1-E3 и т.п.

### Стейкинг и блокчейн

- Стейкинг: [22_Стейкинг_токена.md](22_Стейкинг_токена.md)
- Блокчейн-анализ: [24_Блокчейн_анализ.md](24_Блокчейн_анализ.md)

## Master config (пример JSON)

```json
{
  "game": {
    "field": { "maxBuildingsPlaced": 9, "demolishRefundRate": 0.25 },
    "mine": {
      "gridSize": 36,
      "checkin": { "cooldownHours": 10, "attemptsPerClaim": 3 },
      "prizeCellsDistribution": [
        { "cells": 2, "chancePct": 10 },
        { "cells": 3, "chancePct": 20 },
        { "cells": 4, "chancePct": 30 },
        { "cells": 5, "chancePct": 25 },
        { "cells": 6, "chancePct": 15 }
      ],
      "prizeCellLoot": { "relicPct": 72.0, "amuletPct": 15.0, "coinsPct": 12.1, "eggPct": 0.9 },
      "eggRoll": { "targetEggPerClick": 0.001, "derivedEggGivenPrizeCellPct": 0.909 }
    },
    "eggs": {
      "colors": [
        { "color": "red", "rarity": "common", "weight": 22 },
        { "color": "green", "rarity": "common", "weight": 22 },
        { "color": "blue", "rarity": "common", "weight": 22 },
        { "color": "yellow", "rarity": "common", "weight": 18 },
        { "color": "purple", "rarity": "rare", "weight": 10 },
        { "color": "black", "rarity": "epic", "weight": 5 },
        { "color": "white", "rarity": "legendary", "weight": 1 }
      ]
    }
  }
}
```

## game_rules (ключи)

- **checkin_rules** — baseCdMinutes (600), minCdMinutes (540), grantedAttempts (3), resetBonusMinutesAfterCheckin (true), riskEarlyWindowSeconds, riskEarlyHitsToFlag  
- **mine_rules** — gridSize, eggChancePerDig (0.001), prizeCellsDist, rarityWeights10x, prizeTypeWeights, coinsFallbackByRarity  
- **ads_rules** — enabledIncomeMultIfAdsOff (0.5), checkinCdBonus (short: 1, long: 2), checkinCdBonusCapMinutes (60), dailyAdCap (short: 30, long: 15)  
- **donation_rules** — donationPoints (STARS: 1, DIAMONDS: 1000), leaderboards (week, month, all)  
- **withdraw_credit_rules** — donationTonEq (DIAMONDS, STARS) для зачёта в 10%  

## Функции (сигнатуры)

- **exchange_currency**(p_user_id, p_from, p_to, p_from_amount, p_idem_key) → JSONB  
- **donate_to_profile**(p_user_id, p_currency, p_amount, p_period_key, p_credit_withdraw, p_idem_key) → JSONB  
- **record_ad_view**(p_user_id, p_ad_kind, p_provider, p_ip_hash, p_device_hash, p_vpn_flag, p_idem_key) → JSONB  
- **toggle_ads**(p_user_id, p_enabled) → JSONB  
- **get_ads_income_mult**(p_user_id) → NUMERIC  
- **checkin**(p_user_id, p_ip_hash, p_device_hash, p_vpn_flag) → JSONB  
- **mine_create**(p_user_id) → BIGINT  
- **mine_dig**(p_user_id, p_mine_id, p_cell_index, p_attempt_source, p_ip_hash, p_device_hash, p_vpn_flag) → JSONB  
- **ensure_balance_row**(p_user_id, p_currency)  
- **lock_item_to_escrow**(p_owner_id, p_user_item_id, p_lock_type, p_lock_id)  
- **unlock_escrow_items**(p_lock_type, p_lock_id) → INT  
- **create_market_order**(p_seller_id, p_user_item_ids[], p_pay_currency, p_pay_amount, p_expires_at, p_idem_key) → JSONB  
- **fill_market_order_coins**(p_buyer_id, p_order_id, p_fee_pct, p_idem_key) → JSONB  
- **cancel_market_order**(p_seller_id, p_order_id) → JSONB  
- **create_trade_offer**(p_maker_id, p_maker_items[], p_taker_items[], p_taker_id, p_want_currency, p_want_amount, p_expires_at) → JSONB  
- **accept_trade_offer**(p_taker_id, p_offer_id, p_taker_items[], p_idem_key) → JSONB  
- **cancel_trade_offer**(p_maker_id, p_offer_id) → JSONB  
- **can_admin**(p_admin_id, p_action) → BOOLEAN  
- **link_accounts_manual**(p_admin_id, p_root_user_id, p_linked_user_id, p_reason, p_confidence) → JSONB  
- **unlink_accounts**(p_admin_id, p_root_user_id, p_linked_user_id, p_note) → JSONB  
- **get_account_links**(p_admin_id, p_user_id) → JSONB  
- **auto_link_by_identity**(p_user_id, p_kind, p_value_hash, p_reason, p_confidence) → INT  

## Идемпотентность

- economy_ledger.idem_key UNIQUE WHERE NOT NULL.  
- Все денежные/escrow операции с idem_key при необходимости.

## Логика баланса (стили)

| Стиль | Результат |
|-------|-----------|
| Агрессия | высокий риск / высокий приз |
| Защита | дольше живёшь / меньше выигрываешь |
| AFK | проигрыш |
| Стратегия | максимум эффективности |
