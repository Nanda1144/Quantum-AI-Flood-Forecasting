-- Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
-- Module: database | Owner: Nanda | License: Apache-2.0
--
-- PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction -
-- Nanda & Navya). It is honest by construction, per the platform README:
-- no fabricated data, no invented metrics, every surrogate or fallback is
-- clearly labelled, and no quantum speedup is ever claimed.

-- ============================================================================
-- 002_model_versioning.up.sql
-- Nanda-owned model registry: model_versions + model_metrics.
--
-- Integrates with (does NOT duplicate) the existing forecast storage from
-- 001_core_tables: forecasts.* is referenced via existing stable keys
-- (forecast_id, model_id, model_version) and any per-forecast metric tracing
-- joins model_versions.id -> forecasts.model_version.
--
-- Provenance: dataset_reference / model_artifact_reference / evaluation_dataset
-- preserve experiment lineage. Metric columns follow the repository's existing
-- convention (nse/rmse/mae as in backend's models table) plus r2/classification
-- scores where applicable.
--
-- Anti-fake-metric rules: metrics columns are NULLABLE; a row must carry at
-- least one score; every score is bounded to its physical range. Seed data is
-- development-marked and contains NO metric rows (see seeds/).
--
-- Idempotency: constraints are declared inline in CREATE TABLE (IF NOT EXISTS
-- skips existing tables), indexes use IF NOT EXISTS, triggers drop+recreate.
-- All DDL is transactional.
-- ============================================================================

-- Generic updated_at bump, shared by the registry tables below.
-- clock_timestamp() (not now()) so updated_at reflects real time even when the
-- surrounding transaction started earlier.
CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger AS $$
BEGIN
  NEW.updated_at = clock_timestamp();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TABLE IF NOT EXISTS model_versions (
  id                        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  model_name                TEXT NOT NULL,
  algorithm                 TEXT NOT NULL,
  version                   TEXT NOT NULL,
  dataset_reference         TEXT NOT NULL,
  model_artifact_reference  TEXT NOT NULL DEFAULT '',
  status                    TEXT NOT NULL DEFAULT 'development',
  training_started_at       TIMESTAMPTZ,
  training_completed_at     TIMESTAMPTZ,
  deployed_at               TIMESTAMPTZ,
  created_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT chk_model_versions_status CHECK (status IN ('active', 'retired', 'development')),
  CONSTRAINT chk_model_versions_not_blank CHECK (model_name <> '' AND algorithm <> '' AND version <> ''),
  CONSTRAINT chk_model_versions_time_order CHECK (
    (training_completed_at IS NULL OR training_started_at IS NULL OR training_completed_at >= training_started_at)
    AND (deployed_at IS NULL OR training_completed_at IS NULL OR deployed_at >= training_completed_at)
  )
);

-- A version must be unique within its model.
CREATE UNIQUE INDEX IF NOT EXISTS uq_model_versions_name_version
  ON model_versions (model_name, version);

-- Only one active version per model.
CREATE UNIQUE INDEX IF NOT EXISTS ux_model_versions_one_active_per_model
  ON model_versions (model_name)
  WHERE status = 'active';

-- Frequently queried registry fields.
CREATE INDEX IF NOT EXISTS idx_model_versions_name_status ON model_versions (model_name, status);
CREATE INDEX IF NOT EXISTS idx_model_versions_status ON model_versions (status);
CREATE INDEX IF NOT EXISTS idx_model_versions_updated_at ON model_versions (updated_at DESC);

CREATE TABLE IF NOT EXISTS model_metrics (
  id                 BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  model_version_id   BIGINT NOT NULL,
  rmse               DOUBLE PRECISION,
  mae                DOUBLE PRECISION,
  nse                DOUBLE PRECISION,
  r2                 DOUBLE PRECISION,
  accuracy           DOUBLE PRECISION,
  precision          DOUBLE PRECISION,
  recall             DOUBLE PRECISION,
  f1                 DOUBLE PRECISION,
  training_time_ms   BIGINT,
  inference_time_ms  BIGINT,
  evaluation_dataset TEXT NOT NULL DEFAULT 'default',
  evaluated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  -- model_metrics must reference model_versions.
  CONSTRAINT fk_model_metrics_version FOREIGN KEY (model_version_id)
    REFERENCES model_versions (id) ON DELETE CASCADE,
  CONSTRAINT chk_model_metrics_non_negative CHECK (
    (rmse IS NULL OR rmse >= 0)
    AND (mae IS NULL OR mae >= 0)
    AND (training_time_ms IS NULL OR training_time_ms >= 0)
    AND (inference_time_ms IS NULL OR inference_time_ms >= 0)
  ),
  CONSTRAINT chk_model_metrics_bounded CHECK (
    (accuracy IS NULL OR (accuracy >= 0 AND accuracy <= 1))
    AND (precision IS NULL OR (precision >= 0 AND precision <= 1))
    AND (recall IS NULL OR (recall >= 0 AND recall <= 1))
    AND (f1 IS NULL OR (f1 >= 0 AND f1 <= 1))
    AND (nse IS NULL OR nse <= 1)
    AND (r2 IS NULL OR r2 <= 1)
  ),
  CONSTRAINT chk_model_metrics_at_least_one CHECK (
    COALESCE(rmse, mae, nse, r2, accuracy, precision, recall, f1) IS NOT NULL
  )
);

CREATE INDEX IF NOT EXISTS idx_model_metrics_version ON model_metrics (model_version_id);
CREATE INDEX IF NOT EXISTS idx_model_metrics_evaluated_at ON model_metrics (evaluated_at DESC);

DROP TRIGGER IF EXISTS trg_model_versions_updated_at ON model_versions;
CREATE TRIGGER trg_model_versions_updated_at
  BEFORE UPDATE ON model_versions
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_model_metrics_updated_at ON model_metrics;
CREATE TRIGGER trg_model_metrics_updated_at
  BEFORE UPDATE ON model_metrics
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();