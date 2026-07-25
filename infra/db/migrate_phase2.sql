-- Apply on existing Timescale volumes created before Phase 2
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
