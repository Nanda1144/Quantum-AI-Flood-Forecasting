from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, field_validator, ConfigDict

class SensorIngestPayload(BaseModel):
    sensor_id: str = Field(..., alias="sensor_id", json_schema_extra={"example": "S101"}, description="Sensor code string (e.g. S101)")
    water_level: float = Field(..., json_schema_extra={"example": 5.4}, description="Water level in meters")
    rainfall: float = Field(..., json_schema_extra={"example": 42.0}, description="Precipitation in mm")
    flow_rate: float = Field(..., json_schema_extra={"example": 3.1}, description="Flow rate in m^3/s")
    temperature: float = Field(..., json_schema_extra={"example": 29.0}, description="Ambient temperature in Celsius")
    timestamp: Optional[datetime] = Field(default=None, description="Telemetry timestamp (ISO 8601)")

    @field_validator("water_level")
    @classmethod
    def validate_water_level(cls, v: float) -> float:
        if v < 0:
            raise ValueError("water_level must be non-negative")
        if v > 100:
            raise ValueError("water_level exceeds maximum physically plausible value (100m)")
        return round(v, 2)

    @field_validator("rainfall")
    @classmethod
    def validate_rainfall(cls, v: float) -> float:
        if v < 0:
            raise ValueError("rainfall must be non-negative")
        return round(v, 2)

    @field_validator("flow_rate")
    @classmethod
    def validate_flow_rate(cls, v: float) -> float:
        if v < 0:
            raise ValueError("flow_rate must be non-negative")
        return round(v, 2)

    @field_validator("temperature")
    @classmethod
    def validate_temperature(cls, v: float) -> float:
        if v < -60 or v > 80:
            raise ValueError("temperature value out of sensor operational limits (-60 to 80 ┬░C)")
        return round(v, 2)

    model_config = ConfigDict(
        populate_by_name=True,
        json_schema_extra={
            "example": {
                "sensor_id": "S101",
                "water_level": 5.4,
                "rainfall": 42.0,
                "flow_rate": 3.1,
                "temperature": 29.0,
                "timestamp": "2026-09-20T10:30:00"
            }
        }
    )

class SensorDataResponse(BaseModel):
    id: int
    sensor_id: int
    sensor_code: str
    location_name: Optional[str] = None
    water_level: float
    rainfall: float
    flow_rate: float
    temperature: float
    risk_level: str
    status: str = "ACTIVE"
    recorded_at: datetime

    model_config = ConfigDict(from_attributes=True)

class ProcessedSensorDataResponse(BaseModel):
    id: int
    sensor_id: int
    status: str
    risk_level: str
    processed_at: datetime

    model_config = ConfigDict(from_attributes=True)

