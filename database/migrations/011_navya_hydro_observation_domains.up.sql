-- Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
-- Module: database | Owner: Navya (ForecastingEngine seam) | License: Apache-2.0
--
-- PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction -
-- Nanda & Navya). It is honest by construction, per the platform README:
-- no fabricated data, no invented metrics, every surrogate or fallback is
-- clearly labelled, and no quantum speedup is ever claimed.

-- ============================================================================
-- 011_navya_hydro_observation_domains.up.sql
-- Navya-owned: record-level storage for the Phase 1 data domains.
--
-- This is the storage half of the Phase 1 foundation implemented in
-- `ai-service/app/engines/hydro/{domains,quality,datasets}.py`. Those modules
-- define what one record of each domain is; this file gives each one a table
-- and a set of constraints, so a schema that is only enforced in Python can
-- still be bypassed by a direct INSERT.
--
-- Integrates with (does NOT modify) the team schema and with 010:
--   * `navya_forecast_provenance(forecast_id)` from 010 is referenced as a
--     foreign key by `navya_risk_score`. Neither table is altered here.
--   * No team table is created, altered, retyped, indexed or dropped. Migrations
--     001-009 are not touched, and no column is added to anything a team insert
--     path writes to.
--
-- WHY NEW TABLES RATHER THAN AN ALTER
-- The same reasoning as 010: the team's `forecasts` table is not ours to change,
-- and coupling the team's insert path to columns it does not know about creates
-- a merge conflict on every future phase. Everything here is additive.
--
-- ANTI-FABRICATION RULES (enforced in the schema, not just in code)
--   1. Every observation carries `dataset_type` from the three-value vocabulary,
--      and a non-real record MUST carry the mandatory warning while a real one
--      MUST NOT. There is no third state. This mirrors
--      chk_navya_provenance_disclaimer in 010 rather than inventing a variant.
--   2. A measurement value must be finite. PostgreSQL accepts 'NaN'::float8 and
--      stores it, so `value <> 'NaN'` is NOT sufficient on its own; infinity must
--      be excluded explicitly. An unreadable value is a quality_status, not a row.
--   3. A measurement must declare its unit. An unlabelled number cannot be
--      compared, converted or audited. The unit is NOT checked against a
--      whitelist: this repository has no authority over which units a foreign
--      dataset uses, and an unrecognised unit is a warning, not a rejection.
--   4. A timestamp must carry an explicit zone. `observed_at` is TIMESTAMPTZ,
--      and a naive input is interpreted in the session TimeZone at insert time -
--      exactly the silent offset shift this schema exists to prevent. Callers
--      must pass an offset; `domains.parse_instant` refuses a naive string before
--      it ever reaches here.
--   5. A duplicate identity is refused by a UNIQUE index rather than left for a
--      convention. A *conflict* (same identity, different values) is deliberately
--      NOT refused and NOT resolved: it is a question for the dataset owner, and
--      this schema does not pick a winner.
--   6. A risk score in [0, 1] with no score at all is different from a score of
--      zero, so an unassessed area stays NULL with status 'pending' rather than
--      defaulting to 0. An unassessed area is not a safe area.
--   7. `threshold_policy = 'approved'` requires a threshold AND a source for it.
--      Silence is not approval - same rule as 010.
--   8. A quality report may not claim a clean batch it did not check: the counts
--      must add up, and 'ok' requires zero rejected records.
--
-- NO FABRICATED CONTENT
-- This migration creates empty tables. It inserts no rainfall, level, discharge,
-- inflow, station identifier, threshold, coordinate, population figure or flood
-- event. `navya_dataset_catalog` is seeded with nothing; the committed synthetic
-- sample is described by `datasets.synthetic_sample_descriptor()`, and populating
-- a table from that file is an application decision, not a schema one.
--
-- Idempotency: CREATE TABLE / INDEX / VIEW IF NOT EXISTS. All DDL is
-- transactional. Re-running is a no-op.
--
-- Reversibility: see 011_navya_hydro_observation_domains.down.sql. It drops only
-- the objects introduced here.
--
-- VERIFICATION STATUS - READ THIS
-- This file has been statically reviewed (see
-- `ai-service/tests/test_hydro_phase1_migration.py`) and NOT executed. No
-- PostgreSQL server or `psql` binary was available in the Phase 1 environment.
-- Migration 010 records a live run against a local server in
-- 02_Architecture/ASSUMPTIONS_AND_LIMITATIONS.md; no comparable claim is made
-- here, because none was earned. Anyone applying this migration must run it
-- against a real instance and treat that run, not these tests, as the
-- verification.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- navya_dataset_catalog
-- What a dataset is and which domains it covers.
--
-- This exists because a missing domain is otherwise invisible: nothing breaks,
-- the pipeline trains on whatever was supplied, and the omission surfaces months
-- later as an unexplained gap. Here it is a row.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS navya_dataset_catalog (
  id                        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

  -- Stable identifier for the dataset. NOT NULL because a dataset nobody can
  -- name cannot be audited or excluded from a training run.
  dataset_reference         TEXT NOT NULL,

  -- 'real' | 'synthetic' | 'unknown'. Defaults to 'unknown' because asserting a
  -- type nobody declared is the failure this whole project is built to prevent.
  dataset_type              TEXT NOT NULL DEFAULT 'unknown',
  dataset_license           TEXT,
  dataset_checksum          TEXT,
  sampling_interval         TEXT,
  -- NULL in the committed synthetic sample: that file has no station column, and
  -- inventing a gauge identity for it would promote a config placeholder into a
  -- property of the data.
  station_reference         TEXT,
  source_organisation       TEXT,
  location_kind             TEXT,

  -- Domain coverage as JSONB: one {"domain", "status", "record_count", "units",
  -- "notes"} object per domain, exactly as `datasets.coverage_matrix()` emits.
  -- status is 'available' | 'absent' | 'unknown'. 'absent' is a fact (this
  -- source affirmatively does not carry the domain); 'unknown' is the absence of
  -- a fact, and the two are not interchangeable.
  domain_coverage           JSONB NOT NULL DEFAULT '[]'::JSONB,

  -- Human-supplied facts that are still unknown, so the gap is queryable rather
  -- than inferred from a NULL elsewhere in the row.
  missing_fields            TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],

  -- The mandatory label. Same rule as 010, byte for byte in intent.
  disclaimer                TEXT,

  -- Schema version of the descriptor, so a stored row can be read back with the
  -- schema it was written against.
  schema_version            TEXT NOT NULL DEFAULT 'navya-hydro-schema/v1',
  described_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
  notes                     TEXT NOT NULL DEFAULT '',

  CONSTRAINT chk_navya_dataset_catalog_reference CHECK (
    dataset_reference <> ''
  ),

  CONSTRAINT chk_navya_dataset_catalog_type CHECK (
    dataset_type IN ('real', 'synthetic', 'unknown')
  ),

  -- (1) Non-real data must be labelled; real data must not be. The second
  --     direction matters as much as the first: a genuine observation dismissed
  --     as fake is its own kind of dishonesty.
  CONSTRAINT chk_navya_dataset_catalog_disclaimer CHECK (
    (dataset_type = 'real' AND disclaimer IS NULL)
    OR (dataset_type IN ('synthetic', 'unknown') AND disclaimer IS NOT NULL AND disclaimer <> '')
  ),

  -- Coverage that is not an array of objects is not coverage. This catches a
  -- truncated or hand-edited JSONB column, which would otherwise read as
  -- "no domains declared" instead of "this row is malformed".
  CONSTRAINT chk_navya_dataset_catalog_coverage CHECK (
    jsonb_typeof(domain_coverage) = 'array'
  )
);

-- One row per dataset reference. Re-registering the same dataset with different
-- coverage is a mistake worth refusing, not a silent overwrite.
CREATE UNIQUE INDEX IF NOT EXISTS uq_navya_dataset_catalog_reference
  ON navya_dataset_catalog (dataset_reference);

-- "Which datasets are synthetic?" - the audit query run before every report.
CREATE INDEX IF NOT EXISTS idx_navya_dataset_catalog_type
  ON navya_dataset_catalog (dataset_type, described_at DESC);

CREATE INDEX IF NOT EXISTS idx_navya_dataset_catalog_disclaimer
  ON navya_dataset_catalog (described_at DESC)
  WHERE disclaimer IS NOT NULL;

-- ----------------------------------------------------------------------------
-- navya_observation
-- One record for one domain, at one location, at one instant.
--
-- Domains: weather, rainfall, water_level, discharge, inflow. `flood_event` and
-- `risk_score` do not carry measurements and live in their own tables below.
--
-- The domain/quantity pairing is enforced in `navya_observation_measurement`
-- rather than here, because a row-per-measurement design is what makes the check
-- possible at all; see the comment on that table's constraint.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS navya_observation (
  id                        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

  -- Identity for duplicate detection: domain + location + instant. Reported by
  -- `quality.check_observation_collection`; enforced by uq_navya_observation_identity.
  domain                    TEXT NOT NULL,
  -- A station, a reach or a catchment. NOT NULL and non-blank: an observation
  -- that cannot be attributed to a place cannot be used for anything, and a NULL
  -- here would be an unusable row masquerading as a gap.
  location_reference        TEXT NOT NULL,

  -- TIMESTAMPTZ, deliberately. A naive timestamp is interpreted in the session
  -- TimeZone at insert time, which is how a series silently shifts by an offset
  -- and every downstream chronological boundary becomes wrong with nothing to
  -- report it. Callers pass an explicit offset (domains.parse_instant refuses a
  -- naive string before it reaches here).
  observed_at               TIMESTAMPTZ NOT NULL,

  -- The interval a rate was measured over, e.g. '1h'. Required for a per-hour
  -- rainfall intensity, because a rate without a window cannot be accumulated
  -- unambiguously. Accumulation itself is Phase 3 work and is NOT computed here.
  measurement_window        TEXT,

  source_reference          TEXT,
  provenance_reference      TEXT,
  dataset_reference         TEXT,

  dataset_type              TEXT NOT NULL DEFAULT 'unknown',
  -- Record-level quality, orthogonal to provenance: a value can be perfectly
  -- well-attributed and still be 'suspect'. Defaults to 'unknown' because
  -- asserting 'ok' without having checked is a claim this schema cannot support.
  quality_status            TEXT NOT NULL DEFAULT 'unknown',
  -- 'missing' is a declared absence by the supplier, which is a different fact
  -- from a NULL column.
  quality_note              TEXT,

  -- The mandatory label. Same rule as 010.
  disclaimer                TEXT,

  notes                     TEXT NOT NULL DEFAULT '',
  created_at                TIMESTAMPTZ NOT NULL DEFAULT now(),

  CONSTRAINT fk_navya_observation_dataset FOREIGN KEY (dataset_reference)
    REFERENCES navya_dataset_catalog (dataset_reference),

  CONSTRAINT chk_navya_observation_domain CHECK (
    domain IN ('weather', 'rainfall', 'water_level', 'discharge', 'inflow')
  ),

  CONSTRAINT chk_navya_observation_not_blank CHECK (
    location_reference <> ''
  ),

  CONSTRAINT chk_navya_observation_dataset_type CHECK (
    dataset_type IN ('real', 'synthetic', 'unknown')
  ),

  -- (1) Same labelling rule as 010, restated because a per-domain table is a
  --     second place this could be got wrong.
  CONSTRAINT chk_navya_observation_disclaimer CHECK (
    (dataset_type = 'real' AND disclaimer IS NULL)
    OR (dataset_type IN ('synthetic', 'unknown') AND disclaimer IS NOT NULL AND disclaimer <> '')
  ),

  -- Mirrors domains.QUALITY_STATUSES exactly. Adding a value here means adding
  -- it to the Python vocabulary too, and the two are asserted equal in
  -- `tests/test_hydro_domains.py` / `test_hydro_phase1_migration.py`.
  CONSTRAINT chk_navya_observation_quality_status CHECK (
    quality_status IN ('ok', 'suspect', 'missing', 'rejected', 'unknown')
  ),

  -- A record with no measurement row cannot be an observation; the
  -- NOT EXISTS guard below covers the reverse direction, and this constraint
  -- covers the empty-string case that a CHECK on <> '' would miss.
  CONSTRAINT chk_navya_observation_window_not_blank CHECK (
    measurement_window IS NULL OR measurement_window <> ''
  )
);

-- Duplicate identity is refused by the database, not by convention. Two rows
-- with the same domain + location + instant and IDENTICAL values are a
-- re-import; two with DIFFERENT values are a conflict, and this index refuses
-- both rather than letting either reach storage. A conflict is still reported
-- as a finding by `quality.check_observation_collection` - this index makes it
-- impossible to *store* one, it does not decide which reading was right.
CREATE UNIQUE INDEX IF NOT EXISTS uq_navya_observation_identity
  ON navya_observation (domain, location_reference, observed_at);

-- The common query: one series, in time order, for one domain.
CREATE INDEX IF NOT EXISTS idx_navya_observation_series
  ON navya_observation (domain, location_reference, observed_at DESC);

CREATE INDEX IF NOT EXISTS idx_navya_observation_dataset
  ON navya_observation (dataset_reference)
  WHERE dataset_reference IS NOT NULL;

-- "Show me every record that must not be presented as a result."
CREATE INDEX IF NOT EXISTS idx_navya_observation_disclaimer
  ON navya_observation (created_at DESC)
  WHERE disclaimer IS NOT NULL;

-- ----------------------------------------------------------------------------
-- navya_observation_measurement
-- The quantities of one observation.
--
-- One row per quantity rather than one wide row per domain, because the units
-- differ per quantity and a record with mixed units cannot be compared or
-- converted without the reader re-parsing it. It also makes the domain/quantity
-- pairing checkable: a single CHECK on the parent cannot see the child's values.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS navya_observation_measurement (
  id                        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

  observation_id            BIGINT NOT NULL,

  -- e.g. 'water_level', 'rainfall', 'inflow', or a declared weather quantity
  -- such as 'temperature'. NOT NULL because a number with no name is not a
  -- measurement of anything.
  quantity                  TEXT NOT NULL,

  -- (2) A measurement value must be a finite real number. This is two checks,
  --     not one, and the second is not optional: PostgreSQL accepts 'NaN'::float8
  --     and stores it faithfully, and `value <> 'NaN'` is TRUE for both +Infinity
  --     and -Infinity. So NaN is excluded by name and infinity by range.
  value                     DOUBLE PRECISION NOT NULL,

  -- (3) A unit must be present. Deliberately NOT whitelisted: 'cusecs', 'ft' and
  --     an honest 'UNDETERMINED (DEMO - no unit assigned)' are all legitimate
  --     strings, and an unrecognised unit is a quality WARNING, never a rejection.
  unit                      TEXT NOT NULL,

  -- The interval a rate was measured over, repeated on the measurement row so the
  -- rate/window pairing is checkable without a join back to the parent.
  measurement_window        TEXT,

  -- True when this quantity is a per-hour rate rather than an amount. Recorded
  -- rather than inferred, so a reader never has to re-parse the unit string.
  is_rate                   BOOLEAN NOT NULL DEFAULT FALSE,

  notes                     TEXT NOT NULL DEFAULT '',

  -- No ON DELETE CASCADE: deleting an observation must not silently delete the
  -- evidence of what it contained. A cascade here would let a measurement
  -- disappear from the record while the quality report still refers to it.
  CONSTRAINT fk_navya_measurement_observation FOREIGN KEY (observation_id)
    REFERENCES navya_observation (id) ON DELETE RESTRICT,

  CONSTRAINT chk_navya_measurement_not_blank CHECK (
    quantity <> '' AND unit <> ''
  ),

  -- NaN, excluded by name: `value <> 'NaN'` evaluates TRUE for infinity, so the
  -- range check below is a separate and necessary half of this rule.
  CONSTRAINT chk_navya_measurement_value_finite CHECK (
    value <> 'NaN'::DOUBLE PRECISION
  ),

  CONSTRAINT chk_navya_measurement_value_range CHECK (
    value > '-Infinity'::DOUBLE PRECISION AND value < 'Infinity'::DOUBLE PRECISION
  ),

  -- A rate whose window was never declared cannot be accumulated later without
  -- ambiguity. Accumulation itself is Phase 3 work and is NOT done here.
  CONSTRAINT chk_navya_measurement_rate_window CHECK (
    NOT is_rate OR (measurement_window IS NOT NULL AND measurement_window <> '')
  )
);

-- One value per quantity per observation. Two values for one quantity at one
-- instant are ambiguous, and a row-per-measurement design is what makes this
-- expressible at all.
CREATE UNIQUE INDEX IF NOT EXISTS uq_navya_measurement_quantity
  ON navya_observation_measurement (observation_id, quantity);

-- (2, cont.) An observation with no measurement row is not an observation.
--
--      This CANNOT be a CHECK constraint, and the reason is worth recording
--      because it is a PostgreSQL rule rather than a style choice: CHECK
--      constraints may not contain subqueries, and they run per-row with no
--      visibility of child rows. So "this parent has at least one child" is not
--      expressible as CHECK. `Observation.__post_init__` already refuses an empty
--      measurement set in the application; the trigger below is the database's
--      half, for an INSERT that bypasses the application layer.
--
--      It is DEFERRABLE INITIALLY DEFERRED on purpose. A parent row is inserted
--      before its measurements exist, so an immediate trigger would reject every
--      legitimate ingest; deferring to COMMIT is what makes "insert the parent
--      and its measurements in one transaction" the enforced requirement. An
--      incomplete transaction rolls back as a unit, so nothing partial survives.
--
--      Not enforced by this trigger: deleting a measurement row out from under a
--      stored observation. An observation is treated as immutable once written,
--      and that is an application-level convention rather than a database
--      invariant. It is stated here rather than left for a reader to assume.
CREATE OR REPLACE FUNCTION navya_observation_has_measurement()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM navya_observation_measurement AS m
    WHERE m.observation_id = NEW.id
  ) THEN
    RAISE EXCEPTION
      'navya_observation % (% at %) has no measurement row; an empty measurement set is a gap, not a reading',
      NEW.id, NEW.location_reference, NEW.observed_at
      USING ERRCODE = '23514';
  END IF;
  RETURN NULL;
END;
$$;

DROP TRIGGER IF EXISTS trg_navya_observation_has_measurement ON navya_observation;

CREATE CONSTRAINT TRIGGER trg_navya_observation_has_measurement
AFTER INSERT OR UPDATE ON navya_observation
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW
EXECUTE FUNCTION navya_observation_has_measurement();

-- ----------------------------------------------------------------------------
-- navya_flood_event
-- One flood occurrence at one area.
--
-- THIS TABLE IS EMPTY AND STAYS EMPTY UNTIL SOMEONE SUPPLIES A REGISTER. No
-- flood event has been invented to populate it. It exists so that "this
-- repository has no event register" is a queryable fact rather than a
-- vocabulary that was never written down.
--
-- `severity` is free TEXT, not an enum. There is no approved severity scale in
-- this project, and inventing one would present this project's guess as a
-- standard. `severity_source` names the authority a real register used.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS navya_flood_event (
  id                        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

  event_reference           TEXT NOT NULL,
  area_reference            TEXT NOT NULL,

  started_at                TIMESTAMPTZ NOT NULL,
  -- NULL means "no end was recorded", which is NOT the same as "the flood is
  -- still happening". Keeping them distinct matters when someone reads this
  -- table to decide whether to issue a warning.
  ended_at                  TIMESTAMPTZ,

  severity                  TEXT,
  severity_source           TEXT,
  status                    TEXT NOT NULL DEFAULT 'unknown',

  source_reference          TEXT,
  provenance_reference      TEXT,
  dataset_reference         TEXT,

  dataset_type              TEXT NOT NULL DEFAULT 'unknown',
  disclaimer                TEXT,
  notes                     TEXT NOT NULL DEFAULT '',

  created_at                TIMESTAMPTZ NOT NULL DEFAULT now(),

  CONSTRAINT fk_navya_flood_event_dataset FOREIGN KEY (dataset_reference)
    REFERENCES navya_dataset_catalog (dataset_reference),

  CONSTRAINT chk_navya_flood_event_reference CHECK (
    event_reference <> '' AND area_reference <> ''
  ),

  -- An event that ends before it begins is not a shortened event; it is a
  -- transcription error, and storing it would corrupt every duration computed
  -- from this table.
  CONSTRAINT chk_navya_flood_event_window CHECK (
    ended_at IS NULL OR ended_at >= started_at
  ),

  CONSTRAINT chk_navya_flood_event_dataset_type CHECK (
    dataset_type IN ('real', 'synthetic', 'unknown')
  ),

  CONSTRAINT chk_navya_flood_event_disclaimer CHECK (
    (dataset_type = 'real' AND disclaimer IS NULL)
    OR (dataset_type IN ('synthetic', 'unknown') AND disclaimer IS NOT NULL AND disclaimer <> '')
  ),

  -- Free text by design; see the table comment. Only 'unknown' is fixed, because
  -- it is this schema's own word for "not recorded", not a value from any source.
  CONSTRAINT chk_navya_flood_event_status CHECK (
    status <> ''
  )
);

-- Two records claiming one event reference are either a duplicate import or a
-- genuine disagreement about what happened. The identity index refuses the
-- second at storage; `quality.check_flood_events` reports both as findings.
CREATE UNIQUE INDEX IF NOT EXISTS uq_navya_flood_event_reference
  ON navya_flood_event (event_reference);

CREATE INDEX IF NOT EXISTS idx_navya_flood_event_area
  ON navya_flood_event (area_reference, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_navya_flood_event_window
  ON navya_flood_event (started_at, ended_at);

-- ----------------------------------------------------------------------------
-- navya_risk_score
-- One assessed area, optionally attributable to a forecast.
--
-- Schema only. The risk ENGINE is Phase 6, and the exposure model that would put
-- a population or an asset behind a score does not exist in this repository. So
-- this table carries NO population column, NO asset count, NO coordinates and NO
-- elevation, and nothing populates those fields, because nothing knows them.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS navya_risk_score (
  id                        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

  area_reference            TEXT NOT NULL,

  -- (6) NULL means "not assessed". A score of 0.0 would mean "assessed, no
  --     risk", which is a different and much stronger claim. An unassessed area
  --     is not a safe area.
  risk_score                DOUBLE PRECISION CHECK (
                                risk_score IS NULL
                                OR (risk_score >= 0.0 AND risk_score <= 1.0)
                              ),

  -- Reuses the platform vocabulary from contract.py rather than a new list, so
  -- the two cannot drift. NULL while the score is NULL.
  risk_level                TEXT,

  -- Lifecycle of THIS record. Deliberately not the forecast's status vocabulary
  -- ('completed'/'pending'/'failed'): that describes a forecast, and borrowing it
  -- would conflate "the forecast failed" with "the assessment was not made".
  status                    TEXT NOT NULL DEFAULT 'pending',

  -- Nullable FK into 010. A risk record may legitimately exist with no forecast
  -- behind it (a manual assessment), so this is nullable rather than required.
  forecast_reference        TEXT,

  assessed_at               TIMESTAMPTZ,
  threshold                 DOUBLE PRECISION,
  -- 'pending' | 'approved'.
  threshold_policy          TEXT NOT NULL DEFAULT 'pending',
  threshold_source          TEXT,

  provenance_reference      TEXT,
  dataset_reference         TEXT,

  dataset_type              TEXT NOT NULL DEFAULT 'unknown',
  disclaimer                TEXT,
  notes                     TEXT NOT NULL DEFAULT '',

  created_at                TIMESTAMPTZ NOT NULL DEFAULT now(),

  -- No ON DELETE clause: the default NO ACTION means a forecast cannot be
  -- deleted while a risk score still cites it. Same reasoning as 010's FK.
  CONSTRAINT fk_navya_risk_score_forecast FOREIGN KEY (forecast_reference)
    REFERENCES navya_forecast_provenance (forecast_id),

  CONSTRAINT fk_navya_risk_score_dataset FOREIGN KEY (dataset_reference)
    REFERENCES navya_dataset_catalog (dataset_reference),

  CONSTRAINT chk_navya_risk_score_area CHECK (
    area_reference <> ''
  ),

  CONSTRAINT chk_navya_risk_score_status CHECK (
    status IN ('pending', 'recorded', 'withheld')
  ),

  -- Mirrors contract.SUPPORTED_RISK_LEVELS verbatim, including its UPPERCASE
  -- spelling. Asserted equal to the Python tuple by the Phase 1 migration test,
  -- so this list and that one cannot drift apart unnoticed.
  CONSTRAINT chk_navya_risk_score_level CHECK (
    risk_level IS NULL OR risk_level IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')
  ),

  CONSTRAINT chk_navya_risk_score_dataset_type CHECK (
    dataset_type IN ('real', 'synthetic', 'unknown')
  ),

  CONSTRAINT chk_navya_risk_score_disclaimer CHECK (
    (dataset_type = 'real' AND disclaimer IS NULL)
    OR (dataset_type IN ('synthetic', 'unknown') AND disclaimer IS NOT NULL AND disclaimer <> '')
  ),

  -- NaN must be excluded by name here too: `risk_score >= 0.0` is FALSE for NaN,
  -- so the range check already refuses it, but an explicit statement of intent
  -- costs nothing and survives a future edit that relaxes the range.
  CONSTRAINT chk_navya_risk_score_finite CHECK (
    risk_score IS NULL OR risk_score <> 'NaN'::DOUBLE PRECISION
  ),

  -- (7) Approval is a claim about provenance, so it requires evidence.
  --     Silence is not approval. Same rule as 010.
  CONSTRAINT chk_navya_risk_score_threshold_policy CHECK (
    (threshold_policy = 'pending')
    OR (threshold_policy = 'approved' AND threshold IS NOT NULL
        AND threshold_source IS NOT NULL AND threshold_source <> '')
  ),

  -- (6, cont.) A recorded score must have both halves. A risk_level with no
  --     score is a label attached to nothing.
  CONSTRAINT chk_navya_risk_score_recorded CHECK (
    status <> 'recorded' OR (risk_score IS NOT NULL AND risk_level IS NOT NULL
                             AND assessed_at IS NOT NULL)
  )
);

-- Re-assessing an area at a later instant is legitimate - that is a new
-- forecast. Two records claiming the SAME instant for one area are a duplicate
-- or a conflict, and the index refuses both at storage.
CREATE UNIQUE INDEX IF NOT EXISTS uq_navya_risk_score_area_instant
  ON navya_risk_score (area_reference, assessed_at)
  WHERE assessed_at IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_navya_risk_score_area
  ON navya_risk_score (area_reference, assessed_at DESC);

CREATE INDEX IF NOT EXISTS idx_navya_risk_score_forecast
  ON navya_risk_score (forecast_reference)
  WHERE forecast_reference IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_navya_risk_score_disclaimer
  ON navya_risk_score (created_at DESC)
  WHERE disclaimer IS NOT NULL;

-- ----------------------------------------------------------------------------
-- navya_data_quality_report
-- What `quality.summarise()` found, stored so an ingest is auditable after the
-- fact rather than only at the moment it ran.
--
-- `issues` holds the stable issue codes from `quality.py` verbatim. They are a
-- query surface: add a code, never re-spell one.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS navya_data_quality_report (
  id                        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

  -- 'observation' | 'flood_event' | 'risk_score' | 'dataset' | 'collection'.
  subject_kind              TEXT NOT NULL,
  -- Free text: a file path, a batch label, a table name. What was inspected.
  subject_reference         TEXT,
  dataset_reference         TEXT,

  -- (8) The counters must add up. A summary whose parts do not sum to its total
  --     is a bug in the reporting, and storing it would make that bug
  --     indistinguishable from a real quality problem later.
  records_checked           INTEGER NOT NULL DEFAULT 0,
  records_clean             INTEGER NOT NULL DEFAULT 0,
  records_suspect           INTEGER NOT NULL DEFAULT 0,
  records_rejected          INTEGER NOT NULL DEFAULT 0,

  -- The stable codes, with their severity and message. JSONB because the shape
  -- is per-issue and must not need a schema migration to add a field.
  issues                    JSONB NOT NULL DEFAULT '[]'::JSONB,

  -- Duplicate and conflicting keys found across the batch. Populated, never
  -- resolved: `quality.ConflictReport` deliberately offers no `resolve`.
  duplicate_keys            TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
  conflicting_keys          TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],

  -- 'ok' | 'rejected'. Mirrors summarise()'s derived value; stored so the query
  -- does not have to recompute it from the counters.
  quality_status            TEXT NOT NULL DEFAULT 'ok',
  -- Provenance of the report itself.
  reported_by               TEXT,
  assessed_at               TIMESTAMPTZ NOT NULL DEFAULT now(),

  CONSTRAINT chk_navya_quality_subject_kind CHECK (
    subject_kind IN ('observation', 'flood_event', 'risk_score', 'dataset', 'collection')
  ),

  CONSTRAINT chk_navya_quality_counts_non_negative CHECK (
    records_checked >= 0 AND records_clean >= 0
    AND records_suspect >= 0 AND records_rejected >= 0
  ),

  -- (8, cont.) clean + suspect + rejected must account for every checked
  --          record. Nothing may be silently dropped from the tally.
  CONSTRAINT chk_navya_quality_counts_balance CHECK (
    records_clean + records_suspect + records_rejected = records_checked
  ),

  -- A batch reported 'ok' with rejected records in it is a contradiction, and
  -- it is the exact shape of "we had problems and did not say so".
  CONSTRAINT chk_navya_quality_status CHECK (
    quality_status IN ('ok', 'suspect', 'rejected')
    AND NOT (quality_status = 'ok' AND records_rejected > 0)
  ),

  CONSTRAINT chk_navya_quality_issues_array CHECK (
    jsonb_typeof(issues) = 'array'
  )
);

CREATE INDEX IF NOT EXISTS idx_navya_quality_subject
  ON navya_data_quality_report (subject_kind, assessed_at DESC);

CREATE INDEX IF NOT EXISTS idx_navya_quality_dataset
  ON navya_data_quality_report (dataset_reference)
  WHERE dataset_reference IS NOT NULL;

-- A batch with conflicts is not a batch that passed.
CREATE INDEX IF NOT EXISTS idx_navya_quality_conflicts
  ON navya_data_quality_report (assessed_at DESC)
  WHERE array_length(conflicting_keys, 1) IS NOT NULL;

-- ----------------------------------------------------------------------------
-- navya_domain_availability
-- The audit view: which domains exist in this project, and whether any of them
-- have data.
--
-- A VIEW, not a table, on purpose. It derives `present_in_repository` from the
-- `navya_observation` rows themselves, so the answer cannot drift from the data
-- the way a hand-maintained status column would. There are no rows to fabricate:
-- with an empty database every domain reports FALSE, which is the truth.
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW navya_domain_availability AS
SELECT d.domain,
       d.requires_measurement,
       -- Derived from the stored rows, never asserted by hand. With an empty
       -- database every domain reports FALSE, which is the truth.
       (d.count > 0)                                AS present_in_repository,
       d.count                                      AS record_count,
       d.first_observed_at,
       d.last_observed_at,
       d.distinct_locations,
       d.non_real_record_count                      AS non_real_record_count
FROM (
  SELECT s.domain,
         s.requires_measurement,
         COUNT(o.id)                                AS count,
         MIN(o.observed_at)                         AS first_observed_at,
         MAX(o.observed_at)                         AS last_observed_at,
         COUNT(DISTINCT o.location_reference)       AS distinct_locations,
         COUNT(o.id) FILTER (WHERE o.dataset_type <> 'real') AS non_real_record_count
  FROM (
    -- The full domain list, so a domain with no rows still appears. Written out
    -- rather than read from a table, because there is deliberately no table of
    -- "all domains": that list belongs to the code that owns it, and duplicating
    -- it here is how two vocabularies start to disagree.
    SELECT 'weather'::TEXT AS domain, TRUE AS requires_measurement
    UNION ALL SELECT 'rainfall', TRUE
    UNION ALL SELECT 'water_level', TRUE
    UNION ALL SELECT 'discharge', TRUE
    UNION ALL SELECT 'inflow', TRUE
    UNION ALL SELECT 'flood_event', FALSE
    UNION ALL SELECT 'risk_score', FALSE
  ) AS s
  LEFT JOIN navya_observation AS o
    ON o.domain = s.domain
  GROUP BY s.domain, s.requires_measurement
) AS d
ORDER BY d.domain;

COMMENT ON VIEW navya_domain_availability IS
  'Phase 1 audit view: one row per data domain, with the number of observation '
  'rows actually stored. Derived from the data, never asserted by hand. With an '
  'empty database every domain reports present_in_repository = FALSE, which is '
  'the honest state: no real hydrological observation data exists in this '
  'repository, and no synthetic value in it was produced by this migration.';