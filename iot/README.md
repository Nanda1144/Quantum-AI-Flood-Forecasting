# iot

Sensor / IoT ingestion for Q-FLARE (telemetered water-level and rainfall
readings).

> **Status:** implementation planned. The **consuming contract is defined**
> below so ingestion can be built against a target rather than a blank page.

## What the platform expects

Two consumers depend on observed telemetry:

1. **Forecast freshness** — the backend status model
   (`GET /api/ai/status`, `backend/src/services/status.service.ts`) reports
   `online` / `degraded` / `unavailable` from the latest stored forecast and
   its staleness (`FRESHNESS_STALE_MS`). Live observations keep that record
   fresh.
2. **Dashboard chart** — the AI Analytics forecast time-series
   (`ForecastSection` + `charts/ForecastChart`) plots the stored
   `forecast_series`; observed water level is the ground truth the forecast is
   charted against. Stored forecasts persist in the `forecasts` table
   (`database/`), shared by reference across modules — ingestion must **write
   to the store, never duplicate it**.

## Planned scope

- Ingest telemetered water-level and rainfall readings from station sensors.
- Normalise + timestamp observations into PostgreSQL (the `forecasts`/
  `model_versions` store), feeding the observed-water-level series used by the
  dashboard and by training/forecast models.
- Backfill/hydrology provenance so ingested readings are honest and auditable
  (same pledge as the rest of the platform: no fabricated data).

## Suggested contract shape

Mirror the existing seams: a thin ingestion service exposing e.g.
`postObservation(site, level /*m*/, rainfall /*mm*/)` and an idempotent batch
writer keyed on `(site, reading_time)`, plus a read API the backend can call to
refresh the observed series. Land it in this folder behind the `database/`
tables it targets, following the ownership model in the root `README.md`.