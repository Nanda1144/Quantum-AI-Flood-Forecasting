-- Seed data for Sensor Data Management Module

-- 1. Insert initial registered sensors
INSERT INTO sensors (sensor_code, location_name, latitude, longitude, sensor_type, created_at)
VALUES 
    ('S101', 'North River Basin - Sector 4', 28.6139, 77.2090, 'ULTRASONIC_LEVEL', NOW() - INTERVAL '10 days'),
    ('S102', 'East Reservoir Dam Gate 2', 28.7041, 77.1025, 'RADAR_LEVEL', NOW() - INTERVAL '10 days'),
    ('S103', 'South Delta Canal Entry', 28.5355, 77.3910, 'FLOW_AND_LEVEL', NOW() - INTERVAL '10 days'),
    ('S104', 'West Tributary Bridge 9', 28.4595, 77.0266, 'ULTRASONIC_LEVEL', NOW() - INTERVAL '5 days'),
    ('S105', 'Central Spillway Alpha', 28.5700, 77.3200, 'MULTI_PARAM', NOW() - INTERVAL '2 days')
ON CONFLICT (sensor_code) DO NOTHING;

-- 2. Insert telemetry readings
INSERT INTO sensor_data (sensor_id, water_level, rainfall, flow_rate, temperature, risk_level, recorded_at)
VALUES 
    (1, 1.5, 5.0, 1.2, 27.5, 'LOW', NOW() - INTERVAL '1 hour'),
    (1, 5.4, 42.0, 3.1, 29.0, 'HIGH', NOW()),
    (2, 3.2, 18.5, 2.4, 28.0, 'MEDIUM', NOW()),
    (3, 6.8, 65.0, 5.2, 30.5, 'CRITICAL', NOW()),
    (4, 0.8, 0.0, 0.5, 26.0, 'LOW', NOW()),
    (5, 4.5, 38.0, 2.9, 28.8, 'HIGH', NOW());

-- 3. Insert processed status data
INSERT INTO processed_sensor_data (sensor_id, status, risk_level, processed_at)
VALUES
    (1, 'ACTIVE', 'HIGH', NOW()),
    (2, 'ACTIVE', 'MEDIUM', NOW()),
    (3, 'CRITICAL', 'CRITICAL', NOW()),
    (4, 'ACTIVE', 'LOW', NOW()),
    (5, 'ACTIVE', 'HIGH', NOW());
