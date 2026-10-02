-- Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
-- Module: database | Owner: Navya (ForecastingEngine seam) | License: Apache-2.0
--
-- PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction -
-- Nanda & Navya). It is honest by construction, per the platform README:
-- no fabricated data, no invented metrics, every surrogate or fallback is
-- clearly labelled, and no quantum speedup is ever claimed.

-- ============================================================================
-- 011_navya_hydro_observation_domains.down.sql
-- Reversal of 011_navya_hydro_observation_domains.up.sql.
--
-- Reversible by design: every object introduced by 011 is Navya-owned, and the
-- migration inserts no rows of its own, so dropping them restores the pre-011
-- schema exactly. Nothing from 001-010 is touched - no team table, column, row,
-- index, constraint, view or function belonging to another owner is altered or
-- dropped here.
--
-- Idempotency: `IF EXISTS` / `OR REPLACE` make a repeated rollback a no-op,
-- matching the up-migration's `IF NOT EXISTS` convention.
--
-- ORDER
-- Children before parents, for the two foreign-key relationships:
--   navya_observation_measurement -> navya_observation
--   navya_flood_event / navya_risk_score -> navya_dataset_catalog
-- `navya_risk_score` also references `navya_forecast_provenance` from 010, and
-- dropping 011 must NOT drop that table - only the rows in it that cite 010.
--
-- WHAT IS LOST, STATED PLAINLY
-- Any observation, measurement, flood event, risk score or quality report stored
-- by this migration is destroyed. That is the expected behaviour of a down
-- migration, but it is worth writing down rather than leaving to be discovered:
-- in an honest Phase 1 database these tables are empty, because 011 seeds
-- nothing and no real hydrological observation data exists in this repository.
-- ============================================================================

-- The audit view first: it reads navya_observation and is the one object a
-- query could otherwise be holding open when the tables below disappear.
DROP VIEW IF EXISTS navya_domain_availability;

-- Children before parents.
DROP TABLE IF EXISTS navya_observation_measurement;

-- The trigger goes with the function it calls. Dropping the table would drop the
-- trigger implicitly, but stating it keeps the reversal readable and safe to run
-- against a partially-created schema.
DROP TRIGGER IF EXISTS trg_navya_observation_has_measurement ON navya_observation;

DROP FUNCTION IF EXISTS navya_observation_has_measurement();

DROP TABLE IF EXISTS navya_observation;

DROP TABLE IF EXISTS navya_flood_event;

-- navya_risk_score references navya_forecast_provenance (010) and
-- navya_dataset_catalog (this migration). Dropping it removes neither.
DROP TABLE IF EXISTS navya_risk_score;

DROP TABLE IF EXISTS navya_data_quality_report;

-- Last: two tables above reference it.
DROP TABLE IF EXISTS navya_dataset_catalog;