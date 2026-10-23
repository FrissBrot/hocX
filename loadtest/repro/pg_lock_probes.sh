#!/usr/bin/env bash
# Zwei PostgreSQL-Sperrsemantiken, die der Audit nachgemessen hat - in einem Wegwerf-Container
# ohne Bezug zu hocX-Daten (tmpfs, wird am Ende entfernt).
#  1) Blockiert ein wartendes UPDATE storage_state (Backup-Hold/Cutover) neue FOR-SHARE-Schreiber?
#     Ergebnis 2026-10-21: nein (0,13 s) - der Hold kann verhungern, Schreiber laufen weiter.
#  2) Gibt idle_in_transaction_session_timeout einen pg_try_advisory_xact_lock frei, den
#     run_advisory_locked_loop auf seiner untätigen Lock-Verbindung hält?
#     Ergebnis 2026-10-21: ja - nach dem Timeout erhält ein zweiter "Worker" denselben Lock.
set -euo pipefail
NAME=hocx-audit-pgprobe
docker run -d --name "$NAME" -e POSTGRES_PASSWORD=probe --tmpfs /var/lib/postgresql/data postgres:16 >/dev/null
trap 'docker rm -f "$NAME" >/dev/null' EXIT
until docker exec "$NAME" pg_isready -U postgres >/dev/null 2>&1; do sleep 1; done
P="docker exec -i $NAME psql -U postgres -qAt"
$P -c "CREATE TABLE storage_state(id int primary key, v int); INSERT INTO storage_state VALUES (1,0);"
$P -c "CREATE ROLE app LOGIN PASSWORD 'x'; ALTER ROLE app SET idle_in_transaction_session_timeout='3s';"

echo "== 1) FOR SHARE hinter wartendem UPDATE"
( echo "BEGIN; SELECT 1 FROM storage_state WHERE id=1 FOR SHARE; SELECT pg_sleep(8); COMMIT;" | $P >/dev/null ) &
sleep 1
( echo "BEGIN; UPDATE storage_state SET v=v+1 WHERE id=1; COMMIT;" | $P >/dev/null ) &
sleep 1
start=$(date +%s%N)
$P -c "BEGIN; SELECT 1 FROM storage_state WHERE id=1 FOR SHARE; COMMIT;" >/dev/null
echo "   neuer FOR-SHARE-Schreiber: $(( ($(date +%s%N) - start) / 1000000 )) ms"
wait

echo "== 2) Advisory-xact-Lock vs. idle_in_transaction_session_timeout (3 s)"
coproc LOCK { docker exec -i "$NAME" psql -U app -d postgres -qAt 2>&1; }
echo "BEGIN; SELECT pg_try_advisory_xact_lock(202600015);" >&"${LOCK[1]}"
sleep 1
echo "   t=1s zweiter Worker: $(docker exec -i "$NAME" psql -U app -d postgres -qAt -c 'SELECT pg_try_advisory_xact_lock(202600015)')"
sleep 4
echo "   t=5s zweiter Worker: $(docker exec -i "$NAME" psql -U app -d postgres -qAt -c 'SELECT pg_try_advisory_xact_lock(202600015)')"
echo "COMMIT;" >&"${LOCK[1]}" 2>/dev/null || true
