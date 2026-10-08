import pytest
import sys
from pathlib import Path

backend_path = Path(__file__).resolve().parent.parent / "backend"
if str(backend_path) not in sys.path:
    sys.path.insert(0, str(backend_path))

from iot.sensors.risk_processor import evaluate_risk_level, determine_sensor_status, process_raw_sensor_data

def test_risk_level_low():
    assert evaluate_risk_level(0.0) == "LOW"
    assert evaluate_risk_level(1.99) == "LOW"

def test_risk_level_medium():
    assert evaluate_risk_level(2.0) == "MEDIUM"
    assert evaluate_risk_level(3.5) == "MEDIUM"
    assert evaluate_risk_level(3.99) == "MEDIUM"

def test_risk_level_high():
    assert evaluate_risk_level(4.0) == "HIGH"
    assert evaluate_risk_level(5.4) == "HIGH"
    assert evaluate_risk_level(5.99) == "HIGH"

def test_risk_level_critical():
    assert evaluate_risk_level(6.0) == "CRITICAL"
    assert evaluate_risk_level(8.5) == "CRITICAL"
    assert evaluate_risk_level(12.0) == "CRITICAL"

def test_determine_sensor_status():
    assert determine_sensor_status("LOW") == "ACTIVE"
    assert determine_sensor_status("MEDIUM") == "ACTIVE"
    assert determine_sensor_status("HIGH") == "ACTIVE"
    assert determine_sensor_status("CRITICAL") == "CRITICAL"

def test_process_raw_sensor_data():
    output = process_raw_sensor_data(water_level=5.4, rainfall=42.0)
    assert output == {
        "water_level": 5.4,
        "rainfall": 42.0,
        "risk_level": "HIGH",
        "status": "ACTIVE"
    }

