#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ACTION="${1:-all}"
ENV_FILE="$REPO_DIR/.env.e2e.example"
DC=(docker compose -p hocx-e2e --env-file "$ENV_FILE" -f "$REPO_DIR/docker-compose.yml" -f "$REPO_DIR/docker-compose.dev.yml" -f "$REPO_DIR/docker-compose.e2e.yml" --project-directory "$REPO_DIR")

wait_for_url() {
  local url="$1"
  for _ in $(seq 1 90); do
    if curl --fail --silent "$url" >/dev/null 2>&1; then return 0; fi
    sleep 2
  done
  echo "Dienst nicht erreichbar: $url" >&2
  return 1
}

start_stack() {
  "${DC[@]}" up -d --build
  wait_for_url http://127.0.0.1:18000/api/health
  wait_for_url http://127.0.0.1:13000/login
  wait_for_url http://127.0.0.1:18001/api/health
  wait_for_url http://127.0.0.1:13001/
}

run_tests() {
  if [[ "${E2E_USE_HOST_PLAYWRIGHT:-0}" == "1" ]]; then
    (cd "$REPO_DIR/frontend" && PLAYWRIGHT_BASE_URL=http://127.0.0.1:13000 E2E_ABGABEBOX_BASE_URL=http://127.0.0.1:13001 E2E_USER_EMAIL=admin@hocx.local E2E_USER_PASSWORD='ChangeMe123!' npm run test:e2e)
  else
    docker run --rm --network host -v "$REPO_DIR/frontend:/work" -w /work \
      -e CI="${CI:-}" -e PLAYWRIGHT_BASE_URL=http://127.0.0.1:13000 \
      -e E2E_ABGABEBOX_BASE_URL=http://127.0.0.1:13001 \
      -e E2E_USER_EMAIL=admin@hocx.local -e E2E_USER_PASSWORD='ChangeMe123!' \
      mcr.microsoft.com/playwright:v1.55.0-noble sh -c 'npm ci && npm run test:e2e'
  fi
}

stop_stack() {
  "${DC[@]}" down --volumes --remove-orphans
  rm -rf "$REPO_DIR/storage-e2e"
}

case "$ACTION" in
  up) start_stack ;;
  test) run_tests ;;
  down) stop_stack ;;
  all)
    trap stop_stack EXIT
    start_stack
    if ! run_tests; then
      mkdir -p "$REPO_DIR/frontend/test-results"
      "${DC[@]}" logs --no-color > "$REPO_DIR/frontend/test-results/e2e-services.log" 2>&1 || true
      exit 1
    fi
    ;;
  *) echo "Usage: $0 [up|test|down|all]" >&2; exit 2 ;;
esac
