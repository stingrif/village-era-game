-- Survival MMO: локации, путешествия, базовые ресурсы item_defs.

CREATE TABLE IF NOT EXISTS locations (
    location_id TEXT PRIMARY KEY,
    zone_id TEXT REFERENCES zones(zone_id),
    type TEXT NOT NULL DEFAULT 'forest',
    name TEXT NOT NULL,
    map_x REAL NOT NULL DEFAULT 50,
    map_y REAL NOT NULL DEFAULT 50,
    energy_cost INTEGER NOT NULL DEFAULT 5,
    travel_seconds INTEGER NOT NULL DEFAULT 60,
    loot_table_key TEXT NOT NULL DEFAULT 'forest_basic',
    active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS travels (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    from_id TEXT NOT NULL,
    to_id TEXT NOT NULL,
    start_ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    arrive_ts TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL DEFAULT 'in_progress'
);

CREATE INDEX IF NOT EXISTS idx_travels_user_status ON travels(user_id, status);
CREATE INDEX IF NOT EXISTS idx_travels_arrive_ts ON travels(arrive_ts);

INSERT INTO locations (location_id, zone_id, type, name, map_x, map_y, energy_cost, travel_seconds, loot_table_key, active)
VALUES
    ('loc_forest_1', 'zone_1', 'forest', 'Тёмный Лес', 40, 30, 5, 120, 'forest_basic', TRUE),
    ('loc_quarry_1', 'zone_3', 'quarry', 'Каменный Карьер', 65, 20, 8, 180, 'quarry_basic', TRUE),
    ('loc_bunker_1', 'zone_3', 'bunker', 'Бункер Б-3', 72, 18, 15, 300, 'bunker_rare', TRUE)
ON CONFLICT (location_id) DO NOTHING;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'item_defs'
    ) THEN
        INSERT INTO item_defs (item_type, subtype, key, name, rarity, effects_json, limits_json, craftable, base_level)
        VALUES
            ('resource', 'material', 'resource_wood', 'Древесина', 'common', '{}'::jsonb, '{}'::jsonb, FALSE, 1),
            ('resource', 'material', 'resource_stone', 'Камень', 'common', '{}'::jsonb, '{}'::jsonb, FALSE, 1),
            ('resource', 'material', 'resource_scrap', 'Металлолом', 'rare', '{}'::jsonb, '{}'::jsonb, FALSE, 1),
            ('resource', 'material', 'resource_metal', 'Металл', 'rare', '{}'::jsonb, '{}'::jsonb, FALSE, 1)
        ON CONFLICT (key) DO NOTHING;
    END IF;
END $$;
