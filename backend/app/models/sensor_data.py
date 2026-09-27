from datetime import datetime, timezone
from sqlalchemy import Column, Integer, Float, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from app.database import Base

class SensorData(Base):
    __tablename__ = "sensor_data"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    sensor_id = Column(Integer, ForeignKey("sensors.id", ondelete="CASCADE"), nullable=False, index=True)
    water_level = Column(Float, nullable=False)
    rainfall = Column(Float, nullable=False)
    flow_rate = Column(Float, nullable=False)
    temperature = Column(Float, nullable=False)
    risk_level = Column(String(20), nullable=False, index=True)
    recorded_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True)

    # Relationship
    sensor = relationship("Sensor", back_populates="readings")
