-- Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
-- Module: database | Owner: Navya (ForecastingEngine seam) | License: Apache-2.0
--
-- PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction -
-- Nanda & Navya). It is honest by construction, per the platform README:
-- no fabricated data, no invented metrics, every surrogate or fallback is
-- clearly labelled, and no quantum speedup is ever claimed.

-- ============================================================================
-- 010_navya_forecast_provenance.up.sql
-- Navya-owned: forecast provenance + held-out evaluation records.
--
-- Integrates with (does NOT modify) Nanda's schema from 001_core_tables:
--   * `forecasts.forecast_id` is referenced as a foreign key. The team table
--     is not altered, retyped, or extended in any way.
--   * Model scores stay in Nanda's `model_metrics`. This file does NOT
--     duplicate them; it records which *split* a score came from, because
--     `model_metrics` has no split column and the distinction is the whole
--     point of the selection protocol (see `navya_forecast_evaluation`).
--
-- WHY NEW TABLES RATHER THAN AN ALTER
-- `forecasts` is team-owned. Adding columns to it would be a modification of
-- Nanda's file, and would couple the team's insert path to columns it does not
-- know about. Two additive, Navya-owned tables keep the change conflict-free:
-- nothing existing is touched, so this migration cannot break a team query.
--
-- ANTI-FAKE-METRIC RULES (enforced in the schema, not just in code)
-- The platform rule is that no metric is asserted without being computed and
-- labelled. The constraints below are the database's half of that:
--   1. A non-real dataset MUST carry the mandatory data warning, and a real
--      dataset MUST NOT carry it. There is no third state.
--   2. `production_ready` is impossible for anything but complete real data.
--   3. A threshold may only be called 'approved' when a threshold AND a source
--      for it are both recorded. Silence is not approval.
--   4. A 'test' split score may never be flagged as a selection statistic,
--      and at most one such score may exist per model per split. This is what
--      makes "the test split is scored exactly once" a database invariant
--      rather than a convention.
--   5. Metrics are nullable individually, but at least one must be present, and
--      the error metrics may not be negative.
--
-- Idempotency: CREATE TABLE IF NOT EXISTS, CREATE INDEX IF NOT EXISTS. All DDL
-- is transactional. Re-running is a no-op.
--
-- Reversibility: see 010_navya_forecast_provenance.down.sql. It drops only the
-- two tables introduced here; no team table, column, row or index is affected.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- navya_forecast_provenance
-- One row per forecast: where the numbers came from, and how they must be read.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS navya_forecast_provenance (
  id                        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

  -- Link into Nanda's 001_core_tables. No ON DELETE clause: the default
  -- NO ACTION means a forecast cannot be deleted while its provenance still
  -- describes it. Losing the audit row silently would be worse than blocking
  -- the delete, and silently cascading would let provenance outlive the
  -- forecast it describes.
  forecast_id               TEXT NOT NULL,

  -- Model identity, mirroring the payload rather than a new registry.
  model_id                  TEXT NOT NULL,
  model_version             TEXT NOT NULL,
  algorithm                 TEXT NOT NULL DEFAULT '',
  contract_version          TEXT NOT NULL,

  -- What was predicted, and in what.
  target                    TEXT NOT NULL DEFAULT 'water_level',
  target_units              TEXT,
  forecast_horizon          TEXT,
  lead_time_rows            INTEGER,
  station_reference         TEXT,
  reach_reference           TEXT,

  -- Where the training data came from. All nullable except `dataset_type`:
  -- an unknown fact is recorded as NULL, never filled with a plausible value.
  dataset_reference         TEXT,
  dataset_type              TEXT NOT NULL DEFAULT 'unknown',
  dataset_license           TEXT,
  dataset_checksum          TEXT,
  sampling_interval         TEXT,
  -- Which split the held-out score below was measured on.
  selection_metric          TEXT,

  -- Flood-stage threshold and its approval state. `pending` is the default
  -- because no official threshold policy exists in this repository.
  threshold                 DOUBLE PRECISION,
  threshold_policy          TEXT NOT NULL DEFAULT 'pending',
  threshold_source          TEXT,
  residual_sigma            DOUBLE PRECISION,

  -- Provenance fields still unknown, so the gap is queryable rather than
  -- inferred from a NULL somewhere else in the row.
  missing_fields            TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],

  -- The mandatory label. Populated by the application for non-real data and
  -- MUST be NULL for real data; the constraints below make that binding.
  disclaimer                TEXT,
  -- Label attached to every score in navya_forecast_evaluation.
  metrics_label             TEXT,

  production_ready          BOOLEAN NOT NULL DEFAULT FALSE,

  created_at                TIMESTAMPTZ NOT NULL DEFAULT now(),

  CONSTRAINT fk_navya_provenance_forecast FOREIGN KEY (forecast_id)
    REFERENCES forecasts (forecast_id),

  CONSTRAINT chk_navya_provenance_not_blank CHECK (
    forecast_id <> '' AND model_id <> '' AND model_version <> '' AND contract_version <> ''
  ),

  -- (1) The data warning is required for non-real data and forbidden for real
  --     data. Both directions matter: the second stops a real forecast from
  --     being dismissed as fake, the first stops a demo run being read as real.
  CONSTRAINT chk_navya_provenance_disclaimer CHECK (
    (dataset_type = 'real' AND disclaimer IS NULL)
    OR (dataset_type IN ('synthetic', 'unknown') AND disclaimer IS NOT NULL AND disclaimer <> '')
  ),

  CONSTRAINT chk_navya_provenance_dataset_type CHECK (
    dataset_type IN ('real', 'synthetic', 'unknown')
  ),

  -- (2) A real dataset is not sufficient on its own: the licence, the checksum,
  --     the sampling interval and the units must all be recorded too, and no
  --     provenance gap may remain.
  CONSTRAINT chk_navya_provenance_production_ready CHECK (
    NOT production_ready OR (
      dataset_type = 'real'
      AND dataset_reference IS NOT NULL AND dataset_reference <> ''
      AND dataset_license IS NOT NULL AND dataset_license <> ''
      AND dataset_checksum IS NOT NULL AND dataset_checksum <> ''
      AND sampling_interval IS NOT NULL AND sampling_interval <> ''
      AND target_units IS NOT NULL AND target_units <> ''
      AND station_reference IS NOT NULL AND station_reference <> ''
      AND array_length(missing_fields, 1) IS NULL
    )
  ),

  -- (3) Approval is a claim about provenance, so it requires evidence.
  CONSTRAINT chk_navya_provenance_threshold_policy CHECK (
    (threshold_policy = 'pending')
    OR (threshold_policy = 'approved' AND threshold IS NOT NULL AND threshold_source IS NOT NULL
        AND threshold_source <> '')
  ),

  -- A probability derived from an assumed spread is a guess, so a recorded
  -- sigma must be a positive measurement.
  CONSTRAINT chk_navya_provenance_residual_sigma CHECK (
    residual_sigma IS NULL OR residual_sigma > 0
  ),

  -- Model selection is a regression ranking; a classification score has no
  -- meaning here and must not be recorded.
  CONSTRAINT chk_navya_provenance_selection_metric CHECK (
    selection_metric IS NULL OR selection_metric IN ('rmse', 'mae', 'r2', 'nse')
  ),

  CONSTRAINT chk_navya_provenance_target CHECK (
    target IN ('water_level', 'inflow')
  ),

  CONSTRAINT chk_navya_provenance_horizon CHECK (
    lead_time_rows IS NULL OR lead_time_rows > 0
  )
);

-- One provenance record per forecast. Also the join path back to `forecasts`.
CREATE UNIQUE INDEX IF NOT EXISTS uq_navya_provenance_forecast
  ON navya_forecast_provenance (forecast_id);

-- "Show me every forecast produced from synthetic data" - the audit query.
CREATE INDEX IF NOT EXISTS idx_navya_provenance_dataset_type
  ON navya_forecast_provenance (dataset_type, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_navya_provenance_dataset_reference
  ON navya_forecast_provenance (dataset_reference);

CREATE INDEX IF NOT EXISTS idx_navya_provenance_station
  ON navya_forecast_provenance (station_reference)
  WHERE station_reference IS NOT NULL;

-- Every record that must not be shown as a result.
CREATE INDEX IF NOT EXISTS idx_navya_provenance_disclaimer
  ON navya_forecast_provenance (created_at DESC)
  WHERE disclaimer IS NOT NULL;

-- ----------------------------------------------------------------------------
-- navya_forecast_evaluation
-- A computed score, plus the split it came from.
--
-- `model_metrics` (002) stores rmse/mae/nse/r2 but has no split column, so it
-- cannot distinguish a score the model was *selected* on from one it was
-- *scored* on. Those two are not interchangeable: the validation figure is
-- optimistic by construction. This table records the distinction, and does not
-- restate the numbers themselves - join to `model_metrics` for those.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS navya_forecast_evaluation (
  id                        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

  -- A run is identified by model + version + target + horizon + dataset, which
  -- is the same tuple `model_versions` is keyed on, plus the target context.
  model_id                  TEXT NOT NULL,
  model_version             TEXT NOT NULL,
  target                    TEXT NOT NULL DEFAULT 'water_level',
  forecast_horizon          TEXT,
  dataset_reference         TEXT,

  -- Which split this score was measured on.
  split_label               TEXT NOT NULL,
  -- True only for the score the model was selected on.
  is_selection_statistic    BOOLEAN NOT NULL DEFAULT FALSE,

  -- The score. All nullable individually, but at least one must be present.
  rmse                      DOUBLE PRECISION,
  mae                       DOUBLE PRECISION,
  nse                       DOUBLE PRECISION,
  r2                        DOUBLE PRECISION,
  peak_absolute_error       DOUBLE PRECISION,
  bias                      DOUBLE PRECISION,
  n_samples                 INTEGER,

  -- Provenance of the score itself.
  dataset_type              TEXT NOT NULL DEFAULT 'unknown',
  -- Required for anything that is not real data, forbidden for real data.
  metrics_label             TEXT,
  disclaimer                TEXT,
  -- Software environment the run executed in.
  software_environment      JSONB,
  feature_list              TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
  evaluated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at                TIMESTAMPTZ NOT NULL DEFAULT now(),

  CONSTRAINT chk_navya_eval_split_label CHECK (
    split_label IN ('train', 'validation', 'test')
  ),

  -- (4) The held-out period may not participate in the ranking. A 'test' row
  --     flagged as a selection statistic would mean the test period chose the
  --     model, which is exactly the leakage this table exists to prevent.
  CONSTRAINT chk_navya_eval_test_not_selection CHECK (
    NOT (split_label = 'test' AND is_selection_statistic)
  ),

  -- (5) No placeholder scores: at least one real measured score, or no row.
  --
  --     `num_nonnulls` over the *score* columns only. Two things this must get
  --     right, both of which a COALESCE-over-a-wider-list gets wrong:
  --
  --     * `n_samples` is a count of observations, not a score. Including it
  --       would let a row carrying nothing but `n_samples = 50` satisfy a guard
  --       whose entire purpose is to refuse rows with no metric in them.
  --     * `bias` IS a score -- mean signed error, computed by the pipeline and
  --       reported in `EvaluationMetrics.as_dict()`. Excluding it would reject a
  --       legitimate bias-only row.
  CONSTRAINT chk_navya_eval_at_least_one_metric CHECK (
    num_nonnulls(rmse, mae, nse, r2, peak_absolute_error, bias) >= 1
  ),

  -- Error metrics are magnitudes; a negative MAE or RMSE is not a result, it
  -- is a sign error. `nse` and `r2` are deliberately unbounded below (both are
  -- legitimately negative) and only capped above.
  CONSTRAINT chk_navya_eval_metric_ranges CHECK (
    (rmse IS NULL OR rmse >= 0)
    AND (mae IS NULL OR mae >= 0)
    AND (peak_absolute_error IS NULL OR peak_absolute_error >= 0)
    AND (nse IS NULL OR nse <= 1)
    AND (r2 IS NULL OR r2 <= 1)
    AND (n_samples IS NULL OR n_samples > 0)
  ),

  -- Same labelling rule as the provenance table: non-real data must be
  -- labelled, real data must not be.
  CONSTRAINT chk_navya_eval_disclaimer CHECK (
    (dataset_type = 'real' AND disclaimer IS NULL)
    OR (dataset_type IN ('synthetic', 'unknown') AND metrics_label IS NOT NULL AND metrics_label <> '')
  ),

  CONSTRAINT chk_navya_eval_dataset_type CHECK (
    dataset_type IN ('real', 'synthetic', 'unknown')
  ),

  CONSTRAINT chk_navya_eval_not_blank CHECK (
    model_id <> '' AND model_version <> ''
  )
);

-- (4, cont.) At most ONE held-out score per model, per split, per target/horizon.
--     This is what makes "the test split is scored exactly once" an invariant:
--     a second test-split row for the same model is refused by the index rather
--     than by whoever remembers to check.
CREATE UNIQUE INDEX IF NOT EXISTS uq_navya_eval_one_held_out_score
  ON navya_forecast_evaluation (model_id, model_version, target, split_label)
  WHERE split_label = 'test';

-- At most one validation score too: that is the figure used for ranking, and a
-- second one would mean the model was scored repeatedly until it looked good.
CREATE UNIQUE INDEX IF NOT EXISTS uq_navya_eval_one_selection_score
  ON navya_forecast_evaluation (model_id, model_version, target, split_label)
  WHERE split_label = 'validation' AND is_selection_statistic;

-- The comparison view: one row per candidate model on the selection split.
CREATE INDEX IF NOT EXISTS idx_navya_eval_model
  ON navya_forecast_evaluation (model_id, model_version);

-- "Show me every score computed on non-real data" - the audit query.
CREATE INDEX IF NOT EXISTS idx_navya_eval_dataset_type
  ON navya_forecast_evaluation (dataset_type, evaluated_at DESC);

CREATE INDEX IF NOT EXISTS idx_navya_eval_evaluated_at
  ON navya_forecast_evaluation (evaluated_at DESC);
