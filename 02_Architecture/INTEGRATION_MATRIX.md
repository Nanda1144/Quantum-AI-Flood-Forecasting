# Integration Matrix

**Owner:** Navya
**Scope:** Every component at the forecast-to-optimization boundary, its owner, its real
status, and the exact action required to connect it.

**Status legend:** `[EXISTING]` · `[MY IMPLEMENTATION]` · `[TEAM IMPLEMENTATION]` ·
`[PROPOSED INTEGRATION]` · `[NOT CURRENTLY AVAILABLE]`

---

## 1. Component matrix

| Component | Owner | Current status | Interface | Dependency | Integration action | Blocker |
|---|---|---|---|---|---|---|
| **Navya forecasting engine** | Navya | `[MY IMPLEMENTATION]` — Phases 1-3 implemented, 993 tests pass | `ForecastEngine` protocol (structural conformance, zero-arg constructible) | numpy / pandas — **not** in the team's `requirements.txt` | Team owner adds ML runtime deps (`AI-REQ-01`) | Runtime deps absent; no `pyproject.toml`/lockfile |
| **Navya frontend module** | Navya | `[MY IMPLEMENTATION]` — 17 files, 109 tests, type-checked, lint-clean, builds | `fetchJson` from the team's `services/aiService`; team `components/ui/*`, `lib/risk`, `lib/format`, `components/charts/chartTheme` | Team frontend tree | Mount in team routing | **Not mounted.** No team route renders it, so it is tree-shaken out of the production bundle |
| **Navya backend module** | Navya | `[MY IMPLEMENTATION]` — 6 files, 129 tests pass | `NavyaForecastRecord`, `ProposedForecastHandoff` | Team contract types | Extend team contract types to carry Navya fields | Team contract has no provenance / split / policy slots |
| **forecast-sync** | Team | `[TEAM IMPLEMENTATION]` — exists, unmodified | Maps AI contract → `Forecast` (L50–63) | Team schemas | Team owner adds slots for provenance, metric split, threshold policy, residual sigma | **No slot exists for any Navya-derived field** |
| **AI service HTTP routes** | Team | `[TEAM IMPLEMENTATION]` — unmodified | `ai-service/app/api/ai.routes.ts` | Engine seam | Team owner registers a route serving the Navya forecast record | **No route exists.** The frontend service has no endpoint to call |
| **Optimization / QUBO** | Team | `[TEAM IMPLEMENTATION]` — unmodified | Accepts `forecast_id` only | Forecast table | Team owner extends the input if risk fields are needed | **`forecast_id` only.** Navya must not modify QUBO logic |
| **Quantum layer** | Team | `[TEAM IMPLEMENTATION]` — unmodified | Team-owned solver interface | QUBO encoding | None from Navya | No quantum result produced or measured by Navya. **No advantage claimed** |
| **Database / data source** | Team schema + **no real data** | `[TEAM IMPLEMENTATION]` schema; `[NOT CURRENTLY AVAILABLE]` data | Migrations 010 and 011 add additive Navya tables and columns | PostgreSQL | Team owner applies the migrations in the ordered chain | **No real dataset exists.** 010 verified 19/19 locally; **011 statically reviewed only** — no live PostgreSQL available |
| **Frontend route** | Team | `[TEAM IMPLEMENTATION]` — unmodified | Team router | Navya dashboard | Team owner mounts `NavyaForecastDashboard` | **Navya dashboard is not mounted** |
| **Sensor optimization** | Team | `[TEAM IMPLEMENTATION]` — unmodified | Candidate sensor configuration | Optimization / QUBO | None from Navya | Objective terms undefined; jointly owned decision |
| **Station → GIS mapping** | Team / external | `[NOT CURRENTLY AVAILABLE]` | `CandidateRiskMappingSpec` (Navya models it; does not populate it) | Authoritative station/reach IDs | Supply authoritative IDs + crosswalk | **No station or reach identifier list, no crosswalk** |
| **Official flood thresholds** | External authority | `[NOT CURRENTLY AVAILABLE]` | `threshold` + `thresholdPolicy` | Official flood-stage source | Supply official stages and datum | **No official source.** All thresholds marked `pending` |
| **Real worktree build env** | Team | `[NOT CURRENTLY AVAILABLE]` | `package.json`, `tsconfig`, `node_modules` | — | Merge team branch, or commit manifests | **Frontend cannot be built or tested in the real worktree** |

---

## 2. The integration statement

> **Existing optimization currently requires forecast_id. Additional forecast-derived risk
> fields require team-owner integration.**

This is reproduced verbatim because it is the precise boundary of what Navya may and may not
do here.

---

## 3. Exact team-owner actions, consolidated

| ID | Action | File(s) | Blocking |
|---|---|---|---|
| `AI-REQ-01` | Add ML runtime dependencies (numpy, pandas) | `ai-service/requirements.txt`; no `pyproject.toml` exists | Engine cannot run on the team's environment |
| `AI-SCHEMA-01` | Add the 16 proposed forecast fields (provenance, metric split, threshold policy, residual sigma) | `ai-service/app/schemas/models.py` | Fields cannot cross the AI boundary. Enumerated in `FIELDS_REQUIRING_INTEGRATION` |
| `AI-SCHEMA-02` | Add `predicted_inflow` + `target_units` | `app/schemas/models.py`, `backend/src/types/contract.ts`, forecasts table | Any non-water-level forecast target. The engine raises rather than mislabel |
| `AI-ROUTE-01` | Register a route serving the Navya forecast record | `ai-service/app/api/ai.routes.ts` | Navya frontend cannot fetch |
| `API-EXT-01` | Add provenance, metric split, threshold policy, residual sigma | `backend/src/types/contract.ts` | Fields cannot cross the API |
| `SYNC-EXT-01` | Add mapping slots for the same fields | `ai-service/app/services/forecast-sync.service.ts` L50-63 | Fields are dropped at the sync boundary |
| `OPT-EXT-01` | Extend optimization input beyond `forecast_id` | team optimization interface | Risk fields cannot reach the optimizer |
| `FE-ROUTE-01` | Mount the Navya dashboard | team frontend router | Navya UI is unreachable in the app |
| `FE-TYPES-01` | Add the provenance / threshold-policy / held-out-metric fields to the frontend AI types | `frontend/src/types/ai.ts` | Dashboard renders, but provenance reads `null` / `unknown` |
| `DB-MIG-01` | Apply migration 010 in the team's ordered chain | `database/migrations/` | Navya provenance is not persisted |
| `DB-MIG-02` | Apply migration 011 in the team's ordered chain | `database/migrations/` | Phase 1 record domains are not persisted. **Not executed against a live PostgreSQL** |
| `DATA-REQ-01` | Supply a real dataset, licence, schema, provenance, sampling, quality rules | — | **No real forecast is possible at all** |
| `THRESH-REQ-01` | Supply official flood stages + datum | — | Thresholds stay `pending` |
| `GIS-REQ-01` | Supply authoritative station/reach IDs and the GIS crosswalk | — | Candidate risk attribution cannot be populated |

**Full register with rationale:** `01_Flood_Forecasting/TEAM_INTEGRATION_REQUIREMENTS.md`
— the file five Navya sources reference by that path.

---

## 4. What is *not* a blocker

For the avoidance of doubt, these are complete and need no team action:

- Navya's forecasting engine, training, evaluation, and provenance logic — implemented and tested
- Navya's data foundation (Phase 1), preprocessing (Phase 2) and feature engineering (Phase 3) — implemented and tested
- Navya's backend namespace — implemented and tested (129 tests)
- Navya's frontend namespace — implemented and tested (109 tests)
- Navya's architecture and research documentation
- Migration 010 — additive, reversible, verified 19/19, ready for the team's chain
- Migration 011 — additive, reversible, statically reviewed. **Not yet executed**, so a database owner still needs to verify it (`DB-MIG-02`)

---

## 5. What is *not* claimed

- Not "fully integrated" — the frontend is unmounted and no route is registered
- Not "deployed" or "in production" — nothing here is deployed
- Not "real flood forecasting performance" — all measurements are synthetic/demo
- Not "hydrologically validated" — Phase 3's features are verified arithmetically correct on generated fixtures. Whether a feature definition is scientifically appropriate for a real catchment is a separate question no test here answers
- Not "quantum advantage" — no quantum result was produced, and none is claimed
