#!/usr/bin/env bash

# Load a dotenv file as data. Deliberately does not use `source`: a server-side
# .env must never become executable shell code during a privileged deploy.
read_host_environment() {
  local marker="${1:-/etc/hocx/environment}"
  local owner_uid mode environment

  if [ ! -f "$marker" ] || [ -L "$marker" ]; then
    echo "Host ist nicht sicher als hocX-Umgebung provisioniert: $marker fehlt oder ist ein Symlink." >&2
    return 1
  fi
  owner_uid="$(stat -c '%u' "$marker")"
  if [ "$marker" = /etc/hocx/environment ]; then
    [ "$owner_uid" = 0 ] || {
      echo "$marker muss root gehoeren." >&2
      return 1
    }
  elif [ "$owner_uid" != "$EUID" ] && [ "$owner_uid" != 0 ]; then
    echo "Unsicherer Eigentuemer der Environment-Markierung $marker." >&2
    return 1
  fi
  mode="$(stat -c '%a' "$marker")"
  if (( (8#$mode & 022) != 0 )); then
    echo "$marker darf nicht gruppen- oder weltbeschreibbar sein (aktuell: $mode)." >&2
    return 1
  fi
  IFS= read -r environment < "$marker" || true
  case "$environment" in
    prod|test)
      printf '%s\n' "$environment"
      ;;
    *)
      echo "Ungueltige hocX-Umgebung in $marker: $environment" >&2
      return 1
      ;;
  esac
}

require_host_environment() {
  local expected="$1"
  local marker="${2:-/etc/hocx/environment}"
  local actual
  actual="$(read_host_environment "$marker")" || return 1
  if [ "$actual" != "$expected" ]; then
    echo "Dieser Host ist dauerhaft als '$actual' provisioniert." >&2
    echo "Die angeforderte Umgebung '$expected' wurde blockiert." >&2
    return 1
  fi
}

# Host-Marker und deploy.sh-Argument heissen prod/test, die Anwendung (HOCX_ENVIRONMENT, siehe
# backend/app/core/config.py::is_production) kennt production/test. Bis zum Audit MAIN-OPS-001
# schrieb deploy.sh den Host-Namen 'prod' in die .env, wodurch das Backend sich auf Prod nicht als
# Produktion sah (/docs offen, Demo-Daten-Sperre aus). Gibt den kanonischen Anwendungswert aus;
# 'prod' wird als Alias fuer bestehende Hosts weiter akzeptiert.
app_environment_for() {
  case "${1,,}" in
    prod|production) printf 'production\n' ;;
    test) printf 'test\n' ;;
    *) printf '%s\n' "$1" ;;
  esac
}

require_unprovisioned_dev_host() {
  local marker="${1:-/etc/hocx/environment}"
  local actual
  if [ ! -e "$marker" ]; then
    return 0
  fi
  actual="$(read_host_environment "$marker")" || return 1
  echo "Der Dev-Stack ist auf einem als '$actual' provisionierten Server gesperrt." >&2
  return 1
}

# Variablen, die frueher in der .env standen und heute nicht mehr existieren. Ein Server, der
# von einem aelteren Release aktualisiert wird, hat sie noch in seiner .env - load_env_file
# ueberspringt sie statt abzubrechen, und scripts/lib/env_migrate.sh entfernt sie aus der
# Datei. Neue Eintraege hier UND in scripts/tests/test_env_migrate.sh beruecksichtigen.
#   TRAEFIK_WEB_DOMAIN: Marketing-Website, mit 1.1.0 entfernt.
ENV_RETIRED_KEYS=(TRAEFIK_WEB_DOMAIN)

is_retired_env_key() {
  local key
  for key in "${ENV_RETIRED_KEYS[@]}"; do
    [ "$key" = "$1" ] && return 0
  done
  return 1
}

is_allowed_env_key() {
  case "$1" in
    ABGABEBOX_BASE_URL|ABGABEBOX_CAPTCHA_SESSION_SECRET|ABGABEBOX_CAPTCHA_SESSION_TTL_MINUTES|\
    ABGABEBOX_DATABASE_URL|ABGABEBOX_DB_PASSWORD|ABGABEBOX_ENVIRONMENT|ABGABEBOX_QUARANTINE_CLEANUP_INTERVAL_MINUTES|\
    ABGABEBOX_QUARANTINE_MAX_AGE_MINUTES|ABGABEBOX_RESCAN_INTERVAL_MINUTES|\
    ABGABEBOX_TENANT_STORAGE_QUOTA_MB|ACME_EMAIL|ADMIN_AUTH_SECRET|ADMIN_SESSION_COOKIE|\
    ADMIN_SESSION_TTL_HOURS|APP_DATABASE_URL|APP_DB_PASSWORD|AUTH_SECRET|AUTH_SECURE_COOKIES|\
    AUTH_SESSION_COOKIE|\
    AUTH_SESSION_TTL_HOURS|CF_DNS_API_TOKEN|CLAMAV_PORT|DATABASE_URL|DEFAULT_TENANT_SLUG|\
    DEMO_TOTP_SEED|DOMAIN_HEALTH_CHECK_INTERVAL_MINUTES|EXPORT_CLEANUP_INTERVAL_MINUTES|\
    EXPORT_RETENTION_DAYS|\
    FRIENDLY_CAPTCHA_API_KEY|FRIENDLY_CAPTCHA_SITEKEY|FRIENDLY_CAPTCHA_VERIFY_URL|\
    GHCR_NAMESPACE|HOCX_ABGABEBOX_BACKEND_IMAGE|HOCX_ABGABEBOX_FRONTEND_IMAGE|\
    HOCX_APP_URL|HOCX_BACKEND_IMAGE|HOCX_COMPOSE_PROJECT|HOCX_DOCS_IMAGE|HOCX_ENVIRONMENT|HOCX_FRONTEND_IMAGE|\
    HOCX_MIN_FREE_KB|HOCX_PHOTO_ANALYSIS_WORKER_IMAGE|HOCX_SIGNING_IDENTITY_REGEXP|\
    HOCX_SINGLE_TENANT_RESOLUTION|HOCX_STORAGE_PATH|\
    HOCX_VERSION|\
    INITIAL_ADMIN_EMAIL|INITIAL_ADMIN_PASSWORD|INTERNAL_API_URL|NEXT_PUBLIC_API_URL|\
    OFFSITE_BACKUP_REMOTE|PHOTO_ANALYSIS_AUTO_QUEUE_END_HOUR|\
    PHOTO_ANALYSIS_AUTO_QUEUE_INTERVAL_MINUTES|PHOTO_ANALYSIS_AUTO_QUEUE_MAX_LOAD_FACTOR|\
    PHOTO_ANALYSIS_AUTO_QUEUE_START_HOUR|PHOTO_WORKER_DATABASE_URL|PHOTO_WORKER_DB_PASSWORD|\
    POSTGRES_DB|\
    POSTGRES_PASSWORD|POSTGRES_PORT|POSTGRES_USER|\
    PROTOCOL_IMAGE_STORAGE_QUOTA_MB|ROUTER_PREFIX|TRAEFIK_ABGABEBOX_DOMAIN|\
    TRAEFIK_ADMIN_DOMAIN|TRAEFIK_ADMIN_PORT|TRAEFIK_CERTRESOLVER|TRAEFIK_DOCS_DOMAIN|\
    TRAEFIK_DOMAIN|TRAEFIK_WEBSECURE_BIND|TRAEFIK_WEB_BIND|TRAEFIK_WEBSITE_DOMAIN|\
    WEBSITE_CONTACT_EMAIL|WORD_IMPORT_RESCAN_INTERVAL_MINUTES)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

# Ersetzt \n, \r, \t, \" und \\ in einem Durchgang. Die fruehere Kette einzelner Ersetzungen
# machte aus einem literalen Backslash vor n (in der Datei \\n) einen Zeilenumbruch.
# Ergebnis in REPLY (keine Command-Substitution, die abschliessende Zeilenumbrueche verschluckt).
unescape_double_quoted() {
  local input="$1" output="" char next i=0
  while [ "$i" -lt "${#input}" ]; do
    char="${input:i:1}"
    if [ "$char" = "\\" ] && [ $((i + 1)) -lt "${#input}" ]; then
      next="${input:i+1:1}"
      case "$next" in
        n) output+=$'\n' ;;
        r) output+=$'\r' ;;
        t) output+=$'\t' ;;
        '"') output+='"' ;;
        "\\") output+="\\" ;;
        *) output+="$char$next" ;;
      esac
      i=$((i + 2))
      continue
    fi
    output+="$char"
    i=$((i + 1))
  done
  REPLY="$output"
}

# Ergebnis in REPLY: Wert ohne Inline-Kommentar (Leerraum + '#') und ohne Leerraum an den Raendern.
strip_unquoted_comment() {
  local value="$1" i seen_text=false
  # Erstes '#' mit Leerraum davor und Text davor beginnt den Kommentar (wie Compose).
  for ((i = 0; i < ${#value}; i++)); do
    case "${value:i:1}" in
      [[:space:]]) ;;
      "#")
        if [ "$seen_text" = true ] && [ "$i" -gt 0 ] && [[ "${value:i-1:1}" == [[:space:]] ]]; then
          value="${value:0:i}"
          break
        fi
        seen_text=true
        ;;
      *) seen_text=true ;;
    esac
  done
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  REPLY="$value"
}

load_env_file() {
  local env_file="$1"
  local line key value mode owner_uid

  if [ ! -f "$env_file" ] || [ -L "$env_file" ]; then
    echo "Env-Datei $env_file muss eine regulaere Datei und darf kein Symlink sein." >&2
    return 1
  fi

  owner_uid="$(stat -c '%u' "$env_file")"
  if [ "$owner_uid" != "$EUID" ] && [ "$owner_uid" != 0 ]; then
    echo "Unsicherer Eigentuemer von $env_file (UID $owner_uid; erwartet $EUID oder root)." >&2
    return 1
  fi

  mode="$(stat -c '%a' "$env_file")"
  if (( (8#$mode & 077) != 0 )); then
    echo "Unsichere Dateirechte fuer $env_file: $mode (erwartet 600 oder restriktiver)." >&2
    return 1
  fi

  while IFS= read -r line || [ -n "$line" ]; do
    line="${line%$'\r'}"
    [[ "$line" =~ ^[[:space:]]*$ || "$line" =~ ^[[:space:]]*# ]] && continue
    line="${line#export }"

    if [[ ! "$line" =~ ^([A-Za-z_][A-Za-z0-9_]*)=(.*)$ ]]; then
      echo "Ungueltige Zeile in $env_file (erwartet KEY=VALUE)." >&2
      return 1
    fi
    key="${BASH_REMATCH[1]}"
    value="${BASH_REMATCH[2]}"

    if is_retired_env_key "$key"; then
      continue
    fi
    if ! is_allowed_env_key "$key"; then
      echo "Nicht erlaubte Variable $key in $env_file." >&2
      return 1
    fi

    if [[ "$value" == "'"*"'" && ${#value} -ge 2 ]]; then
      value="${value:1:${#value}-2}"
    elif [[ "$value" == '"'*'"' && ${#value} -ge 2 ]]; then
      unescape_double_quoted "${value:1:${#value}-2}"
      value="$REPLY"
    else
      # Wie der dotenv-Parser von Compose (Audit MAIN-OPS-015): bei unquotierten Werten beginnt
      # mit Leerraum + '#' ein Kommentar, abschliessender Leerraum zaehlt nicht. Sonst sahen
      # deploy.sh (Secret-Dateien) und Compose (Interpolation) unterschiedliche Werte.
      strip_unquoted_comment "$value"
      value="$REPLY"
    fi

    printf -v "$key" '%s' "$value"
    export "$key"
  done < "$env_file"
}
