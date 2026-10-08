import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from iot.config import settings
from iot.database import engine, Base
from iot.api.routes import router as api_router
from iot.sensors.sensor_service import seed_initial_sensors_and_data
from iot.database import SessionLocal

# Setup logging
logging.basicConfig(
    level=settings.LOG_LEVEL,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("sensor_module")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan context manager for startup and shutdown actions."""
    logger.info("Initializing database tables...")
    Base.metadata.create_all(bind=engine)
    
    # Pre-seed initial sample sensors for immediate functionality
    try:
        db = SessionLocal()
        seed_initial_sensors_and_data(db)
        db.close()
        logger.info("Database initialized and initial seed verified.")
    except Exception as e:
        logger.warning(f"Auto-seed notification: {e}")
        
    yield
    logger.info("Shutting down Sensor Data Module API application...")

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="Production-Ready Sensor Data Management Module for Quantum-AI Flood Forecasting & Disaster Response Platform",
    lifespan=lifespan
)

# Enable CORS for frontend dashboard access
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Exception handlers
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception during request {request.url}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "An internal server error occurred processing sensor request."}
    )

# Register API router
app.include_router(api_router, prefix=settings.API_PREFIX)

@app.get("/health", tags=["Health"])
def health_check():
    return {
        "status": "healthy",
        "service": settings.PROJECT_NAME,
        "database_mode": settings.DATABASE_MODE,
        "version": settings.VERSION
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)

