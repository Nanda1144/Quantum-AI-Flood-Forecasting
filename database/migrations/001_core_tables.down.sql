-- Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
-- Module: database | Owner: Platform | License: Apache-2.0
--
-- PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction -
-- Nanda & Navya). It is honest by construction, per the platform README:
-- no fabricated data, no invented metrics, every surrogate or fallback is
-- clearly labelled, and no quantum speedup is ever claimed.

-- ============================================================================
-- 001_core_tables.down.sql
-- Reverses 001_core_tables.up.sql. Drop order respects foreign keys
-- (optimization_references -> forecasts).
-- ============================================================================

DROP TABLE IF EXISTS optimization_references;
DROP TABLE IF EXISTS models;
DROP TABLE IF EXISTS forecasts;