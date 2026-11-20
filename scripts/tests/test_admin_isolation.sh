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
grep -q '^if ! write_admin_gate_traefik_config; then$' scripts/deploy.sh || fail "deploy.sh schreibt admin-gate.yml nicht"
for example in .env.prod.example .env.test.example; do
  grep -q '^ADMIN_GATE_SECRET=' "$example" || fail "$example ohne ADMIN_GATE_SECRET"
done

# 4b. Quellcode-Stack (docker-compose.yml) angeglichen: Admin-Router mit admin-gate@file, Secret nur
#     fürs Backend, öffentliche Router ohne Admin-Pfade.
for router in hocx-admin-api hocx-admin-auth hocx-tenant-import hocx-admin-frontend; do
  grep -qE "traefik\.http\.routers\.$router\.middlewares=.*admin-gate@file" docker-compose.yml ||
    fail "docker-compose.yml: $router ohne admin-gate@file"
done
# Mit gesetztem Secret (env_file .env wäre die ganze .env - simuliert über --env-file): nur das Backend.
gate_env="$(mktemp)"
cp .env.e2e.example "$gate_env"
printf 'ADMIN_GATE_SECRET=%s\n' "$(printf 'g%.0s' {1..40})" >> "$gate_env"
docker compose -p admiso-src --env-file "$gate_env" -f docker-compose.yml config --format json | python3 -c '
import json, sys
services = json.load(sys.stdin)["services"]
users = sorted(n for n, s in services.items() if (s.get("environment") or {}).get("ADMIN_GATE_SECRET"))
assert users == ["backend"], f"ADMIN_GATE_SECRET bei: {users}"
'
rm -f "$gate_env"

# 5. scripts/lib/admin_gate.sh: Datei mit korrektem YAML, Rechten 0640, ungültige Werte abgelehnt.
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
mkdir -p "$work/infra/traefik/dynamic"
grep -q '^if ! write_admin_gate_traefik_config; then$' scripts/deploy.sh || fail "deploy.sh schreibt admin-gate.yml nicht"
grep -q 'scripts/lib/admin_gate.sh' scripts/verify_release.sh || fail "verify_release.sh prüft admin-gate.yml nicht"
grep -q 'admin_gate_traefik_config_check' scripts/verify_release.sh || fail "verify_release.sh prüft admin-gate.yml nicht"
(
  # shellcheck source=scripts/lib/admin_gate.sh
  source scripts/lib/admin_gate.sh
  # shellcheck disable=SC2034  # von den Funktionen gelesen (PROJECT_DIR, HOCX_ADMIN_SOURCE_CIDRS)
  PROJECT_DIR="$work"
  ADMIN_GATE_SECRET="$(printf 'a%.0s' {1..64})"
  export HOCX_ADMIN_SOURCE_CIDRS="172.31.0.1/32"
  write_admin_gate_traefik_config > /dev/null
  file="$work/infra/traefik/dynamic/admin-gate.yml"
  [ "$(stat -c '%a' "$file")" = 640 ] || fail "admin-gate.yml hat Modus $(stat -c '%a' "$file")"
  grep -q "^          X-Hocx-Admin-Gate: '$ADMIN_GATE_SECRET'$" "$file" || fail "admin-gate.yml ohne Header"
  grep -q '^    admin-gate:$' "$file" || fail "admin-gate.yml ohne Middleware admin-gate"
  # Review M1: admin-gate ist eine Kette aus Quellbeschränkung und Header
  grep -A4 '^    admin-gate:$' "$file" | grep -q -- '- admin-gate-source' || fail "admin-gate ohne Quellbeschränkung"
  grep -A3 '^    admin-gate-source:$' "$file" | grep -q "'172.31.0.1/32'" || fail "Quelladresse fehlt"
  # Review: kein /0 und keine Riesennetze (IPv4 >= /16, IPv6 >= /48)
  for bad_cidr in "0.0.0.0/0" "::/0" "10.0.0.0/8" "10.0.0.0/15" "fd00::/32" "x" "172.31.0.1/32;x" "1.2.3.4/33"; do
    HOCX_ADMIN_SOURCE_CIDRS="$bad_cidr"
    if write_admin_gate_traefik_config > /dev/null 2>&1; then fail "ungültige Quelladresse angenommen: $bad_cidr"; fi
  done
  for good_cidr in "172.31.0.1/32" "10.20.0.0/16" "fd00:1::/48" "172.31.0.1/32,fd00::1/128"; do
    HOCX_ADMIN_SOURCE_CIDRS="$good_cidr"
    write_admin_gate_traefik_config > /dev/null || fail "gültige Quelladresse abgelehnt: $good_cidr"
  done
  HOCX_ADMIN_SOURCE_CIDRS="172.31.0.1/32"
  write_admin_gate_traefik_config > /dev/null
  # verify_release.sh: unveränderte Datei ok, veränderte fällt auf
  REPO_DIR="$work" admin_gate_traefik_config_check || fail "frisch geschriebene admin-gate.yml gilt als abweichend"
  printf '# manipuliert\n' >> "$file"
  if REPO_DIR="$work" admin_gate_traefik_config_check 2> /dev/null; then fail "veränderte admin-gate.yml nicht erkannt"; fi
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
