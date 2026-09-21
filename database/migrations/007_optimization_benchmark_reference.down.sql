-- Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
-- Module: database | Owner: Nanda | License: Apache-2.0
--
-- PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction -
-- Nanda & Navya). It is honest by construction, per the platform README:
-- no fabricated data, no invented metrics, every surrogate or fallback is
-- clearly labelled, and no quantum speedup is ever claimed.

-- ============================================================================
-- 007_optimization_benchmark_reference.down.sql
-- Reverses 007_optimization_benchmark_reference.up.sql.
-- ============================================================================

DROP INDEX IF EXISTS idx_optimization_results_created_at;

ALTER TABLE optimization_results DROP CONSTRAINT IF EXISTS chk_optimization_results_classical_solver;
ALTER TABLE optimization_results DROP CONSTRAINT IF EXISTS chk_optimization_results_approximation_basis;
ALTER TABLE optimization_results DROP CONSTRAINT IF EXISTS chk_optimization_results_approximation_ratio_non_negative;
ALTER TABLE optimization_results DROP CONSTRAINT IF EXISTS chk_optimization_results_approximation_invalid_reason;

ALTER TABLE optimization_results DROP COLUMN IF EXISTS classical_solver;
ALTER TABLE optimization_results DROP COLUMN IF EXISTS classical_runtime_ms;
ALTER TABLE optimization_results DROP COLUMN IF EXISTS approximation_ratio;
ALTER TABLE optimization_results DROP COLUMN IF EXISTS approximation_basis;
ALTER TABLE optimization_results DROP COLUMN IF EXISTS approximation_invalid_reason;
ALTER TABLE optimization_results DROP COLUMN IF EXISTS random_seed;