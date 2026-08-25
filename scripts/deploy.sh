#!/usr/bin/env bash
set -euo pipefail

# Deploy/Update hocX in einer Zielumgebung.
#
# Usage: scripts/deploy.sh <test|prod>
#
# test: laeuft von diesem Dev-Server aus. Die Compose-Dateien liegen im Git-Repo,
#       Daten/Storage/.env liegen isoliert in /docker/hocX-test (--project-directory).
# prod: laeuft direkt auf dem Prod-Server, aus dem Verzeichnis, in dem dieses Repo dort
#       ausgecheckt ist - Compose-Dateien, .env und Storage liegen dort zusammen.
#
# In beiden Faellen heisst die echte Secrets-Datei im jeweiligen Projektverzeichnis
# schlicht ".env" (wie bei Dev) - Compose sucht sie unter diesem Namen sowohl fuer
# --env-file (Variablen-Interpolation in den Compose-Dateien) als auch fuer die
# service-level env_file:-Direktive (Container-Env) im selben Projektverzeichnis.

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENVIRONMENT="${1:-}"

case "$ENVIRONMENT" in
  test)
    PROJECT_NAME=hocx-test
    PROJECT_DIR=/docker/hocX-test
    ENV_FILE="$PROJECT_DIR/.env"
    COMPOSE_ARGS=(
      -f "$REPO_DIR/docker-compose.release.yml"
      -f "$REPO_DIR/docker-compose.clamav.yml"
      -f "$REPO_DIR/docker-compose.test.yml"
      --project-directory "$PROJECT_DIR"
    )
    ;;
  prod)
    PROJECT_NAME=hocx
    PROJECT_DIR="$REPO_DIR"
    ENV_FILE="$PROJECT_DIR/.env"
    COMPOSE_ARGS=(-f "$REPO_DIR/docker-compose.release.yml" -f "$REPO_DIR/docker-compose.clamav.yml" -f "$REPO_DIR/docker-compose.traefik.yml" --project-directory "$PROJECT_DIR")
    ;;
  *)
    echo "Usage: $0 <test|prod>" >&2
    exit 1
    ;;
esac

if [ ! -f "$ENV_FILE" ]; then
  echo "Env-Datei $ENV_FILE fehlt." >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

: "${HOCX_VERSION:?HOCX_VERSION fehlt in $ENV_FILE}"

DC=(docker compose -p "$PROJECT_NAME" --env-file "$ENV_FILE" "${COMPOSE_ARGS[@]}")

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

echo "==> [$ENVIRONMENT] Backup der Datenbank vor dem Update auf $HOCX_VERSION"
BACKUP_DIR="$PROJECT_DIR/backups"
mkdir -p "$BACKUP_DIR"
BACKUP_FILE="$BACKUP_DIR/$(date +%Y%m%d-%H%M%S)-pre-$HOCX_VERSION.sql.gz"
if "${DC[@]}" ps db --status running -q > /dev/null 2>&1 && [ -n "$("${DC[@]}" ps db --status running -q)" ]; then
  "${DC[@]}" exec -T db pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" | gzip > "$BACKUP_FILE"
  echo "    Backup: $BACKUP_FILE"
else
  echo "    db-Container laeuft noch nicht (erster Deploy) - kein Backup noetig."
fi

echo "==> [$ENVIRONMENT] Pull Images ($HOCX_VERSION)"
"${DC[@]}" pull

echo "==> [$ENVIRONMENT] Deploy"
"${DC[@]}" up -d

echo "==> [$ENVIRONMENT] Smoke-Checks"
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

echo "==> [$ENVIRONMENT] Fertig: laeuft jetzt auf $HOCX_VERSION"
