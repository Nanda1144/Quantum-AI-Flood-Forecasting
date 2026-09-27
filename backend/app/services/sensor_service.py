from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import func, desc

from app.models.sensor import Sensor
from app.models.sensor_data import SensorData
from app.models.processed_data import ProcessedSensorData
from app.schemas.sensor_data import SensorIngestPayload, SensorDataResponse
from app.schemas.dashboard import DashboardSummaryResponse, RiskDistribution
from app.services.risk_processor import evaluate_risk_level, determine_sensor_status

def get_or_create_sensor(db: Session, sensor_code: str) -> Sensor:
    """Finds existing sensor by code or auto-registers a new sensor entry."""
    sensor = db.query(Sensor).filter(Sensor.sensor_code == sensor_code).first()
    if not sensor:
        sensor = Sensor(
            sensor_code=sensor_code,
            location_name=f"Monitoring Station {sensor_code}",
            latitude=28.6139 + (hash(sensor_code) % 100) / 1000.0,
            longitude=77.2090 + (hash(sensor_code) % 100) / 1000.0,
            sensor_type="FLOOD_MONITOR"
        )
        db.add(sensor)
        db.commit()
        db.refresh(sensor)
    return sensor

def ingest_sensor_reading(db: Session, payload: SensorIngestPayload) -> SensorDataResponse:
    """Processes incoming sensor payload, saves to raw & processed tables, returns enriched response."""
    sensor = get_or_create_sensor(db, payload.sensor_id)
    
    # Process risk & status
    risk_level = evaluate_risk_level(payload.water_level)
    status = determine_sensor_status(risk_level)
    recorded_at = payload.timestamp or datetime.now(timezone.utc)

    # Save raw telemetry
    raw_entry = SensorData(
        sensor_id=sensor.id,
        water_level=payload.water_level,
        rainfall=payload.rainfall,
        flow_rate=payload.flow_rate,
        temperature=payload.temperature,
        risk_level=risk_level,
        recorded_at=recorded_at
    )
    db.add(raw_entry)

    # Save processed telemetry status
    processed_entry = ProcessedSensorData(
        sensor_id=sensor.id,
        status=status,
        risk_level=risk_level,
        processed_at=recorded_at
    )
    db.add(processed_entry)
    
    db.commit()
    db.refresh(raw_entry)

    return SensorDataResponse(
        id=raw_entry.id,
        sensor_id=sensor.id,
        sensor_code=sensor.sensor_code,
        location_name=sensor.location_name,
        water_level=raw_entry.water_level,
        rainfall=raw_entry.rainfall,
        flow_rate=raw_entry.flow_rate,
        temperature=raw_entry.temperature,
        risk_level=raw_entry.risk_level,
        status=status,
        recorded_at=raw_entry.recorded_at
    )

def get_all_sensors(db: Session) -> List[Sensor]:
    """Retrieves all registered sensors sorted by creation date."""
    return db.query(Sensor).order_by(Sensor.created_at.desc()).all()

def get_latest_sensor_readings(db: Session) -> List[SensorDataResponse]:
    """Retrieves the most recent telemetry reading for each registered sensor."""
    sensors = db.query(Sensor).all()
    results = []
    
    for s in sensors:
        latest_reading = (
            db.query(SensorData)
            .filter(SensorData.sensor_id == s.id)
            .order_by(SensorData.recorded_at.desc())
            .first()
        )
        if latest_reading:
            latest_processed = (
                db.query(ProcessedSensorData)
                .filter(ProcessedSensorData.sensor_id == s.id)
                .order_by(ProcessedSensorData.processed_at.desc())
                .first()
            )
            status = latest_processed.status if latest_processed else "ACTIVE"
            
            results.append(
                SensorDataResponse(
                    id=latest_reading.id,
                    sensor_id=s.id,
                    sensor_code=s.sensor_code,
                    location_name=s.location_name,
                    water_level=latest_reading.water_level,
                    rainfall=latest_reading.rainfall,
                    flow_rate=latest_reading.flow_rate,
                    temperature=latest_reading.temperature,
                    risk_level=latest_reading.risk_level,
                    status=status,
                    recorded_at=latest_reading.recorded_at
                )
            )
    return results

def get_dashboard_summary(db: Session) -> DashboardSummaryResponse:
    """Calculates aggregate dashboard metrics across all sensors."""
    sensors = get_all_sensors(db)
    total_sensors = len(sensors)
    
    latest_readings = get_latest_sensor_readings(db)
    
    if not latest_readings:
        return DashboardSummaryResponse(
            total_sensors=total_sensors,
            latest_water_level=0.0,
            highest_risk_level="LOW",
            total_rainfall=0.0,
            risk_distribution=RiskDistribution(),
            latest_readings=[]
        )
    
    latest_water_level = max(r.water_level for r in latest_readings)
    total_rainfall = round(sum(r.rainfall for r in latest_readings), 2)
    
    dist = {"LOW": 0, "MEDIUM": 0, "HIGH": 0, "CRITICAL": 0}
    risk_severity_order = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}
    highest_severity = 1
    highest_risk_str = "LOW"
    
    for r in latest_readings:
        if r.risk_level in dist:
            dist[r.risk_level] += 1
        sev = risk_severity_order.get(r.risk_level, 1)
        if sev > highest_severity:
            highest_severity = sev
            highest_risk_str = r.risk_level

    risk_dist = RiskDistribution(**dist)
    
    return DashboardSummaryResponse(
        total_sensors=total_sensors,
        latest_water_level=latest_water_level,
        highest_risk_level=highest_risk_str,
        total_rainfall=total_rainfall,
        risk_distribution=risk_dist,
        latest_readings=latest_readings
    )

def seed_initial_sensors_and_data(db: Session):
    """Utility function to populate initial seed records if the DB is empty."""
    if db.query(Sensor).count() > 0:
        return
    
    seed_sensors = [
        {"sensor_code": "S101", "location_name": "North River Basin - Sector 4", "latitude": 28.6139, "longitude": 77.2090},
        {"sensor_code": "S102", "location_name": "East Reservoir Dam Gate 2", "latitude": 28.7041, "longitude": 77.1025},
        {"sensor_code": "S103", "location_name": "South Delta Canal Entry", "latitude": 28.5355, "longitude": 77.3910},
        {"sensor_code": "S104", "location_name": "West Tributary Bridge 9", "latitude": 28.4595, "longitude": 77.0266},
    ]
    
    initial_readings = [
        {"sensor_id": "S101", "water_level": 5.4, "rainfall": 42.0, "flow_rate": 3.1, "temperature": 29.0},
        {"sensor_id": "S102", "water_level": 2.5, "rainfall": 18.0, "flow_rate": 1.8, "temperature": 27.5},
        {"sensor_id": "S103", "water_level": 6.8, "rainfall": 65.0, "flow_rate": 5.2, "temperature": 30.0},
        {"sensor_id": "S104", "water_level": 1.2, "rainfall": 5.0, "flow_rate": 0.9, "temperature": 26.0},
    ]

    for s_data in seed_sensors:
        s = Sensor(**s_data, sensor_type="FLOOD_MONITOR")
        db.add(s)
    db.commit()

    for r_data in initial_readings:
        payload = SensorIngestPayload(**r_data)
        ingest_sensor_reading(db, payload)
