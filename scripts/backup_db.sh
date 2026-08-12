#!/usr/bin/env bash
set -euo pipefail

# Periodic (cron-driven) Postgres backup for hocX.
#
# Unlike the pre-deploy dump in deploy.sh (which only runs right before an update), this
# script is meant to run unattended every night via a cron entry in the current user's
# crontab (see: crontab -l). It uses the exact same dump mechanism as deploy.sh
# ("docker compose exec db pg_dump ..." piped through gzip), so restoring a cron backup
# works exactly like restoring a pre-deploy backup.
#
# What it does:
#   1. Runs `pg_dump` inside the running `db` container and writes a timestamped,
#      gzip-compressed dump to backups/ (the same directory deploy.sh's pre-deploy
#      backups already live in).
#   2. Deletes dumps older than RETENTION_DAYS (default 14) so backups/ doesn't grow
#      unbounded.
#   3. Exits non-zero with a clear error message on any failure (missing .env, db
#      container not running/healthy, pg_dump failure, etc.) - important since this runs
#      unattended from cron and failures need to be visible (e.g. via cron's mail-on-error
#      or a monitoring wrapper), not silently swallowed.
#
# Usage: scripts/backup_db.sh   (no arguments - always targets this repo checkout, i.e.
#                                 the prod deployment at /docker/hocX)
#
# Suggested crontab entry (installed via this task): run nightly at 03:15.
#   15 3 * * * /docker/hocX/scripts/backup_db.sh >> /docker/hocX/backups/backup_db.log 2>&1

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_DIR="$REPO_DIR"
ENV_FILE="$PROJECT_DIR/.env"
BACKUP_DIR="$PROJECT_DIR/backups"
RETENTION_DAYS="${RETENTION_DAYS:-14}"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }
fail() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: $*" >&2; exit 1; }

if [ ! -f "$ENV_FILE" ]; then
  fail "Env-Datei $ENV_FILE fehlt."
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

: "${POSTGRES_USER:?POSTGRES_USER fehlt in $ENV_FILE}"
: "${POSTGRES_DB:?POSTGRES_DB fehlt in $ENV_FILE}"

cd "$PROJECT_DIR"
DC=(docker compose --env-file "$ENV_FILE")

if ! "${DC[@]}" ps db --status running -q > /dev/null 2>&1 || [ -z "$("${DC[@]}" ps db --status running -q)" ]; then
  fail "db-Container laeuft nicht - kein Backup moeglich."
fi

mkdir -p "$BACKUP_DIR"
BACKUP_FILE="$BACKUP_DIR/$(date +%Y%m%d-%H%M%S)-cron.sql.gz"
TMP_FILE="$BACKUP_FILE.tmp"

log "Erstelle Backup: $BACKUP_FILE"
if ! "${DC[@]}" exec -T db pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" | gzip > "$TMP_FILE"; then
  rm -f "$TMP_FILE"
  fail "pg_dump/gzip fehlgeschlagen - kein Backup geschrieben."
fi

if [ ! -s "$TMP_FILE" ]; then
  rm -f "$TMP_FILE"
  fail "Backup-Datei ist leer - verworfen."
fi

mv "$TMP_FILE" "$BACKUP_FILE"
log "Backup abgeschlossen: $BACKUP_FILE ($(du -h "$BACKUP_FILE" | cut -f1))"

log "Loesche Backups aelter als $RETENTION_DAYS Tage..."
find "$BACKUP_DIR" -maxdepth 1 -type f -name "*.sql.gz" -mtime "+$RETENTION_DAYS" -print -delete

log "Fertig."
