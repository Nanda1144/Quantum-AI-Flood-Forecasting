-- Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
-- Module: database | Owner: Platform | License: Apache-2.0
--
-- PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction -
-- Nanda & Navya). It is honest by construction, per the platform README:
-- no fabricated data, no invented metrics, every surrogate or fallback is
-- clearly labelled, and no quantum speedup is ever claimed.

-- ============================================================================
-- dev_model_comparison.sql — DEVELOPMENT-ONLY SEED (model comparison page)
-- ============================================================================
-- !!! DO NOT APPLY IN PRODUCTION !!!
--
-- Purpose: give the "Model Comparison" page ~29 comparable model versions so
-- developers/operators can exercise the evaluation UI with real schema backing
-- (FK/constraints respected) instead of an empty registry.
--
-- Explicitness rules (kept honest on purpose):
--   * Every row is self-identified as development data:
--       - dataset_reference / model_artifact_reference = 'dev://comparison/...'
--       - evaluation_dataset                     = 'dev://comparison/eval/...'
--   * Metrics are SYNTHETIC demo scores for layout/testing only. They must
--     never be presented as real research results — the page shows exactly
--     whatever the backend returns.
--   * Only regression metrics are stored (rmse / mae / r2 / nse). The
--     classification columns (accuracy / precision / recall / f1) are left
--     NULL — no invented classification scores.
--   * Statuses follow the registry rules: at most one 'active' version per
--     model, older versions 'retired', in-flight versions 'development'.
--
-- Idempotent: re-running replaces only the 'dev://comparison/%' namespace.
-- ============================================================================

-- Rebuilding this seed's own namespace; never touches other data.
DELETE FROM model_metrics
  WHERE model_version_id IN (SELECT id FROM model_versions WHERE dataset_reference LIKE 'dev://comparison/%');
DELETE FROM model_versions WHERE dataset_reference LIKE 'dev://comparison/%';

WITH seed(model_name, algorithm, version, status, rmse, mae, r2, nse, training_ms, inference_ms, evaluated_at) AS (
  VALUES
    -- GRU-FloodNet — Gated Recurrent Unit Ensemble
    ('GRU-FloodNet',       'GRU Ensemble',            'v1.0',   'retired',      '0.452', '0.341', '0.844', '0.844', '16800000', '9',  '2026-08-03T10:00:00Z'),
    ('GRU-FloodNet',       'GRU Ensemble',            'v1.2',   'retired',      '0.411', '0.305', '0.862', '0.862', '17400000', '9',  '2026-08-12T10:00:00Z'),
    ('GRU-FloodNet',       'GRU Ensemble',            'v2.0',   'active',       '0.352', '0.261', '0.912', '0.912', '18100000', '8',  '2026-08-24T10:00:00Z'),
    ('GRU-FloodNet',       'GRU Ensemble',            'v2.1-dev', 'development', '0.331', '0.244', '0.921', '0.921', '18500000', '8',  '2026-09-08T10:00:00Z'),
    -- LSTM-Hydro — Long Short-Term Memory
    ('LSTM-Hydro',         'LSTM',                    'v1.0',   'retired',      '0.468', '0.356', '0.831', '0.831', '8600000',  '12', '2026-08-04T10:00:00Z'),
    ('LSTM-Hydro',         'LSTM',                    'v1.1',   'retired',      '0.432', '0.328', '0.852', '0.852', '8950000',  '12', '2026-08-14T10:00:00Z'),
    ('LSTM-Hydro',         'LSTM',                    'v1.3',   'retired',      '0.398', '0.301', '0.877', '0.877', '9200000',  '11', '2026-08-23T10:00:00Z'),
    ('LSTM-Hydro',         'LSTM',                    'v2.0',   'active',       '0.344', '0.258', '0.918', '0.918', '9600000',  '11', '2026-09-05T10:00:00Z'),
    -- XGBoost-Ensemble — Gradient Boosted Trees
    ('XGBoost-Ensemble',   'Gradient Boosted Trees',  'v1.0',   'retired',      '0.512', '0.388', '0.790', '0.790', '2100000',  '3',  '2026-08-05T10:00:00Z'),
    ('XGBoost-Ensemble',   'Gradient Boosted Trees',  'v1.4',   'retired',      '0.476', '0.362', '0.821', '0.821', '2300000',  '3',  '2026-08-16T10:00:00Z'),
    ('XGBoost-Ensemble',   'Gradient Boosted Trees',  'v2.0',   'active',       '0.421', '0.315', '0.862', '0.862', '2550000',  '3',  '2026-08-29T10:00:00Z'),
    ('XGBoost-Ensemble',   'Gradient Boosted Trees',  'v2.1-dev', 'development', '0.402', '0.298', '0.876', '0.876', '2620000',  '3',  '2026-09-11T10:00:00Z'),
    -- Deep-Transformer — Temporal Transformer
    ('Deep-Transformer',   'Temporal Transformer',    'v1.0',   'retired',      '0.291', '0.218', '0.932', '0.932', '14400000', '4',  '2026-08-06T10:00:00Z'),
    ('Deep-Transformer',   'Temporal Transformer',    'v1.1',   'active',       '0.171', '0.132', '0.972', '0.972', '14800000', '4',  '2026-08-21T10:00:00Z'),
    ('Deep-Transformer',   'Temporal Transformer',    'v1.2-dev', 'development', '0.158', '0.120', '0.977', '0.977', '15100000', '4',  '2026-09-03T10:00:00Z'),
    ('Deep-Transformer',   'Temporal Transformer',    'v2.0-dev', 'development', '0.149', '0.112', '0.979', '0.979', '15600000', '4',  '2026-09-13T10:00:00Z'),
    -- QEnhanced-LSTM — Quantum-Inspired LSTM
    ('QEnhanced-LSTM',     'Quantum-Inspired LSTM',   'v0.9',   'retired',      '0.238', '0.180', '0.944', '0.944', '21600000', '11', '2026-08-07T10:00:00Z'),
    ('QEnhanced-LSTM',     'Quantum-Inspired LSTM',   'v1.0',   'active',       '0.148', '0.114', '0.969', '0.969', '23100000', '10', '2026-08-28T10:00:00Z'),
    ('QEnhanced-LSTM',     'Quantum-Inspired LSTM',   'v1.1-dev', 'development', '0.137', '0.104', '0.974', '0.974', '23800000', '10', '2026-09-10T10:00:00Z'),
    -- CNN-Rainfall — 1D Temporal CNN
    ('CNN-Rainfall',       '1D Temporal CNN',         'v1.0',   'retired',      '0.531', '0.399', '0.751', '0.751', '2400000',  '3',  '2026-08-08T10:00:00Z'),
    ('CNN-Rainfall',       '1D Temporal CNN',         'v1.1',   'active',       '0.489', '0.371', '0.810', '0.810', '2550000',  '1',  '2026-08-25T10:00:00Z'),
    ('CNN-Rainfall',       '1D Temporal CNN',         'v2.0-dev', 'development', '0.458', '0.345', '0.834', '0.834', '2600000',  '1',  '2026-09-06T10:00:00Z'),
    ('CNN-Rainfall',       '1D Temporal CNN',         'v2.1-dev', 'development', '0.441', '0.332', '0.847', '0.847', '2680000',  '1',  '2026-09-14T10:00:00Z'),
    -- SARIMA-Baseline — Classical SARIMA
    ('SARIMA-Baseline',    'Classical SARIMA',        'v0.5',   'retired',      '0.621', '0.475', '0.632', '0.632', '45000',    '40', '2026-08-09T10:00:00Z'),
    ('SARIMA-Baseline',    'Classical SARIMA',        'v0.7',   'retired',      '0.583', '0.448', '0.689', '0.689', '50000',    '38', '2026-08-19T10:00:00Z'),
    ('SARIMA-Baseline',    'Classical SARIMA',        'v1.0',   'active',       '0.548', '0.419', '0.721', '0.721', '56000',    '35', '2026-09-01T10:00:00Z'),
    -- Prophet-Hybrid — Prophet + Residual Boosting
    ('Prophet-Hybrid',     'Prophet + Residual Boost', 'v0.9',  'retired',      '0.572', '0.437', '0.702', '0.702', '900000',   '7',  '2026-08-10T10:00:00Z'),
    ('Prophet-Hybrid',     'Prophet + Residual Boost', 'v1.0',  'active',       '0.514', '0.397', '0.763', '0.763', '1100000',  '6',  '2026-08-27T10:00:00Z'),
    ('Prophet-Hybrid',     'Prophet + Residual Boost', 'v1.1-dev', 'development', '0.493', '0.379', '0.782', '0.782', '1180000',  '6',  '2026-09-09T10:00:00Z')
),
versions AS (
  INSERT INTO model_versions
    (model_name, algorithm, version, dataset_reference, model_artifact_reference,
     status, training_started_at, training_completed_at, deployed_at)
  SELECT
    s.model_name, s.algorithm, s.version,
    'dev://comparison/training/panama-basin-2026',
    'dev://comparison/artifacts/' || s.model_name || '-' || s.version,
    s.status,
    -- Training ran during the preceding day (duration = training_ms).
    (s.evaluated_at::timestamptz - interval '1 day' - (s.training_ms::bigint || ' milliseconds')::interval),
    (s.evaluated_at::timestamptz - interval '1 day'),
    -- Active versions were deployed one day after their evaluation completed.
    CASE WHEN s.status = 'active' THEN s.evaluated_at::timestamptz + interval '1 day' END
  FROM seed s
  RETURNING id, model_name, version
)
INSERT INTO model_metrics
  (model_version_id, rmse, mae, nse, r2, training_time_ms, inference_time_ms,
   evaluation_dataset, evaluated_at)
SELECT
  v.id,
  s.rmse::double precision, s.mae::double precision,
  s.nse::double precision, s.r2::double precision,
  s.training_ms::bigint, s.inference_ms::bigint,
  'dev://comparison/eval/gatun-basin-2026',
  s.evaluated_at::timestamptz
FROM seed s
JOIN versions v ON v.model_name = s.model_name AND v.version = s.version;