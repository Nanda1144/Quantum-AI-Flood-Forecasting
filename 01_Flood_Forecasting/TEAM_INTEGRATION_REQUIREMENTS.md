# Team Integration Requirements

**Owner:** Navya (`ai-service/app/engines/hydro/`, `backend/src/navya/forecasting/`,
`frontend/src/navya/forecasting/`) · **Branch:** `feature/navya-forecast`

**Purpose:** every change that belongs to a team owner rather than to Navya,
written down so it is reviewable as a list instead of discovered as a failure.
Nothing in this document has been applied. **Team-owned files modified by this
branch: 0.**

> **This file did not exist.** Four Navya-owned files referenced it before it was
> written: `requirements-hydro.txt`, `README.md`, `PHASE2_PREPROCESSING.md` and
> `__init__.py`. The references were left in place and point here.

The architecture-level view of the same boundary is
[`02_Architecture/INTEGRATION_MATRIX.md`](../02_Architecture/INTEGRATION_MATRIX.md).
That document is the component-by-component picture; this one is the actionable
register. IDs are shared between them, and are quoted from code wherever code
refers to one.

---

## 1. How to read this register

Each item states:

- **ID** — referenced from code comments where one exists, so the requirement
  travels with the code that is blocked by it.
- **Action** — the smallest change that unblocks something.
- **Owner** — whose file has to change.
- **Blocked** — what specifically cannot happen until it does.

Every item is written so it can be actioned without reading Navya's code first.
Where a change is deliberately *not* requested, the item says so, and section 3
lists the things that are complete and need nobody's approval.

---

## 2. The register

### AI-REQ-01 — ML runtime dependencies

| | |
| --- | --- |
| **Action** | Add `numpy>=1.26` and `pandas>=2.1` to `ai-service/requirements.txt`. Optionally `scikit-learn>=1.3`, which unlocks two optional candidates in the model registry. |
| **Owner** | Team. `ai-service/requirements.txt` is team-owned and was **not** modified by this branch. |
| **Source of truth** | `ai-service/app/engines/hydro/requirements-hydro.txt` (Navya-owned, created for exactly this purpose). |
| **Blocked** | The forecasting engine cannot be constructed in the team's environment; Navya's `test_hydro_*` suites and the training entrypoint cannot run there. |
| **Referenced from** | `requirements-hydro.txt` L15, `README.md` L149, `PHASE2_PREPROCESSING.md` L604, `INTEGRATION_MATRIX.md` L46. |

`app.engines.hydro` is only importable when `FORECAST_ENGINE` selects it, so a
deployment that keeps `ReferenceEngine` does not strictly need these. They are
needed to *run* Navya's code, not to keep the platform up.

There is no `pyproject.toml` or lockfile in the repository, so "add a
requirements file" and "pin versions" cannot both be done here.

---

### AI-SCHEMA-01 — extend the Pydantic forecast contract

| | |
| --- | --- |
| **Action** | Add the proposed forecast fields to `ai-service/app/schemas/models.py`. |
| **Owner** | Team. |
| **Blocked** | Provenance, threshold policy, residual sigma and held-out metrics cannot cross the AI boundary. |

The proposed field list is enumerated once, in
`backend/src/navya/forecasting/contract.ts` as
`FIELDS_REQUIRING_INTEGRATION` — 16 fields: `flood_probability`, `risk_level`,
`predicted_value`, `predicted_inflow`, `target`, `target_units`,
`forecast_horizon`, `forecast_timestamp`, `threshold`, `threshold_policy`,
`residual_sigma`, `station_reference`, `provenance_reference`, `dataset_type`,
`status`, `contract_version`.

A test asserts `FIELDS_REQUIRING_INTEGRATION` and the built handoff agree, so
**the list cannot silently go stale**: adding a field without listing it, or
listing one the builder does not emit, fails the suite.

Until this lands, `LOSSY_FIELDS` in `forecast-adapter.ts` is entirely `null` and
`toNavyaForecastRecord()` sets `datasetType: 'unknown'` — the only honest value
when no lineage was sent. A test asserts every `LOSSY_FIELDS` entry is `null`,
which **will fail once this item is implemented**. That is the intended signal
that the register is out of date.

### AI-SCHEMA-02 — `predicted_inflow` and `target_units`

| | |
| --- | --- |
| **Action** | Add `predicted_inflow` and `target_units` to `app/schemas/models.py`, `backend/src/types/contract.ts` and the forecasts table. |
| **Owner** | Team. |
| **Blocked** | Any non-water-level forecast target. |

Until this lands, `HydroForecastEngine.predict()` **raises `EngineNotReadyError`**
for a target other than `water_level` rather than serving an inflow forecast
through a `predicted_water_level` field. Serving it would be a mislabel, and a
mislabel in a field named `predicted_*` is the kind that survives into a
dashboard.

---

### API-EXT-01 — carry the Navya fields across the API

| | |
| --- | --- |
| **Action** | Add provenance, metric split, threshold policy and residual sigma to `backend/src/types/contract.ts`. |
| **Owner** | Team. |
| **Blocked** | Every field in AI-SCHEMA-01, one hop further downstream. |
| **Referenced from** | `backend/src/navya/forecasting/types.ts` L26, L199; `contract.test.ts`. |

`contract.ts` is team-owned and was **not** modified. `backend/src/navya/`
describes the target shape and the pure builders that produce it, so the mapping
can be reviewed and tested before anyone wires it up. Nothing in that directory
is mounted on a team route.

### SYNC-EXT-01 — mapping slots at the sync boundary

| | |
| --- | --- |
| **Action** | Add mapping slots for the same fields in `ai-service/app/services/forecast-sync.service.ts` (L50–63). |
| **Owner** | Team. |
| **Blocked** | Fields are dropped silently at the sync boundary, even once the contract carries them. |

Distinct from API-EXT-01 and easy to miss: a contract can be extended and a
sync mapper can still drop the new fields on the floor, with no error.

### AI-ROUTE-01 — register an HTTP route

| | |
| --- | --- |
| **Action** | Register a route in `ai-service/app/api/ai.routes.ts` serving the Navya forecast record. |
| **Owner** | Team. |
| **Blocked** | The frontend service has no endpoint to call. |

---

### OPT-EXT-01 — extend the optimization input beyond `forecast_id`

| | |
| --- | --- |
| **Action** | Extend the team optimization input if forecast-derived risk fields are needed. |
| **Owner** | Team (QUBO / optimisation are out of Navya's scope entirely). |
| **Blocked** | Forecast-derived risk cannot reach the optimizer's objective. |

**Navya will not make this change**, and the reason is worth recording rather
than leaving as a bare "not mine": `CandidateLocation.floodRisk` already exists,
is consumed by `siteUtility()` in the QUBO builder, and comes from the GIS
candidate store. Replacing it with a forecast-derived value would silently
change every optimization result the platform has produced. That is a
platform-level decision, not a forecasting decision.

The integration statement, reproduced verbatim:

> **Existing optimization currently requires forecast_id. Additional
> forecast-derived risk fields require team-owner integration.**

It is exported as a constant (`INTEGRATION_STATEMENT`) in all three Navya
surfaces and asserted by tests, so it cannot drift or be dropped silently.

---

### GIS-REQ-01 — authoritative station and reach identifiers

| | |
| --- | --- |
| **Action** | Supply authoritative station identifiers, a station register, a station→candidate-location crosswalk, and reach geometry/topology. |
| **Owner** | Team / external authority. |
| **Blocked** | Candidate risk attribution. |

Navya models `CandidateRiskMappingSpec` and does **not** populate it. Six
blockers are enumerated in `MAPPING_BLOCKERS` (backend/src/navya/forecasting/candidate-risk.ts):

1. Authoritative station identifiers and a station register.
2. A station→candidate-location mapping. `CandidateLocation` carries no station key.
3. Reach geometry and topology, to propagate a station forecast downstream.
4. Elevation datum and terrain, to relate stage to a specific site.
5. A documented rule for how forecast risk attenuates along a reach.
6. Provenance for the existing `CandidateLocation.floodRisk`.

`buildCandidateRiskMapping()` returns a **present, clearly-marked empty** mapping
rather than no mapping — a missing object invites a caller to substitute
something. Every attribution carries `derivedFloodRisk: null`, not `0` (which
asserts no flood risk) and not the station risk (which would assume every site
shares the station stage).

No station identifier, coordinate, reach length or basin boundary has been
invented anywhere in this branch to close this gap.

### THRESH-REQ-01 — official flood stages and datum

| | |
| --- | --- |
| **Action** | Supply official flood-stage values and their vertical datum. |
| **Owner** | External authority. |
| **Blocked** | Any threshold that may be presented as an approved number. |

`thresholdPolicyFrom` returns `'pending'` on **every** path, including when a
threshold exists and the label disclaims nothing. Inferring approval from
silence would be fabrication.

---

### FE-ROUTE-01 — mount the Navya dashboard

| | |
| --- | --- |
| **Action** | Mount `NavyaForecastDashboard` in the team frontend router. |
| **Owner** | Team. |
| **Blocked** | The Navya UI is unreachable; it is tree-shaken out of the production bundle. |
| **Referenced from** | `NavyaForecastDashboard.tsx` L42. |

`App.tsx` and `pages/AIAnalyticsDashboard.tsx` are team-owned and were **not**
modified, so nothing on the running application changes until a team owner
mounts the component.

### FE-TYPES-01 — extend the frontend AI types

| | |
| --- | --- |
| **Action** | Add the provenance, threshold-policy and held-out-metric fields to `frontend/src/types/ai.ts`. |
| **Owner** | Team. |
| **Blocked** | The dashboard can render, but provenance and evaluation status read `null` / `'unknown'`. |

Until this lands, `navyaForecastService.ts` records those fields as `null` /
`'unknown'` rather than deriving them.

One deliberate non-inheritance is worth recording: `loadAIAnalytics()` in the
team's `aiService.ts` falls back to clearly-flagged sample data when the backend
is unreachable. Navya's client does not use that fallback, because a component
whose entire job is to say "this number is not trustworthy" cannot itself be fed
invented numbers — the failure would be invisible and self-contradictory. Navya's
client surfaces the error and renders an honest empty state. The team path is
untouched.

---

### DB-MIG-01 — apply migration 010

| | |
| --- | --- |
| **Action** | Apply `database/migrations/010_navya_forecast_provenance.*.sql` in the team's ordered migration chain. |
| **Owner** | Team (database owner). |
| **Blocked** | Navya provenance is not persisted. |
| **State** | Additive and reversible. Verified 19/19 locally. **Not applied by Navya** to the team's chain. |

### DB-MIG-02 — apply migration 011

| | |
| --- | --- |
| **Action** | Apply `database/migrations/011_navya_hydro_observation_domains.*.sql` in the ordered chain. |
| **Owner** | Team (database owner). |
| **Blocked** | Record-level storage for the Phase 1 data domains. |
| **State** | **Statically reviewed only.** No `psql` and no `docker` are available in this environment, so it has never been executed against a live PostgreSQL. It needs a database owner to verify. |

011 creates Navya tables only. It references
`navya_forecast_provenance(forecast_id)` from 010 as a foreign key and **alters
nothing**. No team table is created, altered, retyped, indexed or dropped, and
migrations `001`–`009` are untouched.

### DATA-REQ-01 — a real dataset

| | |
| --- | --- |
| **Action** | Supply a real dataset with its licence, schema, provenance, sampling interval and quality rules. |
| **Owner** | Team / external data source. |
| **Blocked** | **No real forecast is possible at all.** |

Every committed dataset is SYNTHETIC/DEMO and carries, verbatim:

> `THIS DATASET IS SYNTHETIC/DEMO DATA AND MUST NOT BE PRESENTED AS REAL
> HYDROLOGICAL OBSERVATION DATA.`

The verbatim string is preserved end to end and features derived from synthetic
data stay labelled synthetic in every report, every exported row and every
frontend payload. The guard `assertForecastMayBeStored` refuses a synthetic
forecast stripped of its disclaimer.

This is the single largest open item in the register. Every accuracy claim in
this repository is currently a claim about generated data.

---

## 3. What is complete and needs no team action

Stated explicitly, so the register is not read as a list of unfinished work:

- Navya's forecasting engine, preprocessing (Phase 2) and feature engineering
  (Phase 3) — implemented and tested. **993 passed, 1 skipped** in the full
  `ai-service` suite.
- Navya's backend namespace (`backend/src/navya/forecasting/`) — implemented and
  tested.
- Navya's frontend namespace (`frontend/src/navya/forecasting/`) — implemented
  and tested.
- Navya's architecture and research documentation, including this register.
- Migrations 010 and 011 — additive, reversible, written and reviewed.

## 4. What is not claimed

- Not **fully integrated** — the frontend is unmounted and no route is registered.
- Not **deployed** or **in production** — nothing here is deployed.
- Not **real flood-forecasting performance** — every measurement in this
  repository is on synthetic/demo data.
- Not **validated against real hydrology** — Phase 3's features are verified
  arithmetically correct on generated fixtures. Whether a feature *definition* is
  scientifically appropriate for a real catchment is a separate question that no
  test in this branch answers.
- Not **quantum-advantaged** — no quantum result was produced by Navya, and none
  is claimed.
