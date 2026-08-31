#!/usr/bin/env bash
set -euo pipefail

# Deploy/Update hocX in einer Zielumgebung.
#
# Usage: scripts/deploy.sh <test|prod>
#
# test: laeuft direkt auf dem dedizierten Test-Host aus dessen Repo-Checkout. Der Stack
#       ist derselbe wie auf Prod (Release-Images, ClamAV, eigener Traefik), aber mit
#       test-spezifischer .env und Candidate-Tag in HOCX_VERSION.
# prod: laeuft direkt auf dem Prod-Server, aus dem Verzeichnis, in dem dieses Repo dort
#       ausgecheckt ist - Compose-Dateien, .env und Storage liegen dort zusammen.
#
# In beiden Faellen heisst die echte Secrets-Datei im jeweiligen Projektverzeichnis
# schlicht ".env" (wie bei Dev) - Compose sucht sie unter diesem Namen sowohl fuer
# --env-file fuer die Variablen-Interpolation. Secrets werden den jeweils berechtigten
# Services separat als Compose-Secrets unter /run/secrets bereitgestellt.

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENVIRONMENT="${1:-}"

# shellcheck source=scripts/lib/env.sh
source "$REPO_DIR/scripts/lib/env.sh"
# shellcheck source=scripts/lib/cosign.sh
source "$REPO_DIR/scripts/lib/cosign.sh"
# shellcheck source=scripts/lib/github.sh
source "$REPO_DIR/scripts/lib/github.sh"

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

if [ "$EUID" -eq 0 ]; then
  echo "Deployments als root sind fuer hocX gesperrt." >&2
  echo "Bitte als dedizierter Benutzer starten:" >&2
  echo "  sudo -iu hocx-deploy" >&2
  echo "  cd $PROJECT_DIR && ./scripts/deploy.sh $ENVIRONMENT" >&2
  echo "Neue Hosts zuerst als root vorbereiten: ./scripts/provision_deploy_user.sh" >&2
  exit 1
fi

require_host_environment "$ENVIRONMENT"

if ! command -v flock > /dev/null 2>&1; then
  echo "flock wird fuer den Schutz vor parallelen Deployments benoetigt." >&2
  exit 1
fi
umask 077
exec 9> "$PROJECT_DIR/.deploy.lock"
if ! flock -n 9; then
  echo "Ein anderes [$ENVIRONMENT]-Deployment laeuft bereits." >&2
  exit 1
fi

generate_secret() {
  if ! command -v openssl > /dev/null 2>&1; then
    echo "openssl wird zum sicheren Erzeugen der Secrets benoetigt." >&2
    exit 1
  fi
  openssl rand -hex 32
}

prompt_value() {
  local variable="$1"
  local label="$2"
  local default_value="${3:-}"
  local secret="${4:-false}"
  local optional="${5:-false}"
  local value

  while true; do
    if [ -n "$default_value" ]; then
      printf "  %s [%s]: " "$label" "$default_value" >&3
    else
      printf "  %s: " "$label" >&3
    fi

    if [ "$secret" = true ]; then
      IFS= read -r -s value <&3 || exit 1
      printf '\n' >&3
    else
      IFS= read -r value <&3 || exit 1
    fi
    value="${value:-$default_value}"

    if [ -z "$value" ] && [ "$optional" != true ]; then
      echo "    Der Wert darf nicht leer sein." >&3
    elif [[ "$value" == *$'\n'* || "$value" == *"'"* ]]; then
      echo "    Zeilenumbrueche und einfache Anfuehrungszeichen sind nicht erlaubt." >&3
    else
      printf -v "$variable" '%s' "$value"
      return
    fi
  done
}

write_env_value() {
  # Einfache Quotes verhindern, dass der dotenv-Parser oder Compose Sonderzeichen
  # in Tokens und Passwoertern interpretiert. prompt_value schliesst ' deshalb aus.
  printf "%s='%s'\n" "$1" "$2" >> "$ENV_TMP_FILE"
}

create_env_file() {
  local default_domain
  local default_admin_domain
  local default_abgabebox_domain
  local default_docs_domain
  local default_web_domain
  local default_traefik_bind

  if ! exec 3<> /dev/tty; then
    echo "Env-Datei $ENV_FILE fehlt und es ist kein interaktives Terminal verfuegbar." >&2
    echo "Deploy erneut in einem Terminal starten oder $ENV_FILE manuell anlegen." >&2
    exit 1
  fi

  echo "==> [$ENVIRONMENT] Ersteinrichtung: $ENV_FILE wird angelegt" >&3
  echo "    Externe Angaben werden abgefragt; Secrets erzeugt das Skript automatisch." >&3

  if [ "$ENVIRONMENT" = test ]; then
    default_domain="test.hocx.ch"
    default_admin_domain="admin.test.hocx.ch"
    default_abgabebox_domain="abgabe-test.hocx.ch"
    default_docs_domain="docs-test.hocx.ch"
    default_web_domain="web-test.hocx.ch"
  else
    default_domain="hocx.ch"
    default_admin_domain="admin.hocx.ch"
    default_abgabebox_domain="abgabe.hocx.ch"
    default_docs_domain="docs.hocx.ch"
    default_web_domain="web.hocx.ch"
  fi

  prompt_value HOCX_VERSION "Image-Version (HOCX_VERSION)"
  prompt_value GHCR_NAMESPACE "GitHub-/GHCR-Namespace (kleingeschrieben)"
  prompt_value TRAEFIK_DOMAIN "Hauptdomain" "$default_domain"
  if [ "$TRAEFIK_DOMAIN" != "$default_domain" ]; then
    default_admin_domain="admin.$TRAEFIK_DOMAIN"
    default_abgabebox_domain="abgabe.$TRAEFIK_DOMAIN"
    default_docs_domain="docs.$TRAEFIK_DOMAIN"
    default_web_domain="web.$TRAEFIK_DOMAIN"
  fi
  prompt_value TRAEFIK_ADMIN_DOMAIN "Admin-Domain" "$default_admin_domain"
  prompt_value TRAEFIK_ABGABEBOX_DOMAIN "Abgabebox-Domain" "$default_abgabebox_domain"
  prompt_value TRAEFIK_DOCS_DOMAIN "Dokumentations-Domain" "$default_docs_domain"
  prompt_value TRAEFIK_WEB_DOMAIN "Web-Domain" "$default_web_domain"
  prompt_value ACME_EMAIL "E-Mail fuer Let's Encrypt"
  prompt_value CF_DNS_API_TOKEN "Cloudflare DNS API Token" "" true

  if [ "$ENVIRONMENT" = test ]; then
    default_traefik_bind="127.0.0.1"
  else
    default_traefik_bind="0.0.0.0"
  fi
  prompt_value TRAEFIK_BIND \
    "Traefik Bind-Adresse fuer Port 80/443 (127.0.0.1 = rein privat ueber OpenZiti wie der Admin-Zugang, 0.0.0.0 = oeffentlich)" \
    "$default_traefik_bind"
  if [ "$TRAEFIK_BIND" = "0.0.0.0" ]; then
    TRAEFIK_CERTRESOLVER="letsencrypt"
  else
    TRAEFIK_CERTRESOLVER="letsencryptdns"
  fi

  prompt_value INITIAL_ADMIN_EMAIL "E-Mail des ersten Plattform-Admins" "admin@$TRAEFIK_DOMAIN"

  echo "    Friendly Captcha ist optional: leer lassen deaktiviert es fuer die Abgabebox." >&3
  echo "    Auf test/dev laeuft die Abgabebox dann ohne Bot-Check; in Produktion werden" >&3
  echo "    Uploads ohne konfiguriertes Captcha sicher abgelehnt (fail-closed), nicht" >&3
  echo "    stillschweigend durchgelassen." >&3
  prompt_value FRIENDLY_CAPTCHA_SITEKEY "Friendly Captcha Sitekey (leer = deaktiviert)" "" false true
  prompt_value FRIENDLY_CAPTCHA_API_KEY "Friendly Captcha API Key (leer = deaktiviert)" "" true true

  POSTGRES_PASSWORD="$(generate_secret)"
  AUTH_SECRET="$(generate_secret)"
  ADMIN_AUTH_SECRET="$(generate_secret)"
  INITIAL_ADMIN_PASSWORD="$(generate_secret)"
  APP_DB_PASSWORD="$(generate_secret)"
  ABGABEBOX_DB_PASSWORD="$(generate_secret)"
  ABGABEBOX_CAPTCHA_SESSION_SECRET="$(generate_secret)"
  DATABASE_URL="postgresql+psycopg://hocx:${POSTGRES_PASSWORD}@db:5432/hocx"
  APP_DATABASE_URL="postgresql+psycopg://hocx_app:${APP_DB_PASSWORD}@db:5432/hocx"
  ABGABEBOX_DATABASE_URL="postgresql+psycopg://hocx_abgabebox:${ABGABEBOX_DB_PASSWORD}@db:5432/hocx"

  umask 077
  ENV_TMP_FILE="$(mktemp "$PROJECT_DIR/.env.tmp.XXXXXX")"
  trap 'rm -f "$ENV_TMP_FILE"' EXIT
  printf '# Automatisch durch scripts/deploy.sh fuer %s erzeugt. Nicht committen.\n' "$ENVIRONMENT" > "$ENV_TMP_FILE"
  write_env_value HOCX_VERSION "$HOCX_VERSION"
  write_env_value HOCX_ENVIRONMENT "$ENVIRONMENT"
  write_env_value GHCR_NAMESPACE "$GHCR_NAMESPACE"
  write_env_value HOCX_SIGNING_IDENTITY_REGEXP "(?i)^https://github.com/${GHCR_NAMESPACE}/hocx/.github/workflows/build-test-images[.]yml@refs/heads/main$"
  write_env_value ROUTER_PREFIX "$PROJECT_NAME"
  write_env_value POSTGRES_DB "hocx"
  write_env_value POSTGRES_USER "hocx"
  write_env_value POSTGRES_PASSWORD "$POSTGRES_PASSWORD"
  write_env_value DATABASE_URL "$DATABASE_URL"
  write_env_value APP_DB_PASSWORD "$APP_DB_PASSWORD"
  write_env_value APP_DATABASE_URL "$APP_DATABASE_URL"
  write_env_value TRAEFIK_DOMAIN "$TRAEFIK_DOMAIN"
  write_env_value TRAEFIK_ADMIN_DOMAIN "$TRAEFIK_ADMIN_DOMAIN"
  write_env_value TRAEFIK_ADMIN_PORT "8443"
  write_env_value ACME_EMAIL "$ACME_EMAIL"
  write_env_value CF_DNS_API_TOKEN "$CF_DNS_API_TOKEN"
  write_env_value TRAEFIK_WEB_BIND "$TRAEFIK_BIND"
  write_env_value TRAEFIK_WEBSECURE_BIND "$TRAEFIK_BIND"
  write_env_value TRAEFIK_CERTRESOLVER "$TRAEFIK_CERTRESOLVER"
  write_env_value HOCX_STORAGE_PATH "./storage"
  write_env_value NEXT_PUBLIC_API_URL "https://$TRAEFIK_DOMAIN"
  write_env_value INTERNAL_API_URL "http://backend:8000"
  write_env_value TRAEFIK_DOCS_DOMAIN "$TRAEFIK_DOCS_DOMAIN"
  write_env_value TRAEFIK_WEB_DOMAIN "$TRAEFIK_WEB_DOMAIN"
  write_env_value AUTH_SECRET "$AUTH_SECRET"
  write_env_value ADMIN_AUTH_SECRET "$ADMIN_AUTH_SECRET"
  write_env_value INITIAL_ADMIN_EMAIL "$INITIAL_ADMIN_EMAIL"
  write_env_value INITIAL_ADMIN_PASSWORD "$INITIAL_ADMIN_PASSWORD"
  write_env_value TRAEFIK_ABGABEBOX_DOMAIN "$TRAEFIK_ABGABEBOX_DOMAIN"
  write_env_value ABGABEBOX_DB_PASSWORD "$ABGABEBOX_DB_PASSWORD"
  write_env_value ABGABEBOX_DATABASE_URL "$ABGABEBOX_DATABASE_URL"
  write_env_value FRIENDLY_CAPTCHA_SITEKEY "$FRIENDLY_CAPTCHA_SITEKEY"
  write_env_value FRIENDLY_CAPTCHA_API_KEY "$FRIENDLY_CAPTCHA_API_KEY"
  write_env_value ABGABEBOX_CAPTCHA_SESSION_SECRET "$ABGABEBOX_CAPTCHA_SESSION_SECRET"
  mv "$ENV_TMP_FILE" "$ENV_FILE"
  trap - EXIT
  exec 3>&-

  echo "    $ENV_FILE wurde mit Dateirechten 600 erstellt."
  echo "    Das generierte Initial-Admin-Passwort steht in INITIAL_ADMIN_PASSWORD."
}

if [ ! -f "$ENV_FILE" ]; then
  create_env_file
fi

load_env_file "$ENV_FILE"

# Image-Referenzen kommen ausschliesslich aus einem lokal erzeugten, verifizierten
# Release-Manifest. Werte aus der aufrufenden Shell duerfen den ersten Pull nicht lenken.
unset HOCX_BACKEND_IMAGE HOCX_FRONTEND_IMAGE HOCX_ABGABEBOX_BACKEND_IMAGE \
  HOCX_ABGABEBOX_FRONTEND_IMAGE HOCX_DOCS_IMAGE

: "${HOCX_VERSION:?HOCX_VERSION fehlt in $ENV_FILE}"
: "${GHCR_NAMESPACE:?GHCR_NAMESPACE fehlt in $ENV_FILE}"

if [[ ! "$HOCX_VERSION" =~ ^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$ ]]; then
  echo "Ungueltige HOCX_VERSION: $HOCX_VERSION" >&2
  exit 1
fi
if [[ ! "$GHCR_NAMESPACE" =~ ^[a-z0-9][a-z0-9-]{0,38}$ ]]; then
  echo "Ungueltiger GHCR_NAMESPACE: $GHCR_NAMESPACE" >&2
  exit 1
fi

DC=(docker compose -p "$PROJECT_NAME" --env-file "$ENV_FILE" "${COMPOSE_ARGS[@]}")

run_preflight() {
  local command available_kb minimum_kb

  echo "==> [$ENVIRONMENT] Preflight"
  for command in docker openssl gzip stat mktemp df find readlink gh; do
    command -v "$command" > /dev/null 2>&1 || {
      echo "Erforderliches Kommando fehlt: $command" >&2
      return 1
    }
  done
  docker info > /dev/null 2>&1 || {
    echo "Docker-Daemon ist nicht erreichbar." >&2
    return 1
  }
  docker compose version > /dev/null
  ensure_github_auth
  "${DC[@]}" config --quiet

  if [ "${HOCX_ENVIRONMENT:-}" != "$ENVIRONMENT" ]; then
    echo "HOCX_ENVIRONMENT muss auf diesem Host '$ENVIRONMENT' sein." >&2
    return 1
  fi
  if [ "${AUTH_SECURE_COOKIES:-true}" != true ]; then
    echo "AUTH_SECURE_COOKIES darf in Release-Umgebungen nicht deaktiviert sein." >&2
    return 1
  fi
  case "${INITIAL_ADMIN_EMAIL,,}" in
    *@hocx.local)
      echo "Lokale Demo-Admin-Adresse ist in Release-Umgebungen verboten." >&2
      return 1
      ;;
  esac
  for value in "$POSTGRES_PASSWORD" "$APP_DB_PASSWORD" "$AUTH_SECRET" \
    "$ADMIN_AUTH_SECRET" "$INITIAL_ADMIN_PASSWORD" "$ABGABEBOX_DB_PASSWORD" \
    "$ABGABEBOX_CAPTCHA_SESSION_SECRET"; do
    case "$value" in
      ""|ChangeMe123\!*|change-me*|changeme*|secret|hocx|hocx_app|hocx_abgabebox|*keep-local-only*)
        echo "Unsicherer Entwicklungs- oder Platzhalterwert in der Release-Konfiguration." >&2
        return 1
        ;;
    esac
    if [ "${#value}" -lt 20 ]; then
      echo "Release-Secrets muessen mindestens 20 Zeichen lang sein." >&2
      return 1
    fi
  done
  case "$TRAEFIK_DOMAIN" in
    localhost|*.local|*.example.com)
      echo "Entwicklungs-/Beispieldomain ist in einer Release-Umgebung verboten: $TRAEFIK_DOMAIN" >&2
      return 1
      ;;
  esac

  minimum_kb="${HOCX_MIN_FREE_KB:-2097152}"
  [[ "$minimum_kb" =~ ^[1-9][0-9]*$ ]] || {
    echo "HOCX_MIN_FREE_KB muss eine positive Ganzzahl sein." >&2
    return 1
  }
  available_kb="$(df -Pk "$PROJECT_DIR" | awk 'NR == 2 {print $4}')"
  if [ "$available_kb" -lt "$minimum_kb" ]; then
    echo "Zu wenig freier Speicher: ${available_kb} KiB; benoetigt: ${minimum_kb} KiB." >&2
    return 1
  fi
  mkdir -p "$PROJECT_DIR/backups" "$PROJECT_DIR/.releases"
  chmod 700 "$PROJECT_DIR/backups" "$PROJECT_DIR/.releases"
  test -w "$PROJECT_DIR/backups" && test -w "$PROJECT_DIR/.releases" || {
    echo "Backup- oder Release-Verzeichnis ist nicht beschreibbar." >&2
    return 1
  }
  ensure_cosign
  echo "    Preflight: ok"
}

prepare_runtime_permissions() {
  local storage_path="${HOCX_STORAGE_PATH:-./storage}"
  local path

  if [[ "$storage_path" != /* ]]; then
    storage_path="$PROJECT_DIR/${storage_path#./}"
  fi
  for path in "$storage_path" "$PROJECT_DIR/infra/traefik/dynamic"; do
    if [ -L "$path" ]; then
      echo "Runtime-Pfad darf kein Symlink sein: $path" >&2
      return 1
    fi
    mkdir -p "$path"
    case "$(readlink -f "$path")" in
      /|"$PROJECT_DIR")
        echo "Unsicherer Runtime-Pfad: $path" >&2
        return 1
        ;;
    esac
    if find "$path" \( ! -group 5001 -o ! -perm -g+w -o -perm /007 \) -print -quit | grep -q .; then
      if [ "$EUID" -ne 0 ]; then
        echo "$path muss fuer die Container-Gruppe 5001 vorbereitet werden." >&2
        echo "Einmalig als root: chgrp -R 5001 '$path' && chmod -R g+rwX,o-rwx '$path'" >&2
        return 1
      fi
      echo "    Haerte Berechtigungen: $path"
      chgrp -R 5001 "$path"
      chmod -R g+rwX,o-rwx "$path"
      find "$path" -type d -exec chmod g+s {} +
    fi
  done
}

verify_release_images() {
  local service image repository digest_ref

  HOCX_SIGNING_IDENTITY_REGEXP="${HOCX_SIGNING_IDENTITY_REGEXP:-(?i)^https://github.com/${GHCR_NAMESPACE}/hocx/.github/workflows/build-test-images[.]yml@refs/heads/main$}"

  echo "==> [$ENVIRONMENT] Signaturen der gepullten Images pruefen"
  for service in backend frontend abgabebox-backend abgabebox-frontend docs; do
    repository="ghcr.io/${GHCR_NAMESPACE}/hocx-${service}"
    image="${repository}:${HOCX_VERSION}"
    digest_ref="$(docker image inspect "$image" --format '{{range .RepoDigests}}{{println .}}{{end}}' | grep -F "${repository}@sha256:" | head -n 1)"
    if [ -z "$digest_ref" ]; then
      echo "Kein lokaler Digest fuer $image gefunden." >&2
      return 1
    fi
    "$COSIGN_BIN" verify "$digest_ref" \
      --certificate-identity-regexp "$HOCX_SIGNING_IDENTITY_REGEXP" \
      --certificate-oidc-issuer "https://token.actions.githubusercontent.com" \
      > /dev/null
    echo "    $service: Signatur ok ($digest_ref)"
  done
}

create_release_manifest() {
  local service repository image digest_ref variable manifest_file temp_file

  manifest_file="$PROJECT_DIR/.releases/${HOCX_VERSION}.env"
  temp_file="$(mktemp "$PROJECT_DIR/.releases/.manifest.tmp.XXXXXX")"
  trap 'rm -f "$temp_file"' RETURN
  printf "HOCX_VERSION='%s'\n" "$HOCX_VERSION" > "$temp_file"
  for service in backend frontend abgabebox-backend abgabebox-frontend docs; do
    repository="ghcr.io/${GHCR_NAMESPACE}/hocx-${service}"
    image="${repository}:${HOCX_VERSION}"
    digest_ref="$(docker image inspect "$image" --format '{{range .RepoDigests}}{{println .}}{{end}}' | grep -F "${repository}@sha256:" | head -n 1)"
    [ -n "$digest_ref" ] || return 1
    variable="HOCX_${service^^}_IMAGE"
    variable="${variable//-/_}"
    printf "%s='%s'\n" "$variable" "$digest_ref" >> "$temp_file"
  done
  mv "$temp_file" "$manifest_file"
  chmod 600 "$manifest_file"
  trap - RETURN
  load_env_file "$manifest_file"
  echo "    Release-Manifest: $manifest_file"
}

capture_current_release() {
  local current_manifest="$PROJECT_DIR/.releases/current.env"
  local temp_file service container_id repository image_id digest_ref variable previous_version

  [ ! -f "$current_manifest" ] || return 0
  container_id="$("${DC[@]}" ps -q frontend 2> /dev/null || true)"
  [ -n "$container_id" ] || return 0
  previous_version="$(docker inspect "$container_id" --format '{{range .Config.Env}}{{println .}}{{end}}' | sed -n 's/^HOCX_VERSION=//p' | head -n 1)"
  previous_version="${previous_version:-unknown}"
  temp_file="$(mktemp "$PROJECT_DIR/.releases/.current.tmp.XXXXXX")"
  trap 'rm -f "$temp_file"' RETURN
  printf "HOCX_VERSION='%s'\n" "$previous_version" > "$temp_file"

  for service in backend frontend abgabebox-backend abgabebox-frontend docs; do
    container_id="$("${DC[@]}" ps -q "$service" 2> /dev/null || true)"
    [ -n "$container_id" ] || return 0
    repository="ghcr.io/${GHCR_NAMESPACE}/hocx-${service}"
    image_id="$(docker inspect "$container_id" --format '{{.Image}}')"
    digest_ref="$(docker image inspect "$image_id" --format '{{range .RepoDigests}}{{println .}}{{end}}' | grep -F "${repository}@sha256:" | head -n 1)"
    [ -n "$digest_ref" ] || return 0
    variable="HOCX_${service^^}_IMAGE"
    variable="${variable//-/_}"
    printf "%s='%s'\n" "$variable" "$digest_ref" >> "$temp_file"
  done
  mv "$temp_file" "$current_manifest"
  chmod 600 "$current_manifest"
  trap - RETURN
  echo "    Bestehendes Image-Set als Rollback-Ziel erfasst."
}

rollback_apps() {
  local current_manifest="$PROJECT_DIR/.releases/current.env"
  echo "==> [$ENVIRONMENT] Automatischer App-Rollback"
  if [ ! -f "$current_manifest" ]; then
    echo "    Kein vorheriges Release vorhanden; stoppe neu gestartete App-Services." >&2
    "${DC[@]}" stop backend frontend abgabebox-backend abgabebox-frontend docs || true
    return 1
  fi
  load_env_file "$current_manifest"
  if "${DC[@]}" up -d --no-deps --pull never backend frontend abgabebox-backend abgabebox-frontend docs; then
    if run_smoke_checks; then
      echo "    Vorheriges Image-Set wurde wieder gestartet und geprueft."
      echo "    Datenbankmigrationen wurden nicht zurueckgerollt."
      return 0
    fi
    echo "    Vorheriges Image-Set ist gestartet, besteht aber die Smoke-Checks nicht." >&2
    return 1
  fi
  echo "    Rollback fehlgeschlagen; manueller Eingriff erforderlich." >&2
  return 1
}

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
  echo "==> [$ENVIRONMENT] Smoke-Checks"
  wait_for_exec backend "Backend-API" "python3 -c \"import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health', timeout=5)\"" || return 1

  if service_exists frontend; then
    wait_for_exec frontend "Frontend" "node -e \"require('http').get('http://localhost:3000/', res => process.exit(res.statusCode < 500 ? 0 : 1)).on('error', () => process.exit(1))\"" || return 1
  fi

  if service_exists abgabebox-backend; then
    wait_for_exec abgabebox-backend "Abgabebox-Backend" "python3 -c \"import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health', timeout=5)\"" || return 1
  fi

  if service_exists abgabebox-frontend; then
    wait_for_exec abgabebox-frontend "Abgabebox-Frontend" "node -e \"require('http').get('http://localhost:3000/', res => process.exit(res.statusCode < 500 ? 0 : 1)).on('error', () => process.exit(1))\"" || return 1
  fi

  if service_exists docs; then
    wait_for_exec docs "Docs" "wget -q --spider http://localhost/" || return 1
  fi

  if service_exists clamav; then
    wait_for_exec clamav "ClamAV" "clamdcheck.sh" 150 2 || return 1
  fi
}

run_preflight
prepare_runtime_permissions
capture_current_release

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

verify_release_images
create_release_manifest

echo "==> [$ENVIRONMENT] Infrastruktur starten"
"${DC[@]}" up -d --pull never db redis
wait_for_exec db "Postgres" "pg_isready -U '$POSTGRES_USER' -d '$POSTGRES_DB'" 30 2

echo "==> [$ENVIRONMENT] Datenbankmigration"
"${DC[@]}" run --rm --no-deps backend alembic upgrade head

echo "==> [$ENVIRONMENT] Deploy"
if ! "${DC[@]}" up -d --pull never; then
  rollback_apps || true
  exit 1
fi

if ! run_smoke_checks; then
  rollback_apps || true
  exit 1
fi

install -m 600 "$PROJECT_DIR/.releases/${HOCX_VERSION}.env" "$PROJECT_DIR/.releases/current.env"

echo "==> [$ENVIRONMENT] Fertig: laeuft jetzt auf $HOCX_VERSION"
