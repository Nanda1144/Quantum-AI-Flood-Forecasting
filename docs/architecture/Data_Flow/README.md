# Data Flow

**Owner:** forecasting module
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
| 2 | Validation | Forecasting | `[MY IMPLEMENTATION]` |
| 3 | Preprocessing | Forecasting | `[MY IMPLEMENTATION]` |
| 4 | Feature engineering | Forecasting | `[MY IMPLEMENTATION]` |
| 5 | Model input matrix | Forecasting | `[MY IMPLEMENTATION]` |
| 6 | Forecasting | Forecasting | `[MY IMPLEMENTATION]` |
| 7 | Forecast output | Forecasting | `[MY IMPLEMENTATION]` |
| 8 | Flood risk | Forecasting | `[MY IMPLEMENTATION]` (threshold source `[NOT CURRENTLY AVAILABLE]`) |
| 9 | Optimization handoff | Joint | `[PROPOSED INTEGRATION]` — team-owned destination |
| 10 | Persistence | Joint | Migration 010 added by Navya; team schema unchanged |

## The one thing to understand

**There is no real data.** Everything downstream of stage 1 in this repository was exercised
against a committed synthetic sample that carries a mandatory disclaimer. The pipeline is
real and tested; the *input* is not. No forecast produced by this work describes any real
river.

See [`../ASSUMPTIONS_AND_LIMITATIONS.md`](../ASSUMPTIONS_AND_LIMITATIONS.md).
