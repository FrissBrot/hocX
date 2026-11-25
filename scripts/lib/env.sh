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

# Prod nimmt nur Release-Tags (Format wie in release.yml), nie einen test-*-Candidate-Tag.
require_release_version_for() {
  local environment="$1" version="$2"
  if [ "$environment" = prod ] && [[ ! "$version" =~ ^v?[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "Auf Prod sind nur Release-Tags erlaubt (z. B. v1.2.3), nicht: $version" >&2
    echo "Kandidaten zuerst auf Test verifizieren und per release.yml promoten (RUNBOOK Abschnitt 3)." >&2
    return 1
  fi
}

# Ein Test-Candidate (test-<datum>-<sha>-r<n>) wurde aus einem bestimmten main-Commit gebaut;
# Compose-Dateien und Skripte dieses Checkouts muessen mindestens so neu sein. Sonst laeuft das
# neue Image mit altem Stack (fehlende Dienste, Secrets, .env-Migration) - genau so blieb ein
# Test-Host nach dem Update auf 1.2.0 ohne lokales S3 und STORAGE_CREDENTIALS_KEY.
require_deploy_code_for_version() {
  local repo_dir="$1" version="$2" commit
  [[ "$version" =~ ^test-[0-9]{8}-([0-9a-f]{7,40})-r[0-9]+$ ]] || return 0
  commit="${BASH_REMATCH[1]}"
  if ! git -C "$repo_dir" rev-parse --git-dir > /dev/null 2>&1; then
    echo "WARNUNG: kein Git-Checkout - Deploy-Code-Stand fuer $version nicht pruefbar." >&2
    return 0
  fi
  if git -C "$repo_dir" cat-file -e "$commit^{commit}" 2> /dev/null \
    && git -C "$repo_dir" merge-base --is-ancestor "$commit" HEAD; then
    return 0
  fi
  echo "Deploy-Code ($(git -C "$repo_dir" rev-parse --short HEAD)) ist aelter als der Candidate $version." >&2
  echo "Zuerst den Deploy-Code aktualisieren: ./scripts/update_deploy_code.sh --deploy" >&2
  return 1
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

# Optionale, nicht versionierte Compose-Datei fuer host-spezifische Anpassungen (eigene
# Zertifikate, abweichende Port-Bindungen, ...). deploy.sh, verify_release.sh und die
# Hilfsskripte laden sie zuletzt, wenn sie existiert. So bleibt der versionierte Checkout
# unveraendert und update_deploy_code.sh blockiert nicht an lokalen Aenderungen.
HOCX_LOCAL_COMPOSE_FILE=docker-compose.local.yml

# Haengt "-f <repo>/docker-compose.local.yml" an das Array mit dem Namen $2 an, falls die Datei
# existiert. Symlinks werden abgelehnt (gleiche Regel wie fuer .env).
append_local_compose_override() {
  local repo_dir="$1"
  local -n target_args="$2"
  local file="$repo_dir/$HOCX_LOCAL_COMPOSE_FILE"
  if [ -L "$file" ]; then
    echo "$file darf kein Symlink sein." >&2
    return 1
  fi
  [ -f "$file" ] || return 0
  # Bekannte Hotfixes bleiben bis zum erfolgreichen Update geladen (sie sind mit dem neuen Release
  # gleichwertig): ein Rollback auf das alte Release braucht sie noch. deploy.sh räumt sie erst
  # nach den Prüfungen über Traefik weg (retire_local_compose_hotfixes).
  # Ausnahme ab 1.4.3 (Admin-Abschottung): Traefik hängt nur noch im Netz edge. Der 1.4.0-Hotfix
  # (abgabebox-backend über hocx_default) würde die Abgabebox dann unerreichbar machen (504, Rollback
  # bei jedem Update) - er wird nicht geladen, sobald das Release ein anderes Netz selbst setzt. Ein
  # Rollback geht auf current.env (ab 1.4.1), die die Korrektur selbst enthält.
  if _is_known_local_hotfix "$file" && [ "$(_release_abgabebox_network "$repo_dir")" = "edge" ]; then
    echo "    Hinweis: $HOCX_LOCAL_COMPOSE_FILE (bekannter Hotfix traefik.docker.network=hocx_default) wird nicht geladen - das Release setzt das Netz edge selbst; die Datei wird nach dem Update entfernt." >&2
    return 0
  fi
  target_args+=(-f "$file")
}

# Netz, das docker-compose.release.yml für abgabebox-backend an Traefik meldet (default, edge oder leer).
_release_abgabebox_network() {
  local block
  block="$(awk '/^  abgabebox-backend:/{f=1;next} /^  [a-z0-9-]+:/{f=0} f' "$1/docker-compose.release.yml" 2> /dev/null || true)"
  # shellcheck disable=SC2016 # Literal aus der Compose-Datei, keine Shell-Variable
  case "$block" in
    *'traefik.docker.network=${COMPOSE_PROJECT_NAME}_edge'*) echo edge ;;
    *'traefik.docker.network=${COMPOSE_PROJECT_NAME}_default'*) echo default ;;
  esac
}

# Datei besteht genau aus einem bekannten Hotfix (ohne Leerraum verglichen)?
_is_known_local_hotfix() {
  local normalized hotfix
  normalized="$(tr -d '[:space:]' < "$1")"
  for hotfix in "${HOCX_KNOWN_LOCAL_HOTFIXES[@]}"; do
    [ "$normalized" = "$hotfix" ] && return 0
  done
  return 1
}

# Bekannte Hotfixes in docker-compose.local.yml, die ein späteres Release selbst enthält: liegt
# genau ein solcher Hotfix vor und bringt der versionierte Stand die Korrektur schon mit, wird die
# Datei nach backups/ verschoben (Rückgabe 1 = verschoben). Steht mehr in der Datei, bleibt sie
# unverändert, es gibt nur einen Hinweis. Nur deploy.sh ruft das auf, und erst nach einem
# erfolgreichen Update - sonst fehlte der Hotfix einem Rollback auf das alte Release.
#   1.4.0 → 1.4.1: traefik.docker.network für abgabebox-backend (504 auf Prüfseite/Abgabebox)
HOCX_KNOWN_LOCAL_HOTFIXES=(
  'services:abgabebox-backend:labels:-"traefik.docker.network=hocx_default"'
)
retire_local_compose_hotfixes() {
  local repo_dir="$1" file="$1/$HOCX_LOCAL_COMPOSE_FILE" normalized hotfix target
  [ -f "$file" ] && [ ! -L "$file" ] || return 0
  grep -q 'abgabebox-backend' "$file" 2> /dev/null || return 0
  # Nur wenn das Release die Korrektur selbst mitbringt
  # (im Block des Dienstes abgabebox-backend - das Backend trägt dasselbe Label schon länger)
  # Erst den Block lesen, dann suchen: «awk | grep -q» scheiterte unter pipefail sporadisch, wenn
  # grep -q früh beendete und awk dabei SIGPIPE bekam (CI).
  # (ab 1.4.1 _default, ab 1.4.3 _edge - beides heisst: das Release setzt das Netz selbst)
  [ -n "$(_release_abgabebox_network "$repo_dir")" ] || return 0
  normalized="$(tr -d '[:space:]' < "$file")"
  for hotfix in "${HOCX_KNOWN_LOCAL_HOTFIXES[@]}"; do
    if [ "$normalized" = "$hotfix" ]; then
      mkdir -p "$repo_dir/backups"
      target="$repo_dir/backups/docker-compose.local.yml.hotfix-$(date +%Y%m%d%H%M%S)"
      mv "$file" "$target"
      echo "    Hotfix aus $HOCX_LOCAL_COMPOSE_FILE ist im Release enthalten - Datei entfernt (Kopie: $target)." >&2
      return 1
    fi
  done
  if grep -q 'traefik.docker.network' "$file"; then
    echo "    Hinweis: $HOCX_LOCAL_COMPOSE_FILE setzt traefik.docker.network - seit 1.4.1 im Release enthalten, der Eintrag kann weg." >&2
  fi
  return 0
}

# Laufzeitverzeichnisse, die bewusst anderen Besitzern gehoeren (Container-Nutzer 5000/5001,
# root fuer Traefiks ACME-Dateien) und deshalb bei der Besitzpruefung ausgelassen werden.
REPO_RUNTIME_PATHS=(storage storage-local backups infra/traefik/letsencrypt infra/traefik/dynamic .env)

# Bricht ab, wenn Dateien im Checkout (inkl. .git) nicht dem aufrufenden Benutzer gehoeren.
# Typische Ursache: ein frueheres `git pull` oder Kopieren als root. Ohne diese Pruefung bricht
# ein Update mitten im Checkout ab und hinterlaesst einen halb aktualisierten Stand.
require_repo_owned_by_current_user() {
  local repo_dir="$1"
  local -a prune=()
  local path offenders user group
  for path in "${REPO_RUNTIME_PATHS[@]}"; do
    prune+=(-path "$repo_dir/$path" -o)
  done
  unset 'prune[${#prune[@]}-1]'
  offenders="$(find "$repo_dir" -xdev \( "${prune[@]}" \) -prune -o ! -user "$EUID" -print 2> /dev/null | head -n 11)"
  [ -n "$offenders" ] || return 0
  user="$(id -un)"
  group="$(id -gn)"
  echo "Im Checkout gehoeren Dateien nicht $user (Auszug):" >&2
  printf '%s\n' "$offenders" | head -n 10 | sed 's/^/  /' >&2
  echo "Einmalig als root korrigieren (Laufzeitverzeichnisse bleiben unberuehrt):" >&2
  printf '  find %q -xdev \\(' "$repo_dir" >&2
  for path in "${REPO_RUNTIME_PATHS[@]}"; do
    [ "$path" = "${REPO_RUNTIME_PATHS[0]}" ] || printf ' -o' >&2
    printf ' -path %q' "$repo_dir/$path" >&2
  done
  printf ' \\) -prune -o ! -user %q -exec chown %q {} +\n' "$user" "$user:$group" >&2
  return 1
}

# Variablen, die frueher in der .env standen und heute nicht mehr existieren. Ein Server, der
# von einem aelteren Release aktualisiert wird, hat sie noch in seiner .env - load_env_file
# ueberspringt sie statt abzubrechen, und scripts/lib/env_migrate.sh entfernt sie aus der
# Datei. Neue Eintraege hier UND in scripts/tests/test_env_migrate.sh beruecksichtigen.
#   TRAEFIK_WEB_DOMAIN: Marketing-Website, mit 1.1.0 entfernt.
# DOCUMENT_SIGNING_*: Dokumentsignatur entfällt (Hash-Prüfung über die Abgabebox); alte .env
# mit diesen Schlüsseln laden weiter, die Werte werden ignoriert.
# BACKUP_TRUST_FILESYSTEM_REGISTRY: nur noch S3 (0168), das Dateisystem-Register gibt es nicht mehr.
ENV_RETIRED_KEYS=(TRAEFIK_WEB_DOMAIN DOCUMENT_SIGNING_CHAIN_PATH DOCUMENT_SIGNING_DIR DOCUMENT_SIGNING_KEY_PASSWORD DOCUMENT_SIGNING_TSA_URL
  BACKUP_TRUST_FILESYSTEM_REGISTRY)

is_retired_env_key() {
  local key
  for key in "${ENV_RETIRED_KEYS[@]}"; do
    [ "$key" = "$1" ] && return 0
  done
  return 1
}

is_allowed_env_key() {
  case "$1" in
    ABGABEBOX_BASE_URL|ABGABEBOX_CAPTCHA_SESSION_SECRET|ABGABEBOX_DEFAULT_PRIVACY_URL|ABGABEBOX_CAPTCHA_SESSION_TTL_MINUTES|\
    ABGABEBOX_DATABASE_URL|ABGABEBOX_DB_PASSWORD|ABGABEBOX_ENVIRONMENT|ABGABEBOX_QUARANTINE_CLEANUP_INTERVAL_MINUTES|\
    ABGABEBOX_QUARANTINE_MAX_AGE_MINUTES|ABGABEBOX_RESCAN_INTERVAL_MINUTES|\
    ABGABEBOX_TENANT_STORAGE_QUOTA_MB|ACME_EMAIL|ADMIN_AUTH_SECRET|ADMIN_GATE_SECRET|ADMIN_SESSION_COOKIE|\
    ABGABEBOX_UPLOAD_CONCURRENCY|ABGABEBOX_UPLOAD_SLOT_WAIT_SECONDS|GALLERY_UPLOAD_CONCURRENCY|GALLERY_UPLOAD_SLOT_WAIT_SECONDS|\
    CLOUD_IMPORT_MAX_JOB_FILES|CLOUD_IMPORT_MAX_JOB_BYTES|CLOUD_IMPORT_ENABLED|CLOUD_IMPORT_TOKEN_KEY|CLOUD_IMPORT_TOKEN_KEY_PREVIOUS|\
    CLOUD_IMPORT_REDIRECT_BASE_URL|CLOUD_IMPORT_MS_CLIENT_ID|CLOUD_IMPORT_MS_CLIENT_SECRET|CLOUD_IMPORT_MS_CLIENT_SECRET_EXPIRES|\
    CLOUD_IMPORT_MS_AUTHORITY|CLOUD_IMPORT_MS_DOWNLOAD_MODE|\
    BACKUP_BATCH_MAX_BYTES|BACKUP_COMPRESSION|BACKUP_HEAVY_WINDOW_HOURS|BACKUP_DUMP_PUBLIC_KEY_PATH|BACKUP_ENABLED|BACKUP_KNOWN_HOSTS_PATH|BACKUP_PASSPHRASE|\
    BACKUP_REMOTE_PATH|BACKUP_REPOSITORY_ID|BACKUP_REPOSITORY_PATH|BACKUP_SSH_HOST_FINGERPRINT|BACKUP_SSH_KEY_PATH|\
    BACKUP_STAGING_MAX_BYTES|BACKUP_STORAGEBOX_HOST|BACKUP_STORAGEBOX_PORT|BACKUP_STORAGEBOX_QUOTA_BYTES|\
    BACKUP_STORAGEBOX_USER|BACKUP_UPLOAD_RATELIMIT_KIB|\
    HOCX_LEGACY_BACKUP_FORCE|HOCX_PRE_DEPLOY_BACKUP|HOCX_PRE_DEPLOY_BACKUP_ALLOW_PARTIAL|HOCX_PRE_DEPLOY_BACKUP_TIMEOUT|\
    ADMIN_SESSION_TTL_HOURS|APP_DATABASE_URL|APP_DB_PASSWORD|AUTH_SECRET|AUTH_SECRET_PREVIOUS|AUTH_SECURE_COOKIES|AUTH_LEGACY_COOKIE_UNTIL|AUTH_NET6_FACTOR|\
    PASSWORD_LEAK_CHECK|PASSWORD_LEAK_MIN_COUNT|PASSWORD_LEAK_FETCH_PER_MINUTE|PASSWORD_BREACH_RECHECK_DAYS|GEOIP_AUTO_UPDATE|GEO_PLACES_AUTO_UPDATE|\
    AUTH_RISK_MODE|AUTH_SESSION_IDLE_MINUTES|AUTH_SESSION_ABSOLUTE_HOURS|AUTH_EVENT_RETENTION_DAYS|AUTH_STEP_UP_MFA_MINUTES|AUTH_STEP_UP_ADMIN_MINUTES|AUTH_ACCOUNT_IP_FAILURES|AUTH_ACCOUNT_FAILURES_CHALLENGE|AUTH_ACCOUNT_FAILURES_KNOWN_ONLY|AUTH_IP_FAILURES_SOFT|AUTH_IP_FAILURES_HARD|AUTH_NET_FAILURES_SOFT|AUTH_NET_FAILURES_HARD_HOUR|AUTH_GLOBAL_ATTACK_MIN|AUTH_BLOCK_STRIKES|AUTH_BLOCK_MINUTES|AUTH_DEVICE_TTL_DAYS|\
    AUTH_SESSION_COOKIE|\
    AUTH_SESSION_TTL_HOURS|CF_DNS_API_TOKEN|CLAMAV_PORT|DATABASE_URL|DEFAULT_TENANT_SLUG|\
    DB_ADMISSION_RESERVE|DB_ADMISSION_WAIT_SECONDS|DB_MAX_OVERFLOW|DB_POOL_SIZE|DB_POOL_TIMEOUT_SECONDS|\
    DEMO_TOTP_SEED|DOCUMENT_VERIFY_BASE_URL|\
    DOMAIN_HEALTH_CHECK_INTERVAL_MINUTES|EXPORT_CLEANUP_INTERVAL_MINUTES|\
    EXPORT_ENCRYPTION_KEY|EXPORT_RETENTION_DAYS|\
    FRIENDLY_CAPTCHA_API_KEY|FRIENDLY_CAPTCHA_PUZZLE_URL|FRIENDLY_CAPTCHA_SITEKEY|FRIENDLY_CAPTCHA_VERIFY_URL|\
    GARAGE_ADMIN_TOKEN|GARAGE_CAPACITY|GARAGE_RPC_SECRET|GHCR_NAMESPACE|HOCX_ABGABEBOX_BACKEND_IMAGE|HOCX_ABGABEBOX_FRONTEND_IMAGE|\
    HOCX_ADMIN_SOURCE_CIDRS|HOCX_APP_URL|HOCX_BACKEND_IMAGE|HOCX_BACKEND_WORKERS|HOCX_COMPOSE_PROJECT|HOCX_DOCS_IMAGE|HOCX_ENVIRONMENT|HOCX_FRONTEND_IMAGE|\
    HOCX_MANAGE_CRON|HOCX_MIN_FREE_KB|HOCX_PHOTO_ANALYSIS_WORKER_IMAGE|HOCX_REQUIRE_DUMP_ENCRYPTION|HOCX_SIGNING_IDENTITY_REGEXP|\
    HOCX_SERVER_LOCATION|HOCX_SINGLE_TENANT_RESOLUTION|HOCX_STATUS_PAGE_URL|HOCX_STORAGE_PATH|\
    HOCX_VERIFY_CA_FILE|HOCX_VERIFY_TENANT_DOMAIN|HOCX_VERIFY_TENANT_DOMAIN_LIMIT|HOCX_VERSION|\
    INITIAL_ADMIN_EMAIL|INITIAL_ADMIN_PASSWORD|INTERNAL_API_URL|LOCAL_S3_ABGABEBOX_ACCESS_KEY|\
    LOCAL_S3_ABGABEBOX_SECRET_KEY|LOCAL_S3_ACCESS_KEY|LOCAL_S3_SECRET_KEY|STORAGE_ALLOWED_LOCATIONS|STORAGE_CREDENTIALS_KEY|STORAGE_FALLBACK_DAYS|NEXT_PUBLIC_API_URL|\
    SECURITY_ALERT_ADMIN_LOGINS|SECURITY_EXPORTS_PER_HOUR|SECURITY_FAILED_LOGINS_CRITICAL|\
    SECURITY_FAILED_LOGINS_PER_ACCOUNT|SECURITY_FAILED_LOGINS_WARNING|\
    OFFSITE_BACKUP_REMOTE|OVERLOAD_ACTIVE_MINUTES|OVERLOAD_THRESHOLD_LOW|OVERLOAD_THRESHOLD_NORMAL|PHOTO_ANALYSIS_AUTO_QUEUE_END_HOUR|\
    PHOTO_ANALYSIS_AUTO_QUEUE_INTERVAL_MINUTES|PHOTO_ANALYSIS_AUTO_QUEUE_MAX_LOAD_FACTOR|\
    PHOTO_ANALYSIS_AUTO_QUEUE_START_HOUR|PHOTO_WORKER_DATABASE_URL|PHOTO_WORKER_DB_PASSWORD|GEO_DATABASE_URL|GEO_DB_PASSWORD|\
    POSTGRES_DB|\
    POSTGRES_PASSWORD|POSTGRES_PORT|POSTGRES_USER|\
    PROTOCOL_IMAGE_STORAGE_QUOTA_MB|REDIS_PASSWORD|ROUTER_PREFIX|TRAEFIK_ABGABEBOX_DOMAIN|\
    TENANT_OFFBOARDING_GRACE_DAYS|TRAEFIK_ADMIN_DOMAIN|TRAEFIK_ADMIN_PORT|TRAEFIK_CERTRESOLVER|TRAEFIK_DOCS_DOMAIN|\
    TRAEFIK_DOMAIN|TRAEFIK_HOST_DYNAMIC_FILES|TRAEFIK_WEBSECURE_BIND|TRAEFIK_WEB_BIND|TRAEFIK_WEBSITE_DOMAIN|\
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
    # shellcheck disable=SC2163  # exportiert bewusst die Variable, deren Name in $key steht
    export "$key"
  done < "$env_file"
}
