-- Миграция 002: гарантируем существование tigrit_interactions
-- Безопасна для повторного запуска (IF NOT EXISTS).

CREATE TABLE IF NOT EXISTS tigrit_interactions (
    id       BIGSERIAL    PRIMARY KEY,
    ts       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    kind     TEXT         NOT NULL,
    actor_id BIGINT       DEFAULT 0,
    target_id BIGINT,
    payload  TEXT
);

CREATE INDEX IF NOT EXISTS tigrit_interactions_ts_idx
    ON tigrit_interactions (ts DESC);

CREATE INDEX IF NOT EXISTS tigrit_interactions_kind_idx
    ON tigrit_interactions (kind);
