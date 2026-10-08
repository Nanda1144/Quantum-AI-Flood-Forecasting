from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from iot.database import Base

class ProcessedSensorData(Base):
    __tablename__ = "processed_sensor_data"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    sensor_id = Column(Integer, ForeignKey("sensors.id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(String(50), nullable=False, default="ACTIVE", index=True)
    risk_level = Column(String(20), nullable=False)
    processed_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True)

    # Relationship
    sensor = relationship("Sensor", back_populates="processed_readings")

