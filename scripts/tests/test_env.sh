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

echo "env loader tests: ok"
