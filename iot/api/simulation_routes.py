from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from iot.database import get_db
from iot.schemas.simulation import (
    SimulationStartPayload,
    SimulationStatusResponse,
    SimulationSessionResponse,
    SimulationAnalyticsResponse
)
from iot.simulation.simulation_engine import simulation_engine

router = APIRouter(prefix="/simulation", tags=["Simulation Engine"])

@router.post(
    "/start",
    response_model=SimulationStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Start or Change Flood Simulation Scenario",
    description="Starts the simulation engine with selected scenario (NORMAL, MODERATE_RAIN, HEAVY_RAIN, CRITICAL_FLOOD). Generates sensor reading stream every 5 seconds."
)
def start_simulation(
    payload: SimulationStartPayload,
    db: Session = Depends(get_db)
):
    try:
        simulation_engine.start(payload.scenario, db)
        return simulation_engine.get_status()
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start simulation session: {str(e)}"
        )

@router.post(
    "/stop",
    response_model=SimulationStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Stop Simulation Engine",
    description="Stops the currently running flood simulation session."
)
def stop_simulation(db: Session = Depends(get_db)):
    simulation_engine.stop(db)
    return simulation_engine.get_status()

@router.get(
    "/status",
    response_model=SimulationStatusResponse,
    summary="Get Current Simulation Status",
    description="Returns whether simulation is active, current scenario, total generated records count, and last reading."
)
def get_simulation_status():
    return simulation_engine.get_status()

@router.get(
    "/history",
    response_model=List[SimulationSessionResponse],
    summary="Get Simulation History Sessions",
    description="Returns previous simulation sessions and total generated logs per session."
)
def get_simulation_history(db: Session = Depends(get_db)):
    return simulation_engine.get_history(db)

@router.get(
    "/analytics",
    response_model=SimulationAnalyticsResponse,
    summary="Get Simulation Analytics Summary",
    description="Returns aggregate simulation metrics (total sessions, average water level, average rainfall, highest risk generated)."
)
def get_simulation_analytics(db: Session = Depends(get_db)):
    return simulation_engine.get_analytics(db)

