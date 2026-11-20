# shellcheck shell=bash
# Prüfungen von aussen: jeder Traefik-Router wird über den echten Host-Namen (SNI, Zertifikat)
# angesprochen. Die Smoke-Checks in den Containern sehen nicht, ob Traefik einen Dienst erreicht
# - am 19.11.2026 antwortete die Abgabebox-API live mit 504 (Traefik wählte die IP im internen
# storage-Netz), während alle internen Prüfungen grün waren.
#
# Erwartet: TRAEFIK_DOMAIN, TRAEFIK_ABGABEBOX_DOMAIN; optional TRAEFIK_ADMIN_DOMAIN,
# TRAEFIK_DOCS_DOMAIN, TRAEFIK_WEBSITE_DOMAIN, TRAEFIK_WEBSECURE_BIND, HOCX_VERIFY_CA_FILE und
# REPO_DIR (für einen relativen CA-Pfad). Benutzt von deploy.sh und verify_release.sh.

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

# POST mit JSON über Traefik; prüft, dass die Antwort den erwarteten Text enthält.
probe_post_json() {
  local url="$1" body="$2" expected="$3" response
  local -a extra
  mapfile -t extra < <(_traefik_curl_args "$url")
  response="$(curl --silent --show-error --fail --max-time 15 -H 'Content-Type: application/json' \
    --data "$body" "${extra[@]}" "$url")" || return 1
  [[ "$response" == *"$expected"* ]] || { echo "    Unerwartete Antwort: ${response:0:200}" >&2; return 1; }
}

# Alle Router von aussen. Ein Aufruf je Router - Frontend und API einer Domain sind eigene
# Router (eigene Dienste), beide müssen erreichbar sein.
traefik_route_checks() {
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
    _traefik_check "Admin: API" probe_domain "$admin/api/admin/auth/oidc/public-config" || return 1
  fi
  # Docs und Website sind keine Kernfunktion (oft eigene DNS/Zertifikate): ein Fehler dort ist
  # eine Warnung, kein Rollback - ein Rollback setzt nur die Images zurück, nicht die Datenbank.
  if [ -n "${TRAEFIK_DOCS_DOMAIN:-}" ]; then
    _traefik_check "Docs" probe_domain "https://${TRAEFIK_DOCS_DOMAIN}/" || echo "    WARNUNG: Docs über Traefik nicht erreichbar (kein Rollback)." >&2
  fi
  if [ -n "${TRAEFIK_WEBSITE_DOMAIN:-}" ]; then
    _traefik_check "Website (Landing Page)" probe_website_domain "https://${TRAEFIK_WEBSITE_DOMAIN}/" || echo "    WARNUNG: Website über Traefik nicht erreichbar (kein Rollback)." >&2
  fi
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
