#!/usr/bin/env bash
# Lastprofile und Szenarien nacheinander gegen den laufenden Lasttest-Stack (up.sh).
# Je Lauf: k6-Summary, Monitor-CSVs (monitor/sample.sh), Container-Logs, DB-Auswertung
# (monitor/queries.sql). Ergebnisse unter $LT_DIR/results/build-<image-tag>/<lauf>.
# Ein Wächter stoppt k6, wenn auf / weniger als MIN_FREE_GB frei sind (Galerie-ZIPs).
#
# Usage: loadtest/stack/series.sh u100 u250 u500 conc022-50 conc022-200 collab storm heavy
#        python3 loadtest/stack/summarize.py $LT_DIR/results/build-<tag> u100 u250 ...
set -uo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LT_PROJECT="${LT_PROJECT:-hocx-loadtest}"
LT_DIR="${LT_DIR:-/docker/loadtest-stack}"
MIN_FREE_GB="${MIN_FREE_GB:-3}"
K6="$REPO_DIR/loadtest/stack/k6.sh"
TAG="$(docker inspect "$LT_PROJECT-backend-1" --format '{{.Config.Image}}' | cut -d: -f2)"
RES="$LT_DIR/results/build-$TAG"
mkdir -p "$RES" && chmod 777 "$RES"

( while sleep 10; do
    free_kib=$(df --output=avail -k / | tail -1)
    if (( free_kib < MIN_FREE_GB * 1024 * 1024 )); then
      echo "$(date +%T) Platz knapp (${free_kib} KiB) - k6 gestoppt" >> "$RES/progress.txt"
      docker ps -q --filter ancestor=grafana/k6:latest | xargs -r docker stop >/dev/null
    fi
  done ) &
WATCH=$!
trap 'kill $WATCH 2>/dev/null' EXIT

run() {
  local name="$1"; shift
  local out="$RES/$name" k6out="$LT_DIR/results/$name"
  # k6.sh schreibt nach results/<lauf>; Reste eines früheren Laufs dürfen nicht mitwandern
  rm -rf "$k6out"
  mkdir -p "$out" && chmod 777 "$out"
  docker exec "$LT_PROJECT-db-1" psql -U hocx -d hocx_loadtest -qAtc "SELECT pg_stat_statements_reset();" >/dev/null
  LT_PROJECT="$LT_PROJECT" PGDB=hocx_loadtest INTERVAL=5 OUT="$out/monitor" "$REPO_DIR/loadtest/monitor/sample.sh" >/dev/null 2>&1 &
  local mon=$!
  local logs=()
  for svc in backend job-worker abgabebox-backend; do
    docker logs --since 1s -f "$LT_PROJECT-$svc-1" > "$out/$svc.log" 2>&1 &
    logs+=($!)
  done
  local rc=0
  "$K6" "$@" || rc=$?
  echo "$(date +%T) $name exit $rc" >> "$RES/progress.txt"
  kill "$mon" "${logs[@]}" 2>/dev/null
  wait "$mon" 2>/dev/null
  cp -a "$k6out"/k6.txt "$k6out"/summary.json "$out"/ 2>/dev/null
  rm -rf "$k6out"
  docker exec -i "$LT_PROJECT-db-1" psql -U hocx -d hocx_loadtest < "$REPO_DIR/loadtest/monitor/queries.sql" > "$out/db.txt" 2>&1
  sleep 30
}

for spec in "$@"; do
  case "$spec" in
    u10|u50|u100|u250|u500|u1000) run "$spec" interactive.js "$spec" -e PROFILE="$spec" -e PROBE_DURATION=8m ;;
    conc022-*) run "$spec" session_consistency.js "$spec" -e RATE="${spec#conc022-}" -e DURATION=5m ;;
    collab) run collab collab.js collab -e COLLAB_USERS=50 -e TENANT_FILTER=0 -e COLLAB_SECONDS=300 ;;
    # 1-MB-Fotos: 50 VUs x 5 Dateien x 8 MB kosten k6 selbst rund 4 GB
    storm) run storm abgabebox_storm.js storm -e STORM_VUS=50 -e STORM_ITERATIONS=3 -e FIXTURE_IMAGE=/data/fixtures/photo-1mb.jpg ;;
    # 155-MB-ZIP: je Upload-VU einmal im Speicher plus Kopien im Versand - 2 Upload-VUs, 3 GB für k6
    heavy) K6_MEMORY=3g run heavy heavy.js heavy -e HEAVY_TENANTS=0 -e INTERACTIVE_TENANTS=1,2,3,4,5 -e INTERACTIVE_VUS=100 \
             -e UPLOAD_VUS=2 -e HEAVY_DURATION="${HEAVY_DURATION:-10m}" -e FIXTURE_IMAGE=/data/fixtures/photo-8mb.jpg -e FIXTURE_ZIP=/data/fixtures/gallery-200.zip ;;
    *) echo "Unbekannter Lauf: $spec" >&2 ;;
  esac
done
echo "$(date +%T) fertig" >> "$RES/progress.txt"
