from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from iot.database import Base

class SimulationSession(Base):
    __tablename__ = "simulation_sessions"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    scenario = Column(String(50), nullable=False)
    status = Column(String(20), nullable=False, default="RUNNING", index=True)
    started_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    stopped_at = Column(DateTime, nullable=True)

    # Relationships
    logs = relationship("SimulationLog", back_populates="session", cascade="all, delete-orphan")


class SimulationLog(Base):
    __tablename__ = "simulation_logs"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    session_id = Column(Integer, ForeignKey("simulation_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    sensor_id = Column(Integer, ForeignKey("sensors.id", ondelete="CASCADE"), nullable=False, index=True)
    water_level = Column(Float, nullable=False)
    rainfall = Column(Float, nullable=False)
    flow_rate = Column(Float, nullable=False)
    generated_risk = Column(String(20), nullable=False)
    generated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True)

    # Relationships
    session = relationship("SimulationSession", back_populates="logs")
    sensor = relationship("Sensor")

