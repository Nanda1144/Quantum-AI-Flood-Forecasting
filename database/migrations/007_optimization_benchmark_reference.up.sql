-- Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
-- Module: database | Owner: Nanda | License: Apache-2.0
--
-- PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction -
-- Nanda & Navya). It is honest by construction, per the platform README:
-- no fabricated data, no invented metrics, every surrogate or fallback is
-- clearly labelled, and no quantum speedup is ever claimed.

-- ============================================================================
-- 007_optimization_benchmark_reference.up.sql
-- Q-FLARE classical benchmark reference on optimization_results (Nanda).
--
-- Extends the normalized result row (004/006) to carry the classical
-- benchmarking reference fields that were previously only nested inside the
-- job's `result` JSONB or recomputed on read:
--
--   classical_solver            exhaustive | greedy (the reference method)
--   classical_runtime_ms        measured wall time of the reference solver
--   approximation_ratio         direction-aware quantum/reference ratio,
--                               written ONCE at pipeline completion
--   approximation_basis         exact_optimal | greedy_reference — the basis
--                               the stored ratio is interpreted against
--   approximation_invalid_reason  why no ratio exists (or NULL)
--   random_seed                 the seed actually passed to the QAOA driver
--
-- No dedicated benchmark table is created: these five fields are the only
-- benchmark-contract values without a normalized home. Every other field of
-- a classical benchmark (classical/quantum objective, quantum runtime,
-- constraint violations, problem size, exact experiment configuration,
-- created_at) already persists in optimization_results,
-- optimization_results.constraint_violations, quantum_results.runtime_ms,
-- optimization_jobs.request/variables_count and optimization_results.created_at.
-- Duplicating them into a separate table would be redundancy, storing copies
-- instead of measured values.
--
-- The benchmark snapshot is WRITE-ONCE like the result row itself: the
-- repository upsert preserves any previously stored snapshot with COALESCE,
-- and the existing qflare_guard_optimization_delete trigger (004) already
-- blocks hard DELETEs of completed rows.
-- ============================================================================

ALTER TABLE optimization_results ADD COLUMN IF NOT EXISTS classical_solver             TEXT;
ALTER TABLE optimization_results ADD COLUMN IF NOT EXISTS classical_runtime_ms          DOUBLE PRECISION;
ALTER TABLE optimization_results ADD COLUMN IF NOT EXISTS approximation_ratio           DOUBLE PRECISION;
ALTER TABLE optimization_results ADD COLUMN IF NOT EXISTS approximation_basis           TEXT;
ALTER TABLE optimization_results ADD COLUMN IF NOT EXISTS approximation_invalid_reason  TEXT;
ALTER TABLE optimization_results ADD COLUMN IF NOT EXISTS random_seed                   BIGINT;

-- Reference solver names are the two the pipeline can actually run.
ALTER TABLE optimization_results DROP CONSTRAINT IF EXISTS chk_optimization_results_classical_solver;
ALTER TABLE optimization_results ADD CONSTRAINT chk_optimization_results_classical_solver CHECK (
  classical_solver IS NULL OR classical_solver IN ('exhaustive', 'greedy'));

-- The ratio basis names the reference that produced it; the two are never
-- conflated (exhaustive optimum vs greedy heuristic).
ALTER TABLE optimization_results DROP CONSTRAINT IF EXISTS chk_optimization_results_approximation_basis;
ALTER TABLE optimization_results ADD CONSTRAINT chk_optimization_results_approximation_basis CHECK (
  approximation_basis IS NULL OR approximation_basis IN ('exact_optimal', 'greedy_reference'));

-- The stored ratio is the RAW direction-aware quotient and is never clamped
-- (against a heuristic reference it may exceed 1.0), so only the lower bound
-- is constrained.
ALTER TABLE optimization_results DROP CONSTRAINT IF EXISTS chk_optimization_results_approximation_ratio_non_negative;
ALTER TABLE optimization_results ADD CONSTRAINT chk_optimization_results_approximation_ratio_non_negative CHECK (
  approximation_ratio IS NULL OR approximation_ratio >= 0);

-- A NULL ratio is only legitimate when an invalid-reason code says why.
ALTER TABLE optimization_results DROP CONSTRAINT IF EXISTS chk_optimization_results_approximation_invalid_reason;
ALTER TABLE optimization_results ADD CONSTRAINT chk_optimization_results_approximation_invalid_reason CHECK (
  approximation_invalid_reason IS NULL OR approximation_invalid_reason IN (
    'MISSING_CLASSICAL_REFERENCE',
    'MISSING_QUANTUM_OBJECTIVE',
    'OBJECTIVE_NOT_POSITIVE',
    'QUANTUM_OBJECTIVE_NEGATIVE'));

-- Ledger/benchmark ordering surface: completed experiments newest first.
CREATE INDEX IF NOT EXISTS idx_optimization_results_created_at ON optimization_results (created_at DESC);