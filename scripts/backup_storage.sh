#!/usr/bin/env bash
set -euo pipefail
# Nächtliches Objekt-Backup der aktiven Speichergeneration (inkrementell, mit Manifest) nach
# backups/storage/ - immer NACH scripts/backup_db.sh einplanen (Konsistenz, siehe
# docs-site/docs/technik/storage/backup.md). Läuft im storage-worker-Container.
#
#   30 3 * * * /docker/hocX/scripts/run_job.sh backup_storage /docker/hocX/scripts/backup_storage.sh >> /docker/hocX/backups/backup_storage.log 2>&1
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${HOCX_ENV_FILE:-$REPO_DIR/.env}"
cd "$REPO_DIR"
# Abgelöst durch das Borg-Backup (kein lokaler Spiegel mehr, siehe docs-site/docs/technik/backup/).
# shellcheck source=scripts/lib/env.sh
source "$REPO_DIR/scripts/lib/env.sh"
if [ -f "$ENV_FILE" ]; then
  load_env_file "$ENV_FILE"
fi
if [ "${BACKUP_ENABLED:-false}" = true ] && [ "${HOCX_LEGACY_BACKUP_FORCE:-false}" != true ]; then
  echo "Borg-Backup ist aktiv - lokaler Objekt-Spiegel uebersprungen. Cron-Eintrag entfernen (RUNBOOK Abschnitt 7); backups/storage/ bleibt bis zur bewussten Bereinigung erhalten."
  exit 0
fi
DC=(docker compose --env-file "$ENV_FILE")
if [ -n "${HOCX_COMPOSE_PROJECT:-}" ]; then DC+=(-p "$HOCX_COMPOSE_PROJECT"); fi
if [ -n "${HOCX_COMPOSE_FILES:-}" ]; then for file in $HOCX_COMPOSE_FILES; do DC+=(-f "$file"); done; fi
mkdir -p "$REPO_DIR/backups/storage"
"${DC[@]}" exec -T storage-worker python -m app.workers.storage_backup --target /app/backups/storage
"${DC[@]}" exec -T storage-worker python -m app.workers.storage_backup --target /app/backups/storage --verify
