-- Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
-- Module: database | Owner: Nanda | License: Apache-2.0
--
-- PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction -
-- Nanda & Navya). It is honest by construction, per the platform README:
-- no fabricated data, no invented metrics, every surrogate or fallback is
-- clearly labelled, and no quantum speedup is ever claimed.

-- ============================================================================
-- 009_quantum_job_invalid_status.up.sql
-- Q-FLARE quantum job status lifecycle (Nanda).
--
-- The quantum service (app/jobs.py) declares `invalid` as a first-class
-- terminal lifecycle status alongside `failed` and `cancelled`: a submitted
-- run whose measured bitstring does not match the declared binary variables
-- is invalidated with `INVALID_EXECUTION_RESULT`, and the result document for
-- such a job is null. Migration 006 already reserved `cancelled` in the
-- `quantum_jobs.status` CHECK but not `invalid`, so the orchestration backend
-- could not persist an honest `invalid` row for such submissions. This
-- migration widens the CHECK to accept the full terminal set:
--
--     queued -> running -> completed | failed | cancelled | invalid
--
-- The relationship contract is unchanged: only completed jobs may carry a
-- `quantum_results` row, and an `invalid` violation records its error pair on
-- the job row (INVALID_EXECUTION_RESULT) just like a failed execution. The
-- `completed`-only guarantee was previously enforced by the services alone;
-- this migration adds the database trigger so a result row can never be
-- inserted for a job that did not complete (failed / cancelled / invalid /
-- queued / running).
-- ============================================================================

ALTER TABLE quantum_jobs DROP CONSTRAINT IF EXISTS chk_quantum_jobs_status;
ALTER TABLE quantum_jobs ADD CONSTRAINT chk_quantum_jobs_status CHECK (
  status IN ('queued', 'running', 'completed', 'failed', 'cancelled', 'invalid'));

CREATE OR REPLACE FUNCTION chk_quantum_results_only_for_completed_job() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF (SELECT status FROM quantum_jobs WHERE id = NEW.quantum_job_id) <> 'completed' THEN
    RAISE EXCEPTION 'quantum_results only exists for a completed quantum job (status %)',
      (SELECT status FROM quantum_jobs WHERE id = NEW.quantum_job_id)
      USING ERRCODE = '23514', CONSTRAINT = 'chk_quantum_results_parent_completed';
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_quantum_results_only_for_completed_job ON quantum_results;
CREATE TRIGGER trg_quantum_results_only_for_completed_job
  BEFORE INSERT ON quantum_results
  FOR EACH ROW EXECUTE FUNCTION chk_quantum_results_only_for_completed_job();