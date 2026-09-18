-- ============================================================================
-- 002_model_versioning.down.sql
-- Reverses 002_model_versioning.up.sql.
-- model_metrics must be dropped before model_versions (FK dependency).
-- ============================================================================

DROP TABLE IF EXISTS model_metrics;
DROP TABLE IF EXISTS model_versions;
DROP FUNCTION IF EXISTS set_updated_at();