-- Survival MMO: зоны, привязка игрока к домашней зоне, trust и состояние персонажа.

CREATE TABLE IF NOT EXISTS zones (
    zone_id TEXT PRIMARY KEY,
    tg_chat_id BIGINT,
    name TEXT NOT NULL,
    type TEXT NOT NULL DEFAULT 'community',
    xp_multiplier REAL NOT NULL DEFAULT 1.0,
    entry_cost_tokens INTEGER NOT NULL DEFAULT 0,
    map_x REAL NOT NULL DEFAULT 50,
    map_y REAL NOT NULL DEFAULT 50,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    description TEXT NOT NULL DEFAULT '',
    bot_code TEXT
);

INSERT INTO zones (zone_id, name, type, xp_multiplier, entry_cost_tokens, map_x, map_y, active, description, bot_code)
VALUES
    ('zone_1', 'Деревня Тигрит', 'starter',   1.0, 0, 50, 35, TRUE, 'Главная стартовая зона проекта Phoenix', 'zone_1'),
    ('zone_2', 'Торговые ряды',  'starter',   1.2, 0, 30, 25, TRUE, 'Зона торговли. Бонус к XP', 'zone_2'),
    ('zone_3', 'Военный лагерь', 'starter',   1.5, 0, 70, 22, TRUE, 'Зона боя и рейдов. XP x1.5', 'zone_3'),
    ('zone_4', 'Гильдия Северного Ветра', 'community', 1.0, 0, 20, 55, TRUE, 'Сообщество игроков', 'zone_4'),
    ('zone_5', 'Клан Железного Кулака',  'community', 1.0, 0, 75, 60, TRUE, 'Новая зона', 'zone_5'),
    ('zone_6', 'Академия Магии', 'community', 1.2, 0, 45, 70, TRUE, 'Чат магов и алхимиков', 'zone_6')
ON CONFLICT (zone_id) DO NOTHING;

ALTER TABLE IF EXISTS tigrit_user_profile
    ADD COLUMN IF NOT EXISTS home_zone_id TEXT REFERENCES zones(zone_id),
    ADD COLUMN IF NOT EXISTS home_zone_bound_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS home_zone_first_activity_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS home_zone_change_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS character_state TEXT NOT NULL DEFAULT 'alive',
    ADD COLUMN IF NOT EXISTS trust_score INTEGER NOT NULL DEFAULT 50,
    ADD COLUMN IF NOT EXISTS betrayal_flag BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS betrayal_expires_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS clan_id BIGINT;

CREATE INDEX IF NOT EXISTS idx_tigrit_user_profile_home_zone ON tigrit_user_profile(home_zone_id);
CREATE INDEX IF NOT EXISTS idx_tigrit_user_profile_character_state ON tigrit_user_profile(character_state);
