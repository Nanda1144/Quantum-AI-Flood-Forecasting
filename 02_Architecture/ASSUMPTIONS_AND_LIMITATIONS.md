# Assumptions and Limitations

**Owner:** Navya

This document exists so that nobody has to guess. Every limitation that materially affects
the interpretation of this work is listed here, including the ones that are unflattering.

**Marker convention** used across the architecture docs:
`NOT FOUND IN REPOSITORY — HUMAN / TEAM INPUT REQUIRED` and
`NOT FOUND IN LIVE TEAM BRANCH — HUMAN / TEAM INPUT REQUIRED`.

---

## 1. Data limitations

### 1.1 No real dataset exists — the single largest limitation

**`NOT FOUND IN REPOSITORY — HUMAN / TEAM INPUT REQUIRED`**

No approved hydrological dataset exists in this repository. Specifically missing: the dataset
itself, its source and licence, its column schema, its provenance and custody, its sampling
interval and timezone, its missingness profile, its quality-control rules, its station
inventory, and its observation count.

**Consequence:** no forecast produced by this work describes any real river, reach, or
catchment. The pipeline is real; the input is not.

**What exists instead:** a committed synthetic sample at
`ai-service/app/engines/hydro/data/synthetic_hydrology_sample.csv` — 2,160 rows, deterministic
generator, SHA-256 `56f4b7c5b4122b5d9b61db256f8d7afcb7e03d4a1cf9e942c013818386e29ac6` — used
solely so the pipeline is executable and tests have a stable input.

### 1.2 Target variable is undecided

**`NOT FOUND IN REPOSITORY — HUMAN / TEAM INPUT REQUIRED`**

Whether to forecast water level or inflow has not been decided. Units, vertical datum, forecast
horizons, and the meaning of "probability" are all undecided. The contract models water level
and carries inflow as `null` rather than guessing.

### 1.3 Station → GIS mapping is unavailable

**`NOT FOUND IN REPOSITORY — HUMAN / TEAM INPUT REQUIRED`**

No authoritative station or reach identifier list, and no station-to-GIS crosswalk, has been
supplied. Consequently the provenance of `CandidateLocation.floodRisk` is unknown.

`backend/src/navya/forecasting/candidate-risk.ts` models the mapping as an explicit, validatable
specification with declared blockers. It does **not** invent station identifiers, coordinates,
or reach geometry.

### 1.4 Official flood thresholds are unavailable

**`NOT FOUND IN REPOSITORY — HUMAN / TEAM INPUT REQUIRED`**

No government or official flood-stage source has been supplied, and no LOW/MEDIUM/HIGH/CRITICAL
band policy has been approved.

**Consequence:** every threshold in this work is marked `pending`, and
`thresholdPolicyFrom()` returns `pending` on **every** path — including paths where the value
looks official — because inferring approval from the absence of a disclaimer would be reading
an approval into silence. A pending threshold is never rendered as a bare number.

The team's `ReferenceEngine` placeholder of `8.0` is deliberately **not** reused as a default.

---

## 2. Metric and performance limitations

### 2.1 No fabricated metrics — anywhere

There are **no hard-coded, placeholder, or invented metric values** in the implementation. All
metrics are computed from actual predictions and actual observations. The tests include cases
that fail if a metric is ever absent, and cases that refuse to present a metric whose split
does not permit it.

### 2.2 Every measured number is synthetic

The only real measurements are from a single end-to-end run over the **synthetic** 8,760-row
dataset. They are labelled `synthetic/demo evaluation only` at the point of use.

| Split | MAE | RMSE | R² |
|---|---|---|---|
| Validation (selection — optimistic by construction) | 0.1191 | 0.1613 | 0.7884 |
| Held-out test (scored once) | 0.2779 | 0.3645 | 0.6359 |

**These are not real-world hydrological results and must never be presented as such.** The
gap between validation and test is itself evidence that they describe the synthetic generator
rather than any general capability.

### 2.3 No accuracy, precision, recall, or F1 for a regression target

The target is a continuous water level, so classification metrics are meaningless. Navya's
contract omits them entirely rather than rendering a number that invites misreading. The
frontend has tests asserting these words never appear in the rendered output.

### 2.4 Some models are documented but not implemented

LSTM, GRU, Random Forest, and quantum ML appear in the research and as labelled future entries
in the model registry. **None has been trained. No performance is claimed for any of them.**

The executed registry contains only models that can actually run.

---

## 3. Quantum limitations

### 3.1 No quantum claim of any kind

This work contains:

- **No** claim of quantum speedup
- **No** claim of quantum advantage or superiority
- **No** claim that a quantum solver would outperform a classical one here
- **No** quantum result — none was produced, measured, simulated, or estimated

### 3.2 Optimization performance is entirely unassessed

Actual optimization performance depends on the team's implementation and on real evaluation.
Navya has no visibility into the team's solver behaviour and makes no statement about it.

Establishing any comparison would require a real instance, a timed classical baseline, a timed
quantum solver on the same instance, a solution-quality comparison, repetition across instances
with variance, and a stated quantum resource cost. **None of that has been performed**, and all
of it is team-owned.

---

## 4. Integration limitations

### 4.1 The Navya dashboard is not mounted

The 17 files in `frontend/src/navya/forecasting/` compile, type-check, lint, build, and pass
109 tests. They are **not mounted into any team route**, and are therefore **tree-shaken out of
the production bundle**.

**This work does not claim the Navya dashboard is integrated into the live application.** It is
verified in isolation. It has never been observed rendering inside the real application.

### 4.2 No route serves the Navya forecast record

The team's `ai-service/app/api/ai.routes.ts` has no route registered for it. The frontend
service therefore has no endpoint to call, and the dashboard cannot be populated in a running
system. **Blocker `AI-ROUTE-01`.**

### 4.3 `forecast-sync` drops every Navya-derived field

`forecast-sync.service.ts` L50–63 maps the AI contract into `Forecast` with **no slot** for
provenance, metric split, threshold policy, or residual sigma. Even with a route, those fields
would be lost at the sync boundary. **Blockers `API-EXT-01` and `SYNC-EXT-01`.**

### 4.4 Optimization accepts `forecast_id` only

> **Existing optimization currently requires forecast_id. Additional forecast-derived risk
> fields require team-owner integration.**

**Blocker `OPT-EXT-01`.** Navya did not modify the optimization or QUBO logic to work around
this, and will not.

### 4.5 The real worktree cannot build the frontend

`frontend/package.json`, `tsconfig.json`, `tsconfig.app.json`, `vite.config.ts`, and
`node_modules` are **all absent** from Navya's working tree, and `frontend/src/services`,
`components`, `pages`, `types`, and `lib` are **empty directories**.

**Consequence:** the frontend cannot be compiled, tested, or built in the real working tree.
All frontend results in this project come from a **temporary harness** built from the team
branch, and are labelled as harness results wherever they appear. They are **not** real-worktree
results.

---

## 5. Verification limitations

| Check | Where it ran | Limitation |
|---|---|---|
| Python suite (412) | Overlay with the team seam present | On Navya's branch alone, the engine contract tests **skip** via seam detection, because the team's engine files do not exist there |
| Backend TS (129 Navya / 444 total) | Overlay with the team tree | The real worktree has no backend manifests either |
| Frontend (109 / 230) | **Temporary harness** | Not a real-worktree result |
| Migration 010 (19/19) | Local PostgreSQL 17.10 | Verified standalone; **not** applied to the team's ordered migration chain |
| CI results, coverage, deployment evidence | — | **`NOT FOUND IN LIVE TEAM BRANCH — HUMAN / TEAM INPUT REQUIRED`** — no CI run, coverage report, or deployment evidence for the team branch was available |

### 5.1 A pre-existing environment defect, not caused by this work

The team's `ai-service/tests/test_contract.py` cannot be collected in this environment:
`RuntimeError: The starlette.testclient module requires the httpx2 package to be installed.`
This is a pre-existing team dependency gap. Validation runs use
`--ignore=tests/test_contract.py`.

---

## 6. Merge and branch limitations

- The team's `forecastingMergeupdate/README.md` states the common base is `a402062`.
- Navya's branch head is `f253c42`.
- The two branches have **never** been Git-merged, so the seam has not been exercised on a
  single tree by either owner.
- The exact integration branch and SHA, and the person performing the merge, are not formally
  confirmed. **`NOT FOUND IN REPOSITORY — HUMAN / TEAM INPUT REQUIRED`**

---

## 7. Summary of what is genuinely complete

To be fair to the work, these are real and need no team action:

- Navya's forecasting engine, preprocessing, causal feature engineering, chronological splits,
  training, evaluation, and provenance guards — implemented and tested
- Navya's backend namespace — implemented, 129 tests passing
- Navya's frontend namespace — implemented, 109 tests passing, type-checked, lint-clean,
  production build succeeding
- Migration 010 — additive, reversible, verified 19/19
- Architecture and research documentation

What is **not** complete is everything that requires a team-owned file, a real dataset, or an
official threshold source. That list is in [`INTEGRATION_MATRIX.md`](INTEGRATION_MATRIX.md).
