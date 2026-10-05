# API Specifications & Endpoint Reference

Base URL: `http://localhost:8000/api`

---

## 1. Sensor Telemetry Endpoints

### Ingest Live Sensor Telemetry
`POST /api/live-sensor`

Receives real-time telemetry from flood monitoring sensors, validates payloads, evaluates risk thresholds, and persists data.

#### Request Body
```json
{
  "sensor_id": "S101",
  "water_level": 5.4,
  "rainfall": 42.0,
  "flow_rate": 3.1,
  "temperature": 29.0,
  "timestamp": "2026-09-20T10:30:00"
}
```

#### Response (201 Created)
```json
{
  "id": 1,
  "sensor_id": 1,
  "sensor_code": "S101",
  "location_name": "North River Basin - Sector 4",
  "water_level": 5.4,
  "rainfall": 42.0,
  "flow_rate": 3.1,
  "temperature": 29.0,
  "risk_level": "HIGH",
  "status": "ACTIVE",
  "recorded_at": "2026-09-20T10:30:00"
}
```

---

### Get Latest Data
`GET /api/latest-data`

Returns the most recent reading and calculated risk level for every registered sensor.

---

### Get All Registered Sensors
`GET /api/sensors`

Returns metadata for all registered flood monitoring sensors.

---

### Get Dashboard Summary
`GET /api/dashboard`

Returns aggregate summary metrics across all registered sensors.

---

## 2. Flood & Sensor Simulation Engine Endpoints

### Start or Switch Simulation Scenario
`POST /api/simulation/start`

Starts the continuous 5-second simulation loop with the specified scenario mode (`NORMAL`, `MODERATE_RAIN`, `HEAVY_RAIN`, or `CRITICAL_FLOOD`).

#### Request Body
```json
{
  "scenario": "CRITICAL_FLOOD"
}
```

#### Response (200 OK)
```json
{
  "running": true,
  "scenario": "CRITICAL_FLOOD",
  "generated_records": 0,
  "current_session_id": 1,
  "last_reading": null
}
```

---

### Stop Simulation Engine
`POST /api/simulation/stop`

Stops the active simulation session loop.

#### Response (200 OK)
```json
{
  "running": false,
  "scenario": null,
  "generated_records": 45,
  "current_session_id": null,
  "last_reading": { ... }
}
```

---

### Get Simulation Status
`GET /api/simulation/status`

Returns live engine status, active scenario, session record count, and last generated telemetry reading.

---

### Get Simulation History
`GET /api/simulation/history`

Returns history of previous simulation sessions with total log counts.

---

### Get Simulation Analytics
`GET /api/simulation/analytics`

Returns aggregate analytics across all historical simulation sessions (`total_sessions`, `avg_water_level`, `avg_rainfall`, `highest_risk_generated`, `total_records_generated`).
