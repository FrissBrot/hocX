#!/usr/bin/env bash
# Wartungsseite (1.4.3, RUNBOOK Abschnitt 20).
#
#   scripts/tests/test_maintenance_page.sh          statische Prüfungen (CI, deploy-script-tests)
#   scripts/tests/test_maintenance_page.sh --live   zusätzlich echter Test mit Traefik in Docker:
#       Wegwerf-Compose-Projekt (eigener Name, zufällige Ports auf 127.0.0.1, eigene Test-CA),
#       App-Container sind nginx-Attrappen mit den echten Traefik-Labels aus
#       docker-compose.release.yml, die Wartungsseite ist der echte Dienst aus
#       docker-compose.traefik.yml. Berührt keine laufende Instanz.
#       Optional MTEST_TENANT_FILE=<tenant-domains.yml>: von traefik_config_service.regenerate()
#       erzeugte Konfiguration für die Mandanten-Domains app.tenant.mtest.test (app) und
#       box.tenant.mtest.test (abgabebox), ROUTER_PREFIX mtest - prüft sie mit.
# Die Prüfausdrücke für expect() und die Python-Programme stehen bewusst in einfachen
# Anführungszeichen (werden erst später bzw. in Python ausgewertet).
# shellcheck disable=SC2016
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_DIR"

COMPOSE_FILES=(-f docker-compose.release.yml -f docker-compose.clamav.yml -f docker-compose.traefik.yml)

compose_json() {
  docker compose --env-file .env.prod.example "${COMPOSE_FILES[@]}" config --format json
}

# --- Compose: Dienst, Härtung, Router ---------------------------------------------------------
compose_json | python3 -c '
import json, re, sys
config = json.load(sys.stdin)
services = config["services"]

page = services.get("maintenance-page")
assert page, "Dienst maintenance-page fehlt"
assert re.fullmatch(r"nginxinc/nginx-unprivileged:alpine@sha256:[0-9a-f]{64}", page["image"]), page["image"]
assert page.get("read_only") is True, "maintenance-page: read_only fehlt"
assert page.get("cap_drop") == ["ALL"], "maintenance-page: cap_drop ALL fehlt"
assert not page.get("cap_add"), "maintenance-page: cap_add nicht erlaubt"
assert "no-new-privileges:true" in page.get("security_opt", []), "maintenance-page: no-new-privileges fehlt"
assert page.get("mem_limit") and page.get("cpus"), "maintenance-page: Ressourcenlimits fehlen"
assert not page.get("ports"), "maintenance-page darf keine Ports veröffentlichen"
assert not page.get("secrets") and not page.get("environment"), "maintenance-page braucht weder Secrets noch Umgebung"
# Eigenes internes Netz nur mit Traefik (Security-Review G2): kein Zugang zu den App-Diensten.
assert list((page.get("networks") or {}).keys()) == ["maintenance"], page.get("networks")
assert config["networks"]["maintenance"].get("internal") is True, config["networks"]["maintenance"]
users = sorted(n for n, s in services.items() if "maintenance" in (s.get("networks") or {}))
assert users == ["maintenance-page", "traefik"], users
mounts = page.get("volumes", [])
assert len(mounts) == 1 and mounts[0]["target"] == "/srv/maintenance" and mounts[0].get("read_only"), mounts
assert mounts[0]["source"].endswith("/infra/maintenance"), mounts
assert "docker.sock" not in json.dumps(page)

def labels(service):
    value = service.get("labels") or {}
    if isinstance(value, list):
        value = dict(item.split("=", 1) for item in value)
    return value

routers = {}
for name, service in services.items():
    for key, value in labels(service).items():
        m = re.fullmatch(r"traefik\.http\.routers\.([^.]+)\.(rule|priority|middlewares|entrypoints)", key)
        if m:
            routers.setdefault(m.group(1), {"service": name})[m.group(2)] = value

def host(rule):
    m = re.match(r"Host\(`([^`]+)`\)", rule)
    return m.group(1) if m else None

env = {}
for line in open(".env.prod.example"):
    if "=" in line and not line.lstrip().startswith("#"):
        k, v = line.strip().split("=", 1)
        env[k] = v
domains = {"main": env["TRAEFIK_DOMAIN"], "abgabebox": env["TRAEFIK_ABGABEBOX_DOMAIN"], "admin": env["TRAEFIK_ADMIN_DOMAIN"]}

fallbacks = {n: r for n, r in routers.items() if r["service"] == "maintenance-page"}
app = {n: r for n, r in routers.items() if r["service"] != "maintenance-page"}
frontend_router = {"main": "frontend", "abgabebox": "abgabebox-frontend", "admin": "admin-frontend"}
for kind, domain in domains.items():
    catch_all = [r for r in fallbacks.values() if host(r["rule"]) == domain and "/api" not in r["rule"]]
    assert len(catch_all) == 1, f"Ausweich-Router für {domain} fehlt"
    # Gleiche Pfade wie das Frontend der Domain: sonst bekäme ein Pfad ohne Router (404) auch im
    # Normalbetrieb die Wartungsseite.
    frontend = [r for n, r in app.items() if n.split("-", 1)[1] == frontend_router[kind]]
    assert len(frontend) == 1 and frontend[0]["rule"] == catch_all[0]["rule"], (frontend, catch_all)
    assert catch_all[0]["priority"] == "1", catch_all
    expected_ep = "adminsecure" if kind == "admin" else "websecure"
    assert catch_all[0]["entrypoints"] == expected_ep, catch_all
    same_host = [r for r in app.values() if host(r["rule"]) == domain]
    assert same_host, f"keine App-Router für {domain}"
    # Niedrigste Priorität: jeder App-Router derselben Domain liegt darüber.
    low = [r for r in same_host if int(r["priority"]) <= 1]
    assert not low, f"App-Router mit Priorität <= 1 auf {domain}: {low}"
    # API-Ausweich-Router: über dem Frontend (10), unter jedem Backend-Router (>= 100).
    api = [r for r in fallbacks.values() if host(r["rule"]) == domain and "/api" in r["rule"]]
    assert len(api) == 1, f"API-Ausweich-Router für {domain} fehlt"
    prio = int(api[0]["priority"])
    for r in same_host:
        if "PathPrefix(`/api" in r["rule"] or "Path(`/api" in r["rule"]:
            assert int(r["priority"]) > prio, (r, api)
        else:
            assert int(r["priority"]) < prio, (r, api)
    assert api[0]["middlewares"] == "maintenance-path-api@file", api
assert all(r["middlewares"].startswith("maintenance-path-") for r in fallbacks.values()), fallbacks
assert labels(page)["traefik.docker.network"].endswith("_maintenance"), labels(page)

# errors-Middleware an allen App-Routern ausser Docs und Website (als erste Middleware).
expected = {
    "frontend": "maintenance-errors@file",
    "admin-frontend": "maintenance-errors-admin@file",
    "abgabebox-frontend": "maintenance-errors-abgabebox@file",
}
missing = []
for name, router in app.items():
    short = name.split("-", 1)[1]
    if short in ("docs", "website-frontend"):
        continue
    want = expected.get(short, "maintenance-errors-api@file")
    first = (router.get("middlewares") or "").split(",")[0]
    if first != want:
        missing.append(f"{name}: {first or chr(45)} (erwartet {want})")
assert not missing, "errors-Middleware fehlt/falsch: " + "; ".join(missing)
print("maintenance compose: ok")
'

# Zählung der Härtung in docker-compose.traefik.yml (test_release_config.sh zählt ebenfalls).
test "$(grep -c '^  maintenance-page:$' docker-compose.traefik.yml)" -eq 1

# --- Traefik-Dateiprovider ---------------------------------------------------------------------
python3 - <<'PY'
import re
text = open("infra/traefik/dynamic/maintenance.yml").read()
def block(name):
    m = re.search(rf"^    {re.escape(name)}:\n((?:      .*\n|\s*\n)+)", text, re.M)
    assert m, f"Middleware {name} fehlt in maintenance.yml"
    return m.group(1)
for name, query in (("maintenance-errors", "/_hocx"), ("maintenance-errors-admin", "/_admin"),
                    ("maintenance-errors-abgabebox", "/_abgabebox"), ("maintenance-errors-api", "/_api")):
    b = block(name)
    assert "service: maintenance-page" in b and f"query: {query}" in b, (name, b)
    assert "statusRewrites" in b, name
api = block("maintenance-errors-api")
# Ein 503 der Backends (Wartungsmodus, Überlast) trägt einen Code und bleibt unverändert.
assert '"502"' in api and '"504"' in api and "503\"" not in api.split("statusRewrites")[0] and "502-504" not in api, api
for variant in ("hocx", "admin", "abgabebox", "api"):
    assert f"path: /_{variant}" in block(f"maintenance-path-{variant}"), variant
assert 'url: "http://maintenance-page:8080"' in text
# Jede @file-Referenz (Compose-Labels, Mandanten-Domains in traefik_config_service.py) existiert.
defined = set(re.findall(r"(?m)^    ([a-z-]+):$", text))
sources = open("docker-compose.release.yml").read() + open("docker-compose.traefik.yml").read() + open("backend/app/services/traefik_config_service.py").read()
for name in set(re.findall(r"(maintenance-[a-z-]+)@file", sources)):
    assert name in defined, f"{name}@file fehlt in maintenance.yml"
print("maintenance traefik file: ok")
PY

# --- nginx: immer 503 (ausser /healthz), Kopfzeilen, CSP-Hash ----------------------------------
python3 - <<'PY'
import base64, hashlib, json, re
conf = open("infra/maintenance/nginx.conf").read()
html = open("infra/maintenance/maintenance.html").read()
returns = re.findall(r"return (\d{3})", conf)
assert returns.count("200") == 1 and "location = /healthz" in conf, returns
assert set(returns) <= {"200", "503"}, returns
for location in ("location = /maintenance.html", "location = /api-503.json"):
    body = conf.split(location, 1)[1].split("}", 1)[0]
    assert "internal;" in body, location
    for header in ('Cache-Control "no-store"', "Retry-After", "X-Hocx-Maintenance-Page"):
        assert header in body, (location, header)
script = re.search(r"<script>(.*?)</script>", html, re.S).group(1)
digest = base64.b64encode(hashlib.sha256(script.encode()).digest()).decode()
assert f"'sha256-{digest}'" in conf, f"CSP-Hash in nginx.conf veraltet, richtig: 'sha256-{digest}'"
assert "unsafe-inline" not in conf.split("script-src", 1)[1].split(";", 1)[0]
assert html.count("<script") == 1, "nur ein Inline-Skript (CSP-Hash)"
# Keine externen Ressourcen, keine Cookies.
assert not re.search(r"(src|href)=\"(https?:)?//", html), "externe Ressource"
assert "@import" not in html and "url(" not in html.split("<!--# include")[0]
assert "document.cookie" not in html and "localStorage" not in html and "sessionStorage" not in html
assert '"omit"' in html, "fetch ohne credentials: omit"
assert 'role="status"' in html and "<h1" in html and "<main" in html
assert '<!--# include virtual="/tokens.css" -->' in html
# JSON-Antwort der API
api = json.load(open("infra/maintenance/api-503.json"))
assert api["code"] not in ("maintenance", "overloaded"), "Code darf keine Sonderbehandlung im Frontend auslösen"
assert isinstance(api["detail"], str) and api["detail"]

# Alle Sprachen aus i18n/locales.json, je vollständig.
locales = list(json.load(open("i18n/locales.json"))["locales"])
default = json.load(open("i18n/locales.json"))["defaultLocale"]
literal = re.search(r"var TEXTS = (\{.*?\n  \});", script, re.S).group(1)
texts = json.loads(re.sub(r"(?m)^(\s*)([a-z]+):", r'\1"\2":', literal))
assert sorted(texts) == sorted(locales), f"Sprachen der Wartungsseite {sorted(texts)} != i18n/locales.json {sorted(locales)}"
for locale, entry in texts.items():
    assert entry.get("reload"), locale
    for variant in ("hocx", "abgabebox"):
        keys = entry.get(variant) or {}
        assert sorted(keys) == ["heading", "hint", "message", "title"], (locale, variant, keys)
        assert all(isinstance(v, str) and v.strip() for v in keys.values()), (locale, variant)
assert f'var DEFAULT_LOCALE = "{default}";' in script
print("maintenance page: ok")
PY

# Design-Tokens: Kopie aktuell (sync-design-tokens.sh --check prüft alle Kopien).
cmp -s design/tokens.css infra/maintenance/tokens.css || { echo "infra/maintenance/tokens.css veraltet: ./scripts/sync-design-tokens.sh" >&2; exit 1; }

# Prüfungen von aussen zählen die Wartungsseite nie als erreichbar: sie liefert immer 503, und
# jede Prüfung in traefik_checks.sh nutzt curl --fail (HTTP >= 400 = Fehler).
test "$(grep -c 'curl --silent --show-error --fail' scripts/lib/traefik_checks.sh)" -eq 1
# probe_post_json (ohne --fail): Statuscode selbst geprüft, Wartung erkannt - mit gefälschtem curl.
FAKE="$(mktemp -d)"
cat > "$FAKE/curl" <<'SH'
#!/usr/bin/env bash
printf '%s\n%s' "$FAKE_BODY" "$FAKE_STATUS"
SH
chmod +x "$FAKE/curl"
probe_case() {
  FAKE_BODY="$1" FAKE_STATUS="$2" PATH="$FAKE:$PATH" bash -c 'source scripts/lib/traefik_checks.sh; probe_post_json https://x.invalid/api/public/verify "{}" "\"found\":false"' 2>&1
}
out="$(probe_case '{"found":false}' 200)" || { echo "probe_post_json: 200 abgelehnt: $out" >&2; exit 1; }
if out="$(probe_case '{"detail":"x","code": "maintenance"}' 503)"; then echo "probe_post_json: Wartung als ok gezählt" >&2; exit 1; fi
grep -q "Wartung noch aktiv" <<< "$out" || { echo "probe_post_json: Wartung nicht gemeldet: $out" >&2; exit 1; }
if out="$(probe_case '{"code":"service_unavailable","found":false}' 503)"; then echo "probe_post_json: Wartungsseite (503) als ok gezählt" >&2; exit 1; fi
grep -q "HTTP 503" <<< "$out" || { echo "probe_post_json: 503 nicht gemeldet: $out" >&2; exit 1; }
if probe_case '{"found":true}' 200 > /dev/null; then echo "probe_post_json: falsche Antwort akzeptiert" >&2; exit 1; fi
rm -rf "$FAKE"
# deploy.sh: Rechte und Neustart bei geänderter nginx.conf
grep -q "chmod -R g+rX,g-w,o-rwx /target" scripts/deploy.sh
grep -q '^  prepare_maintenance_dir$' scripts/deploy.sh
if grep -q '"$PROJECT_DIR/infra/maintenance"; do' scripts/deploy.sh; then
  echo "infra/maintenance darf nicht gruppenschreibbar gehärtet werden" >&2
  exit 1
fi
grep -q 'sync_maintenance_page_config' scripts/deploy.sh

# Wartungsmodus während des Updates: Reihenfolge in deploy.sh (Hauptablauf ausserhalb von Funktionen)
python3 - <<'PY'
import re
lines = open("scripts/deploy.sh").read().split("\n")
def first(pattern, start=0):
    for index in range(start, len(lines)):
        if re.search(pattern, lines[index]):
            return index
    raise AssertionError(f"nicht gefunden: {pattern}")
begin = first(r"^begin_deploy_maintenance$")
trap = first(r"^trap 'end_deploy_maintenance aborted \|\| true' EXIT$")
alembic = first(r'run --rm --no-deps backend alembic')
migration_failed = first(r"Datenbankmigration fehlgeschlagen")
migration_end = first(r"^  end_deploy_maintenance aborted \|\| true$", migration_failed)
migration_exit = first(r"^  exit 1$", migration_failed)
smoke = first(r"^if ! run_smoke_checks; then$")
success = first(r"^if ! end_deploy_maintenance success; then$")
success_exit = first(r"^  exit 1$", success)
assert "rollback_apps" not in "\n".join(lines[success:success_exit]), "Wartung nicht beendbar: kein Rollback"
trap_line = first(r"^trap 'end_deploy_maintenance aborted \|\| true' EXIT$")
assert trap_line < first(r"^begin_deploy_maintenance$"), "EXIT-Trap vor begin_deploy_maintenance"
route_checks = first(r"^if ! traefik_route_checks; then$")
assert trap < begin < alembic, "Trap, dann begin-deploy, beides vor der Migration"
assert migration_end < migration_exit, "Migration fehlgeschlagen: Wartung vor exit beenden"
assert smoke < success < route_checks, "Wartung nach den Smoke-Checks, vor den Traefik-Prüfungen beenden"
# rollback_apps beendet die Wartung in jedem Fall
body = "\n".join(lines[first(r"^rollback_apps\(\) \{$"):first(r"^rollback_app_images\(\) \{$")])
assert "rollback_app_images || status=$?" in body and "end_deploy_maintenance rollback || true" in body, body
# Ende mit dem Image des neuen Releases, SQL-Rückfall, nie Abbruch
text = "\n".join(lines)
assert 'HOCX_BACKEND_IMAGE="$DEPLOY_MAINTENANCE_IMAGE"' in text
assert "WHERE source_job_type = 'deploy' AND state NOT IN ('completed', 'cancelled')" in text
end_fn = text.split("end_deploy_maintenance() {", 1)[1].split("\n}\n", 1)[0]
assert "exit" not in end_fn, "end_deploy_maintenance darf nie abbrechen (nur Rückgabewert)"
assert end_fn.rstrip().endswith("return 1"), "end_deploy_maintenance meldet Misserfolg"
assert "audit_log" in text.split("DEPLOY_MAINTENANCE_END_SQL=", 1)[1].split("\n", 1)[0], "SQL-Rückfall ohne Audit"
begin_fn = text.split("begin_deploy_maintenance() {", 1)[1].split("\n}\n", 1)[0]
assert "return 1" not in begin_fn and "exit" not in begin_fn, "begin_deploy_maintenance darf nie abbrechen"
assert begin_fn.index("DEPLOY_MAINTENANCE_ACTIVE=1") < begin_fn.index("begin-deploy")
print("deploy maintenance order: ok")
PY

echo "maintenance static tests: ok"

[ "${1:-}" = --live ] || exit 0

# =============================================================================================
# Echter Test mit Traefik in Docker
# =============================================================================================
PROJECT="hocx-mtest-$$"
WORK="$(mktemp -d)"
chmod 755 "$WORK"
DOMAIN=hocx.mtest.test
ABG_DOMAIN=abgabe.mtest.test
ADMIN_DOMAIN=admin.mtest.test
TENANT_APP_DOMAIN=app.tenant.mtest.test
TENANT_BOX_DOMAIN=box.tenant.mtest.test

cleanup() {
  docker compose -p "$PROJECT" -f "$WORK/compose.json" down -v --remove-orphans > /dev/null 2>&1 || true
  rm -rf "$WORK"
}
trap cleanup EXIT

# Test-CA und Zertifikat für die drei Domains
openssl req -x509 -newkey rsa:2048 -nodes -days 1 -subj "/CN=hocx mtest CA" \
  -keyout "$WORK/ca.key" -out "$WORK/ca.crt" 2> /dev/null
openssl req -newkey rsa:2048 -nodes -subj "/CN=$DOMAIN" -keyout "$WORK/tls.key" -out "$WORK/tls.csr" 2> /dev/null
printf 'subjectAltName=DNS:%s,DNS:%s,DNS:%s,DNS:%s,DNS:%s\n' "$DOMAIN" "$ABG_DOMAIN" "$ADMIN_DOMAIN" \
  "$TENANT_APP_DOMAIN" "$TENANT_BOX_DOMAIN" > "$WORK/san.ext"
openssl x509 -req -in "$WORK/tls.csr" -CA "$WORK/ca.crt" -CAkey "$WORK/ca.key" -CAcreateserial -days 1 \
  -extfile "$WORK/san.ext" -out "$WORK/tls.crt" 2> /dev/null

mkdir -p "$WORK/dynamic" "$WORK/certs" "$WORK/stub"
cp infra/traefik/dynamic/security.yml infra/traefik/dynamic/maintenance.yml "$WORK/dynamic/"
cp "$WORK/tls.crt" "$WORK/tls.key" "$WORK/certs/"
TENANT=0
if [ -n "${MTEST_TENANT_FILE:-}" ]; then
  cp "$MTEST_TENANT_FILE" "$WORK/dynamic/tenant-domains.yml"
  TENANT=1
fi
cat > "$WORK/dynamic/certs.yml" <<'EOF'
tls:
  stores:
    default:
      defaultCertificate:
        certFile: /certs/tls.crt
        keyFile: /certs/tls.key
EOF
cat > "$WORK/traefik.yml" <<EOF
entryPoints:
  websecure:
    address: ":443"
    http:
      middlewares: [security-headers@file, compress@file]
  adminsecure:
    address: ":8443"
    http:
      middlewares: [security-headers@file, compress@file]
providers:
  docker:
    exposedByDefault: false
    constraints: "Label(\`com.docker.compose.project\`,\`$PROJECT\`)"
  file:
    directory: /etc/traefik/dynamic
    watch: true
# Die Labels nennen letsencrypt/letsencryptdns; hier ohne erreichbare ACME-Instanz (Port 1), das
# Standardzertifikat oben gilt für alle Router.
certificatesResolvers:
  letsencrypt:
    acme:
      email: test@example.invalid
      storage: /tmp/acme.json
      caServer: https://127.0.0.1:1/directory
      tlsChallenge: {}
  letsencryptdns:
    acme:
      email: test@example.invalid
      storage: /tmp/acme-dns.json
      caServer: https://127.0.0.1:1/directory
      tlsChallenge: {}
log:
  level: ERROR
EOF
# App-Attrappe: 200 für alles, /fail-502 und /api/fail-502 -> 502, /api/fail-503 -> 503 mit Code
cat > "$WORK/stub/nginx.conf" <<'EOF'
worker_processes 1;
pid /tmp/nginx.pid;
error_log stderr warn;
events { worker_connections 64; }
http {
  client_body_temp_path /tmp/client_temp;
  proxy_temp_path /tmp/proxy_temp;
  fastcgi_temp_path /tmp/fastcgi_temp;
  uwsgi_temp_path /tmp/uwsgi_temp;
  scgi_temp_path /tmp/scgi_temp;
  access_log off;
  server {
    listen 3000;
    listen 8000;
    location ~ /fail-502$ { return 502; }
    location = /api/fail-503 {
      default_type application/json;
      add_header Retry-After 7 always;
      return 503 '{"detail":"busy","code":"overloaded"}';
    }
    location / { default_type text/plain; return 200 "app-ok\n"; }
  }
}
EOF
chmod -R a+rX "$WORK"

TRAEFIK_IMAGE="$(grep -m1 -E '^    image: traefik:' docker-compose.traefik.yml | awk '{print $2}')"
TRAEFIK_DOMAIN="$DOMAIN" TRAEFIK_ABGABEBOX_DOMAIN="$ABG_DOMAIN" TRAEFIK_ADMIN_DOMAIN="$ADMIN_DOMAIN" ROUTER_PREFIX=mtest \
  docker compose -p "$PROJECT" --env-file .env.prod.example "${COMPOSE_FILES[@]}" config --format json |
  python3 -c '
import json, sys
work, project, traefik_image = sys.argv[1:4]
services = json.load(sys.stdin)["services"]
page = services["maintenance-page"]
out = {"name": project, "services": {}, "networks": {"default": {}, "maintenance": {"internal": True}}}
out["services"]["maintenance-page"] = {k: v for k, v in page.items() if k not in ("depends_on",)}
stub = {
    "image": page["image"],
    "entrypoint": ["nginx", "-c", "/stub/nginx.conf", "-g", "daemon off;"],
    "read_only": True,
    "tmpfs": ["/tmp"],
    "volumes": [{"type": "bind", "source": f"{work}/stub", "target": "/stub", "read_only": True}],
}
for name in ("frontend", "backend", "abgabebox-frontend", "abgabebox-backend"):
    out["services"][name] = dict(stub, labels=services[name]["labels"])
out["services"]["traefik"] = {
    "image": traefik_image,
    "command": ["--configFile=/etc/traefik/traefik.yml"],
    "ports": ["127.0.0.1::443", "127.0.0.1::8443"],
    "networks": ["default", "maintenance"],
    "volumes": [
        {"type": "bind", "source": f"{work}/traefik.yml", "target": "/etc/traefik/traefik.yml", "read_only": True},
        {"type": "bind", "source": f"{work}/dynamic", "target": "/etc/traefik/dynamic", "read_only": True},
        {"type": "bind", "source": f"{work}/certs", "target": "/certs", "read_only": True},
        {"type": "bind", "source": "/var/run/docker.sock", "target": "/var/run/docker.sock", "read_only": True},
    ],
}
json.dump(out, open(f"{work}/compose.json", "w"), indent=1)
' "$WORK" "$PROJECT" "$TRAEFIK_IMAGE"

DC=(docker compose -p "$PROJECT" -f "$WORK/compose.json")
"${DC[@]}" up -d --quiet-pull > /dev/null 2>&1 || { "${DC[@]}" up -d; exit 1; }
WEB_PORT="$("${DC[@]}" port traefik 443 | cut -d: -f2)"
ADMIN_PORT="$("${DC[@]}" port traefik 8443 | cut -d: -f2)"

failures=0
# request <url> -> setzt STATUS, BODY, HEADERS
request() {
  local url="$1" host port rest
  shift
  rest="${url#https://}"
  host="${rest%%/*}"
  port=443
  case "$host" in "$ADMIN_DOMAIN") port="$ADMIN_PORT" ;; *) port="$WEB_PORT" ;; esac
  url="https://$host:$port/${rest#*/}"
  HEADERS="$(mktemp -p "$WORK")"
  BODY="$(curl -sS --max-time 10 --cacert "$WORK/ca.crt" --resolve "$host:$port:127.0.0.1" \
    -D "$HEADERS" "$@" "$url" || true)"
  STATUS="$(awk 'toupper($1) ~ /^HTTP/ {code=$2} END {print code}' "$HEADERS")"
}
header() { grep -i "^$1:" "$HEADERS" | head -1 | cut -d: -f2- | tr -d '\r' | sed 's/^ //'; }
expect() {
  local description="$1" condition="$2"
  if eval "$condition"; then
    echo "    ok: $description"
  else
    echo "    FEHLER: $description (Status $STATUS, $(head -c 160 <<< "$BODY" | tr '\n' ' '))" >&2
    failures=$((failures + 1))
  fi
}
wait_status() {
  local url="$1" want="$2"
  for _ in $(seq 1 40); do
    request "$url"
    [ "$STATUS" = "$want" ] && return 0
    sleep 0.5
  done
  return 1
}
maintenance_html() { [ "$STATUS" = 503 ] && [ "$(header X-Hocx-Maintenance-Page)" = 1 ] && [ "$(header Cache-Control)" = no-store ] && [ "$(header Retry-After)" = 30 ] && [[ "$(header Content-Type)" == text/html* ]] && grep -q "data-variant=\"$1\"" <<< "$BODY"; }
maintenance_json() { [ "$STATUS" = 503 ] && [ "$(header X-Hocx-Maintenance-Page)" = 1 ] && [ "$(header Cache-Control)" = no-store ] && [ "$(header Retry-After)" = 30 ] && [[ "$(header Content-Type)" == application/json* ]] && grep -q '"code":"service_unavailable"' <<< "$BODY"; }

echo "==> Normalbetrieb"
wait_status "https://$DOMAIN/login" 200 || true
expect "Frontend 200" '[ "$STATUS" = 200 ] && [ "$BODY" = app-ok ]'
wait_status "https://$DOMAIN/api/health" 200 || true
expect "Backend /api/health 200" '[ "$STATUS" = 200 ] && [ "$BODY" = app-ok ]'
wait_status "https://$ABG_DOMAIN/" 200 || true
expect "Abgabebox-Frontend 200" '[ "$STATUS" = 200 ]'
wait_status "https://$ABG_DOMAIN/api/health" 200 || true
expect "Abgabebox-API 200" '[ "$STATUS" = 200 ]'
wait_status "https://$ADMIN_DOMAIN/admin/login" 200 || true
expect "Admin-Frontend 200" '[ "$STATUS" = 200 ]'
wait_status "https://$ADMIN_DOMAIN/api/admin/auth/oidc/public-config" 200 || true
expect "Admin-API 200" '[ "$STATUS" = 200 ]'
request "https://$DOMAIN/admin/login"
expect "Hauptdomain /admin (kein Router) bleibt 404, keine Wartungsseite" '[ "$STATUS" = 404 ] && [ -z "$(header X-Hocx-Maintenance-Page)" ]'
if [ "$TENANT" = 1 ]; then
  wait_status "https://$TENANT_APP_DOMAIN/login" 200 || true
  expect "Mandanten-Domain (app) 200" '[ "$STATUS" = 200 ] && [ "$BODY" = app-ok ]'
  request "https://$TENANT_APP_DOMAIN/api/fail-502"
  expect "Mandanten-Domain API 502 -> JSON-503" 'maintenance_json'
  request "https://$TENANT_APP_DOMAIN/fail-502"
  expect "Mandanten-Domain Frontend 502 -> Wartungsseite (hocx)" 'maintenance_html hocx'
  request "https://$TENANT_BOX_DOMAIN/fail-502"
  expect "Mandanten-Domain Abgabebox 502 -> Wartungsseite (abgabebox)" 'maintenance_html abgabebox'
fi
request "https://$DOMAIN/api/fail-503"
expect "503 des Backends (Überlast) bleibt unverändert" '[ "$STATUS" = 503 ] && grep -q overloaded <<< "$BODY" && [ -z "$(header X-Hocx-Maintenance-Page)" ] && [ "$(header Retry-After)" = 7 ]'
request "https://$DOMAIN/api/fail-502"
expect "Backend 502 -> JSON-503 mit Retry-After" 'maintenance_json'
request "https://$ABG_DOMAIN/api/public/fail-502" -X POST --data x
expect "Abgabebox-API 502 (POST) -> JSON-503" 'maintenance_json'
request "https://$DOMAIN/fail-502"
expect "Frontend 502 -> Wartungsseite 503 (hocx)" 'maintenance_html hocx'
expect "Wartungsseite: CSP mit Skript-Hash" '[[ "$(header Content-Security-Policy)" == *"script-src '"'"'sha256-"* ]]'
expect "Wartungsseite: Tokens eingebettet" 'grep -q -- "--accent:" <<< "$BODY" && ! grep -q "<!--#" <<< "$BODY"'
expect "Wartungsseite: HSTS vom Entrypoint" '[ -n "$(header Strict-Transport-Security)" ]'
expect "Wartungsseite: setzt keine Cookies" '[ -z "$(header Set-Cookie)" ]'
request "https://$ADMIN_DOMAIN/fail-502"
expect "Admin-Frontend 502 -> Wartungsseite (admin)" 'maintenance_html admin && grep -q "data-health=\"/api/admin/auth/oidc/public-config\"" <<< "$BODY"'
request "https://$ABG_DOMAIN/fail-502"
expect "Abgabebox-Frontend 502 -> Wartungsseite (abgabebox)" 'maintenance_html abgabebox'

echo "==> Backend gestoppt"
"${DC[@]}" stop backend > /dev/null 2>&1
wait_status "https://$DOMAIN/api/health" 503 || true
expect "/api/health -> JSON-503 (nie 200)" 'maintenance_json'
request "https://$DOMAIN/api/system-status/summary"
expect "/api/system-status/summary -> JSON-503" 'maintenance_json'
request "https://$DOMAIN/login"
expect "Frontend läuft weiter (200)" '[ "$STATUS" = 200 ]'
request "https://$ADMIN_DOMAIN/api/admin/auth/oidc/public-config"
expect "Admin-API -> JSON-503" 'maintenance_json'
# shellcheck source=scripts/lib/traefik_checks.sh
source scripts/lib/traefik_checks.sh
export HOCX_VERIFY_CA_FILE="$WORK/ca.crt"
if probe_domain "https://$DOMAIN:$WEB_PORT/api/health" 2> /dev/null; then
  echo "    FEHLER: traefik_checks zählt die Wartungsseite als erreichbar" >&2
  failures=$((failures + 1))
else
  echo "    ok: traefik_checks (probe_domain) meldet die Wartungsseite als NICHT erreichbar"
fi

echo "==> Alle App-Container gestoppt"
"${DC[@]}" stop frontend abgabebox-frontend abgabebox-backend > /dev/null 2>&1
wait_status "https://$DOMAIN/login" 503 || true
expect "Hauptdomain -> Wartungsseite 503 (Ausweich-Router)" 'maintenance_html hocx'
request "https://$DOMAIN/" -I
expect "HEAD -> 503 mit Kennung" '[ "$STATUS" = 503 ] && [ "$(header X-Hocx-Maintenance-Page)" = 1 ]'
request "https://$DOMAIN/api/auth/login" -X POST --data '{}'
expect "POST /api/auth/login -> JSON-503" 'maintenance_json'
head -c 2048 /dev/urandom > "$WORK/upload-2k.bin"
head -c 5242880 /dev/urandom > "$WORK/upload-5m.bin"
request "https://$ABG_DOMAIN/api/public/x/upload" -X POST -H 'Content-Type: application/octet-stream' --data-binary "@$WORK/upload-2k.bin"
expect "Upload 2 KiB (Ausweich-Router) -> JSON-503, nicht 413" 'maintenance_json'
request "https://$ABG_DOMAIN/api/public/x/upload" -X POST -F "files=@$WORK/upload-5m.bin"
expect "Upload 5 MB multipart (Ausweich-Router) -> JSON-503, nicht 413" 'maintenance_json'
request "https://$DOMAIN/fotos" -X POST --data-binary "@$WORK/upload-5m.bin"
expect "POST 5 MB auf HTML-Pfad -> Wartungsseite 503" 'maintenance_html hocx'
request "https://$ADMIN_DOMAIN/admin/tenants"
expect "Admin -> Wartungsseite (admin)" 'maintenance_html admin'
request "https://$ABG_DOMAIN/abc"
expect "Abgabebox -> Wartungsseite (abgabebox)" 'maintenance_html abgabebox'
request "https://$ABG_DOMAIN/api/public/maintenance-status"
expect "Abgabebox-API -> JSON-503" 'maintenance_json'
if [ "$TENANT" = 1 ]; then
  request "https://$TENANT_APP_DOMAIN/login"
  expect "Mandanten-Domain (app) -> Wartungsseite (Ausweich-Router)" 'maintenance_html hocx'
  request "https://$TENANT_APP_DOMAIN/api/health"
  expect "Mandanten-Domain API -> JSON-503" 'maintenance_json'
  request "https://$TENANT_BOX_DOMAIN/x"
  expect "Mandanten-Domain Abgabebox -> Wartungsseite (abgabebox)" 'maintenance_html abgabebox'
fi
if probe_domain "https://$DOMAIN:$WEB_PORT/login" 2> /dev/null; then
  echo "    FEHLER: traefik_checks zählt die Wartungsseite als erreichbar" >&2
  failures=$((failures + 1))
else
  echo "    ok: traefik_checks meldet die Hauptdomain als NICHT erreichbar"
fi

echo "==> Wieder gestartet"
"${DC[@]}" start backend frontend abgabebox-frontend abgabebox-backend > /dev/null 2>&1
wait_status "https://$DOMAIN/login" 200 || true
expect "Frontend wieder 200" '[ "$STATUS" = 200 ] && [ "$BODY" = app-ok ]'
wait_status "https://$DOMAIN/api/health" 200 || true
expect "/api/health wieder 200 vom Backend" '[ "$STATUS" = 200 ] && [ "$BODY" = app-ok ]'
wait_status "https://$ABG_DOMAIN/" 200 || true
expect "Abgabebox wieder 200" '[ "$STATUS" = 200 ]'
if [ "$TENANT" = 1 ]; then
  wait_status "https://$TENANT_APP_DOMAIN/login" 200 || true
  expect "Mandanten-Domain wieder 200" '[ "$STATUS" = 200 ]'
fi
if probe_domain "https://$DOMAIN:$WEB_PORT/login" 2> /dev/null; then
  echo "    ok: traefik_checks meldet die Hauptdomain wieder als erreichbar"
else
  echo "    FEHLER: traefik_checks nach Neustart nicht erreichbar" >&2
  failures=$((failures + 1))
fi

echo "==> Wartungsseite gestoppt: App läuft unverändert"
"${DC[@]}" stop maintenance-page > /dev/null 2>&1
sleep 3
request "https://$DOMAIN/login"
expect "Frontend weiter 200" '[ "$STATUS" = 200 ]'
request "https://$DOMAIN/api/health"
expect "Backend weiter 200" '[ "$STATUS" = 200 ]'
request "https://$DOMAIN/api/fail-502"
expect "502 ohne Wartungsseite bleibt ein Fehler (kein 200)" '[ "$STATUS" -ge 500 ]'

if [ "$failures" -gt 0 ]; then
  echo "maintenance live tests: $failures Fehler" >&2
  "${DC[@]}" logs --tail 30 traefik maintenance-page >&2 || true
  exit 1
fi
echo "maintenance live tests: ok"
