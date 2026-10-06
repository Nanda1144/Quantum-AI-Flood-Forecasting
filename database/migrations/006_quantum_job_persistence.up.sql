-- Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
-- Module: database | Owner: Nanda | License: Apache-2.0
--
-- PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction -
-- Nanda & Navya). It is honest by construction, per the platform README:
-- no fabricated data, no invented metrics, every surrogate or fallback is
-- clearly labelled, and no quantum speedup is ever claimed.

-- ============================================================================
-- 006_quantum_job_persistence.up.sql
-- Q-FLARE quantum job persistence layer (Nanda).
--
-- Operational record of every REAL quantum submission the platform drives
-- through the quantum FastAPI service. Written by the Nanda orchestration
-- backend, one row per quantum job actually created on the service side:
--
--   quantum_jobs     lifecycle of the submission: the owning pipeline job
--                    (optimization_job_id FK), what was asked for (algorithm,
--                    backend, execution_mode, shots, layers), the resolved
--                    qubit count, the status + audit timestamps
--                    (submitted/started/completed) and an error_code /
--                    error_message pair for terminal failures.
--
--   quantum_results  one normalized row per completed quantum job (id is
--                    always <quantum_job_id>-R1). Measurement counts are stored
--                    as plain JSON (never raw Qiskit/Python objects), and heavy
--                    circuit/metadata payloads are referenced through
--                    raw_metadata_reference instead of being embedded.
--
-- The simulator/hardware distinction is preserved on every row: execution_mode
-- is the mode of THAT submission (simulator | aer | ibm_hardware) and backend
-- is the backend requested for it. A retry ladder that falls back from
-- hardware to the simulator therefore produces one honest failed row
-- (aer/ibm_hardware) and one completed row (simulator) — never a mislabelled
-- single row.
--
-- No credentials are ever stored, and raw circuit objects are never persisted:
-- these tables carry configuration scalars, plain-JSON counts and artifact
-- references only.
--
-- No backfill is performed for jobs created before this migration: earlier the
-- platform did not persist quantum submission ids anywhere, so any reconstructed
-- row would fabricate data (pledge). Older jobs remain auditable from
-- optimization_jobs / optimization_results / optimization_qubo_metadata.
-- ============================================================================

CREATE TABLE IF NOT EXISTS quantum_jobs (
  id                   TEXT PRIMARY KEY,            -- real quantum-service job id (QJ-...)
  optimization_job_id  TEXT NOT NULL,               -- owning pipeline job (003)
  algorithm            TEXT NOT NULL,               -- qaoa
  backend              TEXT NOT NULL,               -- backend requested for this submission
  execution_mode       TEXT NOT NULL,               -- simulator | aer | ibm_hardware
  qubits               INTEGER,                     -- resolved once the run completes
  shots                INTEGER NOT NULL,
  layers               INTEGER NOT NULL,
  status               TEXT NOT NULL,               -- queued | running | completed | failed | cancelled
  submitted_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  started_at           TIMESTAMPTZ,
  completed_at         TIMESTAMPTZ,
  error_code           TEXT,
  error_message        TEXT,
  created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT fk_quantum_jobs_optimization_job FOREIGN KEY (optimization_job_id)
    REFERENCES optimization_jobs (id) ON DELETE CASCADE,
  CONSTRAINT chk_quantum_jobs_execution_mode CHECK (
    execution_mode IN ('simulator', 'aer', 'ibm_hardware')),
  CONSTRAINT chk_quantum_jobs_status CHECK (
    status IN ('queued', 'running', 'completed', 'failed', 'cancelled')),
  CONSTRAINT chk_quantum_jobs_timestamps CHECK (
    (started_at IS NULL OR started_at >= submitted_at)
    AND (completed_at IS NULL OR (started_at IS NOT NULL AND completed_at >= started_at)))
);

CREATE TABLE IF NOT EXISTS quantum_results (
  id                     TEXT PRIMARY KEY,          -- <quantum_job_id>-R1 (one per job)
  quantum_job_id         TEXT NOT NULL,
  bitstring              TEXT,                      -- decoded outcome
  counts                 JSONB,                     -- plain { "1010": 512, ... } measurement counts
  objective_value        DOUBLE PRECISION,
  runtime_ms             DOUBLE PRECISION NOT NULL DEFAULT 0,
  raw_metadata_reference TEXT,                      -- artifact reference; raw circuits never stored
  created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT fk_quantum_results_job FOREIGN KEY (quantum_job_id)
    REFERENCES quantum_jobs (id) ON DELETE CASCADE,
  CONSTRAINT chk_quantum_results_id_matches CHECK (id = quantum_job_id || '-R1')
);

-- 2. Required indexes (spec: optimization_job_id, quantum_job_id, status,
--    created_at). Jobs list by owning pipeline job and live-status reads filter
--    on status; result reads always key on quantum_job_id.
CREATE INDEX IF NOT EXISTS idx_quantum_jobs_optimization_job ON quantum_jobs (optimization_job_id);
CREATE INDEX IF NOT EXISTS idx_quantum_jobs_status           ON quantum_jobs (status);
CREATE INDEX IF NOT EXISTS idx_quantum_jobs_created_at       ON quantum_jobs (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_quantum_results_quantum_job   ON quantum_results (quantum_job_id);
CREATE INDEX IF NOT EXISTS idx_quantum_results_created_at    ON quantum_results (created_at DESC);