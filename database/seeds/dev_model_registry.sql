-- Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
-- Module: database | Owner: Platform | License: Apache-2.0
--
-- PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction -
-- Nanda & Navya). It is honest by construction, per the platform README:
-- no fabricated data, no invented metrics, every surrogate or fallback is
-- clearly labelled, and no quantum speedup is ever claimed.

-- ============================================================================
-- dev_model_registry.sql — DEVELOPMENT-ONLY SEED
-- ============================================================================
-- !!! DO NOT APPLY IN PRODUCTION !!!
--
-- This seed exists purely so a developer can exercise the model registry on a
-- local/staging database. Everything inserted here is explicitly marked as
-- development data:
--
--   * status = 'development'          — never 'active', so nothing reports as live.
--   * dataset_reference / model_artifact_reference = 'dev://...' — synthetic provenance.
--   * NO model_metrics rows are created. The repository policy is "no fake
--     metrics": seeded versions deliberately carry no scores, so they can never
--     be presented as real research results.
--
-- Idempotent: ON CONFLICT (model_name, version) DO NOTHING.
-- ============================================================================

INSERT INTO model_versions
  (model_name, algorithm, version, dataset_reference, model_artifact_reference,
   status, training_started_at, training_completed_at, deployed_at)
VALUES
  ('flood-gru-ensemble',  'GRU Ensemble',  'v0.9.0-dev',
   'dev://sample-data/catchment-east-2026', 'dev://sample-artifacts/flood-gru-ensemble-v0-9-0',
   'development', now() - interval '5 days', now() - interval '4 days', NULL),
  ('flood-lstm-baseline', 'LSTM',          'v0.3.1-dev',
   'dev://sample-data/catchment-west-2026', 'dev://sample-artifacts/flood-lstm-baseline-v0-3-1',
   'development', now() - interval '9 days', now() - interval '8 days', NULL)
ON CONFLICT (model_name, version) DO NOTHING;