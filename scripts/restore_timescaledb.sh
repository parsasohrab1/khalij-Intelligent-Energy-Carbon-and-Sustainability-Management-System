#!/usr/bin/env bash
# E11 — restore TimescaleDB from logical backup (DR drill)
# Usage:
#   ./scripts/restore_timescaledb.sh data/backups/iems_iems_YYYYMMDDTHHMMSSZ.sql.gz
# Dry-run (list only):
#   DRY_RUN=1 ./scripts/restore_timescaledb.sh data/backups/iems_iems_....sql.gz
set -euo pipefail

HOST="${POSTGRES_HOST:-localhost}"
PORT="${POSTGRES_PORT:-5432}"
USER="${POSTGRES_USER:-iems}"
DB="${POSTGRES_DB:-iems}"
FILE="${1:-}"

if [[ -z "${FILE}" ]]; then
  echo "Usage: $0 <backup.sql.gz>" >&2
  echo "Latest backups:" >&2
  ls -1t data/backups/iems_*.sql.gz 2>/dev/null | head -n 5 >&2 || true
  exit 1
fi

if [[ ! -f "${FILE}" ]]; then
  echo "[restore] file not found: ${FILE}" >&2
  exit 1
fi

BYTES="$(wc -c < "${FILE}" | tr -d ' ')"
echo "[restore] file=${FILE} bytes=${BYTES}"

if [[ "${DRY_RUN:-0}" == "1" ]]; then
  echo "[restore] DRY_RUN=1 — verifying gzip integrity only"
  gzip -t "${FILE}"
  echo "[restore] gzip OK — not applying to database"
  exit 0
fi

echo "[restore] WARNING: this replaces objects in database '${DB}' on ${HOST}:${PORT}"
echo "[restore] applying in 3s… (Ctrl-C to abort)"
sleep 3
gunzip -c "${FILE}" | psql -h "${HOST}" -p "${PORT}" -U "${USER}" -d "${DB}" -v ON_ERROR_STOP=1
echo "[restore] done"
