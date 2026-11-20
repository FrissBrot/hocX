#!/usr/bin/env bash
# Auth-Audit SEC-AUTH-001: Live-Test der Admin-Isolation mit echtem Traefik (gleiches Image und
# gleiche infra/traefik/traefik.yml wie der Release-Stack) in Wegwerf-Containern mit eigenem Netz
# und zufälligen Ports auf 127.0.0.1 - nie gegen eine laufende Instanz.
#
# Die Router kommen aus den Labels von docker-compose.release.yml (mit .env.prod.example), dazu
# die versionierten Dateien in infra/traefik/dynamic und eine admin-gate.yml, geschrieben von der
# echten deploy.sh-Funktion. Statt der Dienste antwortet ein Echo-Server mit den empfangenen
# Headern. Zusätzlich ein absichtlich «undichter» Mandanten-Router in der alten Form
# (Host && PathPrefix(/api), SEC-AUTH-001) - der Sperr-Router muss auch ihn abfangen.
#
# Prüft: auf websecure sind /admin und /api/admin für jede Domain 404 (auch mit Pfad-Tricks), ein
# von aussen mitgeschickter Gate-Header kommt nie an, die Admin-Router auf adminsecure setzen ihn,
# normale Pfade und ACME-Pfade bleiben unberührt.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_DIR"

TRAEFIK_IMAGE="$(grep -m1 -E '^    image: traefik:' docker-compose.traefik.yml | awk '{print $2}')"
ECHO_IMAGE="python:3.13-slim@sha256:70729b46c69b4f1e97c4822c1af3df53a1476cf5ddc6c087c0c10bc3a5678c2f"
SUFFIX="$(od -An -N4 -tx4 /dev/urandom | tr -d ' ')"
NAME="hocx-admiso-test-$SUFFIX"
NET="${NAME}_edge"
NET_INTERNAL="${NAME}_proxy"
WORK="$(mktemp -d)"

cleanup() {
  docker rm -f "$NAME-traefik" "$NAME-echo" > /dev/null 2>&1 || true
  docker network rm "$NET" "$NET_INTERNAL" > /dev/null 2>&1 || true
  rm -rf "$WORK"
}
trap cleanup EXIT

fail() {
  echo "FEHLER: $*" >&2
  docker logs "$NAME-traefik" 2>&1 | grep -E 'ERR|WRN' | grep -v 'traefik-socket-proxy' | tail -n 20 >&2 || true
  exit 1
}

mkdir -p "$WORK/dynamic" "$WORK/letsencrypt"
cp infra/traefik/dynamic/security.yml infra/traefik/dynamic/admin-isolation.yml "$WORK/dynamic/"


# Router aus den Compose-Labels -> Dateiprovider (JSON ist gültiges YAML). Dienste zeigen auf den
# Echo-Server, Zertifikate kommen aus Traefiks Standard-Zertifikat (tls: {}).
# shellcheck disable=SC2016  # Python-Code mit Traefik-Backticks, keine Shell-Expansion
docker compose --env-file .env.prod.example -f docker-compose.release.yml -f docker-compose.clamav.yml \
  -f docker-compose.traefik.yml config --format json | python3 -c '
import json, re, sys
services = json.load(sys.stdin)["services"]
env = services["backend"]["environment"]
routers = {}
for service in services.values():
    labels = service.get("labels") or {}
    for key, value in labels.items():
        m = re.match(r"traefik\.http\.routers\.([^.]+)\.(rule|entrypoints|priority|middlewares)$", key)
        if m:
            routers.setdefault(m.group(1), {})[m.group(2)] = value
out = {}
for name, r in routers.items():
    out[name] = {
        "rule": r["rule"],
        "entryPoints": [e.strip() for e in r["entrypoints"].split(",")],
        "priority": int(r.get("priority", 0) or 0),
        "service": "echo",
        "tls": {},
    }
    file_middlewares = [m for m in r.get("middlewares", "").split(",") if m.endswith("@file")]
    if file_middlewares:
        out[name]["middlewares"] = file_middlewares
# Absichtlich undichte Mandanten-Router in der Form vor SEC-AUTH-001
out["leaky-tenant-backend"] = {"rule": "Host(`verein.example.org`) && PathPrefix(`/api`)", "entryPoints": ["websecure"],
                               "priority": 100, "service": "echo", "tls": {}}
out["leaky-tenant-frontend"] = {"rule": "Host(`verein.example.org`)", "entryPoints": ["websecure"],
                                "priority": 10, "service": "echo", "tls": {}}
config = {"http": {"routers": out, "services": {"echo": {"loadBalancer": {"servers": [{"url": "http://echo:8080"}]}}}}}
json.dump(config, open(sys.argv[1], "w"), indent=1)
print(" ".join([env["TRAEFIK_DOMAIN"], env["TRAEFIK_ADMIN_DOMAIN"], env["TRAEFIK_ABGABEBOX_DOMAIN"], env.get("TRAEFIK_DOCS_DOMAIN") or "docs.invalid"]))
' "$WORK/dynamic/routers.yml" > "$WORK/domains"
read -r MAIN ADMIN ABGABEBOX DOCS < "$WORK/domains"

docker network create "$NET" > /dev/null
# admin-gate.yml mit den echten deploy.sh-Funktionen (Gate-Header + Quellbeschränkung auf das
# Gateway des Netzes "<projekt>_edge", Review M1)
ADMIN_GATE_SECRET="$(od -An -N32 -tx1 /dev/urandom | tr -d ' \n')"
mkdir -p "$WORK/project/infra/traefik/dynamic"
(
  # shellcheck source=scripts/lib/admin_gate.sh
  source scripts/lib/admin_gate.sh
  # shellcheck disable=SC2034  # von den Funktionen gelesen
  PROJECT_DIR="$WORK/project" PROJECT_NAME="$NAME"
  write_admin_gate_traefik_config > /dev/null
)
cp "$WORK/project/infra/traefik/dynamic/admin-gate.yml" "$WORK/dynamic/admin-gate.yml"
docker run -d --name "$NAME-echo" --network "$NET" --network-alias echo --read-only --cap-drop ALL \
  --security-opt no-new-privileges:true --memory 64m "$ECHO_IMAGE" python3 -c '
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

class Echo(BaseHTTPRequestHandler):
    def _answer(self):
        body = json.dumps({"echo": True, "path": self.path, "host": self.headers.get("Host"),
                           "gate": self.headers.get_all("X-Hocx-Admin-Gate")}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    do_GET = do_POST = _answer
    def log_message(self, *args):
        pass

ThreadingHTTPServer(("0.0.0.0", 8080), Echo).serve_forever()
' > /dev/null

docker run -d --name "$NAME-traefik" --network "$NET" --network-alias traefik --memory 256m \
  -p 127.0.0.1::80 -p 127.0.0.1::443 -p 127.0.0.1::8443 \
  -v "$REPO_DIR/infra/traefik/traefik.yml:/etc/traefik/traefik.yml:ro" \
  -v "$WORK/dynamic:/etc/traefik/dynamic:ro" \
  -v "$WORK/letsencrypt:/letsencrypt" \
  "$TRAEFIK_IMAGE" --configFile=/etc/traefik/traefik.yml > /dev/null
# Wie im Release: Traefik zusätzlich in einem internen Netz (traefik-docker-api) - die Portweiterleitung
# läuft trotzdem über edge, dessen Gateway die Quellbeschränkung zulässt.
docker network create --internal "$NET_INTERNAL" > /dev/null
docker network connect "$NET_INTERNAL" "$NAME-traefik"

port_of() { docker port "$NAME-traefik" "$1" | head -n 1 | sed 's/.*://'; }
HTTP_PORT="$(port_of 80)"
HTTPS_PORT="$(port_of 443)"
ADMIN_PORT="$(port_of 8443)"

# request <host> <port> <pfad> [curl-Argumente…] -> "<status> <body>"
request() {
  local host="$1" port="$2" path="$3"
  shift 3
  curl --silent --insecure --max-time 10 --path-as-is --resolve "$host:$port:127.0.0.1" \
    --write-out ' %{http_code}' "$@" "https://$host:$port$path" || true
}
status_of() { printf '%s\n' "${1##* }"; }

ready=false
for _ in $(seq 1 40); do
  if [[ "$(request "$ADMIN" "$ADMIN_PORT" /api/admin/x)" == *'"echo": true'* ]]; then
    ready=true
    break
  fi
  sleep 0.5
done
$ready || fail "Traefik/Echo nicht bereit"

# 1. Öffentlicher Entrypoint: Admin-Pfade auf jeder Domain 404, nie beim Dienst
for host in "$MAIN" "$ABGABEBOX" "$DOCS" "$ADMIN" verein.example.org unbekannt.example; do
  for path in /admin /admin/ /admin/login /api/admin /api/admin/auth/health /api/admin/auth/login \
    //api/admin/auth/session /api/./admin/auth/session /%61pi/admin/auth/session /api/%61dmin/x /admin/../admin/login; do
    response="$(request "$host" "$HTTPS_PORT" "$path" -H "X-Hocx-Admin-Gate: $ADMIN_GATE_SECRET")"
    [ "$(status_of "$response")" = 404 ] || fail "websecure $host$path: $(status_of "$response") statt 404 ($response)"
    [[ "$response" != *'"echo"'* ]] || fail "websecure $host$path erreicht einen Dienst"
  done
  response="$(request "$host" "$HTTPS_PORT" /api/admin/auth/login -X POST -d '{}')"
  [ "$(status_of "$response")" = 404 ] || fail "POST websecure $host/api/admin/auth/login: $response"
done

# 2. Normale Pfade bleiben erreichbar; ein von aussen gesetzter Gate-Header kommt nie an
for target in "$MAIN /api/health" "$MAIN /login" "$ABGABEBOX /api/public/maintenance-status" "verein.example.org /api/events"; do
  read -r host path <<< "$target"
  response="$(request "$host" "$HTTPS_PORT" "$path" -H "X-Hocx-Admin-Gate: $ADMIN_GATE_SECRET")"
  [ "$(status_of "$response")" = 200 ] || fail "websecure $host$path nicht erreichbar: $response"
  [[ "$response" == *'"gate": null'* ]] || fail "Gate-Header von aussen durchgereicht: $host$path $response"
done

# 3. Admin-Entrypoint: Gate-Header gesetzt (auch wenn der Client einen eigenen schickt), andere Hosts 404
for path in /api/admin/auth/session /api/admin/tenants/import /login /admin/tenants; do
  response="$(request "$ADMIN" "$ADMIN_PORT" "$path" -H 'X-Hocx-Admin-Gate: gefaelscht')"
  [[ "$response" == *"\"gate\": [\"$ADMIN_GATE_SECRET\"]"* ]] || fail "adminsecure $path ohne korrekten Gate-Header: $response"
done
response="$(request "$ADMIN" "$ADMIN_PORT" /api/admin/auth/login -X POST -d '{}')"
[[ "$response" == *"\"gate\": [\"$ADMIN_GATE_SECRET\"]"* ]] || fail "adminsecure POST login ohne Gate-Header: $response"
for host in "$MAIN" verein.example.org; do
  response="$(request "$host" "$ADMIN_PORT" /api/admin/auth/session)"
  [ "$(status_of "$response")" = 404 ] || fail "adminsecure mit Host $host: $response"
done

# 4. Port 80: nur Weiterleitung auf HTTPS, ACME-Pfad nicht vom Sperr-Router betroffen
code="$(curl --silent --max-time 10 --output /dev/null --write-out '%{http_code}' -H "Host: $MAIN" "http://127.0.0.1:$HTTP_PORT/admin/login" || true)"
[[ "$code" =~ ^30[178]$ ]] || fail "Port 80 /admin/login: $code statt Weiterleitung"
code="$(request "$MAIN" "$HTTPS_PORT" /.well-known/acme-challenge/test)"
[[ "$code" == *'"echo": true'* ]] || fail "ACME-/well-known-Pfad wird blockiert: $code"

# 5. Sperr-Kennzeichen (Review L1): traefik_checks.sh verlangt 404 UND X-Hocx-Admin-Block
headers="$(curl --silent --insecure --max-time 10 --path-as-is --resolve "$MAIN:$HTTPS_PORT:127.0.0.1" -o /dev/null -D - \
  "https://$MAIN:$HTTPS_PORT/api/admin/auth/health")"
grep -qi '^x-hocx-admin-block: *1' <<< "$headers" || fail "Sperr-Router ohne Kennzeichen: $headers"
headers="$(curl --silent --insecure --max-time 10 --resolve "$MAIN:$HTTPS_PORT:127.0.0.1" -o /dev/null -D - "https://$MAIN:$HTTPS_PORT/login")"
if grep -qi '^x-hocx-admin-block' <<< "$headers"; then fail "Kennzeichen auch ausserhalb der Sperre"; fi

# 6. Review M1: Ein Container im selben Netz erreicht den Admin-Entrypoint direkt (traefik:8443) -
#    die Quellbeschränkung lässt nur das Gateway (Docker-Portweiterleitung vom Host) zu.
inside="$(docker run --rm --network "$NET" "$ECHO_IMAGE" python3 -c '
import http.client, ssl, sys
conn = http.client.HTTPSConnection("traefik", 8443, context=ssl._create_unverified_context(), timeout=10)
conn.request("GET", "/api/admin/auth/session", headers={"Host": sys.argv[1], "X-Hocx-Admin-Gate": "x"})
response = conn.getresponse()
print(response.status, response.read().decode()[:200])
' "$ADMIN")"
[[ "$inside" == 403* ]] || fail "Container im Netz erreicht den Admin-Entrypoint: $inside"
response="$(request "$ADMIN" "$ADMIN_PORT" /api/admin/auth/session)"
[[ "$response" == *"\"gate\": [\"$ADMIN_GATE_SECRET\"]"* ]] || fail "Host-Port 127.0.0.1 nicht mehr zugelassen: $response"

echo "admin isolation live tests: ok"
