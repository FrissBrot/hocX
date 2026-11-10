#!/usr/bin/env bash
set -euo pipefail

# scripts/lib/storage_gate.sh (Upgrade-Tor «nur noch S3») gegen ein Fake-Compose: die SQL-Abfragen
# werden anhand ihres Inhalts aus Szenario-Variablen beantwortet, Schreibzugriffe protokolliert.

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TEST_DIR="$(mktemp -d)"
trap 'rm -rf "$TEST_DIR"' EXIT

# shellcheck source=scripts/lib/storage_gate.sh
source "$REPO_DIR/scripts/lib/storage_gate.sh"
POSTGRES_USER=hocx
POSTGRES_DB=hocx
STORAGE_GATE_POLL_SECONDS=0
DC=(fake_dc)

assert_no_update() {
  if grep -q '^UPDATE' "$TEST_DIR/sql.log"; then echo "unerwartete Änderung: $1" >&2; exit 1; fi
}

reset_scenario() {
  DB_RUNNING=1 HAS_STORAGE=t HAS_TENANT=t ACTIVE=garage_local OPEN_MIGRATION="" HAS_FILES=t
  FS_ROWS="" PURGE_AFTER_POLLS=1 PURGE_ERROR=""
  : > "$TEST_DIR/sql.log"
  echo 0 > "$TEST_DIR/polls"
  unset HOCX_SKIP_STORAGE_FALLBACK
}

fake_dc() {
  if [ "$1" = ps ]; then
    [ "$DB_RUNNING" = 1 ] && echo container-id
    return 0
  fi
  local sql="${*: -1}" polls
  echo "$sql" >> "$TEST_DIR/sql.log"
  case "$sql" in
    *"to_regclass('public.storage_state')"*) echo "$HAS_STORAGE" ;;
    *"to_regclass('public.tenant')"*) echo "$HAS_TENANT" ;;
    *"FROM storage_state s JOIN storage_profile p"*) echo "$ACTIVE" ;;
    *"FROM storage_migration"*) echo "$OPEN_MIGRATION" ;;
    *"EXISTS (SELECT 1 FROM storage_object)"*) echo "$HAS_FILES" ;;
    "SELECT g.generation, g.status,"*) printf '%s' "$FS_ROWS" ;;
    UPDATE*) ;;
    "SELECT count(*)"*)
      polls=$(($(cat "$TEST_DIR/polls") + 1)); echo "$polls" > "$TEST_DIR/polls"
      if [ "$polls" -gt "$PURGE_AFTER_POLLS" ]; then echo 0; else echo 1; fi ;;
    "SELECT string_agg"*) echo "$PURGE_ERROR" ;;
    *) echo "unerwartete Abfrage: $sql" >&2; return 1 ;;
  esac
}

# Erster Deploy: keine Datenbank, nichts zu prüfen.
reset_scenario; DB_RUNNING=0
storage_upgrade_gate < /dev/null > /dev/null
test ! -s "$TEST_DIR/sql.log"

# Release vor 1.2 (keine Objektspeicher-Tabellen, aber Daten): gesperrt.
reset_scenario; HAS_STORAGE=f
if storage_upgrade_gate < /dev/null 2> "$TEST_DIR/err"; then echo "vor 1.2 hätte sperren müssen" >&2; exit 1; fi
grep -q "vor 1.2" "$TEST_DIR/err"

# Dateisystem aktiv mit Dateien: Erstmigration fehlt.
reset_scenario; ACTIVE=filesystem
if storage_upgrade_gate < /dev/null 2> "$TEST_DIR/err"; then echo "Dateisystem mit Dateien hätte sperren müssen" >&2; exit 1; fi
grep -q "Erstmigration" "$TEST_DIR/err"

# Dateisystem aktiv ohne Dateien (Neuinstallation): durchlassen, Migration stellt um.
reset_scenario; ACTIVE=filesystem; HAS_FILES=f
storage_upgrade_gate < /dev/null > /dev/null

# Offene Migration: gesperrt.
reset_scenario; OPEN_MIGRATION="live (copying)"
if storage_upgrade_gate < /dev/null 2> "$TEST_DIR/err"; then echo "offene Migration hätte sperren müssen" >&2; exit 1; fi
grep -q "live (copying)" "$TEST_DIR/err"

# Alles bereinigt: keine Rückfrage, keine Änderung.
reset_scenario
storage_upgrade_gate < /dev/null > /dev/null
assert_no_update "alles bereinigt"

# Rückfallfrist läuft, nicht interaktiv ohne Freigabe: Abbruch, nichts geändert.
reset_scenario; FS_ROWS=$'0|retained|t|24.11.2026 10:00\n'
if storage_upgrade_gate < /dev/null 2> "$TEST_DIR/err"; then echo "laufende Frist hätte sperren müssen" >&2; exit 1; fi
grep -q "WARNUNG" "$TEST_DIR/err"
grep -q "HOCX_SKIP_STORAGE_FALLBACK=1" "$TEST_DIR/err"
assert_no_update "Frist ohne Freigabe"

# Rückfallfrist läuft, Überspringen per Variable: Bereinigung anfordern und abwarten.
reset_scenario; FS_ROWS=$'0|retained|t|24.11.2026 10:00\n'; export HOCX_SKIP_STORAGE_FALLBACK=1
storage_upgrade_gate < /dev/null > "$TEST_DIR/out" 2>&1
grep -q "status = 'purge_requested'" "$TEST_DIR/sql.log"
grep -q "WHERE generation = 0 AND status = 'retained'" "$TEST_DIR/sql.log"
grep -q "bereinigt" "$TEST_DIR/out"

# Interaktiv «j»: Frist wird beendet. Zwei Generationen in der Frist - die Antworten dürfen keine
# Zeile der Generationsliste verschlucken (früher las die Schleife aus einem Here-String).
reset_scenario; FS_ROWS=$'0|retained|t|24.11.2026 10:00\n3|retained|t|30.11.2026 10:00\n'
printf 'j\nj\n' | STORAGE_GATE_INTERACTIVE=1 storage_upgrade_gate > "$TEST_DIR/out" 2>&1
grep -q "WHERE generation = 0 AND status = 'retained'" "$TEST_DIR/sql.log"
grep -q "WHERE generation = 3 AND status = 'retained'" "$TEST_DIR/sql.log"

# Interaktiv «n» (Standard bei Enter): Abbruch, nichts geändert.
reset_scenario; FS_ROWS=$'0|retained|t|24.11.2026 10:00\n'
if printf '\n' | STORAGE_GATE_INTERACTIVE=1 storage_upgrade_gate > /dev/null 2>&1; then echo "Enter hätte abbrechen müssen" >&2; exit 1; fi
assert_no_update "interaktiv abgelehnt"

# Unerwartete Generationsnummer aus der Datenbank: Abbruch statt SQL zu bauen.
reset_scenario; FS_ROWS=$'0;DROP|retained|f|\n'
if storage_upgrade_gate < /dev/null > /dev/null 2>&1; then echo "ungültige Generation hätte abbrechen müssen" >&2; exit 1; fi
assert_no_update "ungültige Generation"

# Unbekannter Wert der Variable: kein stilles Überspringen.
reset_scenario; FS_ROWS=$'0|retained|t|24.11.2026 10:00\n'; export HOCX_SKIP_STORAGE_FALLBACK=vielleicht
if storage_upgrade_gate < /dev/null 2> /dev/null; then echo "unbekannter Wert hätte sperren müssen" >&2; exit 1; fi
assert_no_update "unbekannter Wert"

# Frist abgelaufen: ohne Rückfrage bereinigen.
reset_scenario; FS_ROWS=$'0|retained|f|01.11.2026 10:00\n'
storage_upgrade_gate < /dev/null > "$TEST_DIR/out" 2>&1
grep -q "abgelaufen" "$TEST_DIR/out"
grep -q "status = 'purge_requested'" "$TEST_DIR/sql.log"

# Bereinigung läuft schon: nur abwarten, keine neue Anforderung.
reset_scenario; FS_ROWS=$'0|purging|f|\n'
storage_upgrade_gate < /dev/null > /dev/null 2>&1
assert_no_update "Bereinigung läuft schon"

# Bereinigung wird nicht fertig: Abbruch nach dem Timeout.
reset_scenario; FS_ROWS=$'0|purge_requested|f|\n'; PURGE_AFTER_POLLS=999; PURGE_ERROR="g0: OSError"
if HOCX_STORAGE_PURGE_TIMEOUT=0 storage_upgrade_gate < /dev/null 2> "$TEST_DIR/err"; then echo "Timeout hätte abbrechen müssen" >&2; exit 1; fi
grep -q "OSError" "$TEST_DIR/err"
grep -q "nicht fertig" "$TEST_DIR/err"

echo "storage gate tests: ok"
