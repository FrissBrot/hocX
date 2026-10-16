#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=scripts/lib/env.sh
source "$REPO_DIR/scripts/lib/env.sh"

TEST_DIR="$(mktemp -d)"
trap 'rm -rf "$TEST_DIR"' EXIT
ENV_FILE="$TEST_DIR/test.env"
MARKER="$TEST_DIR/must-not-exist"

printf "POSTGRES_DB='hocx test'\nAUTH_SECRET='\$(touch %s)'\n" "$MARKER" > "$ENV_FILE"
chmod 600 "$ENV_FILE"
load_env_file "$ENV_FILE"
test "$POSTGRES_DB" = "hocx test"
test "$AUTH_SECRET" = "\$(touch $MARKER)"
test ! -e "$MARKER"

printf "APP_DB_PASSWORD='s3cret'\nAPP_DATABASE_URL='postgresql+psycopg://hocx_app:s3cret@db:5432/hocx'\n" > "$ENV_FILE"
chmod 600 "$ENV_FILE"
load_env_file "$ENV_FILE"
test "$APP_DB_PASSWORD" = "s3cret"
test "$APP_DATABASE_URL" = "postgresql+psycopg://hocx_app:s3cret@db:5432/hocx"

# Jede Variable aus .env.example muss load_env_file passieren, sonst bricht deploy.sh auf
# Servern ab, die sie gesetzt haben.
grep -E '^[A-Z_][A-Z0-9_]*=' "$REPO_DIR/.env.example" | cut -d= -f1 | while read -r key; do
  is_allowed_env_key "$key" || { echo "Variable $key aus .env.example ist nicht erlaubt." >&2; exit 1; }
done

printf 'PATH=/attacker-controlled\n' > "$ENV_FILE"
chmod 600 "$ENV_FILE"
if load_env_file "$ENV_FILE" 2> /dev/null; then
  echo "Nicht erlaubte Variable wurde akzeptiert." >&2
  exit 1
fi

printf 'POSTGRES_DB=hocx\n' > "$ENV_FILE"
chmod 644 "$ENV_FILE"
if load_env_file "$ENV_FILE" 2> /dev/null; then
  echo "Unsichere Dateirechte wurden akzeptiert." >&2
  exit 1
fi

chmod 600 "$ENV_FILE"
ln -s "$ENV_FILE" "$TEST_DIR/symlink.env"
if load_env_file "$TEST_DIR/symlink.env" 2> /dev/null; then
  echo "Symlink wurde akzeptiert." >&2
  exit 1
fi

ENVIRONMENT_MARKER="$TEST_DIR/environment"
printf 'prod\n' > "$ENVIRONMENT_MARKER"
chmod 444 "$ENVIRONMENT_MARKER"
test "$(read_host_environment "$ENVIRONMENT_MARKER")" = prod
require_host_environment prod "$ENVIRONMENT_MARKER"
if require_host_environment test "$ENVIRONMENT_MARKER" 2> /dev/null; then
  echo "Falsche Host-Umgebung wurde akzeptiert." >&2
  exit 1
fi
if require_unprovisioned_dev_host "$ENVIRONMENT_MARKER" 2> /dev/null; then
  echo "Dev wurde auf provisioniertem Host akzeptiert." >&2
  exit 1
fi

# MAIN-OPS-001: Host-Umgebung prod -> Anwendungswert production; 'prod' bleibt als Alias gueltig.
test "$(app_environment_for prod)" = production
test "$(app_environment_for production)" = production
test "$(app_environment_for test)" = test
# deploy.sh schreibt den kanonischen Wert und vergleicht im Preflight ueber dieselbe Abbildung.
grep -q 'write_env_value HOCX_ENVIRONMENT "$(app_environment_for "$ENVIRONMENT")"' "$REPO_DIR/scripts/deploy.sh"
grep -q 'app_environment_for "${HOCX_ENVIRONMENT:-}"' "$REPO_DIR/scripts/deploy.sh"
grep -q '^HOCX_ENVIRONMENT=production$' "$REPO_DIR/.env.prod.example"


# MAIN-OPS-015: Werte wie der dotenv-Parser von Compose lesen.
printf '%s\n' \
  'POSTGRES_DB=hocx # Kommentar # noch einer' \
  'POSTGRES_USER=  hocx_user   ' \
  'POSTGRES_PASSWORD=abc#def' \
  'AUTH_SECRET="a\\nb"' \
  'ADMIN_AUTH_SECRET="zeile1\nzeile2"' \
  "INITIAL_ADMIN_PASSWORD='bleibt # wie es ist'" \
  'TRAEFIK_DOMAIN= # nur Kommentar' > "$ENV_FILE"
chmod 600 "$ENV_FILE"
load_env_file "$ENV_FILE"
test "$POSTGRES_DB" = "hocx" || { echo "Inline-Kommentar wurde nicht entfernt: '$POSTGRES_DB'" >&2; exit 1; }
test "$POSTGRES_USER" = "hocx_user"
test "$POSTGRES_PASSWORD" = "abc#def"
test "$AUTH_SECRET" = 'a\nb' || { echo "Literales \\\\n wurde falsch entschluesselt: '$AUTH_SECRET'" >&2; exit 1; }
test "$ADMIN_AUTH_SECRET" = $'zeile1\nzeile2'
test "$INITIAL_ADMIN_PASSWORD" = "bleibt # wie es ist"
# Wie Compose: ohne Wert davor ist '#' kein Kommentar.
test "$TRAEFIK_DOMAIN" = "# nur Kommentar"

echo "env loader tests: ok"
