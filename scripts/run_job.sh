#!/usr/bin/env bash
set -uo pipefail

# Führt einen Host-Cronjob aus und meldet Start, Ende, Dauer und Ergebnis an die Job-Übersicht im
# Platform-Admin (/admin/jobs) - über die SQL-Funktionen record_job_start/record_job_run aus
# Migration 0105, per `docker compose exec db psql` (derselbe Weg wie backup_db.sh' pg_dump).
#
# Schlägt der Job fehl, meldet ihn das Backend innerhalb einer Minute per ntfy (sofern unter
# /admin/notifications eingerichtet). Läuft er gar nicht mehr (Cron-Eintrag weg, Host neu
# aufgesetzt), fällt er nach max_silence_seconds aus backend/app/core/job_registry.py als
# "überfällig" auf - darum dort jeden neuen Cronjob mit seinem Namen eintragen.
#
# Usage: scripts/run_job.sh <job_name> <befehl> [argumente...]
#   15 3 * * * /docker/hocX/scripts/run_job.sh backup_db /docker/hocX/scripts/backup_db.sh >> /docker/hocX/backups/backup_db.log 2>&1
#
# Exit-Code ist immer der des Befehls - ein Fehler beim Melden (DB weg) ändert ihn nicht, damit
# Cron-Mail/Logs weiterhin das echte Ergebnis zeigen.

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${HOCX_ENV_FILE:-$REPO_DIR/.env}"
# Wie viel der Ausgabe eines fehlgeschlagenen Jobs als Fehlermeldung gespeichert wird.
ERROR_TAIL_BYTES=1500

# shellcheck source=scripts/lib/env.sh
source "$REPO_DIR/scripts/lib/env.sh"
# shellcheck source=scripts/lib/stack.sh
source "$REPO_DIR/scripts/lib/stack.sh"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] run_job: $*" >&2; }

if [ "$#" -lt 2 ]; then
  echo "Usage: $0 <job_name> <befehl> [argumente...]" >&2
  exit 64
fi

JOB_NAME="$1"
shift
# Gleiche Regel wie in record_job_run (Migration 0105) - schon hier prüfen, damit ein Tippfehler
# beim Einrichten sofort auffällt und nicht erst als stiller Meldefehler.
if ! [[ "$JOB_NAME" =~ ^[a-z0-9][a-z0-9_.-]{0,99}$ ]]; then
  echo "Ungültiger Jobname '$JOB_NAME' (erlaubt: a-z, 0-9, _ . -)" >&2
  exit 64
fi

if [ -f "$ENV_FILE" ]; then
  load_env_file "$ENV_FILE"
fi

# Projekt und Compose-Dateien explizit (Audit MAIN-OPS-010), sonst fand der Wrapper auf dem
# Test-Host (hocx-test) oder in einem anders benannten Checkout die DB nicht.
STACK_READY=false
if resolve_hocx_stack "$REPO_DIR"; then
  STACK_READY=true
else
  log "WARNUNG: Compose-Projekt nicht bestimmbar - Lauf wird nicht gemeldet."
fi

report() {
  # SQL über stdin statt -c: nur so ersetzt psql die :'variablen' (sicheres Quoting der
  # Fehlermeldung, die beliebigen Text enthalten kann).
  if [ -z "${POSTGRES_USER:-}" ] || [ -z "${POSTGRES_DB:-}" ]; then
    log "WARNUNG: POSTGRES_USER/POSTGRES_DB fehlen - Lauf wird nicht gemeldet."
    return 0
  fi
  [ "$STACK_READY" = true ] || return 0
  if ! (cd "$REPO_DIR" && docker compose -p "$STACK_PROJECT" --env-file "$ENV_FILE" "${STACK_COMPOSE_ARGS[@]}" exec -T db \
      psql -X -q -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$@" >/dev/null); then
    log "WARNUNG: Meldung an die Job-Übersicht fehlgeschlagen (Job selbst unberührt)."
  fi
}

STARTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "SELECT record_job_start(:'job');" | report -v job="$JOB_NAME"

OUTPUT_FILE="$(mktemp)"
trap 'rm -f "$OUTPUT_FILE"' EXIT

# Ausgabe weiterreichen (Cron-Logdatei) und zugleich für die Fehlermeldung mitschneiden.
"$@" > >(tee "$OUTPUT_FILE") 2> >(tee -a "$OUTPUT_FILE" >&2)
EXIT_CODE=$?
wait

if [ "$EXIT_CODE" -eq 0 ]; then
  STATUS="success"
  ERROR=""
else
  STATUS="failure"
  ERROR="Exit-Code $EXIT_CODE: $(tail -c "$ERROR_TAIL_BYTES" "$OUTPUT_FILE")"
fi

if [ "$STATUS" = "success" ]; then
  echo "SELECT record_job_run(:'job', 'success', :'started'::timestamptz, now(), NULL, TRUE);" \
    | report -v job="$JOB_NAME" -v started="$STARTED_AT"
else
  echo "SELECT record_job_run(:'job', 'failure', :'started'::timestamptz, now(), :'error', TRUE);" \
    | report -v job="$JOB_NAME" -v started="$STARTED_AT" -v error="$ERROR"
fi

exit "$EXIT_CODE"
