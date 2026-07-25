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
