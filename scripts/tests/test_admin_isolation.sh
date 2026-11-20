#!/usr/bin/env bash
# Auth-Audit SEC-AUTH-001: Plattform-Admin nur über die Admin-Domain auf dem Admin-Entrypoint.
# Statische Prüfung der Release-Konfiguration (läuft in der CI, braucht nur docker compose und
# python3 ohne Zusatzpakete). Der Live-Test mit echtem Traefik: test_admin_isolation_live.sh.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_DIR"

fail() {
  echo "FEHLER: $*" >&2
  exit 1
}

COMPOSE_FILES=(-f docker-compose.release.yml -f docker-compose.clamav.yml -f docker-compose.traefik.yml)

# 1. Router aus den Labels: kein Router ausser den Admin-Routern matcht Admin-Pfade, Admin-Router nur
#    auf adminsecure mit admin-gate@file, Sperr-Router mit höchster Priorität (Regel-Interpreter).
docker compose --env-file .env.prod.example "${COMPOSE_FILES[@]}" config --format json |
  python3 scripts/tests/admin_isolation_check.py

# 2. adminsecure ist auf dem Host nur an 127.0.0.1 gebunden (Ziel des OpenZiti-Tunnels), 80/443 nie
#    auf den Admin-Port.
docker compose --env-file .env.prod.example "${COMPOSE_FILES[@]}" config --format json | python3 -c '
import json, sys
ports = json.load(sys.stdin)["services"]["traefik"]["ports"]
admin = [p for p in ports if int(p["target"]) == 8443]
assert len(admin) == 1 and admin[0].get("host_ip") == "127.0.0.1", f"Admin-Port nicht nur lokal: {admin}"
assert all(int(p["target"]) in (80, 443, 8443) for p in ports), ports
'
grep -q '^  adminsecure:$' infra/traefik/traefik.yml || fail "Entrypoint adminsecure fehlt"
grep -A1 '^  adminsecure:$' infra/traefik/traefik.yml | grep -q 'address: ":8443"' || fail "adminsecure nicht auf :8443"

# 3. Gate-Header: auf websecure und adminsecure zuerst entfernen (web leitet nur um) (traefik.yml), Strip-Middleware mit leerem
#    Wert, das Secret nie im Repo und nie als Label.
for entrypoint in websecure adminsecure; do
  block="$(awk -v ep="  $entrypoint:" '$0 == ep {f=1; next} f && /^  [a-z]+:$/ {f=0} f && !/^[[:space:]]*#/' infra/traefik/traefik.yml)"
  first="$(grep -A1 -E '^      middlewares:$' <<< "$block" | sed -n '2p' | tr -d ' ')"
  [ "$first" = "-admin-gate-strip@file" ] || fail "Entrypoint $entrypoint: admin-gate-strip@file nicht als erste Middleware ($first)"
done
grep -A3 '^    admin-gate-strip:$' infra/traefik/dynamic/admin-isolation.yml | grep -q 'X-Hocx-Admin-Gate: ""' ||
  fail "admin-gate-strip entfernt den Header nicht"
if grep -rqE '^    admin-gate:$' infra/traefik/dynamic/ --include='*.yml' --exclude='admin-gate.yml' 2> /dev/null; then
  fail "Middleware admin-gate (mit Secret) gehört nicht ins Repo"
fi
git ls-files --error-unmatch infra/traefik/dynamic/admin-gate.yml > /dev/null 2>&1 && fail "admin-gate.yml ist eingecheckt"
git check-ignore -q infra/traefik/dynamic/admin-gate.yml || fail "admin-gate.yml fehlt in .gitignore"
if grep -q 'X-Hocx-Admin-Gate\|customrequestheaders' docker-compose*.yml; then
  fail "Gate-Header als Label (sichtbar per docker inspect) statt über admin-gate.yml"
fi

# 4. Secret vollständig verdrahtet (SECURITY-RULES §5.2), nur das Backend bekommt es.
docker compose --env-file .env.prod.example "${COMPOSE_FILES[@]}" config --format json | python3 -c '
import json, sys
services = json.load(sys.stdin)["services"]
users = sorted(n for n, s in services.items() if any(x["source"] == "admin_gate_secret" for x in s.get("secrets", [])))
assert users == ["backend"], f"admin_gate_secret bei: {users}"
assert services["backend"]["environment"].get("ADMIN_GATE_SECRET_FILE") == "/run/secrets/admin_gate_secret"
'
grep -q '"ADMIN_GATE_SECRET"' backend/app/core/config.py || fail "config.py: ADMIN_GATE_SECRET ohne _FILE"
grep -q 'ADMIN_GATE_SECRET' scripts/lib/env.sh || fail "env.sh-Allowlist ohne ADMIN_GATE_SECRET"
grep -q 'ADMIN_GATE_SECRET' scripts/lib/env_migrate.sh || fail "env_migrate.sh erzeugt ADMIN_GATE_SECRET nicht"
# shellcheck disable=SC2016  # literale Suchmuster
grep -q 'write_secret_file "$secrets_dir" admin_gate_secret "$ADMIN_GATE_SECRET"' scripts/deploy.sh || fail "deploy.sh: Secret-Datei"
grep -q '^write_admin_gate_traefik_config$' scripts/deploy.sh || fail "deploy.sh schreibt admin-gate.yml nicht"
for example in .env.prod.example .env.test.example; do
  grep -q '^ADMIN_GATE_SECRET=' "$example" || fail "$example ohne ADMIN_GATE_SECRET"
done

# 5. deploy.sh-Funktion: Datei mit korrektem YAML, Rechten 0660, ungültige Werte abgelehnt.
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
mkdir -p "$work/infra/traefik/dynamic"
fn="$(sed -n '/^write_admin_gate_traefik_config() {$/,/^}$/p' scripts/deploy.sh)"
[ -n "$fn" ] || fail "write_admin_gate_traefik_config nicht gefunden"
(
  eval "$fn"
  # shellcheck disable=SC2034  # von der Funktion gelesen
  PROJECT_DIR="$work"
  ADMIN_GATE_SECRET="$(printf 'a%.0s' {1..64})"
  write_admin_gate_traefik_config > /dev/null
  file="$work/infra/traefik/dynamic/admin-gate.yml"
  [ "$(stat -c '%a' "$file")" = 660 ] || fail "admin-gate.yml hat Modus $(stat -c '%a' "$file")"
  grep -q "^          X-Hocx-Admin-Gate: '$ADMIN_GATE_SECRET'$" "$file" || fail "admin-gate.yml ohne Header"
  grep -q '^    admin-gate:$' "$file" || fail "admin-gate.yml ohne Middleware admin-gate"
  for bad in "" "kurz" "mit'quote-und-genug-zeichen-0123456789abcdef" "$(printf 'a%.0s' {1..40})
zeile"; do
    ADMIN_GATE_SECRET="$bad"
    if write_admin_gate_traefik_config > /dev/null 2>&1; then
      fail "ungültiger Wert angenommen: ${bad:0:20}"
    fi
  done
  [ -z "$(find "$work/infra/traefik/dynamic" -name '.admin-gate.tmp.*')" ] || fail "Temporärdatei liegen geblieben"
)

echo "admin isolation tests: ok"
