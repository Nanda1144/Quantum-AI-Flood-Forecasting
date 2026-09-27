# Overall Architecture

**Owner:** Navya
**Scope:** Conceptual system architecture for the Q-FLARE flood forecasting platform, as it
relates to UC-067 flood forecasting.

---

## What this folder contains

| File | Purpose |
|---|---|
| `README.md` | This index and the status legend used across all architecture docs |
| `system-architecture.md` | The full conceptual pipeline, end to end, with ownership boundaries |
| `system-architecture.mmd` | Mermaid source for the same diagram (raw, no code fence) |

---

## Status legend

Every component in every architecture document is tagged with exactly one of these. The tags
are deliberately blunt: the single largest risk in this project is a reader assuming a
component is live when it is a proposal.

| Tag | Meaning |
|---|---|
| `[EXISTING]` | Present in the repository on the integration branch `origin/features/Nanda-ai-quantum` and not authored by Navya |
| `[MY IMPLEMENTATION]` | Written and executed by Navya, inside a Navya-owned namespace only |
| `[TEAM IMPLEMENTATION]` | Team-authored and load-bearing; Navya does not modify it |
| `[PROPOSED INTEGRATION]` | Designed by Navya, not yet implemented by anyone |
| `[NOT CURRENTLY AVAILABLE]` | Required by the design, absent from the repository, and blocked on human/team input |

---

## The pipeline at a glance

```
Data Sources
  -> Data Validation / Cleaning
  -> Feature Engineering
  -> Forecasting Models
  -> Flood Risk Assessment
  -> Forecast / Decision Handoff
  -> Sensor Optimization
  -> Quantum / Optimization Layer
  -> Disaster Response / Dashboard
```

Each stage, its owner, and its real status are documented in `system-architecture.md`.
The one-line summary of where the honest boundary sits:

> The **forecasting** stages are implemented and executed by Navya. The **optimization,
> quantum, GIS, IoT and deployment** stages are team-owned. The **dataset** itself does not
> exist. Nothing in this project has been deployed.

---

## Honest status summary

- Navya's forecasting engine and both Navya-owned namespaces (backend + frontend) are
  implemented, unit-tested, type-checked, and build cleanly.
- Navya's frontend module is **not mounted** into the team's application routes.
- No real hydrological dataset has been identified, so no real forecast has been produced.
- All measured numbers that exist anywhere in this work are **synthetic/demo** numbers,
  labelled as such at the point of use.
- The quantum and optimization layers are team-owned. This work claims **no** quantum
  advantage, speedup, or performance superiority of any kind.

See `../ASSUMPTIONS_AND_LIMITATIONS.md` for the full list of limitations and
`../INTEGRATION_MATRIX.md` for the component-by-component ownership and blocker table.
