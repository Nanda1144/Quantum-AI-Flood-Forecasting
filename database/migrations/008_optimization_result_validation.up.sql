-- Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
-- Module: database | Owner: Nanda | License: Apache-2.0
--
-- PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction -
-- Nanda & Navya). It is honest by construction, per the platform README:
-- no fabricated data, no invented metrics, every surrogate or fallback is
-- clearly labelled, and no quantum speedup is ever claimed.

-- ============================================================================
-- 008_optimization_result_validation.up.sql
-- Q-FLARE final-result validation contract on optimization_results (Nanda).
--
-- optimization_jobs + optimization_results are the SOURCE OF TRUTH for a final
-- optimization result. The normalized row already carries the required
-- contract columns:
--
--   id, optimization_job_id, bitstring, selected_locations (location IDs ONLY),
--   objective_value, constraint_violations, validation_status, runtime_ms,
--   classical_objective, quantum_objective, approximation_quality, created_at
--
-- `selected_locations` stores candidate/location IDs and references only — the
-- GIS module owns the authoritative spatial information, so no geometry/name/
-- risk data is duplicated here.
--
-- This step makes an INVALID result permanently distinguishable from a
-- VALIDATED one by adding the third state and the validation/explanation
-- columns:
--
--   validation_status      valid | invalid | pending_validation
--                          (VALID | INVALID | PENDING_VALIDATION)
--   validation_timestamp   when the verdict was recorded (NULL while pending)
--   validation_details     the persisted verdict (status + summary + violations)
--   explanation_metadata   how the objective decomposes (breakdown + coverage)
--
-- Indexes for optimization_job_id / validation_status / created_at already
-- exist (004, 007); they are re-asserted here so the contract is self-contained
-- and idempotent under `ensureSchema`.
-- ============================================================================

-- 1. Validation / explanation columns.
ALTER TABLE optimization_results ADD COLUMN IF NOT EXISTS validation_timestamp TIMESTAMPTZ;
ALTER TABLE optimization_results ADD COLUMN IF NOT EXISTS validation_details   JSONB;
ALTER TABLE optimization_results ADD COLUMN IF NOT EXISTS explanation_metadata JSONB;

-- 2. A recorded verdict must say when it was recorded; a pending row has no
--    verdict yet. Backfill pre-008 rows from created_at — the write time the
--    verdict was computed — never an invented time.
UPDATE optimization_results
   SET validation_timestamp = created_at
 WHERE validation_timestamp IS NULL
   AND validation_status IN ('valid', 'invalid');

-- 3. Statuses: a validated result, a rejected result, and a result still
--    awaiting validation are three distinct states.
ALTER TABLE optimization_results DROP CONSTRAINT IF EXISTS chk_optimization_results_validation_status;
ALTER TABLE optimization_results ADD CONSTRAINT chk_optimization_results_validation_status CHECK (
  validation_status IN ('valid', 'invalid', 'pending_validation'));

-- A recorded verdict detail must carry the time it was recorded. (The column is
-- allowed to be NULL when no details are stored — e.g. legacy/backfilled rows —
-- so the constraint never forces an invented timestamp.)
ALTER TABLE optimization_results DROP CONSTRAINT IF EXISTS chk_optimization_results_validation_timestamp;
ALTER TABLE optimization_results ADD CONSTRAINT chk_optimization_results_validation_timestamp CHECK (
  validation_details IS NULL OR validation_timestamp IS NOT NULL);

-- The details/metadata columns are JSON objects (or honestly absent).
ALTER TABLE optimization_results DROP CONSTRAINT IF EXISTS chk_optimization_results_validation_details;
ALTER TABLE optimization_results ADD CONSTRAINT chk_optimization_results_validation_details CHECK (
  validation_details IS NULL OR jsonb_typeof(validation_details) = 'object');

ALTER TABLE optimization_results DROP CONSTRAINT IF EXISTS chk_optimization_results_explanation_metadata;
ALTER TABLE optimization_results ADD CONSTRAINT chk_optimization_results_explanation_metadata CHECK (
  explanation_metadata IS NULL OR jsonb_typeof(explanation_metadata) = 'object');

-- 4. Required indexes (idempotent re-assertion).
CREATE INDEX IF NOT EXISTS idx_optimization_results_job               ON optimization_results (optimization_job_id);
CREATE INDEX IF NOT EXISTS idx_optimization_results_validation_status ON optimization_results (validation_status);
CREATE INDEX IF NOT EXISTS idx_optimization_results_created_at        ON optimization_results (created_at DESC);
