-- Migration 003: Create migration tracking table.
--
-- Records which database migrations have already been applied.
-- This prevents accidentally running the same migration twice.

CREATE TABLE IF NOT EXISTS public.schema_migrations (
    version VARCHAR(20) PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);