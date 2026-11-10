#!/usr/bin/env bash
set -euo pipefail

# Spielt einen Dump aus backups/ (backup_db.sh oder Pre-Deploy-Backup von deploy.sh) in die
# Datenbank der Instanz dieses Checkouts zurueck.
#
# Usage: scripts/restore_db.sh <backups/…sql.gz|…sql.gz.gpg> [--yes]
#
# Verschlüsselte Dumps (.sql.gz.gpg, scripts/lib/dump_crypto.sh) brauchen den privaten Schlüssel aus
# der Notfallmappe: BACKUP_DUMP_PRIVATE_KEY_PATH=<Datei> setzen oder im GPG-Schlüsselbund haben.
#
# Warum ein eigenes Skript (Audit MAIN-OPS-002): Die Dumps sind Plain-SQL ohne --clean. Frueher
# empfahl das RUNBOOK, sie direkt in die laufende, bereits migrierte Datenbank zu pipen. Dabei
# scheitern CREATE- und COPY-Befehle an vorhandenen Objekten bzw. Zeilen, psql laeuft ohne
# ON_ERROR_STOP weiter und endet mit Exit 0 - ein Mischzustand aus neuem Schema und fehlenden
# Daten, der als Erfolg erscheint. Dieses Skript:
#   1. prueft den Dump (gzip -t) und verlangt eine Bestaetigung (Datenbankname eintippen oder
#      --yes),
#   2. stoppt die Dienste mit DB-Verbindung (backend, abgabebox-backend, photo-analysis-worker),
#   3. sichert den aktuellen Stand zuerst als backups/<zeit>-pre-restore.sql.gz,
#   4. loescht die Datenbank, legt sie leer neu an und vergibt CONNECT an die App-Rollen
#      (Datenbank-Rechte stehen nicht im pg_dump; Rollen sind clusterweit und bleiben erhalten),
#   5. spielt den Dump mit ON_ERROR_STOP=1 in einer einzigen Transaktion ein - jeder Fehler
#      bricht ab, statt einen halben Stand zu hinterlassen.
# Die gestoppten Dienste bleiben danach gestoppt: der Code muss erst auf die Version gebracht
# werden, zu der das Schema des Dumps passt (RUNBOOK Abschnitt 5).
#
# Die Dateiablage (storage/) ist NICHT Teil des Dumps, siehe RUNBOOK Abschnitt 10.

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${HOCX_ENV_FILE:-$REPO_DIR/.env}"
BACKUP_DIR="${HOCX_BACKUP_DIR:-$REPO_DIR/backups}"
DB_CLIENT_SERVICES=(backend abgabebox-backend photo-analysis-worker)
APP_DB_ROLES=(hocx_app hocx_abgabebox hocx_photo_worker)

# shellcheck source=scripts/lib/env.sh
source "$REPO_DIR/scripts/lib/env.sh"
# shellcheck source=scripts/lib/stack.sh
source "$REPO_DIR/scripts/lib/stack.sh"
# shellcheck source=scripts/lib/dump_crypto.sh
source "$REPO_DIR/scripts/lib/dump_crypto.sh"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }
fail() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] FEHLER: $*" >&2; exit 1; }

DUMP_FILE=""
ASSUME_YES=false
for arg in "$@"; do
  case "$arg" in
    --yes) ASSUME_YES=true ;;
    -*) fail "Unbekannte Option: $arg" ;;
    *)
      [ -z "$DUMP_FILE" ] || fail "Nur eine Dump-Datei angeben."
      DUMP_FILE="$arg"
      ;;
  esac
done
if [ -z "$DUMP_FILE" ]; then
  echo "Usage: $0 <backups/…sql.gz> [--yes]" >&2
  exit 64
fi
case "$DUMP_FILE" in
  *.sql.gz|*.sql.gz.gpg) ;;
  *) fail "Erwartet wird ein gzip-komprimierter Plain-SQL-Dump (*.sql.gz oder *.sql.gz.gpg): $DUMP_FILE" ;;
esac
if ! { [ -f "$DUMP_FILE" ] && [ -s "$DUMP_FILE" ]; }; then fail "Dump $DUMP_FILE fehlt oder ist leer."; fi
if [[ "$DUMP_FILE" == *.gpg ]]; then
  # Einmal entschlüsseln (bleibt gzip), im geschützten Backup-Ordner, am Ende entfernt.
  mkdir -p "$BACKUP_DIR"
  chmod 700 "$BACKUP_DIR"
  PLAIN_DUMP="$(mktemp "$BACKUP_DIR/.restore-XXXXXX.sql.gz")"
  trap 'rm -f "$PLAIN_DUMP"' EXIT
  decrypt_dump_to "$DUMP_FILE" "$PLAIN_DUMP" || fail "Dump $DUMP_FILE konnte nicht entschlüsselt werden (privater Schlüssel?)."
  DUMP_FILE="$PLAIN_DUMP"
fi
gzip -t "$DUMP_FILE" 2> /dev/null || fail "Dump $DUMP_FILE ist kein gueltiges gzip (beschaedigt/abgeschnitten?)."

[ -f "$ENV_FILE" ] || fail "Env-Datei $ENV_FILE fehlt."
load_env_file "$ENV_FILE"
resolve_hocx_stack "$REPO_DIR"
: "${POSTGRES_USER:?POSTGRES_USER fehlt in $ENV_FILE}"
: "${POSTGRES_DB:?POSTGRES_DB fehlt in $ENV_FILE}"
[[ "$POSTGRES_DB" =~ ^[a-z_][a-z0-9_]*$ ]] || fail "POSTGRES_DB '$POSTGRES_DB' ist kein einfacher Bezeichner."
[[ "$POSTGRES_USER" =~ ^[a-z_][a-z0-9_]*$ ]] || fail "POSTGRES_USER '$POSTGRES_USER' ist kein einfacher Bezeichner."

cd "$REPO_DIR"
DC=(docker compose -p "$STACK_PROJECT" --env-file "$ENV_FILE" "${STACK_COMPOSE_ARGS[@]}")

if [ -z "$("${DC[@]}" ps db --status running -q 2> /dev/null || true)" ]; then
  fail "db-Container von Projekt '$STACK_PROJECT' laeuft nicht (ggf. HOCX_COMPOSE_PROJECT setzen, siehe scripts/lib/stack.sh)."
fi

echo "Restore in Projekt '$STACK_PROJECT' ($STACK_KIND), Datenbank '$POSTGRES_DB'"
echo "  Dump: $DUMP_FILE"
echo "  Der aktuelle Inhalt der Datenbank wird ERSETZT (vorher gesichert)."
if [ "$ASSUME_YES" != true ]; then
  read -r -p "Zum Bestaetigen den Datenbanknamen eintippen: " answer
  [ "$answer" = "$POSTGRES_DB" ] || fail "Abgebrochen."
fi

psql_admin() {
  "${DC[@]}" exec -T db psql -X -q -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" "$@"
}

mapfile -t defined_services < <("${DC[@]}" config --services)
stop_services=()
for service in "${DB_CLIENT_SERVICES[@]}"; do
  for defined in "${defined_services[@]}"; do
    [ "$service" = "$defined" ] && stop_services+=("$service")
  done
done
if [ "${#stop_services[@]}" -gt 0 ]; then
  log "Stoppe Dienste mit DB-Verbindung: ${stop_services[*]}"
  "${DC[@]}" stop "${stop_services[@]}"
fi

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"
check_dump_encryption || fail "Keine Sicherung ohne Verschlüsselung möglich - nichts verändert (Dienste bleiben gestoppt)."
SAFETY_FILE="$BACKUP_DIR/$(date +%Y%m%d-%H%M%S)-pre-restore$(dump_suffix)"
log "Sichere aktuellen Stand: $SAFETY_FILE"
if ! "${DC[@]}" exec -T db pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" | write_dump "$SAFETY_FILE.tmp" \
  || [ ! -s "$SAFETY_FILE.tmp" ]; then
  rm -f "$SAFETY_FILE.tmp"
  fail "Sicherung des aktuellen Stands fehlgeschlagen - nichts veraendert (Dienste bleiben gestoppt)."
fi
mv "$SAFETY_FILE.tmp" "$SAFETY_FILE"

log "Lege Datenbank '$POSTGRES_DB' neu an"
psql_admin -d postgres <<SQL
DROP DATABASE IF EXISTS "$POSTGRES_DB" WITH (FORCE);
CREATE DATABASE "$POSTGRES_DB" OWNER "$POSTGRES_USER";
SQL
for role in "${APP_DB_ROLES[@]}"; do
  psql_admin -d "$POSTGRES_DB" <<SQL
DO \$\$ BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '$role') THEN
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO %I', current_database(), '$role');
  END IF;
END \$\$;
SQL
done

log "Spiele Dump ein (ON_ERROR_STOP, eine Transaktion)"
if ! gunzip -c "$DUMP_FILE" | psql_admin --single-transaction -d "$POSTGRES_DB"; then
  echo >&2
  echo "Restore fehlgeschlagen - die Transaktion wurde vollstaendig zurueckgerollt, die Datenbank ist leer." >&2
  echo "Vorherigen Stand wiederherstellen: $0 $SAFETY_FILE" >&2
  exit 1
fi

revision="$(psql_admin -d "$POSTGRES_DB" -At -c 'SELECT version_num FROM alembic_version' 2> /dev/null || true)"
log "Restore abgeschlossen. Alembic-Stand des Dumps: ${revision:-unbekannt}"
log "Sicherung des vorherigen Stands: $SAFETY_FILE"
echo
echo "Naechste Schritte: Code auf die Version bringen, zu der dieser Schema-Stand passt, dann starten:"
case "$STACK_KIND" in
  prod|test) echo "  HOCX_VERSION in .env setzen, ./scripts/deploy.sh $STACK_KIND && ./scripts/verify_release.sh $STACK_KIND" ;;
  server) echo "  passenden Commit auschecken, docker compose -p $STACK_PROJECT … up -d (siehe RUNBOOK Abschnitt 11)" ;;
esac
