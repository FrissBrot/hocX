#!/usr/bin/env bash
set -euo pipefail

# scripts/run_job.sh gegen ein Fake-`docker` im PATH: meldet Start und Ergebnis per psql (SQL über
# stdin, Werte als psql-Variablen) und gibt immer den Exit-Code des eigentlichen Befehls zurück.

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TEST_DIR="$(mktemp -d)"
trap 'rm -rf "$TEST_DIR"' EXIT

mkdir -p "$TEST_DIR/bin"
cat > "$TEST_DIR/bin/docker" <<EOF
#!/usr/bin/env bash
{ echo "ARGS: \$*"; cat; echo; } >> "$TEST_DIR/calls.log"
exit "\${FAKE_DOCKER_EXIT:-0}"
EOF
chmod +x "$TEST_DIR/bin/docker"
export PATH="$TEST_DIR/bin:$PATH"

printf "POSTGRES_USER=hocx\nPOSTGRES_DB=hocx\n" > "$TEST_DIR/test.env"
chmod 600 "$TEST_DIR/test.env"
export HOCX_ENV_FILE="$TEST_DIR/test.env"
export HOCX_HOST_MARKER_FILE="$TEST_DIR/no-marker"

# Erfolg: Start + success, Exit-Code 0, Ausgabe wird durchgereicht.
OUTPUT="$("$REPO_DIR/scripts/run_job.sh" backup_db sh -c 'echo hallo')"
test "$OUTPUT" = "hallo"
grep -q "record_job_start(:'job')" "$TEST_DIR/calls.log"
grep -q "record_job_run(:'job', 'success'" "$TEST_DIR/calls.log"
grep -q -- "-v job=backup_db" "$TEST_DIR/calls.log"

# Explizites Compose-Projekt statt implizitem Verzeichnisnamen (Audit MAIN-OPS-010).
grep -q -- "-p hocx --env-file $TEST_DIR/test.env -f $REPO_DIR/docker-compose.yml --project-directory $REPO_DIR exec -T db" "$TEST_DIR/calls.log"
: > "$TEST_DIR/calls.log"
printf 'test\n' > "$TEST_DIR/marker"
chmod 444 "$TEST_DIR/marker"
HOCX_HOST_MARKER_FILE="$TEST_DIR/marker" "$REPO_DIR/scripts/run_job.sh" backup_db true
grep -q -- "-p hocx-test .* -f $REPO_DIR/docker-compose.test.yml" "$TEST_DIR/calls.log"

# Fehler: Exit-Code des Befehls bleibt erhalten, Ausgabe landet in der Fehlermeldung.
: > "$TEST_DIR/calls.log"
set +e
"$REPO_DIR/scripts/run_job.sh" backup_db sh -c "echo \"pg_dump: kaputt; DROP TABLE x;'\" >&2; exit 3" 2>/dev/null
EXIT_CODE=$?
set -e
test "$EXIT_CODE" -eq 3
grep -q "record_job_run(:'job', 'failure'" "$TEST_DIR/calls.log"
grep -q "error=Exit-Code 3: pg_dump: kaputt; DROP TABLE x;'" "$TEST_DIR/calls.log"

# Meldung schlägt fehl (DB weg): Exit-Code des Jobs bleibt trotzdem 0.
FAKE_DOCKER_EXIT=1 "$REPO_DIR/scripts/run_job.sh" backup_db true 2>/dev/null

# Ungültiger Jobname wird abgelehnt, bevor irgendetwas läuft.
if "$REPO_DIR/scripts/run_job.sh" "Backup DB" true 2>/dev/null; then
  echo "Ungültiger Jobname wurde akzeptiert." >&2
  exit 1
fi

echo "run_job tests: ok"
