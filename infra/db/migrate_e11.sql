-- E11 Enterprise Ops — multi-site registry
CREATE TABLE IF NOT EXISTS sites (
    id          SERIAL PRIMARY KEY,
    code        TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL,
    region      TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO sites (code, name, region) VALUES
    ('khalij', 'Khalij Complex', 'gulf')
ON CONFLICT (code) DO NOTHING;

ALTER TABLE plants ADD COLUMN IF NOT EXISTS site_id INTEGER REFERENCES sites(id);

UPDATE plants
SET site_id = (SELECT id FROM sites WHERE code = 'khalij')
WHERE site_id IS NULL;
