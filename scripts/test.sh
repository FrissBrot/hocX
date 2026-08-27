#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ACTION="${1:-all}"
ENV_FILE="$REPO_DIR/.env"

usage() {
  echo "Usage: $0 [backend|abgabebox-backend|frontend|abgabebox-frontend|e2e|all]" >&2
}

if [ ! -f "$ENV_FILE" ]; then
  echo "Env-Datei $ENV_FILE fehlt. Zuerst: cp .env.example .env" >&2
  exit 1
fi

TEST_DC=(
  docker compose
  -p hocx-tests
  -f "$REPO_DIR/docker-compose.tests.yml"
  --project-directory "$REPO_DIR"
)

DEV_DC=(docker compose -p hocx-dev --env-file "$ENV_FILE" -f "$REPO_DIR/docker-compose.yml" -f "$REPO_DIR/docker-compose.dev.yml" --project-directory "$REPO_DIR")

cleanup_python_tests() {
  "${TEST_DC[@]}" --profile tests down --volumes --remove-orphans
}

run_backend() {
  local status=0
  "${TEST_DC[@]}" --profile tests run --rm --build backend-test || status=$?
  cleanup_python_tests
  return "$status"
}

run_abgabebox_backend() {
  local status=0
  "${TEST_DC[@]}" --profile tests run --rm --build abgabebox-backend-test || status=$?
  cleanup_python_tests
  return "$status"
}

run_frontend() {
  "${DEV_DC[@]}" exec -T frontend npm test
}

run_abgabebox_frontend() {
  "${DEV_DC[@]}" exec -T abgabebox-frontend npm test
}

run_e2e() {
  "$REPO_DIR/scripts/e2e.sh" all
}

case "$ACTION" in
  backend) run_backend ;;
  abgabebox-backend) run_abgabebox_backend ;;
  frontend) run_frontend ;;
  abgabebox-frontend) run_abgabebox_frontend ;;
  e2e) run_e2e ;;
  all)
    run_backend
    run_abgabebox_backend
    run_frontend
    run_abgabebox_frontend
    run_e2e
    ;;
  *) usage; exit 2 ;;
esac
