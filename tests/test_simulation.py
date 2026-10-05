import pytest
import sys
from pathlib import Path

backend_path = Path(__file__).resolve().parent.parent / "backend"
if str(backend_path) not in sys.path:
    sys.path.insert(0, str(backend_path))

from app.services.simulation_service import simulation_engine, SCENARIO_CONFIGS
from app.models.simulation import SimulationSession, SimulationLog
from app.models.sensor_data import SensorData

def test_scenario_configs():
    assert "NORMAL" in SCENARIO_CONFIGS
    assert "MODERATE_RAIN" in SCENARIO_CONFIGS
    assert "HEAVY_RAIN" in SCENARIO_CONFIGS
    assert "CRITICAL_FLOOD" in SCENARIO_CONFIGS

    assert SCENARIO_CONFIGS["NORMAL"]["water_max"] < 2.0
    assert SCENARIO_CONFIGS["MODERATE_RAIN"]["water_min"] >= 2.0
    assert SCENARIO_CONFIGS["HEAVY_RAIN"]["water_min"] >= 4.0
    assert SCENARIO_CONFIGS["CRITICAL_FLOOD"]["water_min"] >= 6.0

def test_simulation_engine_start_stop(db_session):
    # Start NORMAL scenario
    session = simulation_engine.start("NORMAL", db_session)
    assert session.id is not None
    assert session.scenario == "NORMAL"
    assert session.status == "RUNNING"
    assert simulation_engine.is_running is True

    status = simulation_engine.get_status()
    assert status.running is True
    assert status.scenario == "NORMAL"

    # Stop simulation
    stopped_session = simulation_engine.stop(db_session)
    assert stopped_session is not None
    assert stopped_session.status == "STOPPED"
    assert simulation_engine.is_running is False

def test_simulation_tick_generation(db_session):
    # Start CRITICAL_FLOOD scenario
    simulation_engine.start("CRITICAL_FLOOD", db_session)

    # Generate single tick manually with session injection
    tick = simulation_engine.generate_single_tick("S101", db_session)
    assert tick is not None
    assert tick["sensor_code"] == "S101"
    assert tick["water_level"] >= 6.0
    assert tick["generated_risk"] == "CRITICAL"

    # Verify database log entry in simulation_logs
    log = db_session.query(SimulationLog).filter(SimulationLog.session_id == simulation_engine.get_status().current_session_id).first()
    assert log is not None
    assert log.water_level >= 6.0
    assert log.generated_risk == "CRITICAL"

    # Verify integration with existing raw telemetry table (sensor_data)
    raw_data = db_session.query(SensorData).order_by(SensorData.id.desc()).first()
    assert raw_data is not None
    assert raw_data.water_level == tick["water_level"]

    simulation_engine.stop(db_session)

def test_api_simulation_endpoints(client):
    # 1. Start simulation
    res_start = client.post("/api/simulation/start", json={"scenario": "HEAVY_RAIN"})
    assert res_start.status_code == 200
    data_start = res_start.json()
    assert data_start["running"] is True
    assert data_start["scenario"] == "HEAVY_RAIN"

    # 2. Get status
    res_status = client.get("/api/simulation/status")
    assert res_status.status_code == 200
    assert res_status.json()["running"] is True

    # 3. Stop simulation
    res_stop = client.post("/api/simulation/stop")
    assert res_stop.status_code == 200
    assert res_stop.json()["running"] is False

    # 4. Get history
    res_history = client.get("/api/simulation/history")
    assert res_history.status_code == 200
    history = res_history.json()
    assert len(history) >= 1
    assert history[0]["scenario"] == "HEAVY_RAIN"

    # 5. Get analytics
    res_analytics = client.get("/api/simulation/analytics")
    assert res_analytics.status_code == 200
    analytics = res_analytics.json()
    assert "total_sessions" in analytics
    assert "avg_water_level" in analytics
