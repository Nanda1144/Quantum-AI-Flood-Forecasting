import pytest
import sys
from pathlib import Path
from pydantic import ValidationError

backend_path = Path(__file__).resolve().parent.parent / "backend"
if str(backend_path) not in sys.path:
    sys.path.insert(0, str(backend_path))

from iot.schemas.sensor_data import SensorIngestPayload

def test_valid_ingest_payload():
    payload_data = {
        "sensor_id": "S101",
        "water_level": 5.4,
        "rainfall": 42.0,
        "flow_rate": 3.1,
        "temperature": 29.0,
        "timestamp": "2026-09-20T10:30:00"
    }
    payload = SensorIngestPayload(**payload_data)
    assert payload.sensor_id == "S101"
    assert payload.water_level == 5.4
    assert payload.rainfall == 42.0
    assert payload.flow_rate == 3.1
    assert payload.temperature == 29.0

def test_missing_required_fields():
    # Missing sensor_id
    with pytest.raises(ValidationError):
        SensorIngestPayload(water_level=5.4, rainfall=42.0, flow_rate=3.1, temperature=29.0)

    # Missing water_level
    with pytest.raises(ValidationError):
        SensorIngestPayload(sensor_id="S101", rainfall=42.0, flow_rate=3.1, temperature=29.0)

def test_negative_water_level_validation():
    with pytest.raises(ValidationError) as excinfo:
        SensorIngestPayload(
            sensor_id="S101",
            water_level=-1.5,
            rainfall=10.0,
            flow_rate=2.0,
            temperature=25.0
        )
    assert "water_level must be non-negative" in str(excinfo.value)

def test_negative_rainfall_validation():
    with pytest.raises(ValidationError) as excinfo:
        SensorIngestPayload(
            sensor_id="S101",
            water_level=2.0,
            rainfall=-5.0,
            flow_rate=2.0,
            temperature=25.0
        )
    assert "rainfall must be non-negative" in str(excinfo.value)

def test_temperature_limits_validation():
    with pytest.raises(ValidationError) as excinfo:
        SensorIngestPayload(
            sensor_id="S101",
            water_level=2.0,
            rainfall=5.0,
            flow_rate=2.0,
            temperature=100.0
        )
    assert "temperature value out of sensor operational limits" in str(excinfo.value)

