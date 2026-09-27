from typing import List, Dict
from pydantic import BaseModel, ConfigDict
from app.schemas.sensor_data import SensorDataResponse

class RiskDistribution(BaseModel):
    LOW: int = 0
    MEDIUM: int = 0
    HIGH: int = 0
    CRITICAL: int = 0

class DashboardSummaryResponse(BaseModel):
    total_sensors: int
    latest_water_level: float
    highest_risk_level: str
    total_rainfall: float
    risk_distribution: RiskDistribution
    latest_readings: List[SensorDataResponse]

    model_config = ConfigDict(from_attributes=True)
