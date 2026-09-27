def test_post_live_sensor(client):
    payload = {
        "sensor_id": "S101",
        "water_level": 5.4,
        "rainfall": 42.0,
        "flow_rate": 3.1,
        "temperature": 29.0,
        "timestamp": "2026-09-20T10:30:00"
    }
    response = client.post("/api/live-sensor", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["sensor_code"] == "S101"
    assert data["water_level"] == 5.4
    assert data["risk_level"] == "HIGH"
    assert data["status"] == "ACTIVE"

def test_get_sensors(client):
    # Ingest data to populate DB
    payload = {
        "sensor_id": "S102",
        "water_level": 1.5,
        "rainfall": 5.0,
        "flow_rate": 1.0,
        "temperature": 25.0
    }
    client.post("/api/live-sensor", json=payload)

    response = client.get("/api/sensors")
    assert response.status_code == 200
    sensors = response.json()
    assert len(sensors) >= 1
    codes = [s["sensor_code"] for s in sensors]
    assert "S102" in codes

def test_get_latest_data(client):
    payload = {
        "sensor_id": "S103",
        "water_level": 6.5,
        "rainfall": 60.0,
        "flow_rate": 4.5,
        "temperature": 31.0
    }
    client.post("/api/live-sensor", json=payload)

    response = client.get("/api/latest-data")
    assert response.status_code == 200
    readings = response.json()
    assert len(readings) >= 1
    s103_reading = next(r for r in readings if r["sensor_code"] == "S103")
    assert s103_reading["water_level"] == 6.5
    assert s103_reading["risk_level"] == "CRITICAL"
    assert s103_reading["status"] == "CRITICAL"

def test_get_dashboard_summary(client):
    client.post("/api/live-sensor", json={
        "sensor_id": "S101",
        "water_level": 5.4,
        "rainfall": 42.0,
        "flow_rate": 3.1,
        "temperature": 29.0
    })
    client.post("/api/live-sensor", json={
        "sensor_id": "S102",
        "water_level": 1.2,
        "rainfall": 5.0,
        "flow_rate": 0.8,
        "temperature": 24.0
    })

    response = client.get("/api/dashboard")
    assert response.status_code == 200
    dash = response.json()
    assert dash["total_sensors"] >= 2
    assert dash["latest_water_level"] == 5.4
    assert dash["highest_risk_level"] == "HIGH"
    assert dash["total_rainfall"] == 47.0
    assert dash["risk_distribution"]["HIGH"] >= 1
    assert dash["risk_distribution"]["LOW"] >= 1
