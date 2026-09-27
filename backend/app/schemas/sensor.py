from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict

class SensorBase(BaseModel):
    sensor_code: str = Field(..., json_schema_extra={"example": "S101"}, description="Unique sensor identifier code")
    location_name: str = Field(..., json_schema_extra={"example": "North River Basin - Sector 4"})
    latitude: float = Field(..., ge=-90.0, le=90.0, json_schema_extra={"example": 28.6139})
    longitude: float = Field(..., ge=-180.0, le=180.0, json_schema_extra={"example": 77.2090})
    sensor_type: str = Field(default="FLOOD_MONITOR", json_schema_extra={"example": "ULTRASONIC_LEVEL"})

class SensorCreate(SensorBase):
    pass

class SensorResponse(SensorBase):
    id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
