# shellcheck shell=bash
# Prüfungen von aussen: jeder Traefik-Router wird über den echten Host-Namen (SNI, Zertifikat)
# angesprochen. Die Smoke-Checks in den Containern sehen nicht, ob Traefik einen Dienst erreicht
# - am 19.11.2026 antwortete die Abgabebox-API live mit 504 (Traefik wählte die IP im internen
# storage-Netz), während alle internen Prüfungen grün waren.
#
# Erwartet: TRAEFIK_DOMAIN, TRAEFIK_ABGABEBOX_DOMAIN; optional TRAEFIK_ADMIN_DOMAIN,
# TRAEFIK_DOCS_DOMAIN, TRAEFIK_WEBSITE_DOMAIN, TRAEFIK_WEBSECURE_BIND, HOCX_VERIFY_CA_FILE,
# HOCX_VERIFY_TENANT_DOMAIN(_LIMIT), optional die Funktion tenant_domains_for_checks und REPO_DIR (für einen relativen CA-Pfad und tenant-domains.yml).
# Benutzt von deploy.sh und verify_release.sh.

# curl-Argumente für eine URL: Host-Namen auf die Traefik-Bindung bzw. 127.0.0.1 auflösen, falls
# kein DNS (oder eine private Bindung), eigene Test-CA.
_traefik_curl_args() {
  local url="$1" host port bind ca
  host="${url#https://}"
  host="${host%%/*}"
  port=443
  if [[ "$host" == *:* ]]; then
    port="${host##*:}"
    host="${host%:*}"
  fi
  bind="${TRAEFIK_WEBSECURE_BIND:-0.0.0.0}"
  if [ "$port" != 443 ]; then
    # Admin-Entrypoint (adminsecure) ist nur an 127.0.0.1 gebunden (docker-compose.traefik.yml)
    printf '%s\n' --resolve "$host:$port:127.0.0.1"
  elif [ "$bind" != 0.0.0.0 ]; then
    printf '%s\n' --resolve "$host:443:$bind"
  elif ! getent hosts "$host" > /dev/null 2>&1; then
    printf '%s\n' --resolve "$host:443:127.0.0.1"
  fi
  ca="${HOCX_VERIFY_CA_FILE:-}"
  if [ -n "$ca" ]; then
    [[ "$ca" == /* ]] || ca="${REPO_DIR:-.}/$ca"
    printf '%s\n' --cacert "$ca"
  fi
}

# GET über Traefik; gibt die effektive URL (nach Redirects) aus. HTTP >= 400 und TLS-Fehler
# lassen den Check scheitern.
# Die Wartungsseite (Ausweich-Router, RUNBOOK Abschnitt 20) antwortet immer mit 503 und zählt so
# nie als erreichbar - --fail nicht entfernen (scripts/tests/test_maintenance_page.sh).
curl_via_traefik() {
  local url="$1"
  local -a extra
  mapfile -t extra < <(_traefik_curl_args "$url")
  curl --silent --show-error --fail --location --max-time 15 --output /dev/null --write-out '%{url_effective}' \
    "${extra[@]}" "$url"
}

probe_domain() {
  curl_via_traefik "$1" > /dev/null
}

# Landet die Website-Domain auf /login, erkennt das Frontend sie nicht als Website (z. B.
# TRAEFIK_WEBSITE_DOMAIN fehlt im Container) - der reine Statuscode wäre trotzdem 200.
probe_website_domain() {
  local effective path
  effective="$(curl_via_traefik "$1")" || return 1
  path="${effective#https://*/}"
  [[ "/$path" != /login* ]]
}

# POST mit JSON über Traefik; prüft, dass die Antwort den erwarteten Text enthält. HTTP >= 400
# scheitert; ein 503 mit Code "maintenance" (Wartungsmodus noch aktiv, z. B. ein nicht beendetes
# Deploy-Fenster) wird als solcher gemeldet statt als «nicht erreichbar».
probe_post_json() {
  local url="$1" body="$2" expected="$3" response status
  local -a extra
  mapfile -t extra < <(_traefik_curl_args "$url")
  response="$(curl --silent --show-error --max-time 15 -H 'Content-Type: application/json' \
    --data "$body" --write-out $'\n%{http_code}' "${extra[@]}" "$url")" || return 1
  status="${response##*$'\n'}"
  response="${response%$'\n'*}"
  if [ "$status" = 503 ] && [[ "$response" =~ \"code\":[[:space:]]*\"maintenance\" ]]; then
    echo "    Wartung noch aktiv (503 maintenance) - Wartungsfenster beenden: Adminportal -> System -> Wartung" >&2
    return 1
  fi
  if ! [[ "$status" =~ ^[0-9]{3}$ ]] || [ "$status" -ge 400 ]; then
    echo "    HTTP $status: ${response:0:200}" >&2
    return 1
  fi
  [[ "$response" == *"$expected"* ]] || { echo "    Unerwartete Antwort: ${response:0:200}" >&2; return 1; }
}

# Alle Router von aussen. Ein Aufruf je Router - Frontend und API einer Domain sind eigene
# Router (eigene Dienste), beide müssen erreichbar sein.
traefik_route_checks() {
  dynamic_config_files_check || return 1
  local zero_hash
  zero_hash="$(printf '0%.0s' {1..64})"
  _traefik_check "Hauptdomain: Frontend" probe_domain "https://${TRAEFIK_DOMAIN}/login" || return 1
  _traefik_check "Hauptdomain: Backend-API" probe_domain "https://${TRAEFIK_DOMAIN}/api/health" || return 1
  _traefik_check "Abgabebox: Frontend" probe_domain "https://${TRAEFIK_ABGABEBOX_DOMAIN}/" || return 1
  _traefik_check "Abgabebox: API (GET)" probe_domain "https://${TRAEFIK_ABGABEBOX_DOMAIN}/api/public/maintenance-status" || return 1
  _traefik_check "Abgabebox: Prüfseite (POST /api/public/verify)" \
    probe_post_json "https://${TRAEFIK_ABGABEBOX_DOMAIN}/api/public/verify" "{\"sha256\":\"$zero_hash\"}" '"found":false' || return 1
  if [ -n "${TRAEFIK_ADMIN_DOMAIN:-}" ]; then
    local admin="https://${TRAEFIK_ADMIN_DOMAIN}:${TRAEFIK_ADMIN_PORT:-8443}"
    _traefik_check "Admin: Frontend" probe_domain "$admin/admin/login" || return 1
    _traefik_check "Admin: API" probe_domain "$admin/api/admin/auth/health" || return 1
  fi
  admin_isolation_checks || return 1
  # Docs und Website sind keine Kernfunktion (oft eigene DNS/Zertifikate): ein Fehler dort ist
  # eine Warnung, kein Rollback - ein Rollback setzt nur die Images zurück, nicht die Datenbank.
  if [ -n "${TRAEFIK_DOCS_DOMAIN:-}" ]; then
    _traefik_check "Docs" probe_domain "https://${TRAEFIK_DOCS_DOMAIN}/" || echo "    WARNUNG: Docs über Traefik nicht erreichbar (kein Rollback)." >&2
  fi
  if [ -n "${TRAEFIK_WEBSITE_DOMAIN:-}" ]; then
    _traefik_check "Website (Landing Page)" probe_website_domain "https://${TRAEFIK_WEBSITE_DOMAIN}/" || echo "    WARNUNG: Website über Traefik nicht erreichbar (kein Rollback)." >&2
  fi
}

# Auth-Audit SEC-AUTH-001: Das Plattform-Admin-Panel (/admin, /api/admin) darf über den
# öffentlichen Entrypoint (websecure, Port 443) auf KEINER Domain erreichbar sein - weder auf der
# Haupt-, Abgabebox-, Docs- oder Website-Domain noch auf einer Mandanten-Domain oder der
# Admin-Domain selbst (die nur über adminsecure/OpenZiti bedient wird). Erwartet wird eine 4xx
# (der Sperr-Router in infra/traefik/dynamic/admin-isolation.yml antwortet mit 404).
#
# Immer direkt gegen die eigene Traefik-Bindung (--resolve), nie über DNS: eine Mandanten-Domain
# kann auf einen fremden Server zeigen. --insecure: geprüft wird nur der Statuscode, es wird
# nichts Geheimes gesendet, und eine Mandanten-Domain hat evtl. (noch) kein Zertifikat.
probe_admin_blocked() {
  local url="$1" method="${2:-GET}" host bind headers code
  host="${url#https://}"
  host="${host%%/*}"
  bind="${TRAEFIK_WEBSECURE_BIND:-0.0.0.0}"
  [ "$bind" != 0.0.0.0 ] || bind=127.0.0.1
  # --path-as-is: Pfad-Tricks (//api/admin, %61) unverändert senden
  headers="$(curl --silent --insecure --path-as-is --max-time 15 --output /dev/null --dump-header - -X "$method" \
    --resolve "$host:443:$bind" "$url")" || true
  code="$(awk 'NR == 1 {print $2}' <<< "$headers")"
  if [ "$code" = 404 ] && grep -qi '^x-hocx-admin-block: *1' <<< "$headers"; then
    return 0
  fi
  echo "    $method $url antwortet über den öffentlichen Entrypoint mit HTTP ${code:-?} ohne Sperr-Kennzeichen (erwartet: 404 + X-Hocx-Admin-Block)" >&2
  return 1
}

# Aktive Mandanten-Domains für die Prüfung (höchstens HOCX_VERIFY_TENANT_DOMAIN_LIMIT, Standard 20):
# HOCX_VERIFY_TENANT_DOMAIN (Komma-Liste) oder die Funktion tenant_domains_for_checks des Aufrufers
# (deploy.sh/verify_release.sh lesen tenant-domains.yml im Backend-Container), sonst die Datei, falls lesbar.
admin_check_tenant_domains() {
  local file="${REPO_DIR:-.}/infra/traefik/dynamic/tenant-domains.yml" limit="${HOCX_VERIFY_TENANT_DOMAIN_LIMIT:-20}"
  # shellcheck disable=SC2016  # literale Backticks der Traefik-Regel
  {
    if [ -n "${HOCX_VERIFY_TENANT_DOMAIN:-}" ]; then
      tr ',' '\n' <<< "$HOCX_VERIFY_TENANT_DOMAIN"
    elif declare -F tenant_domains_for_checks > /dev/null; then
      tenant_domains_for_checks || true
    elif [ -r "$file" ]; then
      cat "$file"
    fi
  } | grep -o 'Host(`[^`]*`)\|^[a-z0-9.-]*$' | sed -e 's/^Host(`//' -e 's/`)$//' | grep . | sort -u | head -n "$limit" || true
}

admin_isolation_checks() {
  local host path tenant
  local -a hosts=("$TRAEFIK_DOMAIN" "$TRAEFIK_ABGABEBOX_DOMAIN")
  [ -z "${TRAEFIK_ADMIN_DOMAIN:-}" ] || hosts+=("$TRAEFIK_ADMIN_DOMAIN")
  [ -z "${TRAEFIK_DOCS_DOMAIN:-}" ] || hosts+=("$TRAEFIK_DOCS_DOMAIN")
  [ -z "${TRAEFIK_WEBSITE_DOMAIN:-}" ] || hosts+=("$TRAEFIK_WEBSITE_DOMAIN")
  while IFS= read -r tenant; do
    [ -z "$tenant" ] || hosts+=("$tenant")
  done < <(admin_check_tenant_domains)
  for host in "${hosts[@]}"; do
    for path in /api/admin/auth/health /api/%61dmin/auth/health //api/admin/auth/health /admin/login /admin; do
      _traefik_negative_check "Admin gesperrt: $host$path" probe_admin_blocked "https://$host$path" || return 1
    done
    _traefik_negative_check "Admin gesperrt: POST $host/api/admin/auth/login" \
      probe_admin_blocked "https://$host/api/admin/auth/login" POST || return 1
  done
}

# Review L4: Das Backend darf im Traefik-Dateiprovider-Verzeichnis nur tenant-domains.yml schreiben.
# Ein eigenes Unterverzeichnis ginge nicht: Traefik lädt Unterverzeichnisse zwar, beobachtet sie aber
# nicht (live geprüft) - neue Mandanten-Domains würden erst nach einem Traefik-Neustart aktiv.
# Stattdessen: jede andere Konfigurationsdatei dort lässt Deploy und verify_release.sh scheitern.
# Erlaubt sind: alle im Repo versionierten Dateien des Verzeichnisses (git ls-files - so kann eine
# neue versionierte Datei wie maintenance.yml in 1.5.0 die Prüfung nicht mehr sprengen), die beiden
# generierten Dateien (tenant-domains.yml vom Backend, admin-gate.yml vom Deploy) und host-eigene
# Dateien, die der Betreiber in .env ausdrücklich nennt (TRAEFIK_HOST_DYNAMIC_FILES, Dateinamen mit
# Leerzeichen/Komma getrennt, z. B. test-ziti-tls.yml für das Zertifikat des Test-Hosts). Eine
# Host-Datei muss eine normale Datei sein (kein Symlink, kein Verzeichnis).
dynamic_config_allowed_names() {
  local repo="${REPO_DIR:-.}" name
  git -C "$repo" ls-files -- infra/traefik/dynamic | sed 's#.*/##' || return 1
  printf '%s\n' tenant-domains.yml admin-gate.yml
  for name in $(tr ',' ' ' <<< "${TRAEFIK_HOST_DYNAMIC_FILES:-}"); do
    printf '%s\n' "$name"
  done
}

dynamic_config_files_check() {
  local dir="${REPO_DIR:-.}/infra/traefik/dynamic" found allowed unexpected="" path name host_name
  if ! allowed="$(dynamic_config_allowed_names)"; then
    echo "    Versionierte Traefik-Dateien nicht ermittelbar (git ls-files in ${REPO_DIR:-.})" >&2
    return 1
  fi
  for host_name in $(tr ',' ' ' <<< "${TRAEFIK_HOST_DYNAMIC_FILES:-}"); do
    case "$host_name" in
      */* | .* | "" ) echo "    TRAEFIK_HOST_DYNAMIC_FILES: ungültiger Dateiname «$host_name»" >&2; return 1 ;;
    esac
    path="$dir/$host_name"
    if [ -e "$path" ] && { [ -L "$path" ] || [ ! -f "$path" ]; }; then
      echo "    Host-Datei $path ist keine normale Datei (Symlink/Verzeichnis)" >&2
      return 1
    fi
  done
  # find-Fehler (z. B. Verzeichnis nicht lesbar) = Fehlschlag, nicht «nichts gefunden» (Review L4)
  if ! found="$(find "$dir" -mindepth 1 \( -name '*.yml' -o -name '*.yaml' -o -name '*.toml' -o -type d \) -print)"; then
    echo "    Traefik-Dateiprovider-Verzeichnis nicht prüfbar: $dir" >&2
    return 1
  fi
  while IFS= read -r path; do
    [ -n "$path" ] || continue
    name="${path#"$dir"/}"
    if [ -d "$path" ] || ! grep -qxF -- "$name" <<< "$allowed"; then
      unexpected="$unexpected $path"
    fi
  done <<< "$found"
  if [ -n "$unexpected" ]; then
    echo "    Unerwartete Dateien im Traefik-Dateiprovider-Verzeichnis (von wem?):$unexpected" >&2
    echo "    Host-eigene Dateien in .env freigeben: TRAEFIK_HOST_DYNAMIC_FILES=\"<datei.yml>\"" >&2
    return 1
  fi
  # Versionierte Dateien unverändert (das Backend kann im Verzeichnis schreiben)
  if ! git -C "${REPO_DIR:-.}" diff --quiet -- infra/traefik/dynamic; then
    echo "    Versionierte Traefik-Dateien wurden verändert: git -C ${REPO_DIR:-.} diff -- infra/traefik/dynamic" >&2
    return 1
  fi
  echo "    Traefik-Dateiprovider: nur bekannte, unveränderte Dateien"
}

_traefik_negative_check() {
  local description="$1"
  shift
  for _ in 1 2 3; do
    if "$@" 2> /dev/null; then
      echo "    $description: ok"
      return 0
    fi
    sleep 3
  done
  "$@" || true # letzter Versuch mit Fehlerausgabe
  echo "    $description: ÖFFENTLICH ERREICHBAR (SEC-AUTH-001)" >&2
  return 1
}

# Ein Check mit Wiederholungen: Traefik übernimmt neue Container erst nach einigen Sekunden.
_traefik_check() {
  local description="$1"
  shift
  for _ in 1 2 3 4 5 6; do
    if "$@" 2> /dev/null; then
      echo "    $description: ok"
      return 0
    fi
    sleep 5
  done
  "$@" || true # letzter Versuch mit Fehlerausgabe
  echo "    $description: NICHT erreichbar über Traefik" >&2
  return 1
}
