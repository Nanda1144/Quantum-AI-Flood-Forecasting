-- Quantum-AI Flood Forecasting & Disaster Response Platform
-- Database Schema for Sensor Data Management Module
-- Target DB: PostgreSQL (Supabase Compatible)

-- Enable UUID extension if needed
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- -------------------------------------------------------------
-- Table: sensors
-- Stores registered flood monitoring sensors and geographic metadata
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sensors (
    id SERIAL PRIMARY KEY,
    sensor_code VARCHAR(50) UNIQUE NOT NULL,
    location_name VARCHAR(255) NOT NULL,
    latitude DOUBLE PRECISION NOT NULL,
    longitude DOUBLE PRECISION NOT NULL,
    sensor_type VARCHAR(100) NOT NULL DEFAULT 'FLOOD_MONITOR',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

-- Index for fast lookup by sensor code
CREATE INDEX IF NOT EXISTS idx_sensors_code ON sensors(sensor_code);

-- -------------------------------------------------------------
-- Table: sensor_data
-- Stores raw telemetry readings ingested from flood sensors
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sensor_data (
    id SERIAL PRIMARY KEY,
    sensor_id INTEGER NOT NULL REFERENCES sensors(id) ON DELETE CASCADE,
    water_level DOUBLE PRECISION NOT NULL,
    rainfall DOUBLE PRECISION NOT NULL,
    flow_rate DOUBLE PRECISION NOT NULL,
    temperature DOUBLE PRECISION NOT NULL,
    risk_level VARCHAR(20) NOT NULL,
    recorded_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

-- Indexes for sensor_data lookups and analytics
CREATE INDEX IF NOT EXISTS idx_sensor_data_sensor_id ON sensor_data(sensor_id);
CREATE INDEX IF NOT EXISTS idx_sensor_data_recorded_at ON sensor_data(recorded_at DESC);
CREATE INDEX IF NOT EXISTS idx_sensor_data_risk_level ON sensor_data(risk_level);

-- -------------------------------------------------------------
-- Table: processed_sensor_data
-- Stores risk evaluation results and operational status flags
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS processed_sensor_data (
    id SERIAL PRIMARY KEY,
    sensor_id INTEGER NOT NULL REFERENCES sensors(id) ON DELETE CASCADE,
    status VARCHAR(50) NOT NULL DEFAULT 'ACTIVE',
    risk_level VARCHAR(20) NOT NULL,
    processed_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

-- Indexes for processed_sensor_data
CREATE INDEX IF NOT EXISTS idx_processed_sensor_data_sensor_id ON processed_sensor_data(sensor_id);
CREATE INDEX IF NOT EXISTS idx_processed_sensor_data_status ON processed_sensor_data(status);
CREATE INDEX IF NOT EXISTS idx_processed_sensor_data_processed_at ON processed_sensor_data(processed_at DESC);
