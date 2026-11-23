-- Run once on a database created BEFORE this column existed (fresh installs get it from schema.sql).
ALTER TABLE services ADD COLUMN IF NOT EXISTS active BOOLEAN NOT NULL DEFAULT TRUE;
