from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.sensor import SensorResponse
from app.schemas.sensor_data import SensorIngestPayload, SensorDataResponse
from app.schemas.dashboard import DashboardSummaryResponse
from app.services import sensor_service
from app.api.simulation_routes import router as simulation_router

router = APIRouter()

# Include simulation engine sub-router
router.include_router(simulation_router)

@router.post(
    "/live-sensor",
    response_model=SensorDataResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ingest Real-Time Sensor Telemetry",
    description="Receives real-time telemetry from flood monitoring sensors, validates payloads, evaluates risk thresholds, and persists data."
)
def ingest_live_sensor(
    payload: SensorIngestPayload,
    db: Session = Depends(get_db)
):
    try:
        result = sensor_service.ingest_sensor_reading(db, payload)
        return result
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(ve))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to ingest sensor telemetry: {str(e)}"
        )

@router.get(
    "/latest-data",
    response_model=List[SensorDataResponse],
    summary="Get Latest Sensor Readings",
    description="Returns the most recent reading and calculated risk level for every registered sensor."
)
def get_latest_data(db: Session = Depends(get_db)):
    return sensor_service.get_latest_sensor_readings(db)

@router.get(
    "/sensors",
    response_model=List[SensorResponse],
    summary="Get All Registered Sensors",
    description="Returns metadata for all registered flood monitoring sensors."
)
def get_sensors(db: Session = Depends(get_db)):
    return sensor_service.get_all_sensors(db)

@router.get(
    "/dashboard",
    response_model=DashboardSummaryResponse,
    summary="Get Dashboard Summary Metrics",
    description="Returns aggregate metrics including total sensors count, highest water level, rainfall totals, risk distribution, and latest readings."
)
def get_dashboard_summary(db: Session = Depends(get_db)):
    return sensor_service.get_dashboard_summary(db)

@router.post(
    "/seed",
    summary="Seed Initial Sensor Data",
    description="Populates the database with initial sample sensors and readings if empty."
)
def seed_database(db: Session = Depends(get_db)):
    sensor_service.seed_initial_sensors_and_data(db)
    return {"message": "Database successfully seeded with sample sensors and readings."}
