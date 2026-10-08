from iot.models.sensor import Sensor
from iot.models.sensor_data import SensorData
from iot.models.processed_data import ProcessedSensorData

def test_sensor_creation_and_relationships(db_session):
    sensor = Sensor(
        sensor_code="TEST_S999",
        location_name="Test Station Alpha",
        latitude=28.5,
        longitude=77.5,
        sensor_type="ULTRASONIC"
    )
    db_session.add(sensor)
    db_session.commit()
    db_session.refresh(sensor)

    assert sensor.id is not None
    assert sensor.sensor_code == "TEST_S999"

    # Add raw reading
    reading = SensorData(
        sensor_id=sensor.id,
        water_level=3.5,
        rainfall=12.0,
        flow_rate=2.1,
        temperature=28.0,
        risk_level="MEDIUM"
    )
    db_session.add(reading)

    # Add processed data
    processed = ProcessedSensorData(
        sensor_id=sensor.id,
        status="ACTIVE",
        risk_level="MEDIUM"
    )
    db_session.add(processed)
    db_session.commit()

    db_session.refresh(sensor)
    assert len(sensor.readings) == 1
    assert sensor.readings[0].water_level == 3.5
    assert len(sensor.processed_readings) == 1
    assert sensor.processed_readings[0].status == "ACTIVE"

