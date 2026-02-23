-- Миграция 001: расширение таблицы tigrit_village
-- Безопасна для повторного запуска (IF NOT EXISTS).
-- Рекомендуется создать pg_dump перед первым запуском.

ALTER TABLE tigrit_village
    ADD COLUMN IF NOT EXISTS name          TEXT    DEFAULT 'Тигрит',
    ADD COLUMN IF NOT EXISTS xp            INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS population_max INTEGER DEFAULT 50;
