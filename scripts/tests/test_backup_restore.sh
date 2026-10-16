#!/usr/bin/env bash
set -euo pipefail

# scripts/backup_db.sh und scripts/restore_db.sh gegen ein Fake-`docker` im PATH
# (Audit MAIN-OPS-002/-003/-006/-010): explizites Compose-Projekt je Host-Markierung,
# Offsite-Fehler als Exit != 0, Restore nur mit ON_ERROR_STOP in eine frisch angelegte DB.

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TEST_DIR="$(mktemp -d)"
trap 'rm -rf "$TEST_DIR"' EXIT

fail() {
  echo "FEHLER: $*" >&2
  exit 1
}

mkdir -p "$TEST_DIR/bin"
cat > "$TEST_DIR/bin/docker" <<EOF
#!/usr/bin/env bash
args="\$*"
case "\$args" in
  *" ps db "*) echo "ARGS: \$args" >> "$TEST_DIR/calls.log"; echo "container-id" ;;
  *" config --services"*) printf 'db\nbackend\nfrontend\nabgabebox-backend\n' ;;
  *" pg_dump "*) echo "ARGS: \$args" >> "$TEST_DIR/calls.log"; echo "-- fake dump" ;;
  *" psql "*)
    { echo "ARGS: \$args"; cat; echo; } >> "$TEST_DIR/calls.log"
    case "\$args" in *--single-transaction*) exit "\${FAKE_RESTORE_EXIT:-0}" ;; esac
    ;;
  *) echo "ARGS: \$args" >> "$TEST_DIR/calls.log" ;;
esac
exit 0
EOF
cat > "$TEST_DIR/bin/rclone" <<EOF
#!/usr/bin/env bash
exit "\${FAKE_RCLONE_EXIT:-0}"
EOF
chmod +x "$TEST_DIR/bin/docker" "$TEST_DIR/bin/rclone"
export PATH="$TEST_DIR/bin:$PATH"

printf "POSTGRES_USER=hocx\nPOSTGRES_DB=hocx\n" > "$TEST_DIR/test.env"
chmod 600 "$TEST_DIR/test.env"
export HOCX_ENV_FILE="$TEST_DIR/test.env"
export HOCX_BACKUP_DIR="$TEST_DIR/backups"
export HOCX_HOST_MARKER_FILE="$TEST_DIR/no-marker"
unset OFFSITE_BACKUP_REMOTE HOCX_COMPOSE_PROJECT || true

marker() {
  rm -f "$TEST_DIR/marker"
  printf '%s\n' "$1" > "$TEST_DIR/marker"
  chmod 444 "$TEST_DIR/marker"
  export HOCX_HOST_MARKER_FILE="$TEST_DIR/marker"
}

# --- Backup ohne Host-Markierung: Quellcode-Instanz, Projekt explizit ---------------------
: > "$TEST_DIR/calls.log"
"$REPO_DIR/scripts/backup_db.sh" > /dev/null
grep -q -- "-p hocx --env-file $TEST_DIR/test.env -f $REPO_DIR/docker-compose.yml --project-directory $REPO_DIR exec -T db pg_dump" "$TEST_DIR/calls.log" \
  || fail "Backup ohne Markierung nutzt nicht -p hocx -f docker-compose.yml"
ls "$TEST_DIR/backups/"*-cron.sql.gz > /dev/null 2>&1 || fail "Kein Cron-Backup geschrieben"

# Ueber dev.sh betriebene Instanz: Projekt hocx-dev inkl. Dev-Overlay.
: > "$TEST_DIR/calls.log"
HOCX_COMPOSE_PROJECT=hocx-dev "$REPO_DIR/scripts/backup_db.sh" > /dev/null
grep -q -- "-p hocx-dev .* -f $REPO_DIR/docker-compose.dev.yml" "$TEST_DIR/calls.log" \
  || fail "HOCX_COMPOSE_PROJECT=hocx-dev laedt das Dev-Overlay nicht"

# --- Backup auf prod-Host: Release-Stack -------------------------------------------------
marker prod
: > "$TEST_DIR/calls.log"
"$REPO_DIR/scripts/backup_db.sh" > /dev/null
grep -q -- "-p hocx .* -f $REPO_DIR/docker-compose.release.yml" "$TEST_DIR/calls.log" \
  || fail "Backup auf prod nutzt nicht den Release-Stack"

# --- Backup auf test-Host wird abgelehnt -------------------------------------------------
marker test
if "$REPO_DIR/scripts/backup_db.sh" > /dev/null 2>&1; then
  fail "Backup auf einem test-Host wurde nicht abgelehnt"
fi
export HOCX_HOST_MARKER_FILE="$TEST_DIR/no-marker"

# --- Offsite-Fehler: Exit != 0, lokales Backup bleibt ------------------------------------
rm -rf "$TEST_DIR/backups"
set +e
OFFSITE_BACKUP_REMOTE="remote:bucket" FAKE_RCLONE_EXIT=1 "$REPO_DIR/scripts/backup_db.sh" > /dev/null 2>&1
rc=$?
set -e
test "$rc" -ne 0 || fail "Fehlgeschlagene Offsite-Kopie endete mit Exit 0"
ls "$TEST_DIR/backups/"*-cron.sql.gz > /dev/null 2>&1 || fail "Lokales Backup fehlt nach Offsite-Fehler"
OFFSITE_BACKUP_REMOTE="remote:bucket" "$REPO_DIR/scripts/backup_db.sh" > /dev/null \
  || fail "Erfolgreiche Offsite-Kopie meldet einen Fehler"

# --- Restore: beschaedigter Dump wird vor jeder Aenderung abgelehnt -----------------------
printf 'kein gzip' > "$TEST_DIR/broken.sql.gz"
: > "$TEST_DIR/calls.log"
if "$REPO_DIR/scripts/restore_db.sh" "$TEST_DIR/broken.sql.gz" --yes > /dev/null 2>&1; then
  fail "Beschaedigter Dump wurde akzeptiert"
fi
test ! -s "$TEST_DIR/calls.log" || fail "Restore hat trotz beschaedigtem Dump docker aufgerufen"

# --- Restore ohne Bestaetigung bricht ab -------------------------------------------------
printf -- '-- dump\n' | gzip > "$TEST_DIR/good.sql.gz"
: > "$TEST_DIR/calls.log"
if echo "falsch" | "$REPO_DIR/scripts/restore_db.sh" "$TEST_DIR/good.sql.gz" > /dev/null 2>&1; then
  fail "Restore ohne korrekte Bestaetigung lief durch"
fi
if grep -q " stop \| DROP DATABASE" "$TEST_DIR/calls.log"; then
  fail "Restore hat ohne Bestaetigung etwas veraendert"
fi

# --- Restore erfolgreich: stoppen, sichern, neu anlegen, mit ON_ERROR_STOP einspielen -----
: > "$TEST_DIR/calls.log"
echo "hocx" | "$REPO_DIR/scripts/restore_db.sh" "$TEST_DIR/good.sql.gz" > /dev/null
grep -q " stop backend abgabebox-backend$" "$TEST_DIR/calls.log" || fail "DB-Dienste wurden nicht gestoppt"
ls "$TEST_DIR/backups/"*-pre-restore.sql.gz > /dev/null 2>&1 || fail "Keine Sicherung vor dem Restore"
grep -q 'DROP DATABASE IF EXISTS "hocx" WITH (FORCE);' "$TEST_DIR/calls.log" || fail "DB wurde nicht neu angelegt"
grep -q "GRANT CONNECT ON DATABASE" "$TEST_DIR/calls.log" || fail "CONNECT fuer App-Rollen fehlt"
grep -q -- "psql -X -q -v ON_ERROR_STOP=1 -U hocx --single-transaction -d hocx" "$TEST_DIR/calls.log" \
  || fail "Dump wird nicht mit ON_ERROR_STOP in einer Transaktion eingespielt"
stop_line="$(grep -n ' stop ' "$TEST_DIR/calls.log" | head -n1 | cut -d: -f1)"
drop_line="$(grep -n 'DROP DATABASE' "$TEST_DIR/calls.log" | head -n1 | cut -d: -f1)"
test "$stop_line" -lt "$drop_line" || fail "DB wird vor dem Stoppen der Dienste geloescht"
if grep -q " start \| up " "$TEST_DIR/calls.log"; then
  fail "Restore darf die Dienste nicht selbst wieder starten"
fi

# --- Restore schlaegt fehl: Exit != 0 ------------------------------------------------------
if FAKE_RESTORE_EXIT=3 "$REPO_DIR/scripts/restore_db.sh" "$TEST_DIR/good.sql.gz" --yes > /dev/null 2>&1; then
  fail "Fehlgeschlagener Restore endete mit Exit 0"
fi

echo "backup/restore tests: ok"
