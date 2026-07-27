-- E9 Advisory → Action — approval / apply / audit / savings columns
ALTER TABLE optimization_recommendations
    ALTER COLUMN status TYPE VARCHAR(32);

ALTER TABLE optimization_recommendations
    ADD COLUMN IF NOT EXISTS approved_by TEXT,
    ADD COLUMN IF NOT EXISTS approved_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS applied_by TEXT,
    ADD COLUMN IF NOT EXISTS applied_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS apply_mode VARCHAR(16),
    ADD COLUMN IF NOT EXISTS baseline_intensity DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS baseline_efficiency DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS realized_saving_kwh_per_h DOUBLE PRECISION;

CREATE TABLE IF NOT EXISTS recommendation_audit_events (
    id                  SERIAL PRIMARY KEY,
    recommendation_id   INTEGER NOT NULL REFERENCES optimization_recommendations(id),
    event_type          TEXT NOT NULL,
    actor               TEXT NOT NULL,
    detail_json         TEXT NOT NULL DEFAULT '{}',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_rec_audit_rec_time
    ON recommendation_audit_events (recommendation_id, created_at DESC);
