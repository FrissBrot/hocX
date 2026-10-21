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
# Usage: scripts/backup_db.sh   (keine Argumente - sichert die Instanz dieses Checkouts)
#
# Welche Instanz das ist, bestimmt scripts/lib/stack.sh (Audit MAIN-OPS-003/-010): auf einem
# als prod markierten Host der Release-Stack (Projekt hocx), auf einem Host ohne Markierung die
# Instanz aus dem Quellcode (docker-compose.yml, Projekt aus HOCX_COMPOSE_PROJECT, Default hocx;
# laeuft sie ueber scripts/dev.sh, HOCX_COMPOSE_PROJECT=hocx-dev setzen). Auf einem als test
# markierten Host wird abgelehnt: dort liegen nur Demo-Daten, die jeder Test-Deploy neu befuellt.
#
# Zurueckspielen: scripts/restore_db.sh <dump> (siehe RUNBOOK Abschnitt 5).
#
# Suggested crontab entry: run nightly at 03:15 (Pfad an den Checkout anpassen).
#   15 3 * * * <repo>/scripts/run_job.sh backup_db <repo>/scripts/backup_db.sh >> <repo>/backups/backup_db.log 2>&1

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_DIR="$REPO_DIR"
ENV_FILE="${HOCX_ENV_FILE:-$PROJECT_DIR/.env}"
BACKUP_DIR="${HOCX_BACKUP_DIR:-$PROJECT_DIR/backups}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"

# shellcheck source=scripts/lib/env.sh
source "$REPO_DIR/scripts/lib/env.sh"
# shellcheck source=scripts/lib/stack.sh
source "$REPO_DIR/scripts/lib/stack.sh"
# shellcheck source=scripts/lib/dump_crypto.sh
source "$REPO_DIR/scripts/lib/dump_crypto.sh"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }
fail() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: $*" >&2; exit 1; }

if [ ! -f "$ENV_FILE" ]; then
  fail "Env-Datei $ENV_FILE fehlt."
fi

load_env_file "$ENV_FILE"

# Nach dem Laden der .env, damit dort ein HOCX_COMPOSE_PROJECT greift.
resolve_hocx_stack "$REPO_DIR" || fail "Host-Markierung ungueltig - kein Backup."
if [ "$STACK_KIND" = test ]; then
  fail "Dieser Host ist als 'test' provisioniert - dort liegen nur Demo-Daten, kein Backup."
fi

# Abgelöst durch das Borg-Backup (docs-site/docs/technik/backup/, RUNBOOK Abschnitt 7): sobald
# es aktiv ist, laeuft dieses Skript nicht mehr unkontrolliert parallel. Bestehende Dumps in
# backups/ bleiben unangetastet. Bewusst trotzdem ausfuehren: HOCX_LEGACY_BACKUP_FORCE=true.
if [ "${BACKUP_ENABLED:-false}" = true ] && [ "${HOCX_LEGACY_BACKUP_FORCE:-false}" != true ]; then
  log "Borg-Backup ist aktiv (BACKUP_ENABLED=true) - lokales Cron-Backup uebersprungen. Cron-Eintrag entfernen (RUNBOOK Abschnitt 7)."
  exit 0
fi

: "${POSTGRES_USER:?POSTGRES_USER fehlt in $ENV_FILE}"
: "${POSTGRES_DB:?POSTGRES_DB fehlt in $ENV_FILE}"

cd "$PROJECT_DIR"
DC=(docker compose -p "$STACK_PROJECT" --env-file "$ENV_FILE" "${STACK_COMPOSE_ARGS[@]}")

if ! "${DC[@]}" ps db --status running -q > /dev/null 2>&1 || [ -z "$("${DC[@]}" ps db --status running -q)" ]; then
  fail "db-Container von Projekt '$STACK_PROJECT' laeuft nicht - kein Backup moeglich (ggf. HOCX_COMPOSE_PROJECT setzen, siehe Kopfkommentar)."
fi

mkdir -p "$BACKUP_DIR"
# Haerten unabhaengig vom Umask des aufrufenden Kontexts (Cron etc.) - anders als deploy.sh
# (chmod 700 in dessen Preflight) laeuft dieses Skript laut Header-Kommentar eigenstaendig
# und darf sich nicht darauf verlassen, dass deploy.sh das Verzeichnis vorher gehaertet hat.
# Die pg_dump-Inhalte (Passwort-Hashes, alle Mandantendaten) duerfen nicht world-/group-lesbar
# im Dateisystem liegen.
chmod 700 "$BACKUP_DIR"
# Mit öffentlichem Schlüssel verschlüsselt (.sql.gz.gpg), sonst wie bisher .sql.gz - siehe
# scripts/lib/dump_crypto.sh (Datenschutz-Audit PRIV-009).
check_dump_encryption || fail "Kein Backup ohne Verschlüsselung (HOCX_REQUIRE_DUMP_ENCRYPTION=true)."
BACKUP_FILE="$BACKUP_DIR/$(date +%Y%m%d-%H%M%S)-cron$(dump_suffix)"
TMP_FILE="$BACKUP_FILE.tmp"

log "Erstelle Backup: $BACKUP_FILE"
if ! "${DC[@]}" exec -T db pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" | write_dump "$TMP_FILE"; then
  rm -f "$TMP_FILE"
  fail "pg_dump/gzip/gpg fehlgeschlagen - kein Backup geschrieben."
fi

if [ ! -s "$TMP_FILE" ]; then
  rm -f "$TMP_FILE"
  fail "Backup-Datei ist leer - verworfen."
fi

mv "$TMP_FILE" "$BACKUP_FILE"
log "Backup abgeschlossen: $BACKUP_FILE ($(du -h "$BACKUP_FILE" | cut -f1))"

log "Loesche eigene Cron-Backups aelter als $RETENTION_DAYS Tage..."
# Nur "-cron.sql.gz" (audit I4, 2026-08-16): "*.sql.gz" traf zuvor auch deploy.sh's
# Pre-Deploy-Backups ("-pre-<version>.sql.gz") und beliebige manuelle Sicherheits-Dumps im
# selben Ordner - ein fuer einen spaeteren Rollback vorgesehenes Backup verschwand damit
# automatisch nach RETENTION_DAYS, ohne dass das je jemand aktiv entschieden hatte.
find "$BACKUP_DIR" -maxdepth 1 -type f \( -name "*-cron.sql.gz" -o -name "*-cron.sql.gz.gpg" \) -mtime "+$RETENTION_DAYS" -print -delete

# Optional offsite copy (audit I5, 2026-08-16): backups/ lives on the same disk/host as
# the live DB volume, so a disk/host failure loses both simultaneously - there was no
# offsite copy of any kind before this. No-ops unless both OFFSITE_BACKUP_REMOTE is set
# (an rclone remote name, e.g. "s3:my-bucket/hocx-backups" - see
# https://rclone.org/docs/#configure for setting one up) and the `rclone` binary is
# installed, so this is safe to leave disabled until someone actually configures a remote.
# Ein Offsite-Fehler laesst den Lauf scheitern (Audit MAIN-OPS-006): frueher endete das Skript
# trotzdem mit 0, run_job.sh meldete "success" und niemand bemerkte die fehlende Offsite-Kopie.
# Das lokale Backup oben ist in dem Fall trotzdem geschrieben.
if [ -n "${OFFSITE_BACKUP_REMOTE:-}" ]; then
  if ! command -v rclone > /dev/null 2>&1; then
    fail "OFFSITE_BACKUP_REMOTE gesetzt, aber 'rclone' ist nicht installiert - Offsite-Kopie fehlt (lokales Backup vorhanden: $BACKUP_FILE)."
  fi
  # Unverschlüsselte Dumps nur auf ein verschlüsselndes rclone-Remote (Typ crypt), PRIV-009.
  case "$BACKUP_FILE" in
    *.gpg) ;;
    *)
      if ! rclone config show "${OFFSITE_BACKUP_REMOTE%%:*}" 2> /dev/null | grep -qE '^type *= *crypt'; then
        fail "Offsite-Kopie verweigert: Dump unverschlüsselt und OFFSITE_BACKUP_REMOTE ist kein rclone-crypt-Remote (lokales Backup vorhanden: $BACKUP_FILE)."
      fi
      ;;
  esac
  log "Kopiere Backup nach OFFSITE_BACKUP_REMOTE=$OFFSITE_BACKUP_REMOTE..."
  if ! rclone copy "$BACKUP_FILE" "$OFFSITE_BACKUP_REMOTE" --quiet; then
    fail "Offsite-Kopie fehlgeschlagen (lokales Backup vorhanden: $BACKUP_FILE)."
  fi
  # Offsite ebenfalls mit Frist: früher kopierte rclone nur und löschte nie (PRIV-009).
  OFFSITE_RETENTION_DAYS="${OFFSITE_RETENTION_DAYS:-$RETENTION_DAYS}"
  if ! rclone delete "$OFFSITE_BACKUP_REMOTE" --min-age "${OFFSITE_RETENTION_DAYS}d" --include "*-cron.sql.gz*" --quiet; then
    fail "Alte Offsite-Kopien konnten nicht entfernt werden."
  fi
  log "Offsite-Kopie abgeschlossen (Frist ${OFFSITE_RETENTION_DAYS} Tage)."
else
  log "Kein OFFSITE_BACKUP_REMOTE gesetzt - Backup bleibt lokal (siehe RUNBOOK.md Abschnitt 10)."
fi

log "Fertig."
