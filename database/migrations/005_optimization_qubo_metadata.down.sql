-- Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
-- Module: database | Owner: Nanda | License: Apache-2.0
--
-- PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction -
-- Nanda & Navya). It is honest by construction, per the platform README:
-- no fabricated data, no invented metrics, every surrogate or fallback is
-- clearly labelled, and no quantum speedup is ever claimed.

-- ============================================================================
-- 005_optimization_qubo_metadata.down.sql
-- Reverts the QUBO metadata layer: drop the required indexes and the table.
-- The 003 optimization_jobs base table and the 004 persistence tables are
-- untouched. A completed job whose QUBO metadata row is dropped keeps its
-- operational record (the inline matrix remains in optimization_jobs.qubo),
-- so the down-migration is non-destructive to the experiment record itself.
-- ============================================================================

DROP INDEX IF EXISTS idx_optimization_qubo_metadata_created_at;
DROP INDEX IF EXISTS idx_optimization_qubo_metadata_job;
DROP TABLE IF EXISTS optimization_qubo_metadata;