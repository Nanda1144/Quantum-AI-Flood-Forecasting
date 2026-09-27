from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Float, DateTime
from sqlalchemy.orm import relationship
from app.database import Base

class Sensor(Base):
    __tablename__ = "sensors"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    sensor_code = Column(String(50), unique=True, nullable=False, index=True)
    location_name = Column(String(255), nullable=False)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    sensor_type = Column(String(100), nullable=False, default="FLOOD_MONITOR")
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    # Relationships
    readings = relationship("SensorData", back_populates="sensor", cascade="all, delete-orphan")
    processed_readings = relationship("ProcessedSensorData", back_populates="sensor", cascade="all, delete-orphan")
