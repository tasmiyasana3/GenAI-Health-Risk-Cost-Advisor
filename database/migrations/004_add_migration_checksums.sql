
-- Add SHA-256 checksum storage to migration history.
-- Existing rows are backfilled by the migration runner.

ALTER TABLE public.schema_migrations
ADD COLUMN IF NOT EXISTS checksum VARCHAR(64);
