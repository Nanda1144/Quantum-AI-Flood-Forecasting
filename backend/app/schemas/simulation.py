from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, field_validator, ConfigDict

class SimulationStartPayload(BaseModel):
    scenario: str = Field(
        ..., 
        json_schema_extra={"example": "CRITICAL_FLOOD"},
        description="Simulation scenario: NORMAL, MODERATE_RAIN, HEAVY_RAIN, or CRITICAL_FLOOD"
    )

    @field_validator("scenario")
    @classmethod
    def validate_and_normalize_scenario(cls, v: str) -> str:
        normalized = v.strip().upper().replace(" ", "_")
        valid_scenarios = {"NORMAL", "MODERATE_RAIN", "HEAVY_RAIN", "CRITICAL_FLOOD"}
        if normalized not in valid_scenarios:
            raise ValueError(
                f"Invalid scenario '{v}'. Must be one of: {', '.join(sorted(valid_scenarios))}"
            )
        return normalized

class SimulationStatusResponse(BaseModel):
    running: bool
    scenario: Optional[str] = None
    generated_records: int = 0
    current_session_id: Optional[int] = None
    last_reading: Optional[Dict[str, Any]] = None

    model_config = ConfigDict(from_attributes=True)

class SimulationSessionResponse(BaseModel):
    id: int
    scenario: str
    status: str
    started_at: datetime
    stopped_at: Optional[datetime] = None
    generated_records: int = 0

    model_config = ConfigDict(from_attributes=True)

class SimulationAnalyticsResponse(BaseModel):
    total_sessions: int = 0
    avg_water_level: float = 0.0
    avg_rainfall: float = 0.0
    highest_risk_generated: str = "LOW"
    total_records_generated: int = 0

    model_config = ConfigDict(from_attributes=True)
