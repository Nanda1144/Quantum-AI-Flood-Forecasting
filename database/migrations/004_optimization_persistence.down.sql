-- Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
-- Module: database | Owner: Nanda | License: Apache-2.0
--
-- PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction -
-- Nanda & Navya). It is honest by construction, per the platform README:
-- no fabricated data, no invented metrics, every surrogate or fallback is
-- clearly labelled, and no quantum speedup is ever claimed.

-- ============================================================================
-- 004_optimization_persistence.down.sql
-- Reverts the persistence layer: drop triggers, function, indexes, tables and
-- the scalar columns added by 004. The 003 optimization_jobs base table and
-- its indexes/columns are untouched.
-- ============================================================================

DROP TRIGGER IF EXISTS trg_optimization_results_delete_protect ON optimization_results;
DROP TRIGGER IF EXISTS trg_optimization_jobs_delete_protect ON optimization_jobs;
DROP FUNCTION IF EXISTS qflare_guard_optimization_delete();

DROP INDEX IF EXISTS idx_optimization_job_audit_job;
DROP INDEX IF EXISTS idx_optimization_results_validation_status;
DROP INDEX IF EXISTS idx_optimization_results_job;
DROP INDEX IF EXISTS idx_optimization_jobs_problem_type;

DROP TABLE IF EXISTS optimization_qubo_artifacts;
DROP TABLE IF EXISTS optimization_job_audit;
DROP TABLE IF EXISTS optimization_results;

ALTER TABLE optimization_jobs
  DROP COLUMN IF EXISTS forecast_reference,
  DROP COLUMN IF EXISTS candidate_reference,
  DROP COLUMN IF EXISTS input_reference,
  DROP COLUMN IF EXISTS variables_count,
  DROP COLUMN IF EXISTS constraints,
  DROP COLUMN IF EXISTS objective_configuration,
  DROP COLUMN IF EXISTS error_message,
  DROP COLUMN IF EXISTS qubo_storage,
  DROP COLUMN IF EXISTS qubo_artifact_reference,
  DROP COLUMN IF EXISTS deleted_at,
  DROP COLUMN IF EXISTS deleted_by,
  DROP COLUMN IF EXISTS delete_reason;