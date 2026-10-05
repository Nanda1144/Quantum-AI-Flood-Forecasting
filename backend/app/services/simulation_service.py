import asyncio
import random
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import SessionLocal
from app.models.sensor import Sensor
from app.models.simulation import SimulationSession, SimulationLog
from app.schemas.sensor_data import SensorIngestPayload
from app.schemas.simulation import (
    SimulationStatusResponse, 
    SimulationSessionResponse, 
    SimulationAnalyticsResponse
)
from app.services import sensor_service

logger = logging.getLogger("sensor_module.simulation")

# Scenario boundary definitions
SCENARIO_CONFIGS = {
    "NORMAL": {
        "water_min": 0.5, "water_max": 1.99,
        "rain_min": 0.0, "rain_max": 15.0,
        "flow_min": 0.5, "flow_max": 1.5,
        "expected_risk": "LOW"
    },
    "MODERATE_RAIN": {
        "water_min": 2.0, "water_max": 3.99,
        "rain_min": 15.0, "rain_max": 35.0,
        "flow_min": 1.5, "flow_max": 3.0,
        "expected_risk": "MEDIUM"
    },
    "HEAVY_RAIN": {
        "water_min": 4.0, "water_max": 5.99,
        "rain_min": 35.0, "rain_max": 60.0,
        "flow_min": 3.0, "flow_max": 5.0,
        "expected_risk": "HIGH"
    },
    "CRITICAL_FLOOD": {
        "water_min": 6.0, "water_max": 10.0,
        "rain_min": 60.0, "rain_max": 120.0,
        "flow_min": 5.0, "flow_max": 10.0,
        "expected_risk": "CRITICAL"
    }
}


class SimulationEngineManager:
    def __init__(self):
        self._is_running = False
        self._current_scenario: Optional[str] = None
        self._current_session_id: Optional[int] = None
        self._task: Optional[asyncio.Task] = None
        self._generated_records_count = 0
        self._last_reading: Optional[Dict[str, Any]] = None

    @property
    def is_running(self) -> bool:
        return self._is_running

    @property
    def current_scenario(self) -> Optional[str]:
        return self._current_scenario

    @property
    def generated_records_count(self) -> int:
        return self._generated_records_count

    def start(self, scenario: str, db: Session) -> SimulationSession:
        """Starts or switches scenario for simulation engine."""
        scenario = scenario.upper().replace(" ", "_")
        if scenario not in SCENARIO_CONFIGS:
            raise ValueError(f"Unknown scenario '{scenario}'. Allowed: {list(SCENARIO_CONFIGS.keys())}")

        # If already running with same scenario, return active session
        if self._is_running and self._current_scenario == scenario and self._current_session_id:
            session = db.get(SimulationSession, self._current_session_id)
            if session:
                return session

        # Stop previous running session if any
        if self._is_running:
            self._stop_session_in_db(db)

        # Create new DB session record
        new_session = SimulationSession(
            scenario=scenario,
            status="RUNNING",
            started_at=datetime.now(timezone.utc)
        )
        db.add(new_session)
        db.commit()
        db.refresh(new_session)

        self._current_scenario = scenario
        self._current_session_id = new_session.id
        self._generated_records_count = 0
        self._is_running = True

        # Launch background generation task if not already scheduled
        if not self._task or self._task.done():
            try:
                loop = asyncio.get_running_loop()
                self._task = loop.create_task(self._run_loop())
            except RuntimeError:
                pass

        logger.info(f"Simulation engine started in '{scenario}' mode (Session ID: {new_session.id})")
        return new_session

    def stop(self, db: Session) -> Optional[SimulationSession]:
        """Stops running simulation session."""
        if not self._is_running and not self._current_session_id:
            return None

        session = self._stop_session_in_db(db)
        self._is_running = False
        self._current_scenario = None
        self._current_session_id = None

        if self._task and not self._task.done():
            self._task.cancel()
            self._task = None

        logger.info("Simulation engine stopped.")
        return session

    def _stop_session_in_db(self, db: Session) -> Optional[SimulationSession]:
        if not self._current_session_id:
            return None
        session = db.get(SimulationSession, self._current_session_id)
        if session and session.status == "RUNNING":
            session.status = "STOPPED"
            session.stopped_at = datetime.now(timezone.utc)
            db.commit()
            db.refresh(session)
        return session

    async def _run_loop(self):
        """Continuous background task generating synthetic telemetry every 5 seconds."""
        sensor_codes = ["S101", "S102", "S103", "S104", "S105"]
        sensor_index = 0

        while self._is_running:
            try:
                await asyncio.sleep(5)
                if not self._is_running or not self._current_scenario:
                    break

                sensor_code = sensor_codes[sensor_index % len(sensor_codes)]
                sensor_index += 1

                self.generate_single_tick(sensor_code)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in simulation loop tick: {e}", exc_info=True)

    def generate_single_tick(self, sensor_code: str = "S101", db: Optional[Session] = None) -> Optional[Dict[str, Any]]:
        """Generates one telemetry reading tick for simulation, persists in pipeline and simulation_logs."""
        if not self._current_scenario or not self._current_session_id:
            return None

        cfg = SCENARIO_CONFIGS.get(self._current_scenario, SCENARIO_CONFIGS["NORMAL"])

        # Randomize values within scenario boundaries
        water_level = round(random.uniform(cfg["water_min"], cfg["water_max"]), 2)
        rainfall = round(random.uniform(cfg["rain_min"], cfg["rain_max"]), 1)
        flow_rate = round(random.uniform(cfg["flow_min"], cfg["flow_max"]), 2)
        temperature = round(random.uniform(24.0, 32.0), 1)

        close_db_on_exit = False
        if db is None:
            db = SessionLocal()
            close_db_on_exit = True

        try:
            # 1. Pipeline integration: Ingest through standard sensor_service (Pydantic validation, Risk processor)
            payload = SensorIngestPayload(
                sensor_id=sensor_code,
                water_level=water_level,
                rainfall=rainfall,
                flow_rate=flow_rate,
                temperature=temperature,
                timestamp=datetime.now(timezone.utc)
            )
            ingested_response = sensor_service.ingest_sensor_reading(db, payload)

            # 2. Database integration: Record entry into simulation_logs table
            sensor = db.query(Sensor).filter(Sensor.sensor_code == sensor_code).first()
            if sensor and self._current_session_id:
                log_entry = SimulationLog(
                    session_id=self._current_session_id,
                    sensor_id=sensor.id,
                    water_level=water_level,
                    rainfall=rainfall,
                    flow_rate=flow_rate,
                    generated_risk=ingested_response.risk_level,
                    generated_at=ingested_response.recorded_at
                )
                db.add(log_entry)
                db.commit()

            self._generated_records_count += 1
            self._last_reading = {
                "sensor_code": sensor_code,
                "water_level": water_level,
                "rainfall": rainfall,
                "flow_rate": flow_rate,
                "temperature": temperature,
                "generated_risk": ingested_response.risk_level,
                "timestamp": ingested_response.recorded_at.isoformat()
            }
            return self._last_reading
        except Exception as e:
            logger.error(f"Failed to ingest single simulation tick: {e}", exc_info=True)
            return None
        finally:
            if close_db_on_exit:
                db.close()

    def get_status(self) -> SimulationStatusResponse:
        """Returns current running status and session statistics."""
        return SimulationStatusResponse(
            running=self._is_running,
            scenario=self._current_scenario,
            generated_records=self._generated_records_count,
            current_session_id=self._current_session_id,
            last_reading=self._last_reading
        )

    def get_history(self, db: Session) -> List[SimulationSessionResponse]:
        """Returns list of previous simulation sessions with total records generated per session."""
        sessions = db.query(SimulationSession).order_by(SimulationSession.started_at.desc()).all()
        results = []
        for s in sessions:
            rec_count = db.query(func.count(SimulationLog.id)).filter(SimulationLog.session_id == s.id).scalar() or 0
            results.append(
                SimulationSessionResponse(
                    id=s.id,
                    scenario=s.scenario,
                    status=s.status,
                    started_at=s.started_at,
                    stopped_at=s.stopped_at,
                    generated_records=rec_count
                )
            )
        return results

    def get_analytics(self, db: Session) -> SimulationAnalyticsResponse:
        """Calculates aggregate simulation statistics across all historical sessions."""
        total_sessions = db.query(func.count(SimulationSession.id)).scalar() or 0
        total_records = db.query(func.count(SimulationLog.id)).scalar() or 0

        if total_records == 0:
            return SimulationAnalyticsResponse(
                total_sessions=total_sessions,
                avg_water_level=0.0,
                avg_rainfall=0.0,
                highest_risk_generated="LOW",
                total_records_generated=0
            )

        avg_water = db.query(func.avg(SimulationLog.water_level)).scalar() or 0.0
        avg_rain = db.query(func.avg(SimulationLog.rainfall)).scalar() or 0.0

        # Determine highest risk level generated
        risk_severity = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}
        logs = db.query(SimulationLog.generated_risk).distinct().all()
        highest_sev = 1
        highest_risk_str = "LOW"

        for log in logs:
            r_str = log[0]
            sev = risk_severity.get(r_str, 1)
            if sev > highest_sev:
                highest_sev = sev
                highest_risk_str = r_str

        return SimulationAnalyticsResponse(
            total_sessions=total_sessions,
            avg_water_level=round(avg_water, 2),
            avg_rainfall=round(avg_rain, 1),
            highest_risk_generated=highest_risk_str,
            total_records_generated=total_records
        )


# Global singleton simulation manager
simulation_engine = SimulationEngineManager()
