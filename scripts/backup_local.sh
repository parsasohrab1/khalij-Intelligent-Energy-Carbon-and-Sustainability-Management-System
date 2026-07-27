#!/usr/bin/env bash
# Local wrapper — writes backup under ./data/backups (Windows Git Bash / WSL / Linux)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export BACKUP_DIR="${BACKUP_DIR:-$ROOT/data/backups}"
export POSTGRES_HOST="${POSTGRES_HOST:-localhost}"
export POSTGRES_USER="${POSTGRES_USER:-iems}"
export POSTGRES_DB="${POSTGRES_DB:-iems}"
mkdir -p "${BACKUP_DIR}"
exec bash "$ROOT/scripts/backup_timescaledb.sh"
