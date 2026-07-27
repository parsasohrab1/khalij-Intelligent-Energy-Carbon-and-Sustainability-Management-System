-- E10 ESG & Market — Scope 3 + assurance + market external_ref
ALTER TABLE carbon_reports
    ADD COLUMN IF NOT EXISTS scope3_kgco2 DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS scope3_detail_json TEXT,
    ADD COLUMN IF NOT EXISTS assurance_status VARCHAR(32) DEFAULT 'draft',
    ADD COLUMN IF NOT EXISTS submitted_by TEXT,
    ADD COLUMN IF NOT EXISTS submitted_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS approved_by TEXT,
    ADD COLUMN IF NOT EXISTS approved_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS locked_by TEXT,
    ADD COLUMN IF NOT EXISTS locked_at TIMESTAMPTZ;

ALTER TABLE carbon_market_syncs
    ADD COLUMN IF NOT EXISTS external_ref TEXT;

CREATE TABLE IF NOT EXISTS carbon_report_assurance_events (
    id                  SERIAL PRIMARY KEY,
    report_id           INTEGER NOT NULL REFERENCES carbon_reports(id),
    event_type          TEXT NOT NULL,
    actor               TEXT NOT NULL,
    detail_json         TEXT NOT NULL DEFAULT '{}',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_carbon_assurance_report
    ON carbon_report_assurance_events (report_id, created_at DESC);
