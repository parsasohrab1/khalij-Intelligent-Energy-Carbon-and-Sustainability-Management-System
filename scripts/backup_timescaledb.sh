#!/usr/bin/env bash
# TimescaleDB logical backup — Phase 5 HA/backup (NFR-REL-01)
set -euo pipefail

HOST="${POSTGRES_HOST:-timescaledb}"
USER="${POSTGRES_USER:-iems}"
DB="${POSTGRES_DB:-iems}"
OUT_DIR="${BACKUP_DIR:-/backups}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
FILE="${OUT_DIR}/iems_${DB}_${STAMP}.sql.gz"

mkdir -p "${OUT_DIR}"
echo "[backup] starting ${FILE}"
pg_dump -h "${HOST}" -U "${USER}" -d "${DB}" | gzip -c > "${FILE}"
# retain last 14 backups
ls -1t "${OUT_DIR}"/iems_*.sql.gz 2>/dev/null | tail -n +15 | xargs -r rm -f
echo "[backup] done ${FILE}"
