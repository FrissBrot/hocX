#!/usr/bin/env bash
set -euo pipefail

# Post-deploy smoke and integrity checks for hocX release-style environments.
#
# Usage: scripts/verify_release.sh <test|prod>
#
# Runs container-local health checks plus endpoint checks through Traefik. Die Domain-Checks
# laufen vom Host aus per curl mit dem echten Host-Namen (SNI + Zertifikatspruefung) und
# brauchen kein DNS: Ist Traefik privat gebunden (TRAEFIK_WEBSECURE_BIND != 0.0.0.0) oder loest
# die Domain auf dem Host nicht auf, wird sie per --resolve direkt auf Traefik gelenkt.
# Ein eigenes CA-Zertifikat (z. B. Test-CA eines privaten Test-Hosts) setzt HOCX_VERIFY_CA_FILE
# in .env (absolut oder relativ zum Repo).

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENVIRONMENT="${1:-}"

# shellcheck source=scripts/lib/env.sh
source "$REPO_DIR/scripts/lib/env.sh"
# shellcheck source=scripts/lib/traefik_checks.sh
source "$REPO_DIR/scripts/lib/traefik_checks.sh"

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

append_local_compose_override "$REPO_DIR" COMPOSE_ARGS || exit 1

if [ ! -f "$ENV_FILE" ]; then
  echo "Env-Datei $ENV_FILE fehlt." >&2
  exit 1
fi

load_env_file "$ENV_FILE"

: "${HOCX_VERSION:?HOCX_VERSION fehlt in $ENV_FILE}"
: "${TRAEFIK_DOMAIN:?TRAEFIK_DOMAIN fehlt in $ENV_FILE}"
: "${TRAEFIK_ABGABEBOX_DOMAIN:?TRAEFIK_ABGABEBOX_DOMAIN fehlt in $ENV_FILE}"

DC=(docker compose -p "$PROJECT_NAME" --env-file "$ENV_FILE" "${COMPOSE_ARGS[@]}")
# Für traefik_checks.sh (SEC-AUTH-001): aktive Mandanten-Domains aus der vom Backend generierten Datei
tenant_domains_for_checks() {
  "${DC[@]}" exec -T backend cat /app/traefik_dynamic/tenant-domains.yml 2> /dev/null
}

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

# Admin-Frontend (eigener Dienst, Review M3): antwortet ohne Admin-Host mit 404, also nur «kein 5xx».
check_admin_frontend_local() {
  "${DC[@]}" exec -T admin-frontend node -e "require('http').get('http://localhost:3000/', res => process.exit(res.statusCode < 500 ? 0 : 1)).on('error', () => process.exit(1))"
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

# MAIN-OPS-001: Das Backend muss auf Prod im Produktionsmodus laufen (kein /docs, Demo-Daten-
# und Konfigurationssperren aktiv). Frueher lief Prod mit HOCX_ENVIRONMENT=prod still als
# Nicht-Produktion; dieser Check macht eine solche Abweichung beim Deploy sichtbar.
check_backend_environment() {
  local expected actual
  expected="$(app_environment_for "$ENVIRONMENT")"
  actual="$("${DC[@]}" exec -T -w /app backend python3 -c \
    "from app.core.config import settings; print('production' if settings.is_production else settings.environment.strip().lower())")"
  if [ "$actual" != "$expected" ]; then
    echo "Backend laeuft als '$actual', erwartet '$expected' (HOCX_ENVIRONMENT pruefen)." >&2
    return 1
  fi
}

run_check "Backend-Health lokal" check_backend_health
run_check "Backend laeuft in der erwarteten Umgebung" check_backend_environment
run_check "Abgabebox-Backend-Health lokal" check_abgabebox_backend_health
run_check "Frontend antwortet lokal" check_frontend_local
run_check "Admin-Frontend antwortet lokal" check_admin_frontend_local
run_check "Docs antworten lokal" check_docs_local
run_check "Alembic steht auf head" check_alembic_head

command -v curl > /dev/null 2>&1 || { echo "curl wird fuer die Domain-Checks benoetigt." >&2; exit 1; }
run_check "Alle Traefik-Router von aussen (Frontend, APIs, Prüfseite, Admin, Docs, Website)" traefik_route_checks

note "Alle Verify-Checks erfolgreich fuer $HOCX_VERSION"

if [ "$ENVIRONMENT" = test ]; then
  run_check "Testnachweis fuer die Prod-Promotion speichern" \
    "$REPO_DIR/scripts/record_tested_candidate.sh"
fi
