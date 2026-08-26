#!/usr/bin/env bash

# Load a dotenv file as data. Deliberately does not use `source`: a server-side
# .env must never become executable shell code during a privileged deploy.
is_allowed_env_key() {
  case "$1" in
    ABGABEBOX_BASE_URL|ABGABEBOX_CAPTCHA_SESSION_SECRET|ABGABEBOX_CAPTCHA_SESSION_TTL_MINUTES|\
    ABGABEBOX_DATABASE_URL|ABGABEBOX_DB_PASSWORD|ABGABEBOX_QUARANTINE_CLEANUP_INTERVAL_MINUTES|\
    ABGABEBOX_QUARANTINE_MAX_AGE_MINUTES|ABGABEBOX_RESCAN_INTERVAL_MINUTES|\
    ABGABEBOX_TENANT_STORAGE_QUOTA_MB|ACME_EMAIL|ADMIN_AUTH_SECRET|ADMIN_SESSION_COOKIE|\
    ADMIN_SESSION_TTL_HOURS|AUTH_SECRET|AUTH_SECURE_COOKIES|AUTH_SESSION_COOKIE|\
    AUTH_SESSION_TTL_HOURS|CF_DNS_API_TOKEN|CLAMAV_PORT|DATABASE_URL|DEFAULT_TENANT_SLUG|\
    DOMAIN_HEALTH_CHECK_INTERVAL_MINUTES|EXPORT_CLEANUP_INTERVAL_MINUTES|EXPORT_RETENTION_DAYS|\
    FRIENDLY_CAPTCHA_API_KEY|FRIENDLY_CAPTCHA_SITEKEY|FRIENDLY_CAPTCHA_VERIFY_URL|\
    GHCR_NAMESPACE|HOCX_ABGABEBOX_BACKEND_IMAGE|HOCX_ABGABEBOX_FRONTEND_IMAGE|\
    HOCX_APP_URL|HOCX_BACKEND_IMAGE|HOCX_DOCS_IMAGE|HOCX_FRONTEND_IMAGE|\
    HOCX_MIN_FREE_KB|HOCX_SIGNING_IDENTITY_REGEXP|HOCX_STORAGE_PATH|HOCX_VERSION|\
    INITIAL_ADMIN_EMAIL|INITIAL_ADMIN_PASSWORD|INTERNAL_API_URL|NEXT_PUBLIC_API_URL|\
    OFFSITE_BACKUP_REMOTE|POSTGRES_DB|POSTGRES_PASSWORD|POSTGRES_PORT|POSTGRES_USER|\
    PROTOCOL_IMAGE_STORAGE_QUOTA_MB|ROUTER_PREFIX|TRAEFIK_ABGABEBOX_DOMAIN|\
    TRAEFIK_ADMIN_DOMAIN|TRAEFIK_ADMIN_PORT|TRAEFIK_DOCS_DOMAIN|TRAEFIK_DOMAIN|\
    TRAEFIK_WEB_DOMAIN|WORD_IMPORT_RESCAN_INTERVAL_MINUTES)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
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

    if ! is_allowed_env_key "$key"; then
      echo "Nicht erlaubte Variable $key in $env_file." >&2
      return 1
    fi

    if [[ "$value" == "'"*"'" && ${#value} -ge 2 ]]; then
      value="${value:1:${#value}-2}"
    elif [[ "$value" == '"'*'"' && ${#value} -ge 2 ]]; then
      value="${value:1:${#value}-2}"
      value="${value//\\n/$'\n'}"
      value="${value//\\r/$'\r'}"
      value="${value//\\t/$'\t'}"
      value="${value//\\\"/\"}"
      value="${value//\\\\/\\}"
    fi

    printf -v "$key" '%s' "$value"
    export "$key"
  done < "$env_file"
}
