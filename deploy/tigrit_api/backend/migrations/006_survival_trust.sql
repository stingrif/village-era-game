-- Survival MMO: trust, репорты, модерация.

CREATE TABLE IF NOT EXISTS survival_reports (
    id BIGSERIAL PRIMARY KEY,
    reporter_id BIGINT NOT NULL,
    target_id BIGINT NOT NULL,
    reason TEXT NOT NULL,
    evidence TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    moderator_id BIGINT,
    resolved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_survival_reports_status ON survival_reports(status);
CREATE INDEX IF NOT EXISTS idx_survival_reports_target ON survival_reports(target_id);
