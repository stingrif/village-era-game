-- Survival MMO: базы и кланы.

CREATE TABLE IF NOT EXISTS clans (
    clan_id BIGSERIAL PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    tg_chat_id BIGINT,
    zone_id TEXT REFERENCES zones(zone_id),
    treasury INTEGER NOT NULL DEFAULT 0,
    created_by BIGINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS clan_members (
    clan_id BIGINT NOT NULL REFERENCES clans(clan_id) ON DELETE CASCADE,
    user_id BIGINT NOT NULL,
    role TEXT NOT NULL DEFAULT 'member',
    joined_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (clan_id, user_id)
);

CREATE TABLE IF NOT EXISTS player_bases (
    user_id BIGINT PRIMARY KEY,
    zone_id TEXT REFERENCES zones(zone_id),
    map_x REAL NOT NULL,
    map_y REAL NOT NULL,
    base_level INTEGER NOT NULL DEFAULT 1,
    base_name TEXT NOT NULL DEFAULT 'База',
    allocated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_player_bases_zone ON player_bases(zone_id);
