#!/usr/bin/env bash
set -euo pipefail

# Lokaler Dev-Workflow aus docker-compose.yml + docker-compose.dev.yml.
#
# Usage:
#   scripts/dev.sh [up|stop|down] [docker compose options]
#
# Beispiele:
#   scripts/dev.sh
#   scripts/dev.sh up --profile docs --profile scan
#   scripts/dev.sh stop
#   scripts/dev.sh down

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_NAME=hocx-dev
ENV_FILE="$REPO_DIR/.env"

usage() {
  cat >&2 <<EOF
Usage:
  $0 [up|stop|down] [docker compose options]

Examples:
  $0
  $0 up --profile docs --profile scan
  $0 stop
  $0 down
EOF
}

ACTION="${1:-up}"
case "$ACTION" in
  up|stop|down)
    shift || true
    ;;
  -*|"")
    ACTION=up
    ;;
  *)
    echo "Unbekannte Aktion: $ACTION" >&2
    usage
    exit 1
    ;;
esac

EXTRA_ARGS=("$@")

if [ ! -f "$ENV_FILE" ]; then
  echo "Env-Datei $ENV_FILE fehlt." >&2
  exit 1
fi

DC=(
  docker compose
  -p "$PROJECT_NAME"
  --env-file "$ENV_FILE"
  -f "$REPO_DIR/docker-compose.yml"
  -f "$REPO_DIR/docker-compose.dev.yml"
  --project-directory "$REPO_DIR"
  "${EXTRA_ARGS[@]}"
)

service_exists() {
  "${DC[@]}" config --services | grep -Fxq "$1"
}

wait_for_exec() {
  local service="$1"
  local description="$2"
  local command="$3"
  local retries="${4:-30}"
  local sleep_seconds="${5:-2}"

  echo "    Pruefe $description"
  for i in $(seq 1 "$retries"); do
    if "${DC[@]}" exec -T "$service" sh -lc "$command" > /dev/null 2>&1; then
      echo "    $description: ok"
      return 0
    fi
    if [ "$i" -eq "$retries" ]; then
      echo "    $description: fehlgeschlagen - bitte Logs pruefen: docker compose -p $PROJECT_NAME logs $service" >&2
      return 1
    fi
    sleep "$sleep_seconds"
  done
}

run_smoke_checks() {
  echo "==> [dev] Smoke-Checks"
  wait_for_exec backend "Backend-API" "python3 -c \"import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health', timeout=5)\""

  if service_exists frontend; then
    wait_for_exec frontend "Frontend" "node -e \"require('http').get('http://localhost:3000/', res => process.exit(res.statusCode < 500 ? 0 : 1)).on('error', () => process.exit(1))\""
  fi

  if service_exists abgabebox-backend; then
    wait_for_exec abgabebox-backend "Abgabebox-Backend" "python3 -c \"import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health', timeout=5)\""
  fi

  if service_exists abgabebox-frontend; then
    wait_for_exec abgabebox-frontend "Abgabebox-Frontend" "node -e \"require('http').get('http://localhost:3000/', res => process.exit(res.statusCode < 500 ? 0 : 1)).on('error', () => process.exit(1))\""
  fi

  if service_exists docs; then
    wait_for_exec docs "Docs" "wget -q --spider http://localhost/"
  fi

  if service_exists clamav; then
    wait_for_exec clamav "ClamAV" "clamdcheck.sh" 150 2
  fi
}

case "$ACTION" in
  up)
    echo "==> [dev] Starte lokalen Dev-Stack"
    "${DC[@]}" up -d --build
    run_smoke_checks
    cat <<'EOF'
==> [dev] Fertig
    Main app:           http://localhost:3000
    Backend / OpenAPI:  http://localhost:8000
    Abgabebox:          http://localhost:3001
    Abgabebox API:      http://localhost:8001
EOF
    ;;
  stop)
    echo "==> [dev] Stoppe lokalen Dev-Stack"
    "${DC[@]}" stop
    ;;
  down)
    echo "==> [dev] Entferne lokalen Dev-Stack"
    "${DC[@]}" down
    ;;
esac
