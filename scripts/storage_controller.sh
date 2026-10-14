#!/usr/bin/env bash
set -euo pipefail

# Host-seitiger Controller für den lokalen S3-Dienst (Garage, Compose-Service local-s3).
#
# Läuft auf dem Host (Cron alle 5 Minuten über run_job.sh, zusätzlich am Ende von deploy.sh) -
# nie im Backend: das Backend bekommt bewusst keinen Docker-Socket (siehe CLAUDE.md,
# Systemmonitoring). Die Entscheidung trifft allein die Datenbank über
# storage_local_s3_decision() (Migration 0113). Benötigt ist das lokale S3, solange es
#   - der aktive Speicher ist,
#   - Quelle oder Ziel einer offenen Migration ist,
#   - eine Generation mit laufender Rückfallfrist (retained) bzw. eine offene Bereinigung hält,
#   - noch nicht verifizierte Objekte einer abgeschlossenen Migration enthält.
# Der Fortschritt einer Kopie allein ist nie ein Grund zum Stoppen.
#
# Stoppen heisst ausschliesslich `docker compose stop local-s3`: Container und Volume bleiben
# erhalten, es wird nichts gelöscht. Wird das lokale S3 wieder gebraucht (z. B. Migration zurück),
# startet dieses Skript den Dienst wieder und wartet auf den Healthcheck.
#
# Usage: scripts/storage_controller.sh [--dry-run]
#   */5 * * * * /docker/hocX/scripts/run_job.sh storage_controller /docker/hocX/scripts/storage_controller.sh >> /docker/hocX/backups/storage_controller.log 2>&1

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${HOCX_ENV_FILE:-$REPO_DIR/.env}"
DRY_RUN=false
[ "${1:-}" = "--dry-run" ] && DRY_RUN=true

# shellcheck source=scripts/lib/env.sh
source "$REPO_DIR/scripts/lib/env.sh"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] storage_controller: $*"; }

[ -f "$ENV_FILE" ] || { log "Env-Datei $ENV_FILE fehlt"; exit 1; }
load_env_file "$ENV_FILE"
: "${POSTGRES_USER:?POSTGRES_USER fehlt}"
: "${POSTGRES_DB:?POSTGRES_DB fehlt}"

cd "$REPO_DIR"
DC=(docker compose --env-file "$ENV_FILE")
if [ -n "${HOCX_COMPOSE_PROJECT:-}" ]; then
  DC+=(-p "$HOCX_COMPOSE_PROJECT")
fi
if [ -n "${HOCX_COMPOSE_FILES:-}" ]; then
  # z. B. "docker-compose.release.yml" auf Servern (wie deploy.sh)
  for file in $HOCX_COMPOSE_FILES; do DC+=(-f "$file"); done
fi

if ! "${DC[@]}" config --services 2>/dev/null | grep -qx local-s3; then
  log "kein Service local-s3 in dieser Compose-Konfiguration - nichts zu tun"
  exit 0
fi

# Fehler beim Abfragen = im Zweifel "benötigt": lieber unnötig laufen lassen als stoppen.
if ! decision="$("${DC[@]}" exec -T db psql -X -A -t -q -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    -c "SELECT needed::text || '|' || reason FROM storage_local_s3_decision()" 2>/dev/null)"; then
  decision="true|db_unavailable"
fi
decision="$(echo "$decision" | tr -d '[:space:]')"
needed="${decision%%|*}"
reason="${decision#*|}"

running=false
if [ -n "$("${DC[@]}" ps local-s3 --status running -q 2>/dev/null)" ]; then
  running=true
fi
log "lokales S3: benötigt=$needed (Grund: $reason), läuft=$running"

if [ "$needed" = "true" ] && [ "$running" = "false" ]; then
  if [ "$DRY_RUN" = true ]; then log "würde local-s3 starten"; exit 0; fi
  log "starte local-s3"
  "${DC[@]}" up -d --no-deps local-s3
  for _ in $(seq 1 30); do
    status="$(docker inspect --format '{{.State.Health.Status}}' "$("${DC[@]}" ps -q local-s3)" 2>/dev/null || echo unknown)"
    if [ "$status" = "healthy" ]; then
      log "local-s3 ist gesund"
      # Einrichtung (Buckets/Schlüssel) idempotent sicherstellen.
      "${DC[@]}" run --rm --no-deps storage-init >/dev/null 2>&1 || log "WARNUNG: storage-init fehlgeschlagen"
      exit 0
    fi
    sleep 5
  done
  log "FEHLER: local-s3 wurde nicht gesund"
  exit 1
fi

if [ "$needed" = "false" ] && [ "$running" = "true" ]; then
  case "$reason" in
    not_needed|no_local_profile) ;;
    *) log "unbekannter Grund '$reason' - aus Vorsicht kein Stopp"; exit 0 ;;
  esac
  if [ "$DRY_RUN" = true ]; then log "würde local-s3 stoppen (Daten bleiben erhalten)"; exit 0; fi
  log "stoppe local-s3 (Volume und Daten bleiben erhalten)"
  "${DC[@]}" stop local-s3
fi
exit 0
