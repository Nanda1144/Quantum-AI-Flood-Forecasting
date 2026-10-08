# Navya — Forecast → Optimization Contract (backend)

**Owner:** forecasting module · **License:** Apache-2.0 · **Module:** `backend`

Everything in `src/features/forecasting/` is new, forecasting-module-owned code. No team-owned
file is modified, and nothing here is mounted into a team route. It is a
**declared contract plus pure functions**, so the forecast→optimization mapping
can be reviewed and tested before anyone wires it up.

---

## The one-sentence answer

> Existing optimization currently requires forecast_id. Additional
> forecast-derived risk fields require team-owner integration.

That sentence is exported as `INTEGRATION_STATEMENT` and asserted verbatim in
`tests/features/forecasting/contract.test.ts`, so it cannot drift as surrounding code changes.

---

## Files

| File | What it does |
| --- | --- |
| `types.ts` | The two payload shapes and the constants. `ExistingOptimizationPayload` is what the running optimizer accepts; `ProposedForecastHandoff` is what Navya produces. Also the verbatim integration statement and the mandatory disclaimers. |
| `contract.ts` | Pure builders that narrow a forecast to the existing payload, plus the list of fields that need a team-owner change. |
| `candidate-risk.ts` | Declares that candidate-level flood risk is **not derivable**, and why. Every `derivedFloodRisk` is `null`. |
| `provenance.ts` | Guards that stop an unlabelled synthetic forecast or a non-held-out score from being presented as a result. |
| `forecast-adapter.ts` | Lossy, pure adapter from the team's `ForecastContract` to a forecast record. Names every field the transport drops. |

---

## What the running optimizer accepts today

`POST /api/optimization/from-forecast` takes:

```
forecast_id                      (required)
risk_score                       (optional)
priority                         (optional: low | medium | high | critical)
candidate_locations_available    (optional)
resource_constraints_available   (optional)
```

`toExistingOptimizationPayload()` emits exactly these keys and nothing else.

### Why the two availability flags are sent as explicit `false`

`OptimizationService.createFromForecast` resolves them as:

```ts
payload.candidate_locations_available ?? true
```

**Omitting the key makes the platform record `true`** — a claim that candidate
locations and resource constraints are available. Neither exists in this
repository. So the builder always sends an explicit `false` by default. A test
asserts the key is *present*, not just falsy, because absence is what would
produce the false claim.

---

## What is NOT accepted today

`FIELDS_REQUIRING_INTEGRATION` lists 16 proposed fields — `flood_probability`,
`risk_level`, `predicted_value`, `predicted_inflow`, `target`, `target_units`,
`forecast_horizon`, `forecast_timestamp`, `threshold`, `threshold_policy`,
`residual_sigma`, `station_reference`, `provenance_reference`, `dataset_type`,
`status`, `contract_version`.

Each needs a team owner to extend `backend/src/types/contract.ts` and
`ai-service/app/schemas/models.py`. See
`docs/forecasting/TEAM_INTEGRATION_REQUIREMENTS.md`. A test asserts the list
and the handoff agree, so the list cannot silently go stale.

---

## Candidate risk: unavailable, and declared so

Two facts pin this down:

1. `CandidateLocation` (team-owned) has **no station key** — fields are `id`,
   `name`, `zone`, `latitude`, `longitude`, `floodRisk`,
   `populationExposure`, `infrastructureCriticality`, `communicationScore`,
   `sensorCostKm`, `coverageRadiusKm`. There is nothing to join a station
   forecast on.
2. `CandidateLocation.floodRisk` **already exists** and is consumed by
   `siteUtility()` in the QUBO builder. It comes from the GIS candidate store,
   not from the forecast, and its provenance is not established anywhere in this
   repository.

So forecast-derived risk does not reach the optimizer's objective today, and
adding it would mean changing the QUBO builder — team-owned. Replacing
`candidate.floodRisk` with a forecast-derived value would silently change every
optimization result the platform has produced.

`buildCandidateRiskMapping()` therefore returns a **present, clearly-marked
empty** mapping rather than no mapping at all — a missing object invites a
caller to substitute something.

Every attribution carries `derivedFloodRisk: null` — not `0` (which asserts no
flood risk) and not the station risk (which would assume every site shares the
station stage).

> **NOT FOUND IN REPOSITORY — HUMAN / TEAM INPUT REQUIRED:** authoritative
> station identifiers and a station register; a station→candidate mapping; reach
> geometry; elevation datum; an attenuation rule; provenance of the existing
> `floodRisk`.

---

## The honesty guards

| Guard | Refuses |
| --- | --- |
| `isPresentableAsRealResult` | Anything but real data with no disclaimer. |
| `areMetricsPresentableAsResult` | Metrics from synthetic/unknown data, from a `train` or `validation` split, or with no recorded split. |
| `assertForecastMayBeStored` | A synthetic forecast stripped of its disclaimer. |
| `assertMetricsMayBeReported` | Reporting a fit or selection statistic as a held-out result. |
| `thresholdPolicyFrom` | Claiming `approved` from silence. The running contract has no approval field, so **every** path returns `pending`. |

Two details worth calling out:

- **`train` and `validation` are both refused.** A training score is not the
  selection statistic, so a guard that trusted only `isSelectionStatistic`
  would let it through — and a training score is the most flattering number
  available. The split is checked directly.
- **`thresholdPolicyFrom` returns `'pending'` on every path**, including when a
  threshold exists and the label disclaims nothing. Inferring approval from
  silence would be fabrication.

---

## Lossy by design

`LOSSY_FIELDS` is entirely `null`, because the running AI contract carries none
of those fields. `toForecastRecord()` sets `datasetType: 'unknown'` — the
only honest value when no lineage was sent. `adapterGaps()` recomputes the open
questions so a consumer sees exactly what the transport dropped.

A test asserts every `LOSSY_FIELDS` entry is `null`. **When a team owner
extends the contract, that test fails** — which is the point.

---

## Tests

```
node --test --test-force-exit --import tsx "tests/features/forecasting/*.test.ts"
```

129 tests. Pure functions only — no database, no network, no HTTP client.
`tests/features/forecasting/helpers/fixtures.ts` is not named `*.test.ts` so it is not
collected.

Fixture numbers are placeholders for a shape, never a claimed result.
`realRecord()` is a counterfactual a test needs to prove a guard has teeth; it is
not a claim that such a record can currently be produced.

Measured: 129 passed / 0 failed, run against the team seam at
`d9b5a03409ef534e7b9d6cd42d25129af6034d9f`. With these files removed the team
suite is unchanged at 315 tests / 263 passed / 0 failed / 52 skipped, and with
them it is 444 / 392 / 0 / 52 — the 52 skips are pre-existing.

`npx tsc -p tsconfig.json --noEmit` → exit 0 under the team's `strict`,
`noUnusedLocals`, `noUnusedParameters`, `verbatimModuleSyntax`.
