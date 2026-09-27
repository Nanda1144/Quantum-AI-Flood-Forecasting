-- Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
-- Module: database | Owner: Navya (ForecastingEngine seam) | License: Apache-2.0
--
-- PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction -
-- Nanda & Navya). It is honest by construction, per the platform README:
-- no fabricated data, no invented metrics, every surrogate or fallback is
-- clearly labelled, and no quantum speedup is ever claimed.

-- ============================================================================
-- 010_navya_forecast_provenance.down.sql
-- Reversal of 010_navya_forecast_provenance.up.sql.
--
-- Reversible by design: the two tables introduced by 010 are Navya-owned and
-- carry no team data, so dropping them restores the pre-010 schema exactly.
-- Nothing from 001-009 is touched - no table, column, row, index, constraint or
-- function belonging to another owner is altered or dropped here.
--
-- Idempotency: `IF EXISTS` makes a repeated rollback a no-op, matching the
-- up-migration's `IF NOT EXISTS` convention.
-- ============================================================================

-- navya_forecast_evaluation has no foreign key to anything owned by a team
-- owner, so it is dropped first on its own merits; the order below is simply
-- "children before parents" for readability.
DROP TABLE IF EXISTS navya_forecast_evaluation;

DROP TABLE IF EXISTS navya_forecast_provenance;
