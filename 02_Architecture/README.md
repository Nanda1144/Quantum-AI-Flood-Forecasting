# Architecture

**Owner:** Navya

Conceptual architecture documentation for the Q-FLARE flood forecasting platform, with
explicit ownership boundaries and an explicit list of what does not yet exist.

---

## Read this first

**Two facts govern everything in this folder:**

1. **There is no real hydrological dataset.** Every number in this documentation that comes
   from a measurement is a **synthetic/demo** measurement, labelled as such at the point of
   use.
2. **The quantum and optimization layers are team-owned, and this work claims no quantum
   advantage, speedup, or performance superiority of any kind.**

Start with [`ASSUMPTIONS_AND_LIMITATIONS.md`](ASSUMPTIONS_AND_LIMITATIONS.md). It is written
so that nobody has to guess what is real.

---

## Contents

| Folder / file | What it covers |
|---|---|
| [`ASSUMPTIONS_AND_LIMITATIONS.md`](ASSUMPTIONS_AND_LIMITATIONS.md) | **Start here.** Every limitation, blocker, and honest caveat |
| [`INTEGRATION_MATRIX.md`](INTEGRATION_MATRIX.md) | Component-by-component ownership, status, dependency, blocker, and exact team-owner action |
| [`Overall_Architecture/`](Overall_Architecture/README.md) | The complete conceptual pipeline, end to end |
| [`Data_Flow/`](Data_Flow/README.md) | Raw data → validation → features → model input → forecast → risk → handoff |
| [`AI_Flow/`](AI_Flow/README.md) | Candidates → comparison → selection → forecast → uncertainty → risk → handoff |
| [`Quantum_AI_Integration/`](Quantum_AI_Integration/README.md) | The intended forecast-to-optimizer boundary, and the explicit no-quantum-claim position |
| [`API_Integration/`](API_Integration/README.md) | The Navya forecast contract, and the team-owned API surface it does not modify |

Each folder contains a `README.md` (index + status legend), a narrative `.md`, and a `.mmd`
Mermaid source for the same diagram.

---

## Status legend

| Tag | Meaning |
|---|---|
| `[EXISTING]` | Present in the repository on the team integration branch, not authored by Navya |
| `[MY IMPLEMENTATION]` | Written and executed by Navya, inside a Navya-owned namespace only |
| `[TEAM IMPLEMENTATION]` | Team-authored and load-bearing; Navya does not modify it |
| `[PROPOSED INTEGRATION]` | Designed by Navya, not yet implemented by anyone |
| `[NOT CURRENTLY AVAILABLE]` | Required by the design, absent, and blocked on human/team input |

---

## The integration statement

> **Existing optimization currently requires forecast_id. Additional forecast-derived risk
> fields require team-owner integration.**

---

## Honest status summary

**Complete and verified:** Navya's forecasting engine, its backend namespace (129 tests), its
frontend namespace (109 tests, type-checked, lint-clean, production build passing), migration
010 (additive, reversible, 19/19 verified), and this documentation.

**Not complete, and not claimed to be:** team routing integration, the registered API route,
`forecast-sync` field mapping, optimization input beyond `forecast_id`, any real dataset, any
official flood threshold, any station-to-GIS mapping, and any deployment.

**Not claimed at all:** real-world forecasting performance, production deployment, and quantum
advantage.
