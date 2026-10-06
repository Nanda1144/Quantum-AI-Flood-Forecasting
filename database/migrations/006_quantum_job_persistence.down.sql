-- Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
-- Module: database | Owner: Nanda | License: Apache-2.0
--
-- PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction -
-- Nanda & Navya). It is honest by construction, per the platform README:
-- no fabricated data, no invented metrics, every surrogate or fallback is
-- clearly labelled, and no quantum speedup is ever claimed.

-- Reversible: drops the quantum job persistence layer (results before jobs,
-- in FK order). The 003 optimization_jobs base table is untouched.
-- ============================================================================

DROP TABLE IF EXISTS quantum_results;
DROP TABLE IF EXISTS quantum_jobs;