#!/usr/bin/env bash
# Sammelt während eines Lasttests alle INTERVAL Sekunden Container-, Datenbank- und Redis-Kennzahlen
# als CSV. Nur lesend. Nur gegen den Lasttest-Stack (Compose-Projekt LT_PROJECT) verwenden.
#   LT_PROJECT=hocx-loadtest INTERVAL=5 OUT=./run-$(date +%s) loadtest/monitor/sample.sh
set -euo pipefail
PROJECT="${LT_PROJECT:?LT_PROJECT (Compose-Projekt des Lasttest-Stacks) setzen}"
case "$PROJECT" in hocx-dev|hocx|hocx-prod) echo "Projekt $PROJECT ist kein Lasttest-Stack" >&2; exit 1 ;; esac
INTERVAL="${INTERVAL:-5}"
OUT="${OUT:-./loadtest-run-$(date +%Y%m%d-%H%M%S)}"
DB="${PROJECT}-db-1"
REDIS="${PROJECT}-redis-1"
PGUSER="${PGUSER:-hocx}"
PGDB="${PGDB:-hocx}"
mkdir -p "$OUT"
echo "ts,container,cpu_pct,mem_usage,mem_pct,net_io,block_io,pids" > "$OUT/docker_stats.csv"
echo "ts,usename,state,n,oldest_xact_s" > "$OUT/pg_activity.csv"
echo "ts,waiting_sessions,max_wait_s" > "$OUT/pg_lock_waits.csv"
echo "ts,connected_clients,used_memory,instantaneous_ops_per_sec,pubsub_channels,keys" > "$OUT/redis.csv"
echo "Schreibe nach $OUT (Ctrl-C beendet)"
while true; do
  ts=$(date +%s)
  docker stats --no-stream --format '{{.Name}},{{.CPUPerc}},{{.MemUsage}},{{.MemPerc}},{{.NetIO}},{{.BlockIO}},{{.PIDs}}' \
    | grep "^${PROJECT}-" | sed "s/^/${ts},/" >> "$OUT/docker_stats.csv" || true
  docker exec "$DB" psql -U "$PGUSER" -d "$PGDB" -AtF, -c \
    "SELECT usename, coalesce(state,'?'), count(*), coalesce(extract(epoch FROM max(now()-xact_start))::int,0)
     FROM pg_stat_activity WHERE datname = current_database() GROUP BY 1,2" 2>/dev/null \
    | sed "s/^/${ts},/" >> "$OUT/pg_activity.csv" || true
  docker exec "$DB" psql -U "$PGUSER" -d "$PGDB" -AtF, -c \
    "SELECT count(*), coalesce(extract(epoch FROM max(now()-query_start))::int,0) FROM pg_stat_activity
     WHERE wait_event_type = 'Lock' AND datname = current_database()" 2>/dev/null \
    | sed "s/^/${ts},/" >> "$OUT/pg_lock_waits.csv" || true
  docker exec "$REDIS" sh -c 'REDISCLI_AUTH="$(cat /run/secrets/redis_password 2>/dev/null)" redis-cli INFO' 2>/dev/null \
    | tr -d '\r' | awk -F: -v ts="$ts" '
        /^connected_clients/{c=$2} /^used_memory:/{m=$2} /^instantaneous_ops_per_sec/{o=$2} /^pubsub_channels/{p=$2}
        /^db0:keys=/{split($2,a,/[=,]/); k=a[2]} END{print ts","c","m","o","p","k}' >> "$OUT/redis.csv" || true
  sleep "$INTERVAL"
done
