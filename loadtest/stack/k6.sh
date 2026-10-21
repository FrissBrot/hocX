#!/usr/bin/env bash
# k6 im Container im Netz des Lasttest-Stacks (backend:8000 direkt, ohne Traefik).
# Usage: loadtest/stack/k6.sh <skript.js> <lauf-name> [weitere k6-Argumente]
#   z. B. loadtest/stack/k6.sh interactive.js u100 -e PROFILE=u100
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LT_PROJECT="${LT_PROJECT:-hocx-loadtest}"
LT_DIR="${LT_DIR:-/docker/loadtest-stack}"
K6_CPUS="${K6_CPUS:-1.5}"
script="$1"; run="$2"; shift 2
mkdir -p "$LT_DIR/results/$run" && chmod 777 "$LT_DIR/results/$run"
docker run --rm --network "${LT_PROJECT}_default" --cpus "$K6_CPUS" \
  -v "$REPO_DIR/loadtest:/lt:ro" -v "$LT_DIR:/data" -w /lt/k6 \
  -e BASE_URL=http://backend:8000 -e ABGABEBOX_URL=http://abgabebox-backend:8000 \
  -e HOCX_LOADTEST_TARGET_CONFIRMED=isolated -e TOKENS_FILE=/data/seed-out/tokens.json \
  grafana/k6:latest run --quiet --summary-trend-stats "avg,min,med,max,p(90),p(95),p(99)" --summary-export "/data/results/$run/summary.json" "$@" "$script" \
  > "$LT_DIR/results/$run/k6.txt" 2>&1
