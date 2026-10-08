# AI Flow

**Owner:** forecasting module
**Documents:** [`ai-flow.md`](ai-flow.md), `ai-flow.mmd`

---

## Purpose

Describes the machine-learning path only: from preprocessed input, through candidate models
and selection, to a forecast carrying uncertainty and risk information, and finally to the
handoff that team-owned optimization consumes.

## Status legend

`[EXISTING]` · `[MY IMPLEMENTATION]` · `[TEAM IMPLEMENTATION]` · `[PROPOSED INTEGRATION]` ·
`[NOT CURRENTLY AVAILABLE]`

## Candidate models

| Model | Status |
|---|---|
| Ridge regression | `[MY IMPLEMENTATION]` — executable |
| XGBoost | `[MY IMPLEMENTATION]` — optional dependency, skip is reported |
| Random Forest | Candidate in research; not in the executed registry |
| LSTM | `[NOT CURRENTLY AVAILABLE]` — future work |
| GRU | `[NOT CURRENTLY AVAILABLE]` — future work |
| Quantum ML | `[NOT CURRENTLY AVAILABLE]` — research only |

The model **registry contains only executable models**. LSTM, GRU and QML are recorded as
explicitly-labelled future entries so the research in `docs/forecasting/Research/` has a
documented landing point. They have **not** been trained, and no performance is claimed for
them.

## No invented performance values

This folder contains no invented metrics. The only numbers that appear are the real,
reproducible measurements from a single end-to-end run on the **synthetic** 8,760-row
dataset, and they are labelled `synthetic/demo evaluation only` at the point of use.
