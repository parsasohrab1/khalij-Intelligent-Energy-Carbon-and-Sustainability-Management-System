# Khalij iEMS

Intelligent Energy, Carbon & Sustainability Management System for olefin and PTA petrochemical units.

Live operator console: **[/dashboard](http://localhost:8000/dashboard)** · API docs: **/docs** · SRS: [`docs/SRS.md`](docs/SRS.md) · Ops: [`docs/RUNBOOK.md`](docs/RUNBOOK.md)

## What you get

| Capability | SRS | How |
|---|---|---|
| 1 Hz energy stream | R-GEN-01/02 | Kafka pipeline **or** Kafka-less demo feeder |
| Live energy & carbon dashboard | R-GEN-03 / FR-CAR-03 | Operator UI + `/api/v1/dashboard/*` |
| Scope 1/2 reports | R-GEN-04 / FR-CAR-01 | Carbon API + scheduler |
| Carbon market staging | FR-CAR-02 | `/api/v1/carbon/market/sync` |
| VSG + ELM/LSTM predict + what-if | FR-ML-01/02/03 | `/api/v1/ml/*` |
| Savings advice + operator feedback | FR-OPT-01/02 | `/api/v1/optimization/*` |
| Real-Time Optimization (RTO) | FR-RTO-01 · E12 | Continuous advisory loop, live Control panel, `/api/v1/rto/*` |
| RBAC + TOTP for settings | NFR-SEC-01 | Auth API + settings 2FA |
| Monitoring / HA | NFR-REL-01 | Prometheus overlay, k8s, backups |
| Plant Connect (OPC) | FR-DATA-01 · E6 | Long-lived OPC session, quality codes, `PLANT_CONNECT` |
| Operator Product | E7 | Role UI, live Notifications, shift CSV, PWA |
| Trusted Models | E8 | Plant-only train, temporal holdout, drift PSI, no fake MAPE |
| Advisory → Action | E9 | Approve → apply (dry-run/OPC), audit trail, impact savings |
| ESG & Market | E10 | Scope 3 light, assurance, ESG pack HTML/CSV, locked market sync |
| Enterprise Ops | E11 | OIDC IdP, multi-site, SLO 99.95%, HA profile, DR drill |

## Quick start (demo — no Kafka)

```bash
# Option A — memory-only live UI (no Docker)
pip install -e ".[dev]"
$env:DEMO_FEEDER="true"; $env:DEMO_MEMORY_ONLY="true"; $env:DEMO_PREFER_MEMORY="true"
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
# open http://localhost:8000/dashboard

# Option B — TimescaleDB + Redis + inline feeder
docker compose -f docker-compose.demo.yml up -d --build
```

## Full stack

```bash
make install
make up                 # API + Kafka producer/consumer + DB + Redis + MLflow + RTO/carbon schedulers
make up-monitoring      # Prometheus / Grafana / Alertmanager + DB backup
make up-prod            # AUTH_ENFORCE + monitoring
make up-ha              # prod + api-b HA profile (:8001)
make e11-checklist      # Enterprise Ops cutover steps
```

Default demo users: `admin/admin`, `operator/operator`, `viewer/viewer`  
TOTP secret (dev): `JBSWY3DPEHPK3PXP`

## Architecture

- **API:** FastAPI (`app/`)
- **Time-series:** TimescaleDB (PostgreSQL)
- **Stream:** Apache Kafka (full stack) or in-process demo feeder
- **Cache:** Redis
- **MLOps:** MLflow (optional; local model registry always available)
- **UI:** `app/static/dashboard.html` served at `/dashboard`

## Make targets

| Target | Purpose |
|---|---|
| `make run` | API only |
| `make demo` | API + inline memory feeder |
| `make demo-feeder` | Standalone 1 Hz DB/memory feeder |
| `make up-demo` | Lightweight compose (no Kafka) |
| `make up-prod` / `make up-ha` | AUTH_ENFORCE (+ optional api-b) |
| `make rto-scheduler` | Standalone E12 Real-Time Optimization advisory loop |
| `make e11-checklist` | Enterprise Ops cutover |
| `make backup` / `make restore-dry-run` | DR drill helpers |
| `make test` | Pytest suite |
