#!/usr/bin/env bash
set -euo pipefail

# Startet in der CI ein echtes Garage (wie test-s3 in docker-compose.tests.yml) und schreibt
# LOCAL_S3_*, TEST_S3_* und STORAGE_CREDENTIALS_KEY nach $GITHUB_ENV. Die Schlüssel werden je
# Lauf zufällig erzeugt und maskiert (SECURITY-RULES §5.1).
#
# Garage läuft im Host-Netz, weil die Admin-API nur auf 127.0.0.1 lauscht. Die S3-Endpunkte
# zeigen aber auf die private IP des Runners, nicht auf 127.0.0.1: der S3-Client sperrt
# Loopback-Ziele bewusst (S3-009, objstore_client.resolve_allowed_address). Private Netze
# bleiben erlaubt, wie bei test-s3 im Compose-Netz.

: "${GITHUB_ENV:?nur in GitHub Actions}"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
GARAGE_IMAGE="dxflrs/garage:v2.5.0@sha256:677e5b758e4425a325b811c425c026bf35a4bf42f7ddbaa773de3f4fd779a5a5"

host_ip="$(ip -4 route get 1.1.1.1 | awk '{for (i = 1; i < NF; i++) if ($i == "src") { print $(i + 1); exit }}')"
if [ -z "$host_ip" ]; then
  echo "Keine private IP des Runners gefunden." >&2
  exit 1
fi
endpoint="http://$host_ip:3900"

storage_key="$(openssl rand -hex 32)"; admin_token="$(openssl rand -hex 32)"; rpc_secret="$(openssl rand -hex 32)"
main_key="GK$(openssl rand -hex 12)"; main_secret="$(openssl rand -hex 32)"
box_key="GK$(openssl rand -hex 12)"; box_secret="$(openssl rand -hex 32)"
for value in "$storage_key" "$admin_token" "$rpc_secret" "$main_key" "$main_secret" "$box_key" "$box_secret"; do
  echo "::add-mask::$value"
done
{
  echo "STORAGE_CREDENTIALS_KEY=$storage_key"
  echo "LOCAL_S3_ENDPOINT=$endpoint"
  echo "LOCAL_S3_BUCKET=hocx-main"
  echo "LOCAL_S3_ABGABEBOX_BUCKET=hocx-abgabebox"
  echo "LOCAL_S3_ACCESS_KEY=$main_key"
  echo "LOCAL_S3_SECRET_KEY=$main_secret"
  echo "LOCAL_S3_ABGABEBOX_ACCESS_KEY=$box_key"
  echo "LOCAL_S3_ABGABEBOX_SECRET_KEY=$box_secret"
  echo "TEST_S3_ENDPOINT=$endpoint"
  echo "TEST_S3_ACCESS_KEY=$main_key"
  echo "TEST_S3_SECRET_KEY=$main_secret"
  echo "TEST_S3_ABGABEBOX_ACCESS_KEY=$box_key"
  echo "TEST_S3_ABGABEBOX_SECRET_KEY=$box_secret"
} >> "$GITHUB_ENV"

docker run -d --name ci-s3 --network host \
  -e GARAGE_RPC_SECRET="$rpc_secret" -e GARAGE_ADMIN_TOKEN="$admin_token" \
  -v "$REPO_DIR/infra/garage/garage.toml:/etc/garage.toml:ro" --tmpfs /var/lib/garage \
  "$GARAGE_IMAGE" > /dev/null
for _ in $(seq 1 30); do
  docker exec ci-s3 /garage status > /dev/null 2>&1 && break
  sleep 2
done
GARAGE_ADMIN_URL=http://127.0.0.1:3903 GARAGE_ADMIN_TOKEN="$admin_token" GARAGE_CAPACITY=1G \
  LOCAL_S3_BUCKET=hocx-main LOCAL_S3_ABGABEBOX_BUCKET=hocx-abgabebox \
  LOCAL_S3_ACCESS_KEY="$main_key" LOCAL_S3_SECRET_KEY="$main_secret" \
  LOCAL_S3_ABGABEBOX_ACCESS_KEY="$box_key" LOCAL_S3_ABGABEBOX_SECRET_KEY="$box_secret" \
  python3 "$REPO_DIR/infra/garage/bootstrap.py"

# Erreichbarkeit über die private IP prüfen (anonym: 403 ist die erwartete Antwort von Garage).
status="$(python3 -c "import sys, urllib.request, urllib.error
try:
    urllib.request.urlopen(sys.argv[1], timeout=5)
    print(200)
except urllib.error.HTTPError as exc:
    print(exc.code)
except OSError as exc:
    print(exc)" "$endpoint/")"
case "$status" in
  200|403) echo "Garage erreichbar unter $endpoint" ;;
  *) echo "Garage unter $endpoint nicht erreichbar: $status" >&2; exit 1 ;;
esac
