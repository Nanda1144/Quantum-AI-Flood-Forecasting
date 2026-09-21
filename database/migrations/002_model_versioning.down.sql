-- Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
-- Module: database | Owner: Nanda | License: Apache-2.0
--
-- PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction -
-- Nanda & Navya). It is honest by construction, per the platform README:
-- no fabricated data, no invented metrics, every surrogate or fallback is
-- clearly labelled, and no quantum speedup is ever claimed.

-- ============================================================================
-- 002_model_versioning.down.sql
-- Reverses 002_model_versioning.up.sql.
-- model_metrics must be dropped before model_versions (FK dependency).
-- ============================================================================

DROP TABLE IF EXISTS model_metrics;
DROP TABLE IF EXISTS model_versions;
DROP FUNCTION IF EXISTS set_updated_at();