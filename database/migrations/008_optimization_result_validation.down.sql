-- Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
-- Module: database | Owner: Nanda | License: Apache-2.0
--
-- PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction -
-- Nanda & Navya). It is honest by construction, per the platform README:
-- no fabricated data, no invented metrics, every surrogate or fallback is
-- clearly labelled, and no quantum speedup is ever claimed.

-- ============================================================================
-- 008_optimization_result_validation.down.sql
-- Reverses 008_optimization_result_validation.up.sql.
--
-- The 008-only `pending_validation` state is collapsed conservatively before
-- the 004 verdict check is restored: a row that was never validated becomes
-- 'invalid' (it was never attested valid). No DELETE is issued — completed
-- result rows are write-once.
-- ============================================================================

UPDATE optimization_results SET validation_status = 'invalid' WHERE validation_status = 'pending_validation';

ALTER TABLE optimization_results DROP CONSTRAINT IF EXISTS chk_optimization_results_validation_status;
ALTER TABLE optimization_results ADD CONSTRAINT chk_optimization_results_validation_status CHECK (
  validation_status IN ('valid', 'invalid'));

ALTER TABLE optimization_results DROP CONSTRAINT IF EXISTS chk_optimization_results_validation_timestamp;
ALTER TABLE optimization_results DROP CONSTRAINT IF EXISTS chk_optimization_results_validation_details;
ALTER TABLE optimization_results DROP CONSTRAINT IF EXISTS chk_optimization_results_explanation_metadata;

ALTER TABLE optimization_results DROP COLUMN IF EXISTS validation_timestamp;
ALTER TABLE optimization_results DROP COLUMN IF EXISTS validation_details;
ALTER TABLE optimization_results DROP COLUMN IF EXISTS explanation_metadata;
