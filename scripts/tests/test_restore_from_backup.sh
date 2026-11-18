#!/usr/bin/env bash
set -euo pipefail

# scripts/lib/restore_from_backup.sh (deploy.sh --restore-from-backup) gegen ein Fake-Compose: die
# Recovery-CLI-Aufrufe werden protokolliert und aus Szenario-Variablen beantwortet, Eingaben kommen
# aus einer Datei statt vom Terminal (RESTORE_TTY).

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TEST_DIR="$(mktemp -d)"
trap 'rm -rf "$TEST_DIR"' EXIT

# shellcheck source=scripts/lib/restore_from_backup.sh
source "$REPO_DIR/scripts/lib/restore_from_backup.sh"
ENVIRONMENT=prod
PROJECT_NAME="hocx-restore-test-$$"
PROJECT_DIR="$TEST_DIR/project"
ENV_FILE="$PROJECT_DIR/.env"
POSTGRES_USER=hocx
POSTGRES_DB=hocx
HOCX_VERSION=v1.4.0
DC=(fake_dc)
RESTORE_TTY="$TEST_DIR/answers"

fail() {
  echo "FEHLER: $*" >&2
  exit 1
}

service_exists() { [ "$1" = local-s3 ] || [ "$1" = db ]; }
sleep() { :; }

reset_scenario() {
  if [ -n "${RESTORE_TTY_FD:-}" ]; then exec {RESTORE_TTY_FD}<&-; RESTORE_TTY_FD=""; fi
  rm -rf "$PROJECT_DIR"
  mkdir -p "$PROJECT_DIR/.releases"
  : > "$ENV_FILE"
  : > "$TEST_DIR/calls.log"
  SCHEMA_STATE=same RESTORED_EXISTS="" RESTORE_RC=0 EMPTY_TABLES=0
  POINTS=$'hocx-rp-alt\t2026-11-10T01:15:00+00:00\t1.3.0\t2600\tFalse\nhocx-rp-neu\t2026-11-18T01:15:00+00:00\t1.4.0\t2660\tFalse\nhocx-rp-kaputt\t2026-11-19T01:15:00+00:00\t1.4.0\t10\tTrue'
}

fake_dc() {
  echo "$*" >> "$TEST_DIR/calls.log"
  local args="$*"
  case "$args" in
    "up -d --pull never db"|"up -d --pull never local-s3") return 0 ;;
    "exec -T db pg_isready"*) return 0 ;;
    "run --rm --no-deps --pull never storage-init") return 0 ;;
    *"app.backup.cli info") echo "repository_id_pinned_ok: True" ;;
    *"app.backup.cli list --details --tsv") printf '%s\n' "$POINTS" ;;
    *"app.backup.cli show "*"--schema-state") echo "$SCHEMA_STATE" ;;
    *"app.backup.cli restore-full "*) return "$RESTORE_RC" ;;
    *"app.backup.cli swap-database "*) return 0 ;;
    *"SELECT 1 FROM pg_database WHERE datname = 'hocx_restored'"*) [ -z "$RESTORED_EXISTS" ] || echo 1 ;;
    *"SELECT 1 FROM pg_database WHERE datname = 'hocx_leer_vor_restore'"*) echo 1 ;;
    *"information_schema.tables"*) echo "$EMPTY_TABLES" ;;
    *"DROP DATABASE"*) return 0 ;;
    *) echo "unerwarteter Aufruf: $args" >&2; return 1 ;;
  esac
}

# 1) Nur auf einem leeren Server; ein vorgemerkter Restore darf fortgesetzt werden
reset_scenario
restore_guard 2> /dev/null || fail "leerer Server muss erlaubt sein"
touch "$PROJECT_DIR/.releases/current.env"
if restore_guard 2> /dev/null; then fail "laufendes Release darf nicht überschrieben werden"; fi
echo "ARCHIVE=hocx-rp-neu" > "$(restore_marker_file)"
restore_guard 2> /dev/null || fail "Fortsetzung mit Vormerkung muss erlaubt sein"

# 2) Normaler Ablauf: neuester gültiger Punkt (ungültige ausgeblendet), Bestätigungswort, lokales S3
reset_scenario
printf '1\nWIEDERHERSTELLEN\n' > "$RESTORE_TTY"
restore_run 2> "$TEST_DIR/out.log" || { cat "$TEST_DIR/out.log" >&2; fail "Restore sollte gelingen"; }
grep -q 'restore-full --archive hocx-rp-neu --target-db hocx_restored --local-s3 --yes$' "$TEST_DIR/calls.log" || fail "restore-full mit neuestem gültigem Punkt und --local-s3 erwartet"
grep -q 'swap-database --live hocx --restored hocx_restored --keep-as hocx_leer_vor_restore --yes' "$TEST_DIR/calls.log" || fail "Datenbanktausch erwartet"
grep -q 'DROP DATABASE "hocx_leer_vor_restore"' "$TEST_DIR/calls.log" || fail "leere Datenbank vom ersten Start soll weg"
grep -q 'hocx-rp-kaputt' "$TEST_DIR/out.log" && fail "ungültiger Punkt darf nicht angeboten werden"
grep -qx 'ARCHIVE=hocx-rp-neu' "$(restore_marker_file)" || fail "Punkt muss für eine Fortsetzung vorgemerkt sein"
grep -q -- '-e APP_DB_PASSWORD' "$TEST_DIR/calls.log" || fail "Rollen-Passwörter gehen als Umgebung, nicht als Argument"

# 3) Falsches Bestätigungswort: nichts wird wiederhergestellt
reset_scenario
printf '1\nja\n' > "$RESTORE_TTY"
if restore_run 2> /dev/null; then fail "ohne Bestätigungswort darf nichts passieren"; fi
grep -q 'restore-full' "$TEST_DIR/calls.log" && fail "restore-full ohne Bestätigung aufgerufen"

# 4) Ältere Version: nach Rückfrage mit kontrollierter Migration
reset_scenario
SCHEMA_STATE=upgrade
printf '2\nja\nWIEDERHERSTELLEN\n' > "$RESTORE_TTY"
restore_run 2> /dev/null || fail "älterer Punkt mit Migration sollte gelingen"
grep -q 'restore-full --archive hocx-rp-alt .*--allow-schema-upgrade' "$TEST_DIR/calls.log" || fail "--allow-schema-upgrade erwartet"

# 5) Neuere Version als das Image: Abbruch mit Hinweis, Punkt vorgemerkt
reset_scenario
SCHEMA_STATE=newer
printf '1\n' > "$RESTORE_TTY"
if restore_run 2> "$TEST_DIR/out.log"; then fail "neuerer Punkt muss abbrechen"; fi
grep -q 'HOCX_VERSION' "$TEST_DIR/out.log" || fail "Hinweis auf HOCX_VERSION erwartet"
grep -qx 'ARCHIVE=hocx-rp-neu' "$(restore_marker_file)" || fail "Punkt muss vorgemerkt bleiben"
grep -q 'restore-full' "$TEST_DIR/calls.log" && fail "restore-full darf nicht laufen"

# 6) Fortsetzung: vorgemerkter Punkt ohne erneute Auswahl, vorhandene Zieldatenbank -> --resume
reset_scenario
echo "ARCHIVE=hocx-rp-neu" > "$(restore_marker_file)"
RESTORED_EXISTS=1
: > "$RESTORE_TTY"
restore_run 2> /dev/null || fail "Fortsetzung sollte ohne Eingaben gelingen"
grep -q 'restore-full --archive hocx-rp-neu .*--resume' "$TEST_DIR/calls.log" || fail "--resume erwartet"
grep -q 'list --details' "$TEST_DIR/calls.log" && fail "vorgemerkter Punkt darf nicht neu gewählt werden"

# 7) Referenzprüfung mit Abweichungen: nur nach ausdrücklicher Zustimmung weiter
reset_scenario
RESTORE_RC=2
printf '1\nWIEDERHERSTELLEN\nnein\n' > "$RESTORE_TTY"
if restore_run 2> /dev/null; then fail "Abweichungen ohne Zustimmung müssen abbrechen"; fi
grep -q 'swap-database' "$TEST_DIR/calls.log" && fail "ohne Zustimmung kein Datenbanktausch"

# 8) .env-Werte ersetzen statt verdoppeln
reset_scenario
printf "BACKUP_ENABLED='false'\nANDERES='x'\n" > "$ENV_FILE"
restore_set_env BACKUP_ENABLED true
[ "$(grep -c '^BACKUP_ENABLED=' "$ENV_FILE")" = 1 ] || fail "Schlüssel doppelt in .env"
grep -qx "BACKUP_ENABLED='true'" "$ENV_FILE" || fail "Wert nicht gesetzt"
grep -qx "ANDERES='x'" "$ENV_FILE" || fail "andere Werte müssen bleiben"
[ "$(stat -c '%a' "$ENV_FILE")" = 600 ] || fail ".env muss 600 bleiben"

echo "restore_from_backup: ok"
