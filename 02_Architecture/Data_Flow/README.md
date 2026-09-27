# Data Flow

**Owner:** Navya
**Documents:** [`data-flow.md`](data-flow.md), `data-flow.mmd`

---

## Purpose

Describes how a row of data becomes a forecast, and — just as importantly — what happens to
its provenance along the way.

## Status legend

`[EXISTING]` · `[MY IMPLEMENTATION]` · `[TEAM IMPLEMENTATION]` · `[PROPOSED INTEGRATION]` ·
`[NOT CURRENTLY AVAILABLE]`

## The ten stages

| # | Stage | Owner | Status |
|---|---|---|---|
| 1 | Raw / historical data | — | `[NOT CURRENTLY AVAILABLE]` — no real dataset exists |
| 2 | Validation | Navya | `[MY IMPLEMENTATION]` |
| 3 | Preprocessing | Navya | `[MY IMPLEMENTATION]` |
| 4 | Feature engineering | Navya | `[MY IMPLEMENTATION]` |
| 5 | Model input matrix | Navya | `[MY IMPLEMENTATION]` |
| 6 | Forecasting | Navya | `[MY IMPLEMENTATION]` |
| 7 | Forecast output | Navya | `[MY IMPLEMENTATION]` |
| 8 | Flood risk | Navya | `[MY IMPLEMENTATION]` (threshold source `[NOT CURRENTLY AVAILABLE]`) |
| 9 | Optimization handoff | Joint | `[PROPOSED INTEGRATION]` — team-owned destination |
| 10 | Persistence | Joint | Migration 010 added by Navya; team schema unchanged |

## The one thing to understand

**There is no real data.** Everything downstream of stage 1 in this repository was exercised
against a committed synthetic sample that carries a mandatory disclaimer. The pipeline is
real and tested; the *input* is not. No forecast produced by this work describes any real
river.

See [`../ASSUMPTIONS_AND_LIMITATIONS.md`](../ASSUMPTIONS_AND_LIMITATIONS.md).
