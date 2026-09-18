-- ============================================================================
-- 003_optimization_jobs.up.sql
-- Q-FLARE optimization orchestration backend (Nanda).
--
-- Operational record for the 15-step optimization pipeline. The heavy
-- payloads (validated request, pipeline steps, QUBO, classical benchmark, full
-- result) are stored as JSONB; the scalar columns mirror the public
-- GET /api/optimization/:id contract so status reads never deserialize blobs.
--
-- `owner` is the authenticated principal — the gateway enforces job ownership
-- on every read (only the owner or an admin may view a job).
-- ============================================================================

CREATE TABLE IF NOT EXISTS optimization_jobs (
  id                  TEXT PRIMARY KEY,
  owner               TEXT NOT NULL,
  status              TEXT NOT NULL,                    -- queued|running|completed|failed|timed_out
  problem_type        TEXT NOT NULL,
  request             JSONB NOT NULL,                   -- validated RunOptimizationRequest
  fallback_policy     TEXT NOT NULL DEFAULT 'retry_simulator',
  algorithm           TEXT NOT NULL,                    -- qaoa
  execution_mode      TEXT NOT NULL,                    -- requested mode (simulator|aer|ibm_hardware)
  execution_mode_used TEXT,                             -- mode actually used (post-fallback)
  backend             TEXT NOT NULL,                    -- requested backend
  backend_used        TEXT,                             -- backend actually used
  fallback_applied    BOOLEAN NOT NULL DEFAULT false,
  fallback_reason     TEXT,
  qubit_count         INTEGER,
  steps               JSONB NOT NULL DEFAULT '[]'::jsonb,  -- PipelineStep[]
  qubo                JSONB,                            -- QuboBuild {doc, linear, quadratic, penaltyScale}
  classical           JSONB,                            -- ClassicalComparison (always stored)
  result              JSONB,                            -- full OptimizationResult
  validation_status   TEXT,                             -- valid|invalid
  validation_summary  TEXT,
  error               JSONB,                            -- {code, message, details?}
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  started_at          TIMESTAMPTZ,
  completed_at        TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_optimization_jobs_status ON optimization_jobs (status);
CREATE INDEX IF NOT EXISTS idx_optimization_jobs_owner ON optimization_jobs (owner);
CREATE INDEX IF NOT EXISTS idx_optimization_jobs_created ON optimization_jobs (created_at DESC);