from typing import Tuple, Dict, Any

def evaluate_risk_level(water_level: float) -> str:
    """
    Evaluates flood risk level according to water level thresholds:
    - LOW: water_level < 2
    - MEDIUM: 2 <= water_level < 4
    - HIGH: 4 <= water_level < 6
    - CRITICAL: water_level >= 6
    """
    if water_level < 2.0:
        return "LOW"
    elif 2.0 <= water_level < 4.0:
        return "MEDIUM"
    elif 4.0 <= water_level < 6.0:
        return "HIGH"
    else:
        return "CRITICAL"

def determine_sensor_status(risk_level: str) -> str:
    """
    Maps risk level to operational sensor status.
    - LOW / MEDIUM / HIGH -> ACTIVE
    - CRITICAL -> CRITICAL
    """
    if risk_level == "CRITICAL":
        return "CRITICAL"
    return "ACTIVE"

def process_raw_sensor_data(water_level: float, rainfall: float) -> Dict[str, Any]:
    """
    Converts incoming raw sensor metrics into standardized processed payload with risk assessment.
    """
    risk_level = evaluate_risk_level(water_level)
    status = determine_sensor_status(risk_level)
    return {
        "water_level": water_level,
        "rainfall": rainfall,
        "risk_level": risk_level,
        "status": status
    }
