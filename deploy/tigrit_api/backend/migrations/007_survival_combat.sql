-- Survival MMO: серверные боевые сессии.

CREATE TABLE IF NOT EXISTS combat_sessions (
    id BIGSERIAL PRIMARY KEY,
    attacker_id BIGINT NOT NULL,
    defender_id BIGINT NOT NULL,
    location_id TEXT,
    attacker_hp INTEGER NOT NULL DEFAULT 100,
    defender_hp INTEGER NOT NULL DEFAULT 100,
    status TEXT NOT NULL DEFAULT 'active',
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_combat_sessions_status ON combat_sessions(status);
CREATE INDEX IF NOT EXISTS idx_combat_sessions_attacker ON combat_sessions(attacker_id);
CREATE INDEX IF NOT EXISTS idx_combat_sessions_defender ON combat_sessions(defender_id);
