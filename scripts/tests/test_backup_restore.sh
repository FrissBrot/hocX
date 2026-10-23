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
echo "\$*" >> "$TEST_DIR/rclone.log"
case "\$1" in
  config) [ -n "\${FAKE_RCLONE_TYPE:-}" ] && echo "type = \${FAKE_RCLONE_TYPE}"; exit 0 ;;
esac
exit "\${FAKE_RCLONE_EXIT:-0}"
EOF
chmod +x "$TEST_DIR/bin/docker" "$TEST_DIR/bin/rclone"
export PATH="$TEST_DIR/bin:$PATH"

printf "POSTGRES_USER=hocx\nPOSTGRES_DB=hocx\n" > "$TEST_DIR/test.env"
chmod 600 "$TEST_DIR/test.env"
export HOCX_ENV_FILE="$TEST_DIR/test.env"
export HOCX_BACKUP_DIR="$TEST_DIR/backups"
export HOCX_HOST_MARKER_FILE="$TEST_DIR/no-marker"
unset OFFSITE_BACKUP_REMOTE HOCX_COMPOSE_PROJECT HOCX_REQUIRE_DUMP_ENCRYPTION BACKUP_DUMP_PRIVATE_KEY_PATH || true
# Ohne Schlüssel (unverschlüsselter Modus), unabhängig vom HOME des Testlaufs.
export BACKUP_DUMP_PUBLIC_KEY_PATH="$TEST_DIR/kein-schluessel.asc"

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
OFFSITE_BACKUP_REMOTE="remote:bucket" FAKE_RCLONE_TYPE=crypt FAKE_RCLONE_EXIT=1 "$REPO_DIR/scripts/backup_db.sh" > /dev/null 2>&1
rc=$?
set -e
test "$rc" -ne 0 || fail "Fehlgeschlagene Offsite-Kopie endete mit Exit 0"
ls "$TEST_DIR/backups/"*-cron.sql.gz > /dev/null 2>&1 || fail "Lokales Backup fehlt nach Offsite-Fehler"
: > "$TEST_DIR/rclone.log"
OFFSITE_BACKUP_REMOTE="remote:bucket" FAKE_RCLONE_TYPE=crypt "$REPO_DIR/scripts/backup_db.sh" > /dev/null \
  || fail "Erfolgreiche Offsite-Kopie meldet einen Fehler"
grep -q "^delete remote:bucket --min-age 14d" "$TEST_DIR/rclone.log" || fail "Alte Offsite-Kopien werden nicht entfernt (PRIV-009)"

# --- Unverschlüsselter Dump nie auf ein normales Remote (PRIV-009) ------------------------
: > "$TEST_DIR/rclone.log"
if OFFSITE_BACKUP_REMOTE="remote:bucket" FAKE_RCLONE_TYPE=s3 "$REPO_DIR/scripts/backup_db.sh" > /dev/null 2>&1; then
  fail "Unverschlüsselter Dump wurde auf ein nicht verschlüsselndes Remote kopiert"
fi
grep -q "^copy " "$TEST_DIR/rclone.log" && fail "rclone copy trotz Ablehnung aufgerufen"

# --- Pflichtmodus ohne Schlüssel bricht ab -------------------------------------------------
if HOCX_REQUIRE_DUMP_ENCRYPTION=true "$REPO_DIR/scripts/backup_db.sh" > /dev/null 2>&1; then
  fail "HOCX_REQUIRE_DUMP_ENCRYPTION=true ohne Schlüssel schrieb trotzdem ein Backup"
fi

# --- Verschlüsselte Dumps mit öffentlichem Schlüssel ----------------------------------------
if command -v gpg > /dev/null 2>&1; then
  KEY_HOME="$TEST_DIR/gnupg"
  mkdir -p "$KEY_HOME" && chmod 700 "$KEY_HOME"
  GNUPGHOME="$KEY_HOME" gpg --batch --quiet --passphrase '' --pinentry-mode loopback \
    --quick-gen-key "hocx-backup-test <backup@example.invalid>" future-default default never 2> /dev/null
  GNUPGHOME="$KEY_HOME" gpg --batch --armor --export > "$TEST_DIR/dump-public.asc"
  GNUPGHOME="$KEY_HOME" gpg --batch --armor --pinentry-mode loopback --passphrase '' --export-secret-keys > "$TEST_DIR/dump-private.asc"
  export BACKUP_DUMP_PUBLIC_KEY_PATH="$TEST_DIR/dump-public.asc"

  rm -rf "$TEST_DIR/backups"
  : > "$TEST_DIR/rclone.log"
  OFFSITE_BACKUP_REMOTE="remote:bucket" FAKE_RCLONE_TYPE=s3 "$REPO_DIR/scripts/backup_db.sh" > /dev/null 2>&1 \
    || fail "Verschlüsselter Dump darf auf ein normales Remote"
  encrypted=""
  for candidate in "$TEST_DIR/backups/"*-cron.sql.gz.gpg; do
    [ -e "$candidate" ] && encrypted="$candidate" && break
  done
  test -n "$encrypted" || fail "Kein verschlüsselter Cron-Dump geschrieben"
  ls "$TEST_DIR/backups/"*-cron.sql.gz > /dev/null 2>&1 && fail "Unverschlüsselte Kopie liegt neben dem verschlüsselten Dump"
  gzip -t "$encrypted" 2> /dev/null && fail "Dump ist nicht verschlüsselt"
  plain="$(GNUPGHOME="$KEY_HOME" gpg --quiet --decrypt "$encrypted" 2> /dev/null | gunzip -c)"
  test "$plain" = "-- fake dump" || fail "Entschlüsselter Dump stimmt nicht"

  # Restore eines verschlüsselten Dumps mit dem privaten Schlüssel aus der Notfallmappe
  : > "$TEST_DIR/calls.log"
  BACKUP_DUMP_PRIVATE_KEY_PATH="$TEST_DIR/dump-private.asc" "$REPO_DIR/scripts/restore_db.sh" "$encrypted" --yes < /dev/null > /dev/null 2>&1 \
    || fail "Restore eines verschlüsselten Dumps schlug fehl"
  grep -q -- "-- fake dump" "$TEST_DIR/calls.log" || fail "Verschlüsselter Dump kam nicht bei psql an"
  ls "$TEST_DIR/backups/"*-pre-restore.sql.gz.gpg > /dev/null 2>&1 || fail "Sicherung vor dem Restore ist nicht verschlüsselt"
  for leftover in "$TEST_DIR/backups/".restore-*; do
    [ -e "$leftover" ] && fail "Entschlüsselte Zwischendatei blieb liegen"
  done
  if GNUPGHOME="$TEST_DIR/leer-gnupg" "$REPO_DIR/scripts/restore_db.sh" "$encrypted" --yes < /dev/null > /dev/null 2>&1; then
    fail "Verschlüsselter Dump liess sich ohne privaten Schlüssel einspielen"
  fi
  export BACKUP_DUMP_PUBLIC_KEY_PATH="$TEST_DIR/kein-schluessel.asc"
  GNUPGHOME="$KEY_HOME" gpgconf --kill gpg-agent > /dev/null 2>&1 || true
else
  echo "gpg fehlt - Verschlüsselungstests übersprungen" >&2
fi

# --- Altersgrenze: alte Dumps weg, der neueste bleibt immer (PRIV-009) ----------------------
(
  # shellcheck source=scripts/lib/dump_crypto.sh
  source "$REPO_DIR/scripts/lib/dump_crypto.sh"
  prune_dir="$TEST_DIR/prune"
  mkdir -p "$prune_dir"
  touch -d "60 days ago" "$prune_dir/20260101-000000-pre-v1.sql.gz.gpg"
  touch -d "45 days ago" "$prune_dir/20260115-000000-pre-v2.sql.gz.gpg"
  prune_dumps_older_than "$prune_dir" '*-pre-*.sql.gz*' 30 > /dev/null
  test ! -e "$prune_dir/20260101-000000-pre-v1.sql.gz.gpg" || fail "Alter Pre-Deploy-Dump wurde nicht entfernt"
  test -e "$prune_dir/20260115-000000-pre-v2.sql.gz.gpg" || fail "Neuester Pre-Deploy-Dump wurde entfernt"
)

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
