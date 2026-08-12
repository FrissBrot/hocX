#!/usr/bin/env bash
set -euo pipefail

# Periodic (cron-driven) retention cleanup for hocX's storage/ tree.
#
# WHY ONLY storage/exports:
#   Of the four directories flagged in the audit as "growing without retention"
#   (storage/tenant_imports, storage/exports, storage/tenant_clones,
#   storage/abgabebox-uploads), only storage/exports turned out to be safe to sweep by
#   age. This was verified against the actual code and the live DB, not assumed:
#
#   - storage/exports (PDF/LaTeX build output, see export_service.py): every export run
#     writes into a brand-new uuid-suffixed file/directory (never overwrites or reuses an
#     old one) and the download route (GET /api/stored-files/{id}/content in
#     api/routes/files.py) already returns a clean 404 ("File missing on filesystem") if
#     the underlying file is gone rather than erroring - and any protocol/global PDF can
#     be regenerated on demand at any time. So deleting old files here only means an old
#     download link 404s instead of serving a stale PDF; nothing breaks.
#
#   - storage/tenant_clones is NOT a one-off export artifact despite looking like one -
#     verified live against prod DB on 2026-08-12: 219 rows in stored_file currently point
#     at paths under tenant_clones/tenant-7/ alone (tenant 7 is a real, existing tenant,
#     see tenant_clone_service.py's _clone_stored_file_content - this directory is the
#     PERMANENT storage location for a cloned tenant's files, not a temp/export dir).
#     Age-based deletion here would silently corrupt a live tenant's data. NOT swept.
#
#   - storage/tenant_imports is the same pattern as tenant_clones (see
#     tenant_import_service.py's _restore_file / _import_stored_files): permanent home for
#     an imported tenant's restored files, referenced indefinitely via stored_file rows.
#     NOT swept, per the audit's own caution.
#
#   - storage/abgabebox-uploads holds live, referenced Abgabebox submissions (and is
#     read/deleted by the main backend on "wieder aufschalten", see
#     docker-compose.yml comment on the backend's abgabebox-storage mount). NOT swept.
#
# What it does:
#   1. Deletes files under storage/exports older than RETENTION_DAYS (default 30),
#      skipping .gitkeep.
#   2. Removes directories under storage/exports left empty by step 1 (e.g. old
#      protocol-<id>/ build dirs), but never storage/exports itself.
#   3. Logs what was (or, with --dry-run, would be) deleted.
#
# Usage:
#   scripts/cleanup_storage.sh              # deletes for real
#   scripts/cleanup_storage.sh --dry-run     # only prints what would be deleted
#
# Suggested crontab entry (installed via this task): run nightly at 03:45, i.e. after
# backup_db.sh's 03:15 run so a backup always predates any cleanup of the same night.
#   45 3 * * * /docker/hocX/scripts/cleanup_storage.sh >> /docker/hocX/backups/cleanup_storage.log 2>&1

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EXPORTS_DIR="$REPO_DIR/storage/exports"
RETENTION_DAYS="${RETENTION_DAYS:-30}"

DRY_RUN=0
if [ "${1:-}" = "--dry-run" ]; then
  DRY_RUN=1
fi

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }
fail() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: $*" >&2; exit 1; }

if [ ! -d "$EXPORTS_DIR" ]; then
  fail "$EXPORTS_DIR fehlt."
fi

if [ "$DRY_RUN" -eq 1 ]; then
  log "DRY-RUN: keine Datei wird geloescht."
  log "Dateien in $EXPORTS_DIR, die aelter als $RETENTION_DAYS Tage sind:"
  find "$EXPORTS_DIR" -type f -not -name ".gitkeep" -mtime "+$RETENTION_DAYS" -print
  COUNT=$(find "$EXPORTS_DIR" -type f -not -name ".gitkeep" -mtime "+$RETENTION_DAYS" | wc -l)
  log "DRY-RUN: $COUNT Datei(en) waeren betroffen. Leere Verzeichnisse wuerden danach ebenfalls entfernt."
  exit 0
fi

log "Loesche Dateien in $EXPORTS_DIR, aelter als $RETENTION_DAYS Tage..."
DELETED=$(find "$EXPORTS_DIR" -type f -not -name ".gitkeep" -mtime "+$RETENTION_DAYS" -print -delete | tee /dev/stderr | wc -l)
log "$DELETED Datei(en) geloescht."

log "Entferne leer gewordene Unterverzeichnisse..."
# -mindepth 1, damit exports/ selbst nie entfernt wird; leert sich rekursiv von innen nach
# aussen (find -depth), sodass z.B. exports/protocol-1/images/ VOR exports/protocol-1/
# geprueft wird.
find "$EXPORTS_DIR" -mindepth 1 -depth -type d -empty -print -delete

log "Fertig."
