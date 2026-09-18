-- ============================================================================
-- 001_core_tables.up.sql
-- Q-FLARE core persistence owned by the Node backend gateway.
--
-- These mirror the gateway's runtime bootstrap (`ensureSchema` in
-- backend/src/repositories/postgres/pool.ts), extracted so the schema has a
-- single reversible, reviewable source of truth in `database/migrations/`.
--
-- OWNERSHIP:
--   * forecasts                 — AI analytics forecast runs (backend-owned).
--   * models                    — legacy flat model registry (backend-owned).
--   * optimization_references   — quantum handoff references (backend-owned).
--
-- All DDL below is idempotent (IF NOT EXISTS) and transactional.
-- ============================================================================

CREATE TABLE IF NOT EXISTS forecasts (
  forecast_id          TEXT PRIMARY KEY,
  flood_probability    DOUBLE PRECISION NOT NULL,
  risk_level           TEXT NOT NULL,
  predicted_water_level DOUBLE PRECISION NOT NULL,
  forecast_horizon     TEXT NOT NULL,
  model_id             TEXT NOT NULL,
  model_name           TEXT NOT NULL,
  model_version        TEXT NOT NULL,
  prediction_timestamp TIMESTAMPTZ NOT NULL,
  status               TEXT NOT NULL,
  created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_forecasts_timestamp ON forecasts (prediction_timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_forecasts_risk ON forecasts (risk_level);
CREATE INDEX IF NOT EXISTS idx_forecasts_model ON forecasts (model_id);

CREATE TABLE IF NOT EXISTS models (
  model_id          TEXT PRIMARY KEY,
  name              TEXT NOT NULL,
  version           TEXT NOT NULL,
  algorithm         TEXT NOT NULL,
  status            TEXT NOT NULL,
  last_trained_at   TIMESTAMPTZ NOT NULL,
  last_evaluated_at TIMESTAMPTZ NOT NULL,
  rmse              DOUBLE PRECISION,
  mae               DOUBLE PRECISION,
  nse               DOUBLE PRECISION,
  accuracy          DOUBLE PRECISION,
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS optimization_references (
  id                            TEXT PRIMARY KEY,
  forecast_id                   TEXT UNIQUE NOT NULL REFERENCES forecasts (forecast_id),
  risk_score                    DOUBLE PRECISION NOT NULL,
  priority                      TEXT NOT NULL,
  candidate_locations_available BOOLEAN NOT NULL,
  resource_constraints_available BOOLEAN NOT NULL,
  ready                         BOOLEAN NOT NULL,
  created_at                    TIMESTAMPTZ NOT NULL DEFAULT now()
);