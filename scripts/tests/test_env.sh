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
# shellcheck disable=SC2016  # Literale Suchmuster, $(...) soll hier nicht expandieren
grep -q 'write_env_value HOCX_ENVIRONMENT "$(app_environment_for "$ENVIRONMENT")"' "$REPO_DIR/scripts/deploy.sh"
# shellcheck disable=SC2016
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
test "$AUTH_SECRET" = 'a\nb' || { printf '%s\n' "Literales \\n wurde falsch entschluesselt: '$AUTH_SECRET'" >&2; exit 1; }
test "$ADMIN_AUTH_SECRET" = $'zeile1\nzeile2'
test "$INITIAL_ADMIN_PASSWORD" = "bleibt # wie es ist"
# Wie Compose: ohne Wert davor ist '#' kein Kommentar.
test "$TRAEFIK_DOMAIN" = "# nur Kommentar"

# MAIN-OPS-016: Prod akzeptiert nur Release-Tags, Test auch Candidate-Tags.
require_release_version_for prod v1.2.3
require_release_version_for prod 1.2.3
require_release_version_for test test-20260825-abc1234-r42
if require_release_version_for prod test-20260825-abc1234-r42 2> /dev/null; then
  echo "Candidate-Tag wurde auf Prod akzeptiert." >&2
  exit 1
fi
# shellcheck disable=SC2016
grep -q 'require_release_version_for "$ENVIRONMENT" "$HOCX_VERSION"' "$REPO_DIR/scripts/deploy.sh"

# Release-Manifeste (.releases/*.env) laufen durch denselben Loader. Jeder Schluessel, den
# deploy.sh hineinschreibt, muss erlaubt sein - sonst brechen Deploy und Rollback ab
# (1.2.0: HOCX_BACKEND_WORKERS fehlte in der Allowlist).
DEPLOY="$REPO_DIR/scripts/deploy.sh"
manifest_keys="$(grep -oE "printf \"[A-Z_]+=" "$DEPLOY" | sed -E 's/printf "//; s/=$//' | sort -u)"
for service in $(grep -oE 'for service in [a-z -]+; do' "$DEPLOY" | head -n 1 | sed -E 's/for service in //; s/; do//'); do
  variable="HOCX_${service^^}_IMAGE"
  manifest_keys+=$'\n'"${variable//-/_}"
done
grep -q HOCX_BACKEND_WORKERS <<< "$manifest_keys" || { echo "Manifest-Schluessel nicht gefunden" >&2; exit 1; }
while read -r key; do
  is_allowed_env_key "$key" || { echo "Manifest-Schluessel $key ist nicht erlaubt." >&2; exit 1; }
done <<< "$manifest_keys"

# Optionaler lokaler Override wird nur angehaengt, wenn er existiert; Symlinks werden abgelehnt.
override_args=(-f base.yml)
append_local_compose_override "$TEST_DIR" override_args
test "${#override_args[@]}" -eq 2
touch "$TEST_DIR/docker-compose.local.yml"
append_local_compose_override "$TEST_DIR" override_args
test "${override_args[*]}" = "-f base.yml -f $TEST_DIR/docker-compose.local.yml"
rm "$TEST_DIR/docker-compose.local.yml"
ln -s /dev/null "$TEST_DIR/docker-compose.local.yml"
if append_local_compose_override "$TEST_DIR" override_args 2> /dev/null; then
  echo "Symlink als lokaler Override akzeptiert." >&2
  exit 1
fi
rm "$TEST_DIR/docker-compose.local.yml"

# Besitzpruefung: Laufzeitverzeichnisse zaehlen nicht, alles andere schon.
OWN_DIR="$TEST_DIR/own"
mkdir -p "$OWN_DIR/storage" "$OWN_DIR/frontend"
touch "$OWN_DIR/frontend/page.tsx" "$OWN_DIR/storage/upload.bin"
require_repo_owned_by_current_user "$OWN_DIR"
if [ "$EUID" -eq 0 ]; then
  chown 4242 "$OWN_DIR/storage/upload.bin"
  require_repo_owned_by_current_user "$OWN_DIR"
  chown 4242 "$OWN_DIR/frontend/page.tsx"
  if require_repo_owned_by_current_user "$OWN_DIR" 2> /dev/null; then
    echo "Fremde Datei im Checkout wurde nicht erkannt." >&2
    exit 1
  fi
fi
# shellcheck disable=SC2016
grep -q 'require_repo_owned_by_current_user "$REPO_DIR"' "$DEPLOY"
# shellcheck disable=SC2016
grep -q 'require_repo_owned_by_current_user "$REPO_DIR"' "$REPO_DIR/scripts/update_deploy_code.sh"

# Candidate-Tags verlangen Deploy-Code, der den gebauten Commit enthaelt.
if git -C "$REPO_DIR" rev-parse --git-dir > /dev/null 2>&1; then
  head_sha="$(git -C "$REPO_DIR" rev-parse --short=7 HEAD)"
  require_deploy_code_for_version "$REPO_DIR" "test-20261024-${head_sha}-r1"
  if require_deploy_code_for_version "$REPO_DIR" test-20261024-0000000-r1 2> /dev/null; then
    echo "Unbekannter Candidate-Commit wurde akzeptiert." >&2
    exit 1
  fi
fi
require_deploy_code_for_version "$REPO_DIR" v1.2.3
# shellcheck disable=SC2016
grep -q 'require_deploy_code_for_version "$REPO_DIR" "$HOCX_VERSION"' "$DEPLOY"

echo "env loader tests: ok"
