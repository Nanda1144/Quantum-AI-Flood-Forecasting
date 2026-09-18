-- ============================================================================
-- 001_core_tables.down.sql
-- Reverses 001_core_tables.up.sql. Drop order respects foreign keys
-- (optimization_references -> forecasts).
-- ============================================================================

DROP TABLE IF EXISTS optimization_references;
DROP TABLE IF EXISTS models;
DROP TABLE IF EXISTS forecasts;