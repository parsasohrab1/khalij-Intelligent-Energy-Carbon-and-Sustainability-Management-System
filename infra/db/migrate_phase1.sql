-- Apply on existing Timescale volumes that were created before Phase 1
CREATE UNIQUE INDEX IF NOT EXISTS uq_sensor_readings_time_plant
    ON sensor_readings (time, plant_id);

CREATE TABLE IF NOT EXISTS stream_alerts (
    id           SERIAL PRIMARY KEY,
    plant_code   TEXT NOT NULL,
    alert_type   TEXT NOT NULL,
    message      TEXT NOT NULL,
    age_seconds  DOUBLE PRECISION,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at  TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_stream_alerts_open
    ON stream_alerts (plant_code, created_at DESC)
    WHERE resolved_at IS NULL;
