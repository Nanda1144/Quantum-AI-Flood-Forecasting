# API Specifications & Endpoint Reference

Base URL: `http://localhost:8000/api`

---

## 1. Ingest Live Sensor Telemetry
`POST /api/live-sensor`

Receives real-time telemetry from flood monitoring sensors, validates payloads, evaluates risk thresholds, and persists data.

### Request Body
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

### Response (201 Created)
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

## 2. Get Latest Data
`GET /api/latest-data`

Returns the most recent reading and calculated risk level for every registered sensor.

### Response (200 OK)
```json
[
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
]
```

---

## 3. Get All Registered Sensors
`GET /api/sensors`

Returns metadata for all registered flood monitoring sensors.

### Response (200 OK)
```json
[
  {
    "id": 1,
    "sensor_code": "S101",
    "location_name": "North River Basin - Sector 4",
    "latitude": 28.6139,
    "longitude": 77.2090,
    "sensor_type": "ULTRASONIC_LEVEL",
    "created_at": "2026-09-17T10:30:00"
  }
]
```

---

## 4. Get Dashboard Summary
`GET /api/dashboard`

Returns aggregate summary metrics across all registered sensors.

### Response (200 OK)
```json
{
  "total_sensors": 4,
  "latest_water_level": 5.4,
  "highest_risk_level": "HIGH",
  "total_rainfall": 130.0,
  "risk_distribution": {
    "LOW": 1,
    "MEDIUM": 1,
    "HIGH": 1,
    "CRITICAL": 1
  },
  "latest_readings": [...]
}
```

---

## 5. Seed Database
`POST /api/seed`

Utility endpoint to populate initial sensors and telemetry readings.
