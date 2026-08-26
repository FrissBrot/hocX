#!/usr/bin/env bash
set -euo pipefail

# Post-deploy smoke and integrity checks for hocX release-style environments.
#
# Usage: scripts/verify_release.sh <test|prod>
#
# Runs container-local health checks plus a small set of externally reachable endpoint
# checks through Traefik. The script assumes DNS/TLS is already set up for the host's
# domains (same expectation as RUNBOOK.md / deployment.md).

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENVIRONMENT="${1:-}"

# shellcheck source=scripts/lib/env.sh
source "$REPO_DIR/scripts/lib/env.sh"

case "$ENVIRONMENT" in
  test)
    PROJECT_NAME=hocx-test
    PROJECT_DIR="$REPO_DIR"
    ENV_FILE="$PROJECT_DIR/.env"
    COMPOSE_ARGS=(
      -f "$REPO_DIR/docker-compose.release.yml"
      -f "$REPO_DIR/docker-compose.clamav.yml"
      -f "$REPO_DIR/docker-compose.traefik.yml"
      -f "$REPO_DIR/docker-compose.test.yml"
      --project-directory "$PROJECT_DIR"
    )
    ;;
  prod)
    PROJECT_NAME=hocx
    PROJECT_DIR="$REPO_DIR"
    ENV_FILE="$PROJECT_DIR/.env"
    COMPOSE_ARGS=(
      -f "$REPO_DIR/docker-compose.release.yml"
      -f "$REPO_DIR/docker-compose.clamav.yml"
      -f "$REPO_DIR/docker-compose.traefik.yml"
      --project-directory "$PROJECT_DIR"
    )
    ;;
  *)
    echo "Usage: $0 <test|prod>" >&2
    exit 1
    ;;
esac

require_host_environment "$ENVIRONMENT"

if [ ! -f "$ENV_FILE" ]; then
  echo "Env-Datei $ENV_FILE fehlt." >&2
  exit 1
fi

load_env_file "$ENV_FILE"

: "${HOCX_VERSION:?HOCX_VERSION fehlt in $ENV_FILE}"
: "${TRAEFIK_DOMAIN:?TRAEFIK_DOMAIN fehlt in $ENV_FILE}"
: "${TRAEFIK_ABGABEBOX_DOMAIN:?TRAEFIK_ABGABEBOX_DOMAIN fehlt in $ENV_FILE}"

DC=(docker compose -p "$PROJECT_NAME" --env-file "$ENV_FILE" "${COMPOSE_ARGS[@]}")

note() {
  printf '==> [%s] %s\n' "$ENVIRONMENT" "$1"
}

run_check() {
  local description="$1"
  shift
  note "$description"
  "$@"
}

probe_from_backend() {
  local url="$1"
  "${DC[@]}" exec -T backend python3 -c "import urllib.request,sys; resp=urllib.request.urlopen('$url', timeout=10); sys.exit(0 if resp.status < 500 else 1)"
}

check_backend_health() {
  probe_from_backend "http://localhost:8000/api/health"
}

check_abgabebox_backend_health() {
  probe_from_backend "http://abgabebox-backend:8000/api/health"
}

check_frontend_local() {
  probe_from_backend "http://frontend:3000/login"
}

check_website_local() {
  probe_from_backend "http://website:3000/"
}

check_docs_local() {
  probe_from_backend "http://docs/"
}

check_alembic_head() {
  local current heads
  current="$("${DC[@]}" exec -T backend sh -lc "cd /app && alembic current 2>/dev/null | awk '{print \$1}' | sort -u")"
  heads="$("${DC[@]}" exec -T backend sh -lc "cd /app && alembic heads 2>/dev/null | awk '{print \$1}' | sort -u")"
  if [ -z "$current" ] || [ -z "$heads" ]; then
    echo "Alembic current/head konnte nicht ermittelt werden." >&2
    return 1
  fi
  if [ "$current" != "$heads" ]; then
    echo "Alembic current ($current) stimmt nicht mit heads ($heads) ueberein." >&2
    return 1
  fi
}

run_check "Backend-Health lokal" check_backend_health
run_check "Abgabebox-Backend-Health lokal" check_abgabebox_backend_health
run_check "Frontend antwortet lokal" check_frontend_local
run_check "Website antwortet lokal" check_website_local
run_check "Docs antworten lokal" check_docs_local
run_check "Alembic steht auf head" check_alembic_head
run_check "Hauptdomain antwortet via Traefik" probe_from_backend "https://${TRAEFIK_DOMAIN}/login"
run_check "Abgabebox antwortet via Traefik" probe_from_backend "https://${TRAEFIK_ABGABEBOX_DOMAIN}/"

if [ -n "${TRAEFIK_DOCS_DOMAIN:-}" ]; then
  run_check "Docs-Domain antwortet via Traefik" probe_from_backend "https://${TRAEFIK_DOCS_DOMAIN}/"
fi

if [ -n "${TRAEFIK_WEB_DOMAIN:-}" ]; then
  run_check "Website-Domain antwortet via Traefik" probe_from_backend "https://${TRAEFIK_WEB_DOMAIN}/"
fi

note "Alle Verify-Checks erfolgreich fuer $HOCX_VERSION"
