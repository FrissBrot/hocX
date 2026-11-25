#!/usr/bin/env bash
set -euo pipefail

# Deploy/Update hocX in einer Zielumgebung.
#
# Usage: scripts/deploy.sh <test|prod> [--restore-from-backup]
#
# --restore-from-backup: neuer, leerer Server aus dem Borg-Backup. Führt durch .env (aus der
#       Notfallmappe), Zugang zur Storage Box (neuer SSH-Schlüssel, Host-Key prüfen), Wahl des
#       Wiederherstellungspunkts und stellt Datenbank und Dateien ins lokale S3 her; danach
#       läuft der normale Deploy weiter. Siehe scripts/lib/restore_from_backup.sh.
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
#
# Update von einem aelteren Release: HOCX_VERSION in .env anheben, dann deploy.sh starten.
# Das Skript migriert die bestehende .env selbst (fehlende Variablen ergaenzen, entfernte
# loeschen, Sicherung als .env.bak-<Zeitstempel>), siehe scripts/lib/env_migrate.sh.
#
# Optional in .env oder Shell: HOCX_SINGLE_TENANT_RESOLUTION=auto - noetig beim Update von
# 1.0.x auf 1.1.0, falls Konten mit mehreren Mandanten-Mitgliedschaften oder ganz ohne
# Mandant existieren (Migration 0078, siehe CHANGELOG). Ohne den Wert bricht die Migration
# in dem Fall ab und listet die Konten auf; die Datenbank bleibt dabei unveraendert.
#
# Deploy-Code zuerst aktualisieren (ab 1.2.4): deploy.sh holt sich vor jedem Lauf den neuesten
# signierten Stand von origin/main (scripts/update_deploy_code.sh) und startet sich damit neu.
# Beim Update auf 1.2.3 rollte sonst ein veraltetes deploy.sh das neue Release aus. Überspringen:
# HOCX_SKIP_DEPLOY_CODE_UPDATE=1 (z. B. ohne Netz oder für einen bewusst älteren Stand).
#
# Nur noch S3 (Migration 0168_s3_only): Update nur, wenn die Dateien schon in S3 liegen. Ist der
# bisherige Dateisystem-Bestand noch in der Rückfallfrist, fragt das Skript, ob sie übersprungen
# werden soll (nicht interaktiv: HOCX_SKIP_STORAGE_FALLBACK=1), siehe scripts/lib/storage_gate.sh.

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENVIRONMENT="${1:-}"
RESTORE_MODE=0
case "${2:-}" in
  "") ;;
  --restore-from-backup) RESTORE_MODE=1 ;;
  *) echo "Usage: $0 <test|prod> [--restore-from-backup]" >&2; exit 1 ;;
esac

# shellcheck source=scripts/lib/env.sh
source "$REPO_DIR/scripts/lib/env.sh"
# shellcheck source=scripts/lib/env_migrate.sh
source "$REPO_DIR/scripts/lib/env_migrate.sh"
# shellcheck source=scripts/lib/cosign.sh
source "$REPO_DIR/scripts/lib/cosign.sh"
# shellcheck source=scripts/lib/traefik_checks.sh
source "$REPO_DIR/scripts/lib/traefik_checks.sh"
# shellcheck source=scripts/lib/admin_gate.sh
source "$REPO_DIR/scripts/lib/admin_gate.sh"
# shellcheck source=scripts/lib/github.sh
source "$REPO_DIR/scripts/lib/github.sh"
# shellcheck source=scripts/lib/image_cleanup.sh
source "$REPO_DIR/scripts/lib/image_cleanup.sh"
# shellcheck source=scripts/lib/dump_crypto.sh
source "$REPO_DIR/scripts/lib/dump_crypto.sh"
# shellcheck source=scripts/lib/pg_upgrade.sh
source "$REPO_DIR/scripts/lib/pg_upgrade.sh"
# shellcheck source=scripts/lib/storage_gate.sh
source "$REPO_DIR/scripts/lib/storage_gate.sh"
# shellcheck source=scripts/lib/restore_from_backup.sh
source "$REPO_DIR/scripts/lib/restore_from_backup.sh"

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
    echo "Usage: $0 <test|prod> [--restore-from-backup]" >&2
    exit 1
    ;;
esac
append_local_compose_override "$REPO_DIR" COMPOSE_ARGS || exit 1

if [ "$EUID" -eq 0 ]; then
  echo "Deployments als root sind fuer hocX gesperrt." >&2
  echo "Bitte als dedizierter Benutzer starten:" >&2
  echo "  sudo -iu hocx-deploy" >&2
  echo "  cd $PROJECT_DIR && ./scripts/deploy.sh $ENVIRONMENT" >&2
  echo "Neue Hosts zuerst als root vorbereiten: ./scripts/provision_deploy_user.sh" >&2
  exit 1
fi

require_host_environment "$ENVIRONMENT"

# Vor der Deploy-Sperre: update_deploy_code.sh nimmt dieselbe Sperre. HOCX_DEPLOY_CODE_UPDATED
# setzt der Neustart unten (bzw. update_deploy_code.sh --deploy) - Schleifenschutz.
case "${HOCX_SKIP_DEPLOY_CODE_UPDATE:-}" in
  1|true|yes|ja)
    echo "==> [$ENVIRONMENT] Deploy-Code-Update übersprungen (HOCX_SKIP_DEPLOY_CODE_UPDATE)"
    ;;
  *)
    if [ "${HOCX_DEPLOY_CODE_UPDATED:-0}" != 1 ]; then
      echo "==> [$ENVIRONMENT] Deploy-Code zuerst aktualisieren (überspringen: HOCX_SKIP_DEPLOY_CODE_UPDATE=1)"
      if ! HOCX_DEPLOY_CODE_UPDATE_FROM_DEPLOY=1 "$REPO_DIR/scripts/update_deploy_code.sh"; then
        echo "Deploy abgebrochen: Deploy-Code-Update fehlgeschlagen; es laeuft weiter das bisherige Release." >&2
        echo "Bewusst mit dem vorhandenen Code deployen: HOCX_SKIP_DEPLOY_CODE_UPDATE=1 $0 $ENVIRONMENT" >&2
        exit 1
      fi
      exec env HOCX_DEPLOY_CODE_UPDATED=1 "$REPO_DIR/scripts/deploy.sh" "$@"
    fi
    ;;
esac

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
require_repo_owned_by_current_user "$REPO_DIR" || exit 1
if [ "$RESTORE_MODE" = 1 ]; then
  mkdir -p "$PROJECT_DIR/.releases"
  restore_guard || exit 1
  restore_prepare_env || exit 1
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
  else
    default_domain="hocx.ch"
    default_admin_domain="admin.hocx.ch"
    default_abgabebox_domain="abgabe.hocx.ch"
    default_docs_domain="docs.hocx.ch"
  fi

  prompt_value HOCX_VERSION "Image-Version (HOCX_VERSION)"
  prompt_value GHCR_NAMESPACE "GitHub-/GHCR-Namespace (kleingeschrieben)"
  prompt_value TRAEFIK_DOMAIN "Hauptdomain" "$default_domain"
  if [ "$TRAEFIK_DOMAIN" != "$default_domain" ]; then
    default_admin_domain="admin.$TRAEFIK_DOMAIN"
    default_abgabebox_domain="abgabe.$TRAEFIK_DOMAIN"
    default_docs_domain="docs.$TRAEFIK_DOMAIN"
  fi
  prompt_value TRAEFIK_ADMIN_DOMAIN "Admin-Domain" "$default_admin_domain"
  prompt_value TRAEFIK_ABGABEBOX_DOMAIN "Abgabebox-Domain" "$default_abgabebox_domain"
  prompt_value TRAEFIK_DOCS_DOMAIN "Dokumentations-Domain" "$default_docs_domain"
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

  DEMO_TOTP_SEED=""
  if [ "$ENVIRONMENT" = test ]; then
    echo "    Optional (nur test): fester TOTP-Seed (base32) fuer die Demo-Konten, damit nach" >&3
    echo "    jedem Test-Deploy derselbe Authenticator-Eintrag weiter funktioniert." >&3
    prompt_value DEMO_TOTP_SEED "DEMO_TOTP_SEED (leer = Einrichtung beim ersten Login)" "" true true
  fi

  POSTGRES_PASSWORD="$(generate_secret)"
  AUTH_SECRET="$(generate_secret)"
  ADMIN_AUTH_SECRET="$(generate_secret)"
  ADMIN_GATE_SECRET="$(generate_secret)"
  INITIAL_ADMIN_PASSWORD="$(generate_secret)"
  APP_DB_PASSWORD="$(generate_secret)"
  ABGABEBOX_DB_PASSWORD="$(generate_secret)"
  ABGABEBOX_CAPTCHA_SESSION_SECRET="$(generate_secret)"
  PHOTO_WORKER_DB_PASSWORD="$(generate_secret)"
  GEO_DB_PASSWORD="$(generate_secret)"
  REDIS_PASSWORD="$(generate_secret)"
  DATABASE_URL="postgresql+psycopg://hocx:${POSTGRES_PASSWORD}@db:5432/hocx"
  APP_DATABASE_URL="postgresql+psycopg://hocx_app:${APP_DB_PASSWORD}@db:5432/hocx"
  ABGABEBOX_DATABASE_URL="postgresql+psycopg://hocx_abgabebox:${ABGABEBOX_DB_PASSWORD}@db:5432/hocx"
  PHOTO_WORKER_DATABASE_URL="postgresql+psycopg://hocx_photo_worker:${PHOTO_WORKER_DB_PASSWORD}@db:5432/hocx"
  GEO_DATABASE_URL="postgresql+psycopg://hocx_geo:${GEO_DB_PASSWORD}@db:5432/hocx"

  umask 077
  ENV_TMP_FILE="$(mktemp "$PROJECT_DIR/.env.tmp.XXXXXX")"
  trap 'rm -f "$ENV_TMP_FILE"' EXIT
  printf '# Automatisch durch scripts/deploy.sh fuer %s erzeugt. Nicht committen.\n' "$ENVIRONMENT" > "$ENV_TMP_FILE"
  write_env_value HOCX_VERSION "$HOCX_VERSION"
  write_env_value HOCX_ENVIRONMENT "$(app_environment_for "$ENVIRONMENT")"
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
  write_env_value AUTH_SECRET "$AUTH_SECRET"
  write_env_value ADMIN_AUTH_SECRET "$ADMIN_AUTH_SECRET"
  write_env_value ADMIN_GATE_SECRET "$ADMIN_GATE_SECRET"
  write_env_value INITIAL_ADMIN_EMAIL "$INITIAL_ADMIN_EMAIL"
  write_env_value INITIAL_ADMIN_PASSWORD "$INITIAL_ADMIN_PASSWORD"
  write_env_value TRAEFIK_ABGABEBOX_DOMAIN "$TRAEFIK_ABGABEBOX_DOMAIN"
  write_env_value ABGABEBOX_DB_PASSWORD "$ABGABEBOX_DB_PASSWORD"
  write_env_value ABGABEBOX_DATABASE_URL "$ABGABEBOX_DATABASE_URL"
  write_env_value FRIENDLY_CAPTCHA_SITEKEY "$FRIENDLY_CAPTCHA_SITEKEY"
  write_env_value FRIENDLY_CAPTCHA_API_KEY "$FRIENDLY_CAPTCHA_API_KEY"
  write_env_value ABGABEBOX_CAPTCHA_SESSION_SECRET "$ABGABEBOX_CAPTCHA_SESSION_SECRET"
  write_env_value PHOTO_WORKER_DB_PASSWORD "$PHOTO_WORKER_DB_PASSWORD"
  write_env_value PHOTO_WORKER_DATABASE_URL "$PHOTO_WORKER_DATABASE_URL"
  write_env_value GEO_DB_PASSWORD "$GEO_DB_PASSWORD"
  write_env_value GEO_DATABASE_URL "$GEO_DATABASE_URL"
  write_env_value REDIS_PASSWORD "$REDIS_PASSWORD"
  if [ -n "$DEMO_TOTP_SEED" ]; then
    write_env_value DEMO_TOTP_SEED "$DEMO_TOTP_SEED"
  fi
  mv "$ENV_TMP_FILE" "$ENV_FILE"
  trap - EXIT
  exec 3>&-

  echo "    $ENV_FILE wurde mit Dateirechten 600 erstellt."
  echo "    Das generierte Initial-Admin-Passwort steht in INITIAL_ADMIN_PASSWORD."
}

if [ ! -f "$ENV_FILE" ]; then
  create_env_file
fi
if [ "$RESTORE_MODE" = 1 ]; then
  restore_import_keys || exit 1
fi
# Auch direkt nach dem Erzeugen: ergaenzt u. a. die Objektspeicher-Secrets (idempotent).
if [ -f "$ENV_FILE" ]; then
  echo "==> [$ENVIRONMENT] Env-Datei pruefen"
  migrate_env_file "$ENV_FILE"
fi

load_env_file "$ENV_FILE"
if [ "$RESTORE_MODE" = 1 ]; then
  restore_setup_backup || exit 1
fi

# Image-Referenzen kommen ausschliesslich aus einem lokal erzeugten, verifizierten
# Release-Manifest. Werte aus der aufrufenden Shell duerfen den ersten Pull nicht lenken.
unset HOCX_BACKEND_IMAGE HOCX_FRONTEND_IMAGE HOCX_ABGABEBOX_BACKEND_IMAGE \
  HOCX_ABGABEBOX_FRONTEND_IMAGE HOCX_DOCS_IMAGE HOCX_PHOTO_ANALYSIS_WORKER_IMAGE

: "${HOCX_VERSION:?HOCX_VERSION fehlt in $ENV_FILE}"
: "${GHCR_NAMESPACE:?GHCR_NAMESPACE fehlt in $ENV_FILE}"

if [[ ! "$HOCX_VERSION" =~ ^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$ ]]; then
  echo "Ungueltige HOCX_VERSION: $HOCX_VERSION" >&2
  exit 1
fi
# Prod nimmt nur Release-Tags (wie release.yml sie vergibt), nie einen Candidate-Tag: die
# Signaturpruefung allein akzeptiert jedes Image aus build-test-images.yml, auch ungetestete
# test-*-Kandidaten (Audit MAIN-OPS-016). Die Test-Freigabe erzwingt release.yml.
require_release_version_for "$ENVIRONMENT" "$HOCX_VERSION" || exit 1
require_deploy_code_for_version "$REPO_DIR" "$HOCX_VERSION" || exit 1
if [[ ! "$GHCR_NAMESPACE" =~ ^[a-z0-9][a-z0-9-]{0,38}$ ]]; then
  echo "Ungueltiger GHCR_NAMESPACE: $GHCR_NAMESPACE" >&2
  exit 1
fi

DC=(docker compose -p "$PROJECT_NAME" --env-file "$ENV_FILE" "${COMPOSE_ARGS[@]}")
# Für traefik_checks.sh (SEC-AUTH-001): aktive Mandanten-Domains aus der vom Backend generierten Datei
tenant_domains_for_checks() {
  "${DC[@]}" exec -T backend cat /app/traefik_dynamic/tenant-domains.yml 2> /dev/null
}

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

  # Host-Umgebung prod -> Anwendungswert production (Alias 'prod' wird toleriert, siehe
  # lib/env.sh::app_environment_for). Der kanonische Wert wird exportiert: Compose bevorzugt
  # Shell-Variablen vor der --env-file, die Container sehen also immer 'production'.
  local app_environment
  app_environment="$(app_environment_for "$ENVIRONMENT")"
  if [ "$(app_environment_for "${HOCX_ENVIRONMENT:-}")" != "$app_environment" ]; then
    echo "HOCX_ENVIRONMENT muss auf diesem Host '$app_environment' sein (aktuell: '${HOCX_ENVIRONMENT:-}')." >&2
    return 1
  fi
  HOCX_ENVIRONMENT="$app_environment"
  export HOCX_ENVIRONMENT
  # Review L2: Der Next.js-Server reicht bei Admin-Aufrufen den Gate-Header an INTERNAL_API_URL weiter -
  # das Ziel muss deshalb intern sein (nie eine öffentliche Domain, über die der Header Dritte erreicht).
  if ! [[ "${INTERNAL_API_URL:-}" =~ ^http://(backend|localhost|127\.0\.0\.1)(:[0-9]+)?/?$ ]]; then
    echo "INTERNAL_API_URL muss intern sein (z. B. http://backend:8000), aktuell: '${INTERNAL_API_URL:-}'." >&2
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
  if [ -n "${AUTH_SECRET_PREVIOUS:-}" ] && [ "${#AUTH_SECRET_PREVIOUS}" -lt 32 ]; then
    echo "AUTH_SECRET_PREVIOUS muss leer oder mindestens 32 Zeichen lang sein." >&2
    return 1
  fi
  # Datei-Import aus Cloud-Diensten (RUNBOOK «Cloud-Import einrichten»): Token-Schlüssel immer
  # (env_migrate erzeugt ihn), Anbieter nur vollständig oder gar nicht konfiguriert.
  if [ -n "${CLOUD_IMPORT_TOKEN_KEY_PREVIOUS:-}" ] && [ "${#CLOUD_IMPORT_TOKEN_KEY_PREVIOUS}" -lt 32 ]; then
    echo "CLOUD_IMPORT_TOKEN_KEY_PREVIOUS muss leer oder mindestens 32 Zeichen lang sein." >&2
    return 1
  fi
  if [ -n "${CLOUD_IMPORT_MS_CLIENT_ID:-}" ]; then
    if [ -z "${CLOUD_IMPORT_MS_CLIENT_SECRET:-}" ]; then
      echo "CLOUD_IMPORT_MS_CLIENT_ID ist gesetzt, CLOUD_IMPORT_MS_CLIENT_SECRET fehlt." >&2
      return 1
    fi
    if ! [[ "${CLOUD_IMPORT_MS_CLIENT_SECRET_EXPIRES:-}" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
      echo "CLOUD_IMPORT_MS_CLIENT_SECRET_EXPIRES (Ablaufdatum des Client-Secrets, JJJJ-MM-TT) fehlt oder ist ungueltig." >&2
      return 1
    fi
  fi
  # Google (Drive + Fotos): Client-ID nur mit Secret; API-Key und App-ID (Picker, nur Google Drive)
  # gemeinsam oder gar nicht. Ablaufdatum optional (Google-Secrets laufen standardmaessig nicht ab).
  if [ -n "${CLOUD_IMPORT_GOOGLE_CLIENT_ID:-}" ] && [ -z "${CLOUD_IMPORT_GOOGLE_CLIENT_SECRET:-}" ]; then
    echo "CLOUD_IMPORT_GOOGLE_CLIENT_ID ist gesetzt, CLOUD_IMPORT_GOOGLE_CLIENT_SECRET fehlt." >&2
    return 1
  fi
  if [ -n "${CLOUD_IMPORT_GOOGLE_API_KEY:-}${CLOUD_IMPORT_GOOGLE_APP_ID:-}" ]; then
    if ! [[ "${CLOUD_IMPORT_GOOGLE_API_KEY:-}" =~ ^[A-Za-z0-9_-]{20,200}$ ]] || ! [[ "${CLOUD_IMPORT_GOOGLE_APP_ID:-}" =~ ^[0-9]{6,30}$ ]]; then
      echo "CLOUD_IMPORT_GOOGLE_API_KEY und CLOUD_IMPORT_GOOGLE_APP_ID (Projektnummer) nur gemeinsam und gueltig setzen." >&2
      return 1
    fi
  fi
  if [ -n "${CLOUD_IMPORT_GOOGLE_CLIENT_SECRET_EXPIRES:-}" ] && ! [[ "${CLOUD_IMPORT_GOOGLE_CLIENT_SECRET_EXPIRES}" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
    echo "CLOUD_IMPORT_GOOGLE_CLIENT_SECRET_EXPIRES muss leer oder ein Datum (JJJJ-MM-TT) sein." >&2
    return 1
  fi
  for value in "$POSTGRES_PASSWORD" "$APP_DB_PASSWORD" "$AUTH_SECRET" \
    "$ADMIN_AUTH_SECRET" "${ADMIN_GATE_SECRET:-}" "$INITIAL_ADMIN_PASSWORD" "$ABGABEBOX_DB_PASSWORD" \
    "$ABGABEBOX_CAPTCHA_SESSION_SECRET" "$PHOTO_WORKER_DB_PASSWORD" "${GEO_DB_PASSWORD:-}" "$STORAGE_CREDENTIALS_KEY" "$EXPORT_ENCRYPTION_KEY" "$CLOUD_IMPORT_TOKEN_KEY" \
    "$GARAGE_RPC_SECRET" "$GARAGE_ADMIN_TOKEN" "$LOCAL_S3_SECRET_KEY" "$LOCAL_S3_ABGABEBOX_SECRET_KEY" "${REDIS_PASSWORD:-}"; do
    case "$value" in
      ""|ChangeMe123\!*|change-me*|changeme*|secret|hocx|hocx_app|hocx_abgabebox|hocx_photo_worker|hocx_geo|*keep-local-only*)
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
  mkdir -p "$PROJECT_DIR/backups" "$PROJECT_DIR/.releases" "$PROJECT_DIR/.secrets"
  chmod 700 "$PROJECT_DIR/backups" "$PROJECT_DIR/.releases" "$PROJECT_DIR/.secrets"
  if ! { test -w "$PROJECT_DIR/backups" && test -w "$PROJECT_DIR/.releases" && test -w "$PROJECT_DIR/.secrets"; }; then
    echo "Backup-, Release- oder Secrets-Verzeichnis ist nicht beschreibbar." >&2
    return 1
  fi
  ensure_cosign
  echo "    Preflight: ok"
}

write_secret_file() {
  local secrets_dir="$1" name="$2" value="$3" temp_file

  # 0644 statt 0600: Compose kopiert bei file:-Secrets die Rechte der Host-Datei
  # 1:1 in den Container und ignoriert dabei jegliche uid/gid/mode-Overrides in
  # der secrets:-Liste eines Service ("not supported, they will be ignored") -
  # bestaetigt per Test gegen die tatsaechlich installierte Compose-Version.
  # Verschiedene Container in diesem Stack lesen ihr Secret als unterschiedliche,
  # nicht-root UIDs (z.B. backend als hocx/5000); 0600 waere fuer alle bis auf
  # root unlesbar gewesen (PermissionError beim Alembic-Start). Kein Sicherheits-
  # verlust: $secrets_dir selbst ist 0700, andere Host-User erreichen die Dateien
  # ueber die Verzeichnisrechte ohnehin nicht, egal welchen Modus die Datei hat.
  temp_file="$(mktemp "$secrets_dir/.tmp.XXXXXX")"
  printf '%s' "$value" > "$temp_file"
  chmod 644 "$temp_file"
  mv "$temp_file" "$secrets_dir/$name"
}

write_secret_files() {
  # Compose-Secrets sind file:-basiert (siehe docker-compose.release.yml), da Docker
  # Compose >= v5.5.0 environment:-Secrets auf read_only-Services ablehnt. Diese
  # Dateien werden bei jedem Deploy frisch aus der geladenen .env geschrieben statt
  # committed - reiner Zwischenstand, gleiches Sicherheitsniveau wie .env selbst
  # (Modus 600, gleicher Host, gleicher Benutzer).
  local secrets_dir="$PROJECT_DIR/.secrets"

  echo "==> [$ENVIRONMENT] Secret-Dateien fuer Compose schreiben"
  write_secret_file "$secrets_dir" postgres_password "$POSTGRES_PASSWORD"
  write_secret_file "$secrets_dir" database_url "$DATABASE_URL"
  write_secret_file "$secrets_dir" app_database_url "$APP_DATABASE_URL"
  write_secret_file "$secrets_dir" app_db_password "$APP_DB_PASSWORD"
  write_secret_file "$secrets_dir" auth_secret "$AUTH_SECRET"
  # Optional (Rotation, RUNBOOK «Anmeldeschutz»): leer = keine Rotation im Gang
  write_secret_file "$secrets_dir" auth_secret_previous "${AUTH_SECRET_PREVIOUS:-}"
  write_secret_file "$secrets_dir" admin_auth_secret "$ADMIN_AUTH_SECRET"
  write_secret_file "$secrets_dir" admin_gate_secret "$ADMIN_GATE_SECRET"
  write_secret_file "$secrets_dir" initial_admin_password "$INITIAL_ADMIN_PASSWORD"
  write_secret_file "$secrets_dir" abgabebox_db_password "$ABGABEBOX_DB_PASSWORD"
  write_secret_file "$secrets_dir" abgabebox_database_url "$ABGABEBOX_DATABASE_URL"
  write_secret_file "$secrets_dir" photo_worker_db_password "$PHOTO_WORKER_DB_PASSWORD"
  write_secret_file "$secrets_dir" photo_worker_database_url "$PHOTO_WORKER_DATABASE_URL"
  write_secret_file "$secrets_dir" geo_db_password "$GEO_DB_PASSWORD"
  write_secret_file "$secrets_dir" geo_database_url "$GEO_DATABASE_URL"
  write_secret_file "$secrets_dir" friendly_captcha_api_key "$FRIENDLY_CAPTCHA_API_KEY"
  write_secret_file "$secrets_dir" abgabebox_captcha_session_secret "$ABGABEBOX_CAPTCHA_SESSION_SECRET"
  write_secret_file "$secrets_dir" cf_dns_api_token "$CF_DNS_API_TOKEN"
  write_secret_file "$secrets_dir" storage_credentials_key "$STORAGE_CREDENTIALS_KEY"
  write_secret_file "$secrets_dir" export_encryption_key "$EXPORT_ENCRYPTION_KEY"
  # Datei-Import (Cloud): Token-Schlüssel, bisheriger Schlüssel während einer Rotation (leer = keine)
  # und Client-Secret der Entra-App (leer = Microsoft nicht angeboten)
  write_secret_file "$secrets_dir" cloud_import_token_key "$CLOUD_IMPORT_TOKEN_KEY"
  write_secret_file "$secrets_dir" cloud_import_token_key_previous "${CLOUD_IMPORT_TOKEN_KEY_PREVIOUS:-}"
  write_secret_file "$secrets_dir" cloud_import_ms_client_secret "${CLOUD_IMPORT_MS_CLIENT_SECRET:-}"
  # Client-Secret des Google-Cloud-Projekts (leer = Google Drive/Fotos nicht angeboten)
  write_secret_file "$secrets_dir" cloud_import_google_client_secret "${CLOUD_IMPORT_GOOGLE_CLIENT_SECRET:-}"
  write_secret_file "$secrets_dir" garage_rpc_secret "$GARAGE_RPC_SECRET"
  write_secret_file "$secrets_dir" garage_admin_token "$GARAGE_ADMIN_TOKEN"
  write_secret_file "$secrets_dir" local_s3_secret_key "$LOCAL_S3_SECRET_KEY"
  write_secret_file "$secrets_dir" local_s3_abgabebox_secret_key "$LOCAL_S3_ABGABEBOX_SECRET_KEY"
  write_secret_file "$secrets_dir" redis_password "$REDIS_PASSWORD"
  # Backup (docs-site/docs/technik/backup/betrieb.md): Passphrase aus .env, SSH-Schlüssel und
  # known_hosts als Dateien auf dem Host. Nicht konfiguriert = leere Platzhalter (der
  # backup-worker meldet dann "nicht eingerichtet" statt dass Compose den Start verweigert).
  write_secret_file "$secrets_dir" backup_passphrase "${BACKUP_PASSPHRASE:-}"
  copy_secret_file "$secrets_dir" backup_ssh_key "${BACKUP_SSH_KEY_PATH:-}" || return 1
  copy_secret_file "$secrets_dir" backup_known_hosts "${BACKUP_KNOWN_HOSTS_PATH:-}" || return 1
  echo "    Secret-Dateien aktuell: $secrets_dir"
}

copy_secret_file() {
  local secrets_dir="$1" name="$2" source="$3" mode owner_uid
  if [ -z "$source" ]; then
    write_secret_file "$secrets_dir" "$name" ""
    return 0
  fi
  if [ ! -f "$source" ] || [ -L "$source" ]; then
    echo "$source (fuer $name) muss eine regulaere Datei und darf kein Symlink sein." >&2
    return 1
  fi
  owner_uid="$(stat -c '%u' "$source")"
  mode="$(stat -c '%a' "$source")"
  if { [ "$owner_uid" != "$EUID" ] && [ "$owner_uid" != 0 ]; } || (( (8#$mode & 077) != 0 )); then
    echo "Unsichere Rechte fuer $source: Besitzer $owner_uid, Modus $mode (erwartet: eigener Benutzer, 600)." >&2
    return 1
  fi
  write_secret_file "$secrets_dir" "$name" "$(cat "$source")
"
}

# Vor Datenbankmigrationen: geschütztes Backup über den laufenden backup-worker, auf dessen Ende
# gewartet wird. Ohne erfolgreiches Backup bricht der Deploy ab - ausser HOCX_PRE_DEPLOY_BACKUP=skip
# ist bewusst gesetzt (dann bleibt der lokale pg_dump oben die einzige Absicherung).
run_pre_deploy_backup() {
  if [ "${BACKUP_ENABLED:-false}" != true ]; then
    echo "    Borg-Backup nicht eingerichtet - nur lokaler Datenbank-Dump."
    return 0
  fi
  if [ "${HOCX_PRE_DEPLOY_BACKUP:-required}" = skip ]; then
    echo "    WARNUNG: HOCX_PRE_DEPLOY_BACKUP=skip - Deploy ohne vorheriges Offsite-Backup (bewusste Entscheidung)."
    return 0
  fi
  if ! "${DC[@]}" ps backup-worker --status running -q 2>/dev/null | grep -q .; then
    echo "backup-worker laeuft nicht - kein Backup vor dem Update moeglich." >&2
    echo "Entweder backup-worker starten oder bewusst HOCX_PRE_DEPLOY_BACKUP=skip setzen." >&2
    return 1
  fi
  # Teilweise erfolgreich (Datenbank-Dump vollstaendig, einzelne Objekte fehlen schon vorher)
  # blockiert den Deploy nicht; die fehlenden Objekte stehen im Log. Streng: ..._ALLOW_PARTIAL=false.
  local partial_args=(--accept-partial)
  if [ "${HOCX_PRE_DEPLOY_BACKUP_ALLOW_PARTIAL:-true}" = false ]; then
    partial_args=()
  fi
  echo "==> [$ENVIRONMENT] Offsite-Backup vor dem Update (geschuetzt, wartet auf Abschluss bzw. ein laufendes Backup)"
  if ! "${DC[@]}" exec -T backup-worker python -m app.backup.cli enqueue-backup --trigger pre_deploy \
      --key "$HOCX_VERSION-$(date +%Y%m%d%H%M%S)" --protect --reason "Vor Update auf $HOCX_VERSION" \
      --wait --timeout "${HOCX_PRE_DEPLOY_BACKUP_TIMEOUT:-7200}" "${partial_args[@]}"; then
    echo "Offsite-Backup vor dem Update fehlgeschlagen - Update abgebrochen, die laufende App ist unveraendert." >&2
    echo "Details: Admin-Portal -> System -> Backups. Bewusst ohne Backup: HOCX_PRE_DEPLOY_BACKUP=skip." >&2
    return 1
  fi
}

prepare_runtime_permissions() {
  local storage_path="${HOCX_STORAGE_PATH:-./storage}"
  local path

  if [[ "$storage_path" != /* ]]; then
    storage_path="$PROJECT_DIR/${storage_path#./}"
  fi
  # infra/traefik/dynamic haertet prepare_thumbnail_dir: dort liegt die versionierte
  # security.yml, die jedes Deploy-Code-Update mit der Gruppe des Deploy-Benutzers neu schreibt.
  path="$storage_path"
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
  if [ "$EUID" -ne 0 ]; then
    # Git legt versionierte Dateien (storage/exports/.gitkeep …) bei einem Deploy-Code-Update mit
    # der umask des Deploy-Benutzers neu an (0644). Gruppe 5001 erben sie über das setgid-Verzeichnis;
    # Gruppenrechte darf der Besitzer selbst setzen, root braucht es nur für fremde Dateien.
    find "$path" -user "$EUID" -group 5001 \( ! -perm -g+w -o -perm /007 \) -exec chmod g+rwX,o-rwx {} + 2> /dev/null || true
    find "$path" -user "$EUID" -group 5001 -type d ! -perm -g+s -exec chmod g+s {} + 2> /dev/null || true
  fi
  if find "$path" \( ! -group 5001 -o ! -perm -g+w -o -perm /007 \) -print -quit | grep -q .; then
    if [ "$EUID" -ne 0 ]; then
      echo "$path muss fuer die Container-Gruppe 5001 vorbereitet werden." >&2
      echo "Einmalig als root: chgrp -R 5001 '$path' && chmod -R g+rwX,o-rwx '$path' && find '$path' -type d -exec chmod g+s {} +" >&2
      return 1
    fi
    echo "    Haerte Berechtigungen: $path"
    chgrp -R 5001 "$path"
    chmod -R g+rwX,o-rwx "$path"
    find "$path" -type d -exec chmod g+s {} +
  fi
}

# infra/traefik/dynamic (Review L4): Traefik liest über Gruppe 5001, das Backend (uid 5000, Gruppe 5001)
# schreibt dort nur tenant-domains.yml (traefik_config_service, atomar über eine .tmp-Datei).
# Verzeichnis 3770 (setgid + Sticky-Bit: niemand ersetzt oder löscht fremde Dateien), versionierte
# Dateien und admin-gate.yml 0640 (nur der Deploy-Benutzer schreibt), tenant-domains.yml 0660.
# Live geprüft: das Backend ersetzt seine eigene Datei weiter, fremde nicht.
traefik_dynamic_dir_ok() {
  local dir="$1"
  [ "$(stat -c '%a %g' "$dir")" = "3770 5001" ] || return 1
  ! find "$dir" -mindepth 1 -maxdepth 1 -type f ! -name tenant-domains.yml ! -name '*.tmp' \
    \( ! -group 5001 -o ! -perm -g+r -o -perm /0137 \) -print -quit | grep -q . || return 1
  ! find "$dir" -mindepth 1 -maxdepth 1 -type f -name tenant-domains.yml \
    \( ! -group 5001 -o ! -perm -g+rw -o -perm /007 \) -print -quit | grep -q .
}

prepare_traefik_dynamic_dir() {
  local dir="$PROJECT_DIR/infra/traefik/dynamic"
  if [ -L "$dir" ]; then
    echo "Runtime-Pfad darf kein Symlink sein: $dir" >&2
    return 1
  fi
  mkdir -p "$dir"
  if traefik_dynamic_dir_ok "$dir"; then
    echo "    dynamic: ok"
    return 0
  fi
  echo "    Haerte Berechtigungen: $dir"
  docker run --rm --pull never --network none --user 0:0 \
    --cap-drop ALL --cap-add CHOWN --cap-add FOWNER --cap-add FSETID --cap-add DAC_OVERRIDE \
    --security-opt no-new-privileges:true --entrypoint sh \
    -v "$dir:/target" "$HOCX_BACKEND_IMAGE" \
    -c 'chgrp -R 5001 /target && chmod 3770 /target \
        && find /target -mindepth 1 -maxdepth 1 -type f ! -name tenant-domains.yml -exec chmod 0640 {} + \
        && find /target -mindepth 1 -maxdepth 1 -type f -name tenant-domains.yml -exec chmod 0660 {} +' || return 1
  traefik_dynamic_dir_ok "$dir" || { echo "Berechtigungen von $dir konnten nicht gesetzt werden." >&2; return 1; }
}

prepare_thumbnail_dir() {
  # storage-local/thumbnails (ab 1.1.0) und storage-local/work (ab 1.2.0, lokaler Arbeitsbereich
  # des Objektspeichers) liegen bewusst ausserhalb von HOCX_STORAGE_PATH und sind nicht im Repo.
  # Existieren sie nicht, legt Docker den Bind-Mount als root:root an und der Backend-Nutzer
  # (uid 5000, Gruppe 5001) kann dort nicht schreiben. Der Deploy-Benutzer darf nicht selbst auf
  # Gruppe 5001 chgrp'en; deshalb laeuft die Berechtigungs-Korrektur in einem kurzlebigen
  # Container aus dem bereits signaturgeprueften Backend-Image (HOCX_BACKEND_IMAGE stammt aus dem
  # Release-Manifest).
  # infra/traefik/dynamic: eigene Regeln, siehe prepare_traefik_dynamic_dir. Git schreibt die
  # versionierten Dateien bei einem Deploy-Code-Update als hocx-deploy 0644 neu, Traefik liest sie
  # nur über die Gruppe 5001 (cap_drop:ALL, siehe docker-compose.traefik.yml).
  # infra/maintenance (Wartungsseite, ab 1.4.3): nur lesbar fuer Gruppe 5001 (nginx im Dienst
  # maintenance-page, UID 101, group_add 5001), ohne Schreibrecht - siehe prepare_maintenance_dir.
  local base="$PROJECT_DIR/storage-local"
  local dir

  echo "==> [$ENVIRONMENT] Lokale Arbeitsverzeichnisse vorbereiten"
  prepare_traefik_dynamic_dir || return 1
  for dir in "$base/thumbnails" "$base/work" "$PROJECT_DIR/backups/storage" "$PROJECT_DIR/backups/borg-work"; do
    if [ -L "$base" ] || [ -L "$dir" ]; then
      echo "Runtime-Pfad darf kein Symlink sein: $dir" >&2
      return 1
    fi
    mkdir -p "$dir"
    if ! find "$dir" \( ! -group 5001 -o ! -perm -g+w -o -perm /007 \) -print -quit | grep -q .; then
      echo "    $(basename "$dir"): ok"
      continue
    fi
    echo "    Haerte Berechtigungen: $dir"
    docker run --rm --pull never --network none --user 0:0 \
      --cap-drop ALL --cap-add CHOWN --cap-add FOWNER --cap-add FSETID --cap-add DAC_OVERRIDE \
      --security-opt no-new-privileges:true --entrypoint sh \
      -v "$dir:/target" "$HOCX_BACKEND_IMAGE" \
      -c 'chgrp -R 5001 /target && chmod -R g+rwX,o-rwx /target && find /target -type d -exec chmod g+s {} +'
  done
  prepare_acme_dir
  prepare_maintenance_dir
}

# infra/maintenance: Gruppe 5001 nur lesen (g+rX, kein g+w), andere nichts. Der Besitzer
# (Deploy-Benutzer, Git) behaelt seine Rechte; setgid, damit neue Dateien die Gruppe erben.
prepare_maintenance_dir() {
  local dir="$PROJECT_DIR/infra/maintenance"

  if [ -L "$dir" ]; then
    echo "Runtime-Pfad darf kein Symlink sein: $dir" >&2
    return 1
  fi
  [ -d "$dir" ] || return 0
  if ! find "$dir" \( ! -group 5001 -o ! -perm -g+r -o -perm /g+w -o -perm /007 -o \( -type d ! -perm -g+xs \) \) -print -quit | grep -q .; then
    echo "    maintenance: ok"
    return 0
  fi
  echo "    Haerte Berechtigungen: $dir (Gruppe 5001 nur lesen)"
  docker run --rm --pull never --network none --user 0:0 \
    --cap-drop ALL --cap-add CHOWN --cap-add FOWNER --cap-add FSETID --cap-add DAC_OVERRIDE \
    --security-opt no-new-privileges:true --entrypoint sh \
    -v "$dir:/target" "$HOCX_BACKEND_IMAGE" \
    -c 'chgrp -R 5001 /target && chmod -R g+rX,g-w,o-rwx /target && find /target -type d -exec chmod g+s {} +'
}

# infra/traefik/letsencrypt gehoert root (Traefik laeuft als root ohne CAP_DAC_OVERRIDE und
# schreibt dort acme.json mit 0600). 0711 statt 0700: Git (als hocx-deploy) muss die versionierte
# .gitkeep per Namen erreichen koennen, sonst meldet `git status` beim Deploy-Code-Update
# "Permission denied". Auflisten kann der Deploy-Benutzer das Verzeichnis weiterhin nicht.
prepare_acme_dir() {
  local dir="$PROJECT_DIR/infra/traefik/letsencrypt"

  if [ -L "$dir" ]; then
    echo "Runtime-Pfad darf kein Symlink sein: $dir" >&2
    return 1
  fi
  mkdir -p "$dir"
  if [ "$(stat -c '%u:%g:%a' "$dir")" = "0:0:711" ]; then
    echo "    letsencrypt: ok"
    return 0
  fi
  echo "    Setze Besitz und Rechte: $dir (root, 0711)"
  docker run --rm --pull never --network none --user 0:0 \
    --cap-drop ALL --cap-add CHOWN --cap-add FOWNER \
    --security-opt no-new-privileges:true --entrypoint sh \
    -v "$dir:/target" "$HOCX_BACKEND_IMAGE" \
    -c 'chown 0:0 /target && chmod 0711 /target'
}


# Worker ohne eigenes Image: sie laufen mit dem Backend-Image (HOCX_BACKEND_IMAGE). Das
# Release-Manifest merkt sich, welche davon das Release hatte - ein Rollback auf ein älteres
# Release (z. B. 1.1.x ohne Objektspeicher/Backup/Dokumentverarbeitung) stoppt die übrigen,
# statt sie mit dem neuen Image neben dem alten Backend weiterlaufen zu lassen.
BACKEND_IMAGE_WORKERS=(storage-worker backup-worker document-worker job-worker)

backend_workers_in_compose() {
  local worker found=()
  for worker in "${BACKEND_IMAGE_WORKERS[@]}"; do
    service_exists "$worker" && found+=("$worker")
  done
  echo "${found[*]:-}"
}

verify_release_images() {
  local service image repository digest_ref

  HOCX_SIGNING_IDENTITY_REGEXP="${HOCX_SIGNING_IDENTITY_REGEXP:-(?i)^https://github.com/${GHCR_NAMESPACE}/hocx/.github/workflows/build-test-images[.]yml@refs/heads/main$}"

  echo "==> [$ENVIRONMENT] Signaturen der gepullten Images pruefen"
  for service in backend frontend abgabebox-backend abgabebox-frontend docs photo-analysis-worker; do
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
  for service in backend frontend abgabebox-backend abgabebox-frontend docs photo-analysis-worker; do
    repository="ghcr.io/${GHCR_NAMESPACE}/hocx-${service}"
    image="${repository}:${HOCX_VERSION}"
    digest_ref="$(docker image inspect "$image" --format '{{range .RepoDigests}}{{println .}}{{end}}' | grep -F "${repository}@sha256:" | head -n 1)"
    [ -n "$digest_ref" ] || return 1
    variable="HOCX_${service^^}_IMAGE"
    variable="${variable//-/_}"
    printf "%s='%s'\n" "$variable" "$digest_ref" >> "$temp_file"
  done
  printf "HOCX_BACKEND_WORKERS='%s'\n" "$(backend_workers_in_compose)" >> "$temp_file"
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

  for service in backend frontend abgabebox-backend abgabebox-frontend docs photo-analysis-worker; do
    container_id="$("${DC[@]}" ps -q "$service" 2> /dev/null || true)"
    if [ -z "$container_id" ]; then
      # photo-analysis-worker gibt es erst ab 1.1.0; ein Host, der von 1.0.x kommt, hat ihn
      # nicht und muss trotzdem ein Rollback-Ziel erfassen koennen.
      [ "$service" != photo-analysis-worker ] || continue
      return 0
    fi
    repository="ghcr.io/${GHCR_NAMESPACE}/hocx-${service}"
    image_id="$(docker inspect "$container_id" --format '{{.Image}}')"
    digest_ref="$(docker image inspect "$image_id" --format '{{range .RepoDigests}}{{println .}}{{end}}' | grep -F "${repository}@sha256:" | head -n 1)"
    [ -n "$digest_ref" ] || return 0
    variable="HOCX_${service^^}_IMAGE"
    variable="${variable//-/_}"
    printf "%s='%s'\n" "$variable" "$digest_ref" >> "$temp_file"
  done
  local worker running_workers=()
  for worker in "${BACKEND_IMAGE_WORKERS[@]}"; do
    [ -n "$("${DC[@]}" ps -q "$worker" 2> /dev/null || true)" ] && running_workers+=("$worker")
  done
  printf "HOCX_BACKEND_WORKERS='%s'\n" "${running_workers[*]:-}" >> "$temp_file"
  mv "$temp_file" "$current_manifest"
  chmod 600 "$current_manifest"
  trap - RETURN
  echo "    Bestehendes Image-Set als Rollback-Ziel erfasst."
}

# Rollback beendet immer auch den Wartungsmodus des Updates: danach läuft wieder ein Release
# (oder gar keins - dann hilft die Wartungsansicht auch nicht weiter).
rollback_apps() {
  local status=0
  # Liefen in diesem Deploy Migrationen, passt das vorherige Image-Set nicht mehr zur Datenbank
  # (1.5.0: 0205 entfernt Admin-Spalten, r90 startete danach nicht mehr). Ein Rollback der Images
  # würde den Ausfall nur sicher machen - stattdessen beim neuen Release bleiben.
  if [ "${MIGRATIONS_APPLIED:-0}" = 1 ]; then
    hold_release_after_migration
    return 1
  fi
  rollback_app_images || status=$?
  end_deploy_maintenance rollback || true
  return "$status"
}

# Kein Rollback nach Migrationen: das neue Release bleibt (es ist das einzige, das zur migrierten
# Datenbank passt) und wird Rollback-Ziel, damit ein späteres rollback nicht auf das inkompatible alte
# Release zurückgeht. Besteht es die Smoke-Checks, endet die Wartung; sonst bleibt die Wartungsseite
# aktiv (Nutzer sehen Wartung statt Fehler), bis der Betreiber eingreift.
hold_release_after_migration() {
  echo "==> [$ENVIRONMENT] KEIN automatischer App-Rollback" >&2
  echo "    Dieses Deploy hat Datenbankmigrationen ausgeführt; das vorherige Release passt nicht zur" >&2
  echo "    migrierten Datenbank. $HOCX_VERSION bleibt aktiv und wird Rollback-Ziel." >&2
  install -m 600 "$PROJECT_DIR/.releases/${HOCX_VERSION}.env" "$PROJECT_DIR/.releases/current.env" || true
  if run_smoke_checks; then
    end_deploy_maintenance aborted || true
    echo "    $HOCX_VERSION läuft und besteht die Smoke-Checks; behoben wird nach vorne (Fix, erneutes Deploy)." >&2
  else
    # Wartungsseite stehen lassen: der EXIT-Trap darf sie nicht beenden
    DEPLOY_MAINTENANCE_ACTIVE=0
    echo "    $HOCX_VERSION besteht die Smoke-Checks NICHT. Der Wartungsmodus bleibt aktiv." >&2
    echo "    Wartung beenden: Admin-Portal -> System -> Wartung -> Freigeben, oder" >&2
    echo "    docker compose -p $PROJECT_NAME ... run --rm --no-deps backend python -m app.maintenance_cli end-deploy --outcome aborted" >&2
  fi
  echo "    Optionen: Fehler beheben und ./scripts/deploy.sh $ENVIRONMENT erneut ausführen, oder das" >&2
  echo "    Datenbank-Backup dieses Laufs einspielen und danach das vorherige Release deployen:" >&2
  echo "    ${BACKUP_FILE:-(kein Backup in diesem Lauf)}" >&2
}

rollback_app_images() {
  local current_manifest="$PROJECT_DIR/.releases/current.env"
  local -a services=(backend frontend abgabebox-backend abgabebox-frontend docs)
  echo "==> [$ENVIRONMENT] Automatischer App-Rollback"
  if [ ! -f "$current_manifest" ]; then
    echo "    Kein vorheriges Release vorhanden; stoppe neu gestartete App-Services." >&2
    "${DC[@]}" stop backend frontend abgabebox-backend abgabebox-frontend docs photo-analysis-worker "${BACKEND_IMAGE_WORKERS[@]}" || true
    return 1
  fi
  # Die Image-Variablen des fehlgeschlagenen Releases duerfen das alte Manifest nicht ueberlagern.
  unset HOCX_BACKEND_IMAGE HOCX_FRONTEND_IMAGE HOCX_ABGABEBOX_BACKEND_IMAGE \
    HOCX_ABGABEBOX_FRONTEND_IMAGE HOCX_DOCS_IMAGE HOCX_PHOTO_ANALYSIS_WORKER_IMAGE HOCX_BACKEND_WORKERS
  load_env_file "$current_manifest"
  # Worker mit dem Backend-Image: mit dem alten Image neu starten, wenn das vorherige Release
  # sie hatte, sonst stoppen (Manifeste vor 1.2.0 kennen HOCX_BACKEND_WORKERS nicht).
  local worker
  for worker in "${BACKEND_IMAGE_WORKERS[@]}"; do
    service_exists "$worker" || continue
    if [[ " ${HOCX_BACKEND_WORKERS:-} " == *" $worker "* ]]; then
      services+=("$worker")
    else
      "${DC[@]}" stop "$worker" || true
    fi
  done
  if [ -n "${HOCX_PHOTO_ANALYSIS_WORKER_IMAGE:-}" ]; then
    services+=(photo-analysis-worker)
  else
    # Vorheriges Release (< 1.1.0) kennt den Worker nicht: den neuen stoppen statt ein
    # nicht vorhandenes Image zu starten, und ihn in den Smoke-Checks auslassen.
    SKIP_PHOTO_WORKER_CHECK=true
    "${DC[@]}" stop photo-analysis-worker || true
  fi
  if "${DC[@]}" up -d --no-deps --pull never "${services[@]}"; then
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

# Richtet einen Host-Cronjob in der crontab des Deploy-Benutzers ein bzw. haelt ihn aktuell
# (Pfade, Compose-Dateien). Eintraege tragen den Marker "# hocx-managed:<projekt>:<name>" und
# werden nur ueber diesen erkannt; andere Zeilen bleiben unveraendert. Ein von Hand
# eingetragener Job (ohne Marker) wird nicht angetastet und auch nicht verdoppelt.
# HOCX_MANAGE_CRON=false in .env schaltet das ab.
install_managed_cron() {
  local name="$1" schedule="$2" command="$3"
  local marker="# hocx-managed:${PROJECT_NAME}:${name}"
  local entry="$schedule $command $marker"
  local current

  if [ "${HOCX_MANAGE_CRON:-true}" = false ]; then
    echo "    Cron $name: nicht verwaltet (HOCX_MANAGE_CRON=false)"
    return 0
  fi
  if ! command -v crontab > /dev/null 2>&1; then
    echo "    crontab fehlt - Cron $name bitte von Hand einrichten (RUNBOOK Abschnitt 10)." >&2
    return 1
  fi
  # % ist in crontab-Zeilen ein Sonderzeichen, Zeilenumbrueche wuerden den Eintrag zerlegen.
  if [[ "$command" == *%* || "$command" == *$'\n'* ]]; then
    echo "    Cron $name: Befehl enthaelt % oder Zeilenumbruch - bitte von Hand einrichten." >&2
    return 1
  fi
  current="$(crontab -l 2> /dev/null || true)"
  if grep -Fxq -- "$entry" <<< "$current"; then
    echo "    Cron $name: ok"
    return 0
  fi
  if grep -Fv -- "$marker" <<< "$current" | grep -Eq "^[^#].*/scripts/run_job\.sh $name "; then
    echo "    Cron $name: von Hand eingetragen - unveraendert gelassen"
    return 0
  fi
  {
    [ -z "$current" ] || grep -Fv -- "$marker" <<< "$current" || true
    printf '%s\n' "$entry"
  } | crontab - || return 1
  echo "    Cron $name: eingerichtet ($schedule)"
}

service_exists() {
  "${DC[@]}" config --services | grep -Fxq "$1"
}

# Traefik liest infra/traefik/traefik.yml (statische Konfiguration: Entrypoints, Timeouts,
# Provider) nur beim Start, und `compose up -d` erstellt den Container bei einer Aenderung
# nur des gemounteten Dateiinhalts nicht neu. So lief Prod nach dem Update auf readTimeout 3h
# weiter mit dem 60-s-Default, und grosse Galerie-Uploads brachen mit 502 ab. Der Hash der
# zuletzt uebernommenen Datei liegt unter .releases/; weicht er ab (oder fehlt er), wird
# Traefik neu erstellt. Die dynamische Konfiguration (infra/traefik/dynamic) laedt Traefik
# per watch selbst nach und braucht das nicht.
sync_traefik_static_config() {
  recreate_on_config_change traefik "$PROJECT_DIR/infra/traefik/traefik.yml" traefik-static Traefik
}

# Wartungsseite (ab 1.4.3): nginx liest infra/maintenance/nginx.conf nur beim Start, HTML/JSON
# dagegen bei jeder Anfrage. Gleiches Muster wie sync_traefik_static_config.
sync_maintenance_page_config() {
  recreate_on_config_change maintenance-page "$PROJECT_DIR/infra/maintenance/nginx.conf" maintenance-nginx Wartungsseite
}

recreate_on_config_change() {
  local service="$1" config="$2" name="$3" label="$4"
  local state="$PROJECT_DIR/.releases/$name.sha256"
  local current

  service_exists "$service" || return 0
  current="$(sha256sum "$config" | cut -d' ' -f1)"
  [ "$(cat "$state" 2> /dev/null)" != "$current" ] || return 0
  echo "==> [$ENVIRONMENT] $label-Konfiguration geaendert - $service neu erstellen"
  "${DC[@]}" up -d --no-deps --force-recreate --pull never "$service" || return 1
  printf '%s\n' "$current" > "$state"
}

# Wartungsmodus während des Updates (app/maintenance_cli.py, RUNBOOK Abschnitt 20): Zwischen
# Migration und Neustart laufen die alten Container gegen ein geändertes Schema. Mit dem Fenster
# sperrt das alte Backend die API (503 "maintenance"), das alte Frontend zeigt angemeldeten
# Nutzern seine Wartungsansicht, die Abgabebox ihr Banner. Admin-API, Healthchecks und der
# Wartungsstatus bleiben offen. Ein Fehler hier ist nur eine Warnung, nie ein Abbruch - das
# Beenden aber darf nie fehlen: Rollback, EXIT-Trap und ein SQL-Rückfall ohne Backend-Image.
# HOCX_DEPLOY_MAINTENANCE=0 schaltet es ab.
DEPLOY_MAINTENANCE_ACTIVE=0
DEPLOY_MAINTENANCE_IMAGE=""
# Statisches SQL ohne Variablen: Fenster beenden, Verlauf und Audit-Eintrag wie die CLI.
DEPLOY_MAINTENANCE_END_SQL="WITH ended AS (UPDATE public.maintenance_window SET state = 'completed', ended_at = now(), updated_at = now() WHERE source_job_type = 'deploy' AND state NOT IN ('completed', 'cancelled') RETURNING id), events AS (INSERT INTO public.maintenance_event (window_id, kind, actor_email, to_state, details) SELECT id, 'transition', 'system:deploy', 'completed', '{\"source\": \"deploy-sql\"}'::jsonb FROM ended) INSERT INTO public.audit_log (actor_email, action, entity_type, details_json) SELECT 'system:deploy', 'admin.maintenance_deploy_ended', 'maintenance_window', jsonb_build_object('window_ids', jsonb_agg(id), 'outcome', 'sql-fallback') FROM ended HAVING count(*) > 0"

# Versionen für die Update-Seite (In-App und statisch, RUNBOOK Abschnitt 20): nur harmlose
# Kennungen, sonst leer. Laufende Version aus dem Rollback-Ziel (.releases/current.env), gelesen
# als Daten - nie per source.
DEPLOY_VERSION_RE='^[0-9A-Za-z][0-9A-Za-z._+-]{0,63}$'
DEPLOY_STATUS_URL_RE='^https://[A-Za-z0-9.-]+(:[0-9]{1,5})?(/[A-Za-z0-9._~/-]*)?$'
DEPLOY_FROM_VERSION=""

clean_deploy_version() {
  if [[ "$1" =~ $DEPLOY_VERSION_RE ]]; then printf '%s' "$1"; fi
}

read_running_version() {
  local manifest="$PROJECT_DIR/.releases/current.env" value
  [ -f "$manifest" ] || return 0
  value="$(sed -n "s/^HOCX_VERSION='\{0,1\}\([^']*\)'\{0,1\}\$/\1/p" "$manifest" | head -n 1)"
  [ "$value" = unknown ] || clean_deploy_version "$value"
}

# Kleine Datei für die statische Wartungsseite (nginx bettet sie per SSI ein): Versionen und Beginn
# des Updates, optional der Link zur Statusseite (HOCX_STATUS_PAGE_URL). Keine Benutzerdaten.
# Nur geprüfte Werte (kein «<», «"» oder «\»), atomar ersetzt, Gruppe 5001 nur lesend (setgid
# des Verzeichnisses, prepare_maintenance_dir). Ein Fehler ist nur eine Warnung.
MAINTENANCE_INFO_FILE="$PROJECT_DIR/infra/maintenance/update-info.json"

write_maintenance_info() {
  local from to url="" since="" tmp fields=()
  from="$(clean_deploy_version "${1:-}")"
  to="$(clean_deploy_version "${2:-}")"
  [ -z "${3:-}" ] || since="$(date +%s)"
  if [[ "${HOCX_STATUS_PAGE_URL:-}" =~ $DEPLOY_STATUS_URL_RE ]]; then
    url="$HOCX_STATUS_PAGE_URL"
  elif [ -n "${HOCX_STATUS_PAGE_URL:-}" ]; then
    echo "    WARNUNG: HOCX_STATUS_PAGE_URL ist keine einfache https-Adresse - ohne Link auf der Wartungsseite." >&2
  fi
  [ -d "$PROJECT_DIR/infra/maintenance" ] || return 0
  if [ -z "$from$to$since$url" ]; then
    rm -f -- "$MAINTENANCE_INFO_FILE"
    return 0
  fi
  [ -z "$since" ] || fields+=("\"update\":true" "\"since\":$since")
  [ -z "$from" ] || fields+=("\"from\":\"$from\"")
  [ -z "$to" ] || fields+=("\"to\":\"$to\"")
  [ -z "$url" ] || fields+=("\"status_url\":\"$url\"")
  tmp="$(mktemp "$PROJECT_DIR/infra/maintenance/.update-info.XXXXXX")" || return 0
  # Halbe Datei (z. B. Platte voll) nie aktivieren.
  if ! (IFS=,; printf '{%s}\n' "${fields[*]}") > "$tmp" || ! chmod 640 "$tmp"; then
    rm -f -- "$tmp"
    echo "    WARNUNG: Update-Info für die Wartungsseite nicht geschrieben." >&2
    return 0
  fi
  chgrp 5001 "$tmp" 2> /dev/null || true
  mv -f -- "$tmp" "$MAINTENANCE_INFO_FILE" || { rm -f -- "$tmp"; echo "    WARNUNG: Update-Info für die Wartungsseite nicht geschrieben." >&2; }
}

# Nach dem Update (Erfolg, Rollback, Abbruch): nur noch der Statusseiten-Link bleibt stehen.
clear_maintenance_info() {
  write_maintenance_info "" "" "" || true
}

# Immer mit dem Backend-Image des neuen Releases (gemerkt bei begin): nach einem Rollback zeigt
# HOCX_BACKEND_IMAGE auf das alte Release, das die CLI noch nicht kennen muss.
deploy_maintenance_cli() {
  HOCX_BACKEND_IMAGE="$DEPLOY_MAINTENANCE_IMAGE" "${DC[@]}" run --rm --no-deps --pull never backend \
    python -m app.maintenance_cli "$@"
}

begin_deploy_maintenance() {
  service_exists backend || return 0
  if [ "${HOCX_DEPLOY_MAINTENANCE:-1}" = 0 ]; then
    echo "==> [$ENVIRONMENT] Wartungsmodus für das Update übersprungen (HOCX_DEPLOY_MAINTENANCE=0)"
    return 0
  fi
  echo "==> [$ENVIRONMENT] Wartungsmodus für das Update aktivieren"
  DEPLOY_MAINTENANCE_IMAGE="${HOCX_BACKEND_IMAGE:-}"
  # Schon vor dem Aufruf: auch ein halb gelungener Start wird am Ende sicher wieder beendet.
  DEPLOY_MAINTENANCE_ACTIVE=1
  local from_args=()
  [ -z "$DEPLOY_FROM_VERSION" ] || from_args=(--from-version "$DEPLOY_FROM_VERSION")
  if ! deploy_maintenance_cli begin-deploy --version "$HOCX_VERSION" ${from_args[@]+"${from_args[@]}"}; then
    echo "    WARNUNG: Wartungsmodus nicht aktiviert - das Update läuft ohne weiter." >&2
  fi
}

# end_deploy_maintenance <success|rollback|aborted> - 1, wenn die Wartung danach noch aktiv ist
end_deploy_maintenance() {
  [ "$DEPLOY_MAINTENANCE_ACTIVE" = 1 ] || return 0
  echo "==> [$ENVIRONMENT] Wartungsmodus des Updates beenden ($1)"
  if deploy_maintenance_cli end-deploy --outcome "$1"; then
    DEPLOY_MAINTENANCE_ACTIVE=0
    return 0
  fi
  echo "    Backend-CLI fehlgeschlagen - beende das Deploy-Fenster direkt in der Datenbank." >&2
  if "${DC[@]}" exec -T db psql -v ON_ERROR_STOP=1 -q -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "$DEPLOY_MAINTENANCE_END_SQL"; then
    DEPLOY_MAINTENANCE_ACTIVE=0
    echo "    Wartungsmodus beendet (SQL)."
    return 0
  fi
  echo "    FEHLER: Wartungsmodus des Updates ist NOCH AKTIV - die App bleibt für Nutzer gesperrt." >&2
  echo "    Manuell beenden: docker compose -p $PROJECT_NAME ... run --rm --no-deps backend python -m app.maintenance_cli end-deploy --outcome $1" >&2
  echo "    oder Admin-Portal -> System -> Wartung -> Freigeben (Fenster «Update»)." >&2
  return 1
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

  # Admin-Panel als eigener Dienst (Review M3); auf einem fremden Host antwortet es mit 404.
  if service_exists admin-frontend; then
    wait_for_exec admin-frontend "Admin-Frontend" "node -e \"require('http').get('http://localhost:3000/', res => process.exit(res.statusCode < 500 ? 0 : 1)).on('error', () => process.exit(1))\"" || return 1
  fi

  if service_exists abgabebox-backend; then
    wait_for_exec abgabebox-backend "Abgabebox-Backend" "python3 -c \"import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health', timeout=5)\"" || return 1
  fi

  if service_exists abgabebox-frontend; then
    wait_for_exec abgabebox-frontend "Abgabebox-Frontend" "node -e \"require('http').get('http://localhost:3000/', res => process.exit(res.statusCode < 500 ? 0 : 1)).on('error', () => process.exit(1))\"" || return 1
  fi

  if service_exists docs; then
    # 127.0.0.1 statt localhost - siehe Kommentar beim docs-Healthcheck in
    # docker-compose.release.yml (IPv6-Verbindung schlaegt sonst fehl, obwohl nginx
    # laeuft).
    wait_for_exec docs "Docs" "wget -q --spider http://127.0.0.1/" || return 1
  fi

  if service_exists clamav; then
    wait_for_exec clamav "ClamAV" "clamdcheck.sh" 150 2 || return 1
  fi

  if service_exists photo-analysis-worker && [ "${SKIP_PHOTO_WORKER_CHECK:-false}" != true ]; then
    # No HTTP endpoint (it's a polling worker, not a web service) - actually loads the
    # baked-in YuNet model instead of just checking the process is alive, so a broken
    # model file or missing dependency fails the deploy here instead of surfacing later
    # as every photo_analysis_job silently failing.
    wait_for_exec photo-analysis-worker "Photo-Analysis-Worker" \
      "python3 -c \"from app.face_quality import load_detector; load_detector('/app/models/face_detection_yunet.onnx')\"" \
      || return 1
  fi

  # Worker ohne HTTP-Endpunkt mit dem Backend-Image: Code lädt, Werkzeuge sind im Image. Nach
  # einem Rollback auf ein Release ohne den Worker ist er gestoppt und wird übersprungen.
  if service_exists document-worker && [ -n "$("${DC[@]}" ps -q --status running document-worker 2> /dev/null || true)" ]; then
    wait_for_exec document-worker "Document-Worker" \
      "python3 -c \"import sys, app.workers.document_worker; from app.services.documents.convert import soffice_binary; from app.services.documents.ocr import ocr_available; sys.exit(0 if soffice_binary() and ocr_available() else 1)\"" \
      || return 1
  fi
  if service_exists storage-worker && [ -n "$("${DC[@]}" ps -q --status running storage-worker 2> /dev/null || true)" ]; then
    wait_for_exec storage-worker "Storage-Worker" "python3 -c \"import app.workers.storage_worker\"" || return 1
  fi
  # storage-init beendet sich nach dem Einrichten; ein Fehler (z. B. Secret nicht lesbar) fiel
  # frueher nicht auf und Garage blieb ohne Schluessel/Buckets. Idempotent erneut ausfuehren.
  if service_exists storage-init && [ -n "$("${DC[@]}" ps -q --status running local-s3 2> /dev/null || true)" ]; then
    echo "    Pruefe Lokales S3 (storage-init)"
    local init_output
    if ! init_output="$("${DC[@]}" run --rm --no-deps --pull never storage-init 2>&1)"; then
      printf '%s\n' "$init_output" | tail -n 20 >&2
      echo "    Lokales S3: Einrichtung fehlgeschlagen" >&2
      return 1
    fi
    echo "    Lokales S3: ok"
  fi
  # Schwere Hintergrundjobs und PDF-Aufträge (Concurrency-Audit Paket 10).
  if service_exists job-worker && [ -n "$("${DC[@]}" ps -q --status running job-worker 2> /dev/null || true)" ]; then
    wait_for_exec job-worker "Job-Worker" "python3 -c \"import app.workers.job_worker; app.workers.job_worker.loop_factories()\"" || return 1
  fi
}

# Behaelt die neuesten <keep> Pre-Deploy-Dumps (*-pre-*.sql.gz[.gpg]) und loescht aeltere. Der
# Zeitstempel am Dateianfang sortiert lexikografisch chronologisch.
prune_pre_deploy_backups() {
  local dir="$1" keep="$2" file
  [[ "$keep" =~ ^[1-9][0-9]*$ ]] || {
    echo "    PRE_DEPLOY_BACKUP_KEEP muss eine positive Zahl sein - keine Rotation." >&2
    return 0
  }
  find "$dir" -maxdepth 1 -type f \( -name '*-pre-*.sql.gz' -o -name '*-pre-*.sql.gz.gpg' \) -printf '%f\n' | sort -r | tail -n "+$((keep + 1))" |
    while IFS= read -r file; do
      rm -f -- "$dir/$file"
      echo "    Altes Pre-Deploy-Backup entfernt: $file"
    done
}

run_preflight
write_secret_files
prepare_runtime_permissions
capture_current_release
# Vor create_release_manifest (das HOCX_VERSION neu lädt): laufendes Release für die Update-Seite.
DEPLOY_FROM_VERSION="$(read_running_version)"

BACKUP_DIR="$PROJECT_DIR/backups"
BACKUP_FILE=""
if [ "$RESTORE_MODE" != 1 ]; then
echo "==> [$ENVIRONMENT] Backup der Datenbank vor dem Update auf $HOCX_VERSION"
mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"
# Verschlüsselt mit dem öffentlichen Schlüssel aus BACKUP_DUMP_PUBLIC_KEY_PATH, sonst gzip mit
# Warnung (scripts/lib/dump_crypto.sh, Datenschutz-Audit PRIV-009).
check_dump_encryption || exit 1
BACKUP_FILE="$BACKUP_DIR/$(date +%Y%m%d-%H%M%S)-pre-$HOCX_VERSION$(dump_suffix)"
if "${DC[@]}" ps db --status running -q > /dev/null 2>&1 && [ -n "$("${DC[@]}" ps db --status running -q)" ]; then
  "${DC[@]}" exec -T db pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" | write_dump "$BACKUP_FILE"
  echo "    Backup: $BACKUP_FILE"
  # Pre-Deploy-Dumps wuchsen bisher unbegrenzt auf derselben Partition (Audit MAIN-OPS-010).
  # Die neuesten PRE_DEPLOY_BACKUP_KEEP (Default 10) bleiben fuer Rollbacks erhalten, aber nicht
  # länger als PRE_DEPLOY_BACKUP_MAX_DAYS (Default 30, die neueste Datei immer) - PRIV-009.
  prune_pre_deploy_backups "$BACKUP_DIR" "${PRE_DEPLOY_BACKUP_KEEP:-10}"
  prune_dumps_older_than "$BACKUP_DIR" '*-pre-*.sql.gz*' "${PRE_DEPLOY_BACKUP_MAX_DAYS:-30}"
else
  echo "    db-Container laeuft noch nicht (erster Deploy) - kein Backup noetig."
fi
if "${DC[@]}" ps db --status running -q > /dev/null 2>&1 && [ -n "$("${DC[@]}" ps db --status running -q)" ]; then
  run_pre_deploy_backup || exit 1
fi

# Nur noch S3: prüft (und bereinigt auf Wunsch) mit dem noch laufenden Release, siehe
# scripts/lib/storage_gate.sh. Ohne Erfolg bleibt alles beim bisherigen Release.
echo "==> [$ENVIRONMENT] Objektspeicher: Voraussetzungen für «nur noch S3»"
if ! storage_upgrade_gate; then
  echo "Deploy abgebrochen; es laeuft weiter das bisherige Release." >&2
  [ ! -f "$BACKUP_FILE" ] || echo "Backup dieses Laufs: $BACKUP_FILE" >&2
  exit 1
fi
fi # RESTORE_MODE: kein Vorab-Backup und kein S3-Tor - es läuft noch kein Release

echo "==> [$ENVIRONMENT] Pull Images ($HOCX_VERSION)"
"${DC[@]}" pull

verify_release_images
create_release_manifest
prepare_thumbnail_dir

# 1.2.0: PostgreSQL 16 -> 18 in ein neues Volume (scripts/lib/pg_upgrade.sh). Läuft nach dem
# Pre-Deploy-Backup und vor dem ersten Start des neuen db-Dienstes; ohne altes Volume ein No-op.
if ! pg_upgrade_major_if_needed "$PROJECT_NAME" "$POSTGRES_USER" "$POSTGRES_DB" "$("${DC[@]}" config --images db)"; then
  echo "Deploy abgebrochen; es laeuft weiter das bisherige Release." >&2
  [ ! -f "$BACKUP_FILE" ] || echo "Backup dieses Laufs: $BACKUP_FILE" >&2
  exit 1
fi

# Nach einem Datenbank-Upgrade sind die alten App-Container gestoppt; scheitert danach die
# Migration, laufen sie wieder (gegen PostgreSQL 18, Schema unverändert).
restart_containers_stopped_for_pg_upgrade() {
  [ "${#PG_UPGRADE_STOPPED_CONTAINERS[@]}" -gt 0 ] || return 0
  echo "    Starte die fuer das Datenbank-Upgrade gestoppten Container wieder." >&2
  docker start "${PG_UPGRADE_STOPPED_CONTAINERS[@]}" > /dev/null || echo "    Neustart fehlgeschlagen; bitte pruefen: docker ps -a" >&2
}

# Neuer Server aus dem Backup: Datenbank und Dateien wiederherstellen, bevor Migrationen laufen.
if [ "$RESTORE_MODE" = 1 ]; then
  restore_run || exit 1
fi

echo "==> [$ENVIRONMENT] Infrastruktur starten"
"${DC[@]}" up -d --pull never db redis
# Wartungsseite vor dem Austausch der App-Container: ihre Ausweich-Router übernehmen, sobald
# Traefik einen App-Router entfernt (Container gestoppt oder noch nicht healthy). Läuft sie schon
# mit unveränderter Konfiguration, ist das ein No-op. Ein Fehler hier stoppt das Update nicht.
if service_exists maintenance-page; then
  if ! "${DC[@]}" up -d --no-deps --pull never maintenance-page || ! sync_maintenance_page_config; then
    echo "    WARNUNG: Wartungsseite nicht gestartet - während des Updates zeigt Traefik seine Fehlerseite." >&2
  fi
fi
wait_for_exec db "Postgres" "pg_isready -U '$POSTGRES_USER' -d '$POSTGRES_DB'" 30 2

# Jeder Abbruch ab hier (exit 1) beendet die Wartung wieder; die Funktion ist idempotent und
# ohne aktive Wartung ein No-op. Vor begin gesetzt: auch ein Abbruch mitten im Start wird erfasst.
trap 'end_deploy_maintenance aborted || true; clear_maintenance_info' EXIT
# Vor begin-deploy: zeigt die statische Wartungsseite während des Neustarts dieselbe
# Update-Meldung («vX → vY») wie die In-App-Seite des Deploy-Fensters.
write_maintenance_info "$DEPLOY_FROM_VERSION" "$HOCX_VERSION" update ||
  echo "    WARNUNG: Update-Info für die Wartungsseite nicht geschrieben." >&2
begin_deploy_maintenance

echo "==> [$ENVIRONMENT] Datenbankmigration"
ALEMBIC_ARGS=()
case "${HOCX_SINGLE_TENANT_RESOLUTION:-}" in
  "") ;;
  auto)
    echo "    HOCX_SINGLE_TENANT_RESOLUTION=auto: Konten mit mehreren Mandanten werden automatisch aufgeloest (Migration 0078)."
    ALEMBIC_ARGS=(-x single_tenant_resolution=auto)
    ;;
  *)
    echo "Ungueltiger HOCX_SINGLE_TENANT_RESOLUTION: ${HOCX_SINGLE_TENANT_RESOLUTION} (erlaubt: auto)" >&2
    exit 1
    ;;
esac
# Ob Migrationen liefen, steht in der Alembic-Ausgabe («Running upgrade a -> b»); danach ist kein
# Rollback der Images mehr möglich (rollback_apps -> hold_release_after_migration).
MIGRATIONS_APPLIED=0
MIGRATION_LOG="$(mktemp)"
migration_status=0
"${DC[@]}" run --rm --no-deps backend alembic ${ALEMBIC_ARGS[@]+"${ALEMBIC_ARGS[@]}"} upgrade head 2>&1 | tee "$MIGRATION_LOG" || migration_status=$?
if grep -q "Running upgrade" "$MIGRATION_LOG"; then
  MIGRATIONS_APPLIED=1
fi
rm -f "$MIGRATION_LOG"
if [ "$migration_status" -ne 0 ]; then
  echo "Datenbankmigration fehlgeschlagen. Die laufende App wurde nicht veraendert." >&2
  restart_containers_stopped_for_pg_upgrade
  end_deploy_maintenance aborted || true
  [ ! -f "$BACKUP_FILE" ] || echo "Backup dieses Laufs: $BACKUP_FILE" >&2
  echo "Meldet die Migration 0078 Konten mit mehreren Mandanten oder ohne Mandant:" >&2
  echo "entweder bereinigen oder HOCX_SINGLE_TENANT_RESOLUTION=auto in .env setzen und erneut deployen." >&2
  exit 1
fi

echo "==> [$ENVIRONMENT] Deploy"
if ! "${DC[@]}" up -d --pull never; then
  rollback_apps || true
  exit 1
fi

if ! write_admin_gate_traefik_config; then
  rollback_apps || true
  exit 1
fi

if ! sync_traefik_static_config; then
  echo "Traefik konnte mit der neuen Konfiguration nicht gestartet werden; manueller Eingriff erforderlich." >&2
  exit 1
fi

if ! run_smoke_checks; then
  rollback_apps || true
  exit 1
fi

# Vor den Prüfungen über Traefik: während voller Wartung sperrt die Abgabebox auch die
# Prüfseite (POST /api/public/verify) - die Prüfung würde scheitern und ein Rollback auslösen.
# Scheitern die Prüfungen danach, rollt rollback_apps zurück (die Wartung ist dann schon beendet).
# Lässt sich die Wartung nicht beenden, scheiterten die Prüfungen nur an ihr - kein Rollback
# eines guten Releases, sondern Abbruch mit klarer Anleitung (das neue Release läuft weiter).
if ! end_deploy_maintenance success; then
  echo "Deploy angehalten: $HOCX_VERSION läuft und hat die Smoke-Checks bestanden, aber der Wartungsmodus" >&2
  echo "des Updates ist noch aktiv (siehe oben). Kein Rollback. Nach dem manuellen Beenden:" >&2
  echo "  ./scripts/verify_release.sh $ENVIRONMENT  und danach ./scripts/deploy.sh $ENVIRONMENT erneut (setzt das Rollback-Ziel)." >&2
  exit 1
fi

# Von aussen über Traefik: jeder Router muss seinen Dienst erreichen (falsches Docker-Netz,
# fehlende Middleware, Zertifikat). Die Smoke-Checks oben laufen in den Containern und sehen das
# nicht - 1.4.0 ging so mit einer per 504 ausgefallenen Abgabebox-API live.
echo "==> [$ENVIRONMENT] Prüfung über Traefik"
if ! traefik_route_checks; then
  if [ -f "$PROJECT_DIR/.releases/current.env" ]; then
    echo "    Mindestens ein Dienst ist über Traefik nicht erreichbar - Rollback." >&2
    rollback_apps || true
    exit 1
  fi
  # Erste Installation: kein Release zum Zurückgehen; oft fehlt nur noch das Zertifikat (DNS,
  # Let's Encrypt). Nicht alles stoppen, sondern deutlich warnen.
  echo "    WARNUNG: Erste Installation, nicht alle Dienste über Traefik erreichbar (Zertifikat/DNS prüfen," >&2
  echo "    danach ./scripts/verify_release.sh $ENVIRONMENT)." >&2
fi

# Ab hier ist das neue Release das Rollback-Ziel: Folgeschritte (Storage-Controller, Cron,
# Demo-Seed) ändern daran nichts mehr. Bisher stand das erst am Ende, ein Fehler dazwischen
# liess current.env auf dem alten Release stehen.
install -m 600 "$PROJECT_DIR/.releases/${HOCX_VERSION}.env" "$PROJECT_DIR/.releases/current.env"
# Erst jetzt (Release läuft und ist über Traefik geprüft): bekannte, im Release enthaltene Hotfixes
# aus docker-compose.local.yml wegräumen. Vorher brauchte sie ein Rollback auf das alte Release.
retire_local_compose_hotfixes "$PROJECT_DIR" || true

# Lokales S3 in den Sollzustand bringen (z. B. nach einem Wechsel zu externem S3 wieder stoppen,
# das `up -d` oben hat es gestartet). Stoppt nur, löscht nie Daten.
controller_files=()
for ((index = 0; index < ${#COMPOSE_ARGS[@]}; index++)); do
  [ "${COMPOSE_ARGS[$index]}" = "-f" ] && controller_files+=("${COMPOSE_ARGS[$((index + 1))]}")
done
HOCX_COMPOSE_PROJECT="$PROJECT_NAME" HOCX_COMPOSE_FILES="${controller_files[*]}" HOCX_ENV_FILE="$ENV_FILE" \
  "$PROJECT_DIR/scripts/storage_controller.sh" || echo "    WARNUNG: Storage-Controller meldete einen Fehler (siehe oben)"
if service_exists local-s3; then
  install_managed_cron storage_controller '*/5 * * * *' \
    "$PROJECT_DIR/scripts/run_job.sh storage_controller env HOCX_COMPOSE_PROJECT=$PROJECT_NAME HOCX_COMPOSE_FILES=\"${controller_files[*]}\" HOCX_ENV_FILE=$ENV_FILE $PROJECT_DIR/scripts/storage_controller.sh >> $PROJECT_DIR/backups/storage_controller.log 2>&1" \
    || echo "    WARNUNG: Cron-Eintrag storage_controller nicht eingerichtet (siehe oben)"
fi

if [ "$ENVIRONMENT" = test ]; then
  echo "==> [$ENVIRONMENT] Demo-Mandant neu befuellen"
  "${DC[@]}" exec -T backend python scripts/seed_test_tenant.py ||
    echo "    WARNUNG: Demo-Mandant konnte nicht neu befuellt werden (siehe oben); das Release laeuft."
fi

# Alte App-Images aufräumen (erst jetzt: das neue Release läuft, current.env zeigt darauf).
# HOCX_IMAGE_KEEP_RELEASES (Default 3) weitere Releases bleiben für ein manuelles Zurückgehen;
# HOCX_IMAGE_CLEANUP=0 schaltet die Bereinigung ab. Ein Fehler hier bricht das Update nicht ab.
if [ "${HOCX_IMAGE_CLEANUP:-1}" != 0 ]; then
  echo "==> [$ENVIRONMENT] Alte Images aufräumen"
  cleanup_old_release_images "$PROJECT_DIR" "$GHCR_NAMESPACE" "${HOCX_IMAGE_KEEP_RELEASES:-3}" ||
    echo "    WARNUNG: Image-Bereinigung fehlgeschlagen (siehe oben); das Release läuft."
fi

echo "==> [$ENVIRONMENT] Fertig: laeuft jetzt auf $HOCX_VERSION"
if [ "$RESTORE_MODE" = 1 ]; then
  restore_finish
fi
