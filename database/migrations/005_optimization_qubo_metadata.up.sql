-- Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
-- Module: database | Owner: Nanda | License: Apache-2.0
--
-- PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction -
-- Nanda & Navya). It is honest by construction, per the platform README:
-- no fabricated data, no invented metrics, every surrogate or fallback is
-- clearly labelled, and no quantum speedup is ever claimed.

-- ============================================================================
-- 005_optimization_qubo_metadata.up.sql
-- Q-FLARE QUBO metadata persistence layer (Nanda).
--
-- One row per job (qubo_id = <optimization_job_id>-Q1) carrying enough plain
-- JSON to reproduce and audit the optimization experiment. This table is a
-- record of WHAT the experiment was, not a cell-per-row relational dump of the
-- matrix (that would be excessive for small problems and untenable for large
-- ones) and never raw Python/Qiskit objects.
--
-- Storage strategy, keyed off `storage_mode`:
--
--   inline   small prototype/research problems (<= OPTIMIZATION_QUBO_INLINE_LIMIT
--            variables): the matrix, linear terms, quadratic terms, penalty
--            configuration and the objective expression are inlined as JSON.
--   artifact larger problems: only a reference + sha-256 checksum + matrix
--            dimensions + storage location + summary metadata are stored. The
--            matrix cells themselves live OUTSIDE the database (artifact store)
--            and are verified on read against the checksum.
--
-- Exactly one representation family is populated per row, enforced by the
-- chk_..._inline / chk_..._artifact constraints.
--
-- The RULE this table encodes:
--   * store enough to reproduce and audit the experiment;
--   * never store raw Python/Qiskit objects;
--   * never build a giant relational table with one row per QUBO matrix cell.
-- ============================================================================

CREATE TABLE IF NOT EXISTS optimization_qubo_metadata (
  qubo_id                 TEXT PRIMARY KEY,             -- <optimization_job_id>-Q1
  optimization_job_id     TEXT NOT NULL,
  storage_mode            TEXT NOT NULL,                -- inline | artifact

  -- Shared scalars.
  variable_count          INTEGER NOT NULL,

  -- Inline representation (small problems).
  matrix                  JSONB,                        -- plain matrix JSON, never Qiskit objects
  linear_terms            JSONB,                        -- number[] linear coefficients
  quadratic_terms         JSONB,                        -- number[][] upper-triangle coefficients
  penalty_configuration   JSONB,                        -- {penaltyScale, offset}
  objective_expression    TEXT,                         -- human-auditable objective string

  -- Artifact representation (large problems) — reference only, no matrix cells.
  artifact_reference      TEXT,                         -- logical artifact id
  checksum                TEXT,                         -- sha-256 hex of the canonical QUBO JSON
  matrix_dimensions       JSONB,                        -- {variables, rowCount, columnCount}
  storage_location        TEXT,                         -- where the matrix physically lives
  metadata                JSONB,                        -- reproducibility summary (algorithm, penalty scale, ...)

  created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),

  CONSTRAINT fk_optimization_qubo_metadata_job FOREIGN KEY (optimization_job_id)
    REFERENCES optimization_jobs (id) ON DELETE CASCADE,
  CONSTRAINT chk_optimization_qubo_metadata_id_matches CHECK (
    qubo_id = optimization_job_id || '-Q1'),
  CONSTRAINT chk_optimization_qubo_metadata_storage_mode CHECK (
    storage_mode IN ('inline', 'artifact')),
  CONSTRAINT chk_optimization_qubo_metadata_positive_variables CHECK (
    variable_count > 0),
  CONSTRAINT chk_optimization_qubo_metadata_inline CHECK (
    storage_mode <> 'inline'
    OR (matrix IS NOT NULL AND linear_terms IS NOT NULL AND quadratic_terms IS NOT NULL
        AND penalty_configuration IS NOT NULL AND objective_expression IS NOT NULL)),
  CONSTRAINT chk_optimization_qubo_metadata_artifact CHECK (
    storage_mode <> 'artifact'
    OR (artifact_reference IS NOT NULL AND checksum IS NOT NULL
        AND matrix_dimensions IS NOT NULL AND storage_location IS NOT NULL AND metadata IS NOT NULL))
);

-- 2. Required indexes: every metadata lookup keys on the owning job, and audit
--    reads list by creation time.
CREATE INDEX IF NOT EXISTS idx_optimization_qubo_metadata_job
  ON optimization_qubo_metadata (optimization_job_id);
CREATE INDEX IF NOT EXISTS idx_optimization_qubo_metadata_created_at
  ON optimization_qubo_metadata (created_at DESC);