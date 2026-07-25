-- Apply on existing Timescale volumes created before Phase 4
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
