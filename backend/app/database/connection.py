import os
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.models.data import Base

# Load environment variables explicitly from backend/.env
ENV_PATH = Path(__file__).resolve().parent.parent.parent / ".env"
if ENV_PATH.exists():
    load_dotenv(dotenv_path=ENV_PATH)
else:
    load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise ValueError(
        "DATABASE_URL is not set in backend/.env. "
        "Please provide a valid DATABASE_URL (e.g., sqlite:///./qflare.db or postgresql+psycopg2://USER:PASSWORD@HOST:PORT/DATABASE)."
    )

connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False

engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def test_connection():
    try:
        with engine.connect() as connection:
            result = connection.execute(text("SELECT 1"))
            return result.scalar()
    except Exception as exc:
        raise RuntimeError(
            f"Database connection test failed. Ensure DATABASE_URL in backend/.env is valid and reachable. Error: {exc}"
        ) from exc


def create_tables():
    try:
        Base.metadata.create_all(bind=engine)
    except Exception as exc:
        print(f"Warning: Failed to create database tables: {exc}")
        raise RuntimeError(
            f"Could not initialize database schema. Check DATABASE_URL in backend/.env. Details: {exc}"
        ) from exc