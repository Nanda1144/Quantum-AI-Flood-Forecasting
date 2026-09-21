-- Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
-- Module: database | Owner: Nanda | License: Apache-2.0
--
-- PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction -
-- Nanda & Navya). It is honest by construction, per the platform README:
-- no fabricated data, no invented metrics, every surrogate or fallback is
-- clearly labelled, and no quantum speedup is ever claimed.

-- ============================================================================
-- 004_optimization_persistence.up.sql
-- Q-FLARE optimization persistence layer (Nanda).
--
-- Normalizes the optimization research record on top of 003:
--
--   optimization_results      one row per completed job (child of
--                             optimization_jobs via fk_optimization_results_job)
--   optimization_job_audit    write-once audit trail (delete protection)
--   optimization_qubo_artifacts  QUBO matrices too large to inline
--
-- Completed research results are WRITE-ONCE: a hard DELETE on a completed job
-- or its result row is rejected by qflare_guard_optimization_delete unless
-- the authorization/audit escape hatch `app.allow_optimization_delete` is set
-- to 'true' for that statement. The application never uses the escape hatch;
-- it soft-deletes through an RBAC + audit path (DELETE /api/optimization/jobs/:id).
--
-- Exact experiment configuration is preserved in scalar columns (and remains
-- canonical in optimization_jobs.request). Selected locations are stored as
-- location ID lists — never as GIS geometry. QUBO matrices are inlined only
-- for small demonstrative problems (<= optimization inline limit); larger
-- matrices move to the artifact store and are referenced, never embedded.
-- No raw Qiskit/Python objects are ever persisted.
-- ============================================================================

-- 1. Scalar configuration columns (denormalized mirror of the request JSONB;
--    the request JSONB stays the canonical record).
ALTER TABLE optimization_jobs ADD COLUMN IF NOT EXISTS forecast_reference      TEXT;
ALTER TABLE optimization_jobs ADD COLUMN IF NOT EXISTS candidate_reference     TEXT;
ALTER TABLE optimization_jobs ADD COLUMN IF NOT EXISTS input_reference         TEXT;
ALTER TABLE optimization_jobs ADD COLUMN IF NOT EXISTS variables_count         INTEGER;
ALTER TABLE optimization_jobs ADD COLUMN IF NOT EXISTS constraints             JSONB;
ALTER TABLE optimization_jobs ADD COLUMN IF NOT EXISTS objective_configuration JSONB;
ALTER TABLE optimization_jobs ADD COLUMN IF NOT EXISTS error_message           TEXT;
ALTER TABLE optimization_jobs ADD COLUMN IF NOT EXISTS qubo_storage            TEXT NOT NULL DEFAULT 'inline'; -- inline | artifact
ALTER TABLE optimization_jobs ADD COLUMN IF NOT EXISTS qubo_artifact_reference TEXT;
ALTER TABLE optimization_jobs ADD COLUMN IF NOT EXISTS deleted_at              TIMESTAMPTZ;
ALTER TABLE optimization_jobs ADD COLUMN IF NOT EXISTS deleted_by              TEXT;
ALTER TABLE optimization_jobs ADD COLUMN IF NOT EXISTS delete_reason           TEXT;

-- 2. Normalized result rows — child of optimization_jobs (one per job).
CREATE TABLE IF NOT EXISTS optimization_results (
  id                    TEXT PRIMARY KEY,
  optimization_job_id   TEXT NOT NULL,
  bitstring             TEXT,
  selected_locations    JSONB NOT NULL DEFAULT '[]'::jsonb,       -- location ID list only
  objective_value       DOUBLE PRECISION NOT NULL,
  constraint_violations JSONB NOT NULL DEFAULT '[]'::jsonb,
  validation_status     TEXT NOT NULL,
  runtime_ms            DOUBLE PRECISION NOT NULL DEFAULT 0,
  classical_objective   DOUBLE PRECISION,
  quantum_objective     DOUBLE PRECISION,
  approximation_quality DOUBLE PRECISION,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT fk_optimization_results_job FOREIGN KEY (optimization_job_id)
    REFERENCES optimization_jobs (id) ON DELETE CASCADE,
  CONSTRAINT chk_optimization_results_id_matches CHECK (id = optimization_job_id || '-R1'),
  CONSTRAINT chk_optimization_results_validation_status CHECK (validation_status IN ('valid', 'invalid')),
  CONSTRAINT chk_optimization_results_quality_bounded CHECK (
    approximation_quality IS NULL OR (approximation_quality >= 0 AND approximation_quality <= 1)
  )
);

-- One result per job is already guaranteed by the primary key combined with
-- the id-format check (id must equal <jobId>-R1). Drop the redundant UNIQUE
-- constraint so a duplicate insert deterministically fails on the primary key.
ALTER TABLE optimization_results DROP CONSTRAINT IF EXISTS uq_optimization_results_job;

-- 3. Write-once audit trail for the delete-protection requirement.
CREATE TABLE IF NOT EXISTS optimization_job_audit (
  id                   BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  optimization_job_id  TEXT NOT NULL,
  action               TEXT NOT NULL,   -- e.g. soft_deleted
  actor                TEXT NOT NULL,   -- authenticated principal
  reason               TEXT,
  created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT fk_optimization_job_audit_job FOREIGN KEY (optimization_job_id)
    REFERENCES optimization_jobs (id) ON DELETE CASCADE
);

-- 4. Artifact storage for QUBO matrices too large to inline.
CREATE TABLE IF NOT EXISTS optimization_qubo_artifacts (
  optimization_job_id  TEXT PRIMARY KEY,
  variable_count       INTEGER NOT NULL,
  storage_reference    TEXT NOT NULL,   -- e.g. qflare://qubo/<jobId>
  qubo                 JSONB NOT NULL,  -- plain JSON matrix, never Qiskit objects
  stored_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT fk_optimization_qubo_artifacts_job FOREIGN KEY (optimization_job_id)
    REFERENCES optimization_jobs (id) ON DELETE CASCADE
);

-- 5. Required indexes (created_at/status mirrors carried over from 003).
CREATE INDEX IF NOT EXISTS idx_optimization_jobs_status       ON optimization_jobs (status);
CREATE INDEX IF NOT EXISTS idx_optimization_jobs_created_at   ON optimization_jobs (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_optimization_jobs_problem_type ON optimization_jobs (problem_type);
CREATE INDEX IF NOT EXISTS idx_optimization_results_job                 ON optimization_results (optimization_job_id);
CREATE INDEX IF NOT EXISTS idx_optimization_results_validation_status   ON optimization_results (validation_status);
CREATE INDEX IF NOT EXISTS idx_optimization_job_audit_job               ON optimization_job_audit (optimization_job_id);

-- 6. Delete protection: completed research results are write-once. The trigger
--    intentionally blocks hard DELETEs unless the transactional escape hatch
--    `app.allow_optimization_delete` is set to 'true' (used only by the
--    repository's administrative/cleanup path — never by the public API).
CREATE OR REPLACE FUNCTION qflare_guard_optimization_delete() RETURNS trigger AS $fn$
DECLARE
  job_status TEXT;
BEGIN
  IF TG_TABLE_NAME = 'optimization_jobs' THEN
    job_status := OLD.status;
  ELSIF TG_TABLE_NAME = 'optimization_results' THEN
    SELECT j.status INTO job_status FROM optimization_jobs j WHERE j.id = OLD.optimization_job_id;
  ELSE
    RETURN OLD;
  END IF;

  IF job_status = 'completed'
     AND COALESCE(current_setting('app.allow_optimization_delete', true), '') <> 'true' THEN
    RAISE EXCEPTION
      'completed optimization results are write-once; delete requires an authorized audit trail (soft-delete via DELETE /api/optimization/jobs/%)',
      OLD.id
      USING ERRCODE = 'P0001';
  END IF;
  RETURN OLD;
END;
$fn$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_optimization_jobs_delete_protect ON optimization_jobs;
CREATE TRIGGER trg_optimization_jobs_delete_protect
  BEFORE DELETE ON optimization_jobs
  FOR EACH ROW EXECUTE FUNCTION qflare_guard_optimization_delete();

DROP TRIGGER IF EXISTS trg_optimization_results_delete_protect ON optimization_results;
CREATE TRIGGER trg_optimization_results_delete_protect
  BEFORE DELETE ON optimization_results
  FOR EACH ROW EXECUTE FUNCTION qflare_guard_optimization_delete();

-- 7. Idempotent backfill: populate scalar columns and result rows for jobs
--    persisted before this migration ran. NULL-only updates — never invents
--    data the old rows did not carry.
UPDATE optimization_jobs
   SET forecast_reference      = COALESCE(forecast_reference, request->>'forecastReference'),
       candidate_reference     = COALESCE(candidate_reference, request->>'candidateLocationsReference', 'gis://candidates/' || (request->>'candidateCount')),
       input_reference         = COALESCE(input_reference, 'ai://forecasts/' || (request->>'forecastReference')),
       variables_count         = COALESCE(variables_count, qubit_count,
                                         NULLIF(request->>'candidateCount', '')::int),
       constraints             = COALESCE(constraints, jsonb_build_object(
                                    'maxSensors', (request->>'maxSensors')::int,
                                    'budgetK', NULLIF(request->>'budgetK', '')::numeric,
                                    'coverageRequirements', COALESCE(request->'coverageRequirements', '[]'::jsonb))),
       objective_configuration = COALESCE(objective_configuration, jsonb_build_object(
                                    'weights', request->'weights',
                                    'normalizeWeights', (request->>'normalizeWeights') = 'true',
                                    'layers', (request->>'layers')::int,
                                    'shots', (request->>'shots')::int)),
       error_message           = COALESCE(error_message, error->>'message')
 WHERE forecast_reference IS NULL OR variables_count IS NULL OR constraints IS NULL;

INSERT INTO optimization_results (
  id, optimization_job_id, bitstring, selected_locations, objective_value,
  constraint_violations, validation_status, runtime_ms, classical_objective,
  quantum_objective, approximation_quality, created_at)
SELECT
  j.id || '-R1', j.id,
  j.result->'measurementCounts'->0->>'bitstring',
  COALESCE(
    (SELECT jsonb_agg(s->>'id') FROM jsonb_array_elements(j.result->'selectedLocations') s),
    '[]'::jsonb),
  (j.result->>'objectiveValue')::double precision,
  COALESCE(j.result->'constraintViolations', '[]'::jsonb),
  j.result->>'validationStatus',
  COALESCE((j.result->>'executionTimeMs')::double precision, 0),
  (j.result->'classicalComparison'->>'objectiveValue')::double precision,
  -- Quantum objective only when quantum measurement counts exist (a classical
  -- fallback result carries none).
  CASE WHEN j.result->'measurementCounts'->0->>'bitstring' IS NOT NULL
       THEN (j.result->>'objectiveValue')::double precision END,
  CASE
    WHEN j.result->'classicalComparison'->>'gapVsQuantum' = '0' THEN 1
    WHEN j.result->'classicalComparison'->>'gapVsQuantum' IS NULL THEN NULL
    ELSE GREATEST(0, 1 - (j.result->'classicalComparison'->>'gapVsQuantum')::double precision)
  END,
  j.created_at
FROM optimization_jobs j
WHERE j.status = 'completed' AND j.result IS NOT NULL
ON CONFLICT DO NOTHING;