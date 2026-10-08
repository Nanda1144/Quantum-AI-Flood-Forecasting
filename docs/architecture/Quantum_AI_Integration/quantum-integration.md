# Quantum / AI Integration

**Owner:** forecasting module — *integration boundary documentation only*
**Diagram source:** `quantum-integration.mmd`
**Status legend:** see [`README.md`](README.md)

---

## 1. Scope of this document

The forecasting module owns the **forecast side** of the forecast-to-optimization boundary. The team owns the
**optimization and quantum side**. This document describes how the two are intended to meet.

It does **not** describe, modify, evaluate, or benchmark the team's optimization or quantum
implementation, and it makes no performance claim about either.

---

## 2. The intended chain

```
forecast output
  -> flood-risk information
  -> optimization parameters
  -> sensor placement problem
  -> optimization / QUBO layer
  -> candidate sensor configuration
```

---

## 3. Stage by stage

### 3.1 Forecast output `[MY IMPLEMENTATION]`

Produced by `ai-service/app/engines/hydro/engine.py` and carried by the Navya forecast
contract: predicted value, forecast timestamp, horizon, model identifier and version, and a
`synthetic`/`demo` indicator.

### 3.2 Flood-risk information `[MY IMPLEMENTATION]`

Risk band (LOW / MEDIUM / HIGH / CRITICAL), the threshold and its policy, and residual sigma.

**Official flood stage values are `[NOT CURRENTLY AVAILABLE]`.** No official threshold source
has been supplied. Every threshold in this work is marked `pending`, and a pending threshold is
never rendered as an approved number.

### 3.3 Optimization parameters `[PROPOSED INTEGRATION]`

**This stage does not exist yet.** Converting a forecast into objective-function terms — what
a reach's risk contributes, how uncertainty should be weighted, how horizon maps to planning
value — is a modelling decision that belongs jointly with the optimization owner. Navya has not
made it unilaterally, because guessing it would produce a plausible-looking objective with no
agreed meaning.

**Blocked on:** a team owner defining the objective terms.

### 3.4 Sensor placement problem `[TEAM IMPLEMENTATION]`

Team-owned. Navya does not define the placement problem and does not modify it.

### 3.5 Optimization / QUBO layer `[TEAM IMPLEMENTATION]`

Team-owned and load-bearing. **Navya has not modified, and will not modify, the QUBO encoding,
the site-utility formulation, or any optimization logic.** Where integration required an
optimization change, Navya documented the requirement instead of making it.

### 3.6 Candidate sensor configuration `[TEAM IMPLEMENTATION]`

Team-owned result. Navya neither produces nor evaluates it.

---

## 4. The current integration wall

> **Existing optimization currently requires forecast_id. Additional forecast-derived risk
> fields require team-owner integration.**

The team's optimization input accepts `forecast_id` and nothing else. The running contract has
no slot for:

- data provenance
- metric split
- threshold policy
- residual sigma / uncertainty

the response was to ship the contract and the adapter without touching the team's schema:

| forecasting-side artefact | File | Purpose |
|---|---|---|
| `toExistingOptimizationPayload` | `backend/src/features/forecasting/contract.ts` | Maps onto the team's accepted shape |
| `toProposedForecastHandoff` | same | The richer shape, for when a team owner extends the schema |
| `FIELDS_REQUIRING_INTEGRATION` | same | The explicit, enumerable list of what cannot cross yet |
| `buildCandidateRiskMapping` | `candidate-risk.ts` | The station→reach risk mapping, as a **validated specification** with declared blockers |

`candidate-risk.ts` deliberately does **not** invent station identifiers, coordinates, or the
provenance of `CandidateLocation.floodRisk`. No authoritative station or reach list has been
supplied, so the mapping is modelled as a specification that must be supplied with real
identifiers before it can be used.

---

## 5. Quantum performance — the explicit position

### This work claims no quantum advantage.

Specifically, the work contains:

- **No** claim of quantum speedup
- **No** claim of quantum advantage or superiority
- **No** claim that a quantum solver would outperform a classical one on this problem
- **No** quantum result of any kind — none was produced, measured, simulated, or estimated
- **No** predicted or hoped-for quantum benefit presented as a finding

The research in `docs/forecasting/Research/` treats quantum machine learning as an
**experimental component to be investigated**, explicitly not as an assumed improvement, and
states that it "should be treated as an experimental component rather than assuming in
advance that it will outperform classical models."

### What would be required to make any such claim

1. A real sensor-placement instance at a realistic scale
2. A classical baseline solver, timed
3. A quantum solver, timed, on the same instance
4. Solution quality comparison, not just wall-clock
5. Repetition across multiple instances, with variance reported
6. Quantum resource cost stated alongside the timing

Items 1–6 are entirely team-owned activities. **None has been performed.**

### Actual optimization performance

**Depends entirely on the team's implementation and on real evaluation.** This work has no
visibility into the team's solver performance and makes no statement about it.
