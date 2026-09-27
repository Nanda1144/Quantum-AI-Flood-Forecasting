import os
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    PROJECT_NAME: str = "Quantum-AI Flood Data Platform"
    VERSION: str = "1.0.0"
    API_PREFIX: str = "/api"
    
    # Database Settings
    DATABASE_MODE: str = os.getenv("DATABASE_MODE", "postgres")
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL", 
        "sqlite:///./sensor_data.db"  # Fallback SQLite for local dev & testing if postgres env is unset
    )
    
    # Server & CORS
    LOG_LEVEL: str = "INFO"
    CORS_ORIGINS: List[str] = [
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3000",
        "*"
    ]

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()
