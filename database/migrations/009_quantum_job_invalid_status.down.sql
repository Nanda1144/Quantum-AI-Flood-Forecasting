-- Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
-- Module: database | Owner: Nanda | License: Apache-2.0
--
-- PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction -
-- Nanda & Navya). It is honest by construction, per the platform README:
-- no fabricated data, no invented metrics, every surrogate or fallback is
-- clearly labelled, and no quantum speedup is ever claimed.

-- Reversible: narrows `quantum_jobs.status` back to the migration-006 set
-- (without `invalid`) and removes the completed-only result trigger. Only rows
-- that were never written as `invalid` are affected; columns and indexes are
-- untouched.
-- ============================================================================

DROP TRIGGER IF EXISTS trg_quantum_results_only_for_completed_job ON quantum_results;
DROP FUNCTION IF EXISTS chk_quantum_results_only_for_completed_job();

ALTER TABLE quantum_jobs DROP CONSTRAINT IF EXISTS chk_quantum_jobs_status;
ALTER TABLE quantum_jobs ADD CONSTRAINT chk_quantum_jobs_status CHECK (
  status IN ('queued', 'running', 'completed', 'failed', 'cancelled'));