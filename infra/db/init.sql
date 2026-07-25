-- iEMS TimescaleDB bootstrap (sensor time-series + carbon aggregates)
-- Covers R-GEN-01/02, FR-DATA-01/02, FR-CAR-01, FR-ML-02

CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE IF NOT EXISTS plants (
    id          SERIAL PRIMARY KEY,
    code        TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL,
    unit_type   TEXT NOT NULL CHECK (unit_type IN ('olefin', 'pta', 'other')),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO plants (code, name, unit_type) VALUES
    ('olefin', 'Olefin Unit', 'olefin'),
    ('pta', 'PTA Unit', 'pta')
ON CONFLICT (code) DO NOTHING;

CREATE TABLE IF NOT EXISTS sensor_readings (
    time                      TIMESTAMPTZ NOT NULL,
    plant_id                  INTEGER NOT NULL REFERENCES plants(id),
    electricity_power_mw      DOUBLE PRECISION,
    fuel_gas_flow_km3h        DOUBLE PRECISION,
    steam_flow_tonh           DOUBLE PRECISION,
    feed_flow_tonh            DOUBLE PRECISION,
    reactor_temp_c            DOUBLE PRECISION,
    pressure_bar              DOUBLE PRECISION,
    energy_intensity_kgoe_ton DOUBLE PRECISION,
    carbon_emission_kgco2_ton DOUBLE PRECISION,
    energy_efficiency_percent DOUBLE PRECISION
);

SELECT create_hypertable('sensor_readings', 'time', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_sensor_readings_plant_time
    ON sensor_readings (plant_id, time DESC);

CREATE TABLE IF NOT EXISTS carbon_reports (
    id                         SERIAL PRIMARY KEY,
    plant_id                   INTEGER NOT NULL REFERENCES plants(id),
    period_start               TIMESTAMPTZ NOT NULL,
    period_end                 TIMESTAMPTZ NOT NULL,
    period_type                TEXT NOT NULL CHECK (period_type IN ('daily', 'monthly', 'yearly')),
    scope1_kgco2               DOUBLE PRECISION NOT NULL DEFAULT 0,
    scope2_kgco2               DOUBLE PRECISION NOT NULL DEFAULT 0,
    carbon_intensity_kgco2_ton DOUBLE PRECISION,
    created_at                 TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (plant_id, period_start, period_type)
);

CREATE TABLE IF NOT EXISTS model_predictions (
    time                   TIMESTAMPTZ NOT NULL,
    plant_id               INTEGER NOT NULL REFERENCES plants(id),
    horizon_minutes        INTEGER NOT NULL DEFAULT 60,
    predicted_energy_kwh   DOUBLE PRECISION,
    predicted_carbon_kgco2 DOUBLE PRECISION,
    model_name             TEXT NOT NULL,
    model_version          TEXT,
    mape                   DOUBLE PRECISION,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

SELECT create_hypertable('model_predictions', 'time', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_model_predictions_plant_time
    ON model_predictions (plant_id, time DESC);

-- Phase 1: unique key for upserts + stream alerts
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

-- Phase 2: extended carbon reports + market sync audit
ALTER TABLE carbon_reports ADD COLUMN IF NOT EXISTS product_ton DOUBLE PRECISION;
ALTER TABLE carbon_reports ADD COLUMN IF NOT EXISTS sample_count INTEGER;
ALTER TABLE carbon_reports ADD COLUMN IF NOT EXISTS factors_version TEXT;

CREATE TABLE IF NOT EXISTS carbon_market_syncs (
    id              SERIAL PRIMARY KEY,
    batch_id        TEXT NOT NULL UNIQUE,
    plant_code      TEXT,
    status          TEXT NOT NULL,
    registry        TEXT NOT NULL,
    message         TEXT NOT NULL,
    reports_synced  INTEGER NOT NULL DEFAULT 0,
    payload_path    TEXT,
    synced_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Phase 4: optimization recommendations + operator feedback
CREATE TABLE IF NOT EXISTS optimization_recommendations (
    id                              SERIAL PRIMARY KEY,
    plant_code                      TEXT NOT NULL,
    priority                        TEXT NOT NULL,
    title                           TEXT NOT NULL,
    rationale                       TEXT NOT NULL,
    current_json                    TEXT NOT NULL,
    proposed_json                   TEXT NOT NULL,
    deltas_json                     TEXT NOT NULL,
    tags_json                       TEXT NOT NULL DEFAULT '[]',
    benchmark_plant                 TEXT,
    estimated_sec_reduction_pct     DOUBLE PRECISION,
    estimated_energy_saving_kwh_per_h DOUBLE PRECISION,
    estimated_efficiency_gain_pp    DOUBLE PRECISION,
    simulated_intensity_delta       DOUBLE PRECISION,
    simulated_efficiency_delta_pp   DOUBLE PRECISION,
    status                          TEXT NOT NULL DEFAULT 'pending',
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at                     TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_opt_recs_plant_status
    ON optimization_recommendations (plant_code, status, created_at DESC);

CREATE TABLE IF NOT EXISTS recommendation_feedback (
    id                  SERIAL PRIMARY KEY,
    recommendation_id   INTEGER NOT NULL REFERENCES optimization_recommendations(id),
    decision            TEXT NOT NULL CHECK (decision IN ('accepted', 'rejected')),
    operator            TEXT NOT NULL,
    comment             TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
