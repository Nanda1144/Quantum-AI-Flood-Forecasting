# gis

Geospatial data module for Q-FLARE (basins, catchments, candidate sensor
sites).

> **Status:** implementation planned. The **consuming contract is already
> defined and live** in the backend optimization stack (below) — this module
> will grow from a folder + contract into the service that fulfils it.

## What the platform already consumes

The optimization orchestrator (`backend/src/services/optimization-orchestrator.service.ts`)
feeds every run from two federated sources, defined in
`backend/src/services/gis/candidate-store.ts`:

| Source | Interface | Supplies |
| --- | --- | --- |
| Candidate sites | `CandidateStore.getCandidates({ reference, count })` | `CandidateLocation[]` — `id`, `name`, `zone`, `latitude`/`longitude`, `floodRisk`, `populationExposure`, `infrastructureCriticality`, `communicationScore`, `sensorCostK`, `coverageRadiusKm` |
| Planning constraints | `ConstraintsSource.getConstraints({ maxSensors, budgetK, coverageRequirements, candidateCount })` | `ResourceConstraintsInput` — sensor budget, budget cap, coverage floors |

The orchestrator addresses candidates by a **reference** URI, e.g.
`gis://candidates/24`, and the frontend preview surfaces the same data via
`GET /api/optimization/inputs` (candidate count + forecast + risk). Results
persist **location IDs/references only** — the GIS module stays the
authoritative owner of spatial data (a key schema rule; see
`../database/README.md`).

Today a **deterministic generator stand-in** fills both sources so the
end-to-end pipeline runs without a live GIS service. It is seeded by the
reference and count (`mulberry32(hashString(reference))`), mirrors the
frontend simulator (`frontend/src/services/optimization/simulate.ts`), and is
labelled `GIS module (server)` in provenance — a generated stand-in is never
presented as real survey data.

## Planned scope

- Station coordinates, catchment polygons, elevation and land-use layers
  feeding the flood models.
- A real implementation of `CandidateStore`/`ConstraintsSource` behind the same
  interfaces (swap the stand-in without touching the orchestrator).
- Web-map layers for the command-center UI.

## Implementation pointer

To replace the stand-in: implement
`backend/src/services/gis/candidate-store.ts`'s two interfaces from a real
store (PostGIS) and swap the binding in `backend/src/container.ts`
(`candidates`/`constraints`). Everything else — pipeline, persistence, UI —
keeps working unchanged against the same contract.