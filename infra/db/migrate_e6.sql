-- E6 Plant Connect — persist ingest source + OPC quality on sensor_readings
ALTER TABLE sensor_readings
    ADD COLUMN IF NOT EXISTS source TEXT,
    ADD COLUMN IF NOT EXISTS quality TEXT,
    ADD COLUMN IF NOT EXISTS quality_detail TEXT;
