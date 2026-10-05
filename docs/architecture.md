# Quantum-AI Flood Forecasting - Architecture Documentation

## Overview

The **Sensor Data Management & Flood Simulation Module** handles end-to-end telemetry ingestion, background flood simulation generation, real-time risk assessment, data persistence, and interactive dashboard visualization.

```
                    +-----------------------------------------+
                    |  Flood & Sensor Simulation Engine       |
                    |  - 5-second background loop             |
                    |  - Scenarios: NORMAL / MODERATE_RAIN /  |
                    |    HEAVY_RAIN / CRITICAL_FLOOD          |
                    +--------------------+--------------------+
                                         |
                                         | Ingest Telemetry
                                         v
                    +--------------------+--------------------+
                    |   FastAPI Ingestion Gateway            |
                    |   - Pydantic Schema Validator          |
                    |   - Risk Rules Engine (evaluate_risk)  |
                    +--------------------+--------------------+
                                         |
            +----------------------------+----------------------------+
            |                                                         |
            v                                                         v
+-----------+-----------------------+                     +-----------+-----------------------+
| PostgreSQL / Supabase Database    |                     | React + Tailwind Dashboard        |
| - sensors                         |  GET /api/*         | - 5s Auto Refresh Cycle           |
| - sensor_data                     | <------------------ | - Simulation Control Panel        |
| - processed_sensor_data           |                     | - Simulation Analytics Cards      |
| - simulation_sessions (NEW)       |                     | - Real-time Telemetry Table       |
| - simulation_logs (NEW)           |                     +-----------------------------------+
+-----------------------------------+
```

## Scenario Definitions

| Scenario Mode | Water Level (m) | Rainfall (mm) | Flow Rate (m³/s) | Expected Risk |
|---|---|---|---|---|
| **NORMAL** | 0.5 – 2.0 | 0 – 15 | 0.5 – 1.5 | `LOW` |
| **MODERATE_RAIN** | 2.0 – 4.0 | 15 – 35 | 1.5 – 3.0 | `MEDIUM` |
| **HEAVY_RAIN** | 4.0 – 6.0 | 35 – 60 | 3.0 – 5.0 | `HIGH` |
| **CRITICAL_FLOOD** | 6.0 – 10.0 | 60 – 120 | 5.0 – 10.0 | `CRITICAL` |

---

## Data Pipeline Flow

1. **Simulation Generator**: Generates realistic telemetry within selected scenario boundaries every 5 seconds.
2. **Pydantic Validation**: Validates payload structure and data types (`SensorIngestPayload`).
3. **Risk Processing**: Evaluates risk level (`evaluate_risk_level`) and operational status (`determine_sensor_status`).
4. **Database Persistence**: Writes to `sensor_data`, `processed_sensor_data`, and `simulation_logs`.
5. **Dashboard Visualization**: Frontend automatically polls status and telemetry data every 5 seconds to provide real-time monitoring.
