# Quantum-AI Flood Forecasting - Architecture Documentation

## Overview

The **Sensor Data Management Module** handles end-to-end telemetry ingestion, real-time risk assessment, data persistence, and interactive visualization for a flood forecasting platform.

```
                    +--------------------------------+
                    |    IoT Flood Monitoring        |
                    |    Sensors (S101, S102...)     |
                    +---------------+----------------+
                                    |
                                    | REST POST /api/live-sensor
                                    v
                    +---------------+----------------+
                    |   FastAPI Ingestion Gateway    |
                    |   - Pydantic Schema Validator  |
                    |   - Risk Rules Engine          |
                    +---------------+----------------+
                                    |
            +-----------------------+-----------------------+
            |                                               |
            v                                               v
+-----------+-------------------+               +-----------+-------------------+
| PostgreSQL / Supabase         |               | React + Tailwind Dashboard        |
| - sensors (metadata)          |  GET /api/*   | - 10s Auto Refresh Interval      |
| - sensor_data (telemetry)     | <-----------  | - Risk Level Indicators           |
| - processed_sensor_data (risk)|               | - Real-time Telemetry Table       |
+-------------------------------+               +-----------------------------------+
```

## System Components

### 1. Ingestion Layer & Pydantic Validation
- Ingests telemetry payloads: `sensor_id`, `water_level`, `rainfall`, `flow_rate`, `temperature`, `timestamp`.
- Strict validation: non-negative metrics, range bounds on temperature (-60 to +80 °C), physical water level caps (<= 100m).
- Automatic sensor auto-provisioning: If incoming sensor payload references an unregistered `sensor_id`, a new `Sensor` entity is dynamically registered.

### 2. Risk Classification Engine
Calculates severity status based on real-time `water_level`:
- **LOW**: `water_level < 2.0m`
- **MEDIUM**: `2.0m <= water_level < 4.0m`
- **HIGH**: `4.0m <= water_level < 6.0m`
- **CRITICAL**: `water_level >= 6.0m`

Operational Status Mapping:
- `LOW`, `MEDIUM`, `HIGH` -> `ACTIVE`
- `CRITICAL` -> `CRITICAL`

### 3. Database Layer (PostgreSQL / Supabase + SQLAlchemy)
- `sensors`: Stores unique sensor identifiers, location names, and GPS coordinates.
- `sensor_data`: Historical ledger of raw telemetry readings.
- `processed_sensor_data`: Evaluated risk levels and operational status logs.

### 4. Frontend Dashboard (React + Tailwind CSS)
- **Dashboard Cards**: Real-time summary metrics (Total Sensors, Peak Water Level, Cumulative Rainfall, Highest Risk Status).
- **Interactive Sensor Table**: Live list of sensor readings with search filtering by ID or location, risk level pill filters, and timestamp formatting.
- **Auto Refresh**: Background data synchronization every 10 seconds.
- **Interactive Telemetry Simulator**: Ingest Modal allowing users to fire sample payloads directly from UI.
