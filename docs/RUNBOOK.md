# iEMS Phase 5 — Operations Runbook (NFR-SEC-01 / NFR-REL-01)

## SLO
- Availability target: **99.95%** monthly for API `/readyz`
- Prediction p95 latency: **< 3s** (NFR-PER-01)
- Energy MAPE: **< 5%** (NFR-PER-02)

## Auth (RBAC + 2FA)
| User | Password | Role | TOTP secret (dev) |
|------|----------|------|-------------------|
| viewer | viewer | viewer | — |
| operator | operator | operator | `JBSWY3DPEHPK3PXP` |
| admin | admin | admin | `JBSWY3DPEHPK3PXP` |

Settings changes require header `X-2FA-Code: <totp>` plus admin bearer token.

```bash
# login
curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"admin"}'

# patch settings (replace CODE with current TOTP)
curl -s -X PATCH http://localhost:8000/api/v1/settings \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-2FA-Code: $CODE" \
  -H 'Content-Type: application/json' \
  -d '{"stale_data_seconds": 10}'
```

Production: set `AUTH_ENFORCE=true`, rotate `SECRET_KEY`, replace bootstrap users with IdP.

## Deploy
```bash
# base stack
docker compose up -d --build

# monitoring + backups
docker compose -f docker-compose.yml -f docker-compose.monitoring.yml up -d

# production hardening overlay
export SECRET_KEY=$(openssl rand -hex 32)
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

Kubernetes: apply `infra/k8s/config.yaml` then `infra/k8s/api.yaml` (2 replicas + HPA + PDB).

## Health probes
- Liveness: `GET /livez`
- Readiness: `GET /readyz` (DB/Redis)
- Metrics: `GET /metrics`

## Backup / restore (TimescaleDB)
Backups land in `data/backups/iems_*.sql.gz` via `db-backup` service.

```bash
# restore (destructive — take a snapshot first)
gunzip -c data/backups/iems_iems_YYYYMMDD.sql.gz | \
  docker exec -i iems-timescaledb psql -U iems -d iems
```

## Incident response
1. Check Grafana (http://localhost:3000) and Alertmanager (http://localhost:9093).
2. If `IEMSApiDown`: inspect `docker compose ps` / k8s pods; verify `/readyz`.
3. If stream stale: check producer/consumer logs; `GET /api/v1/alerts`.
4. Failover API: scale `iems-api` replicas ≥2; PDB keeps minAvailable=1.
5. Rotate secrets: update k8s Secret / compose env; rolling restart.

## Credential rotation
1. Generate new `SECRET_KEY` (invalidates tokens).
2. Rotate DB/Redis passwords; update secrets; restart dependents.
3. Re-issue operator/admin TOTP seeds via IdP.

## E6 — Plant Connect (OPC-UA)
Exit criteria: **1 Hz stable stream from plant without `DEMO_*` memory fallback**.

### Cutover checklist
1. Replace NodeIds in `infra/opcua/tags.yaml` (scale/offset optional).
2. Apply schema: `psql … -f infra/db/migrate_e6.sql` (or rely on `ensure_unique_index` ADD COLUMN).
3. Install OPC client: `pip install 'iems[opcua]'`.
4. Environment:
   ```bash
   export PLANT_CONNECT=true
   export INGESTION_SOURCE=opcua
   export OPC_UA_ENDPOINT=opc.tcp://plant-host:4840
   export OPC_UA_USERNAME=          # optional
   export OPC_UA_PASSWORD=
   export OPC_UA_USE_SUBSCRIPTION=true
   export PRODUCER_PLANT_CODES=olefin,pta
   # DEMO_FEEDER / DEMO_PREFER_MEMORY ignored when PLANT_CONNECT=true
   ```
5. Start `make producer` + `make consumer` (or full `make up` with producer env overridden).
6. Soak: `make soak` or `python -m scripts.plant_connect_soak --seconds 60`.
7. Verify:
   - `GET /api/v1/ingestion/plant-connect/status`
   - `GET /api/v1/ingestion/opcua/snapshot?plant_code=olefin` → `quality=good`, `source=opcua`
   - `GET /api/v1/dashboard/energy?plant_code=olefin` → no memory path

### Quality codes
| OPC StatusCode class | iEMS `quality` | Stream status |
|---|---|---|
| Good | `good` | `ok` (if fresh) |
| Uncertain | `uncertain` | `ok` if `OPC_UA_ALLOW_UNCERTAIN=true`, else `bad_quality` |
| Bad | `bad` | `bad_quality` → alert `data_quality` |

## E7 — Operator Product (shift console)
Goal: operator completes a shift **without opening `/docs`**.

### Daily path
1. Open `/dashboard` (installable PWA via manifest).
2. Login as `operator` / `operator` (viewer is read-only; admin for settings + TOTP).
3. **display** — confirm stream + KPIs; use **Shift briefing** / **Shift CSV**.
4. **Notifications** — live poll every 20s; severity badge; ack critical items (`operate`).
5. **Control** — analyze / accept-reject recommendations (hidden for viewer).
6. **Reporting** — generate daily carbon report → download **CSV/JSON**.

### APIs added for operators
- `GET /api/v1/auth/me` — role + allowed actions
- `GET /api/v1/operator/shift-summary`
- `GET /api/v1/operator/shift-report.csv`
- Resolve alert requires `operate` (`POST /api/v1/alerts/{id}/resolve`)

## E8 — Trusted Models
Exit criteria: **MAPE &lt;5% on plant temporal holdout**; **no synthetic / physics fallback** when trusted.

Trusted mode is on when `ML_TRUSTED_MODE=true` **or** `PLANT_CONNECT=true`.

### Environment
```bash
export ML_TRUSTED_MODE=true          # or rely on PLANT_CONNECT
export ML_ALLOW_SYNTHETIC=false      # forced off in trusted
export ML_ALLOW_PHYSICS_FALLBACK=false
export ML_ALLOW_VSG_IN_TRUSTED=false # keep VSG off on plant holdout path
export ML_HOLDOUT_RATIO=0.2
export ML_DRIFT_PSI_THRESHOLD=0.2
export ML_PHYSICS_SCALE_PATH=infra/ml/physics_calibration.yaml
export ML_PREFER_TORCH_LSTM=false    # set true if torch works (`iems[ml]`)
export ML_MIN_REAL_SAMPLES=50
```

### Operator / MLOps path
1. Ensure ≥`ML_MIN_REAL_SAMPLES` rows in TimescaleDB for the plant.
2. Train: `POST /api/v1/ml/train` `{ "plant_code":"olefin", "model":"elm" }`  
   - 409 if insufficient plant data or holdout MAPE fails the gate.
3. Trust card: `GET /api/v1/ml/trust/{plant}/{model}`
4. Drift: `GET /api/v1/ml/drift/{plant}/{model}` (PSI vs training feature ref)
5. Physics calibration: `GET|POST /api/v1/ml/calibrate/{plant}`
6. Predict: `POST /api/v1/ml/predict` — **503** if no registered model (no physics MAPE fiction).

### Behaviour matrix
| Mode | Synthetic train | Physics predict fallback | Holdout | LSTM |
|---|---|---|---|---|
| Demo (default) | yes | yes (`mape_estimate=null`) | shuffled | temporal windows (torch or ELM-head) |
| Trusted / Plant Connect | blocked | blocked (503) | last 20% time order | same; history windows at serve |

### Trainer
`python -m app.ml.trainer`: in trusted mode skips retrain when PSI drift is below threshold; never registers models that fail the MAPE gate.

## E9 — Advisory → Action
Exit criteria: **one accepted shift recommendation applied (dry-run OK) with savings / impact tracking**.

Lifecycle: `pending → accepted → approved → applied` (or `rejected` / `failed`).

### Environment
```bash
export OPC_WRITE_ENABLED=false           # keep false until audit readiness
export OPC_WRITE_DRY_RUN_DEFAULT=true    # apply plans writes without OPC I/O
export OPT_REQUIRE_SIM_BEFORE_APPLY=true
export OPT_IMPACT_WINDOW_MINUTES=15
export OPT_WRITABLE_FIELDS=reactor_temp_c,feed_flow_tonh
# Live write also needs:
# export PLANT_CONNECT=true
# export OPC_UA_ENDPOINT=opc.tcp://plant-host:4840
# export OPC_WRITE_ENABLED=true
# and writable write_node_id entries in infra/opcua/tags.yaml
```

### Operator path (Control tab)
1. **Analyze savings** → persist recommendations.
2. **sim** → mandatory before apply when `OPT_REQUIRE_SIM_BEFORE_APPLY=true`.
3. **accept** (`operate`) → **approve** (`operate`).
4. **apply** (`apply` = **admin only**) — default dry-run; plans allowlisted SP writes.
5. **impact** → realized kWh/h vs baseline (or estimate until plant samples exist).
6. **audit** → immutable event trail.

### APIs
- `POST /api/v1/optimization/recommendations/{id}/approve`
- `POST /api/v1/optimization/recommendations/{id}/apply` `{ "dry_run": true }`
- `GET  /api/v1/optimization/recommendations/{id}/impact`
- `GET  /api/v1/optimization/recommendations/{id}/audit`

### Safety
| Gate | Behaviour |
|---|---|
| No sim | 409 on apply |
| Not approved | 409 on apply |
| Live write + `OPC_WRITE_ENABLED=false` | 409 / failed |
| Non-writable tag / field | skipped in plan |
| Role operator | cannot call apply |

Schema: `psql … -f infra/db/migrate_e9.sql` (or auto `ensure_e9_schema` on persist).

## E10 — ESG & Market
Exit criteria: **ESG/audit can receive a presentable pack (HTML/CSV) without relying on raw JSON**.

### Environment
```bash
export CARBON_SCOPE3_PATH=infra/carbon/scope3_factors.yaml
export CARBON_ESG_PACK_DIR=data/reports/esg_packs
export CARBON_MARKET_REQUIRE_LOCKED=true   # sync only locked reports
export CARBON_MARKET_API_URL=              # optional live registry POST
export CARBON_MARKET_API_TOKEN=
```

### Operator path (Reporting tab)
1. **Daily report** → generates Scope 1/2 + light Scope 3 (`draft`).
2. **ESG pack** → HTML/CSV download for auditors.
3. Assurance: **submit** → **approve** (`operate`) → **lock** (`settings` / admin).
4. **Market sync** → stages/POSTs **locked** reports only (unless `CARBON_MARKET_REQUIRE_LOCKED=false`).
5. **Sync history** → prior batches + external refs.

### APIs
- `GET  /api/v1/carbon/reports/{id}/pack?format=html|csv`
- `POST /api/v1/carbon/reports/{id}/submit|approve|lock`
- `GET  /api/v1/carbon/reports/{id}/assurance`
- `POST /api/v1/carbon/market/sync`
- `GET  /api/v1/carbon/market/syncs`

### Light Scope 3
Categories (proxies): Cat3 fuel upstream · Cat1 purchased goods · Cat5 waste — see `infra/carbon/scope3_factors.yaml`.

Schema: `psql … -f infra/db/migrate_e10.sql` (or auto `ensure_e10_schema` on generate).

## E11 — Enterprise Ops
Exit criteria: **prod deploy with `AUTH_ENFORCE=true` and 24×7 monitoring** (measurable 99.95% SLO).

### Environment
```bash
export AUTH_ENFORCE=true
export SECRET_KEY=...                      # required by compose.prod
export OIDC_ENABLED=true
export OIDC_ISSUER=https://idp.example.com/realms/iems
export OIDC_CLIENT_ID=iems-api
export OIDC_CLIENT_SECRET=...
export OIDC_REDIRECT_URI=https://iems.example.com/api/v1/auth/oidc/callback
export SITE_CODE=khalij
export SITE_NAME="Khalij Complex"
# Local IdP stand-in (dev only):
# export OIDC_DEV_BYPASS=true APP_DEBUG=true
```

### Cutover checklist
1. Apply schema: `psql … -f infra/db/migrate_e11.sql`
2. `make up-prod` (or `make up-ha` for second API on :8001)
3. Wire on-call: copy `infra/monitoring/alertmanager.oncall.example.yml` → live webhook
4. Confirm `GET /api/v1/ops/status` → `auth_enforce: true`, OIDC configured
5. OIDC login: `GET /api/v1/auth/oidc/login` → IdP → callback issues iEMS token
6. SLO: Grafana / Prometheus `iems:api_availability:ratio_30d` ≥ 0.9995
7. DR drill: `make backup` then `make restore-dry-run` (monthly)

### APIs
- `GET  /api/v1/ops/status` — AUTH / OIDC / SLO / HA snapshot
- `GET  /api/v1/ops/sites` — multi-site registry + plants
- `GET  /api/v1/auth/oidc/status|login|callback`
- `POST /api/v1/auth/oidc/dev-login` — debug IdP stand-in only

### HA / DR notes
| Layer | Status |
|---|---|
| API | k8s replicas=2 · compose `profile ha` → `api-b:8001` |
| DB | Single TimescaleDB + hourly `pg_dump` · restore via `scripts/restore_timescaledb.sh` |
| Kafka | Single broker (RF=1) — full Kafka HA out of band |
| SLO | Recording rules + `IEMSAvailabilitySLOBreach` in `infra/monitoring/alerts.yml` |

Canvas risk order: **enable IdP before scaling HA**.
