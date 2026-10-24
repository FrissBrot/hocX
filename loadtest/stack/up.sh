#!/usr/bin/env bash
# Isolierten Lasttest-Stack aus dem aktuellen Checkout bauen und starten (loadtest/README.md).
#
# - eigenes Compose-Projekt (Default hocx-loadtest), eigenes Projektverzeichnis mit .env,
#   Secrets, Storage und einer Kopie von infra/ (das Backend schreibt in infra/traefik/dynamic)
# - Release-Compose + ClamAV + docker-compose.loadtest.yml, Images lokal aus diesem Commit
# - nur die für die Szenarien nötigen Dienste (kein Frontend, Backup-, Storage-, Dokument- und
#   Foto-Worker) - spart auf einem geteilten Host Speicher; im Ergebnis vermerken
#
# Usage: LT_DIR=/pfad loadtest/stack/up.sh        (Default: /docker/loadtest-stack)
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LT_PROJECT="${LT_PROJECT:-hocx-loadtest}"
LT_DIR="${LT_DIR:-/docker/loadtest-stack}"
SERVICES=(db redis docker-socket-proxy local-s3 storage-init clamav backend job-worker abgabebox-backend)
SHA="$(git -C "$REPO_DIR" rev-parse --short HEAD)"

case "$LT_PROJECT" in *loadtest*) ;; *) echo "LT_PROJECT muss 'loadtest' enthalten" >&2; exit 1 ;; esac

mkdir -p "$LT_DIR"
cd "$LT_DIR"

if [[ ! -f .env ]]; then
  hex() { openssl rand -hex 32; }
  pg="$(hex)"; app="$(hex)"; abg="$(hex)"; photo="$(hex)"
  umask 077
  cat > .env <<ENV
COMPOSE_PROJECT_NAME=$LT_PROJECT
HOCX_ENVIRONMENT=test
HOCX_VERSION=loadtest-$SHA
GHCR_NAMESPACE=local
ROUTER_PREFIX=$LT_PROJECT
POSTGRES_DB=hocx_loadtest
POSTGRES_USER=hocx
POSTGRES_PASSWORD=$pg
DATABASE_URL=postgresql+psycopg://hocx:$pg@db:5432/hocx_loadtest
APP_DB_PASSWORD=$app
APP_DATABASE_URL=postgresql+psycopg://hocx_app:$app@db:5432/hocx_loadtest
ABGABEBOX_DB_PASSWORD=$abg
ABGABEBOX_DATABASE_URL=postgresql+psycopg://hocx_abgabebox:$abg@db:5432/hocx_loadtest
PHOTO_WORKER_DB_PASSWORD=$photo
PHOTO_WORKER_DATABASE_URL=postgresql+psycopg://hocx_photo_worker:$photo@db:5432/hocx_loadtest
AUTH_SECRET=$(hex)
ADMIN_AUTH_SECRET=$(hex)
INITIAL_ADMIN_EMAIL=admin@loadtest.invalid
INITIAL_ADMIN_PASSWORD=$(hex)
REDIS_PASSWORD=$(hex)
TRAEFIK_DOMAIN=lt.invalid
TRAEFIK_ADMIN_DOMAIN=admin.lt.invalid
TRAEFIK_ABGABEBOX_DOMAIN=abgabe.lt.invalid
TRAEFIK_DOCS_DOMAIN=docs.lt.invalid
NEXT_PUBLIC_API_URL=http://lt.invalid
INTERNAL_API_URL=http://backend:8000
AUTH_SECURE_COOKIES=false
FRIENDLY_CAPTCHA_SITEKEY=
FRIENDLY_CAPTCHA_API_KEY=
ABGABEBOX_CAPTCHA_SESSION_SECRET=$(hex)
DEMO_TOTP_SEED=JBSWY3DPEHPK3PXP
STORAGE_CREDENTIALS_KEY=$(hex)
EXPORT_ENCRYPTION_KEY=$(hex)
GARAGE_RPC_SECRET=$(hex)
GARAGE_ADMIN_TOKEN=$(hex)
LOCAL_S3_ACCESS_KEY=GK$(openssl rand -hex 12)
LOCAL_S3_SECRET_KEY=$(hex)
LOCAL_S3_ABGABEBOX_ACCESS_KEY=GK$(openssl rand -hex 12)
LOCAL_S3_ABGABEBOX_SECRET_KEY=$(hex)
BACKUP_ENABLED=false
HOCX_BACKEND_IMAGE=$LT_PROJECT-backend:$SHA
HOCX_ABGABEBOX_BACKEND_IMAGE=$LT_PROJECT-abgabebox-backend:$SHA
ENV
  umask 022
fi
# Images immer zum aktuellen Commit
sed -i -E "s|^HOCX_BACKEND_IMAGE=.*|HOCX_BACKEND_IMAGE=$LT_PROJECT-backend:$SHA|; s|^HOCX_ABGABEBOX_BACKEND_IMAGE=.*|HOCX_ABGABEBOX_BACKEND_IMAGE=$LT_PROJECT-abgabebox-backend:$SHA|; s|^HOCX_VERSION=.*|HOCX_VERSION=loadtest-$SHA|" .env

set -a
# shellcheck source=/dev/null
. ./.env
set +a

# Secret-Dateien wie deploy.sh (0644 in einem 0700-Verzeichnis)
mkdir -p .secrets && chmod 700 .secrets
secret() { printf '%s' "$2" > ".secrets/$1"; chmod 644 ".secrets/$1"; }
secret postgres_password "$POSTGRES_PASSWORD"; secret database_url "$DATABASE_URL"
secret app_database_url "$APP_DATABASE_URL"; secret app_db_password "$APP_DB_PASSWORD"
secret auth_secret "$AUTH_SECRET"; secret admin_auth_secret "$ADMIN_AUTH_SECRET"
secret initial_admin_password "$INITIAL_ADMIN_PASSWORD"
secret abgabebox_db_password "$ABGABEBOX_DB_PASSWORD"; secret abgabebox_database_url "$ABGABEBOX_DATABASE_URL"
secret photo_worker_db_password "$PHOTO_WORKER_DB_PASSWORD"; secret photo_worker_database_url "$PHOTO_WORKER_DATABASE_URL"
secret friendly_captcha_api_key ""; secret abgabebox_captcha_session_secret "$ABGABEBOX_CAPTCHA_SESSION_SECRET"
secret cf_dns_api_token ""; secret storage_credentials_key "$STORAGE_CREDENTIALS_KEY"
secret export_encryption_key "$EXPORT_ENCRYPTION_KEY"; secret garage_rpc_secret "$GARAGE_RPC_SECRET"
secret garage_admin_token "$GARAGE_ADMIN_TOKEN"; secret local_s3_secret_key "$LOCAL_S3_SECRET_KEY"
secret local_s3_abgabebox_secret_key "$LOCAL_S3_ABGABEBOX_SECRET_KEY"; secret redis_password "$REDIS_PASSWORD"
secret backup_passphrase ""; secret backup_ssh_key ""; secret backup_known_hosts ""

# infra/ als Kopie (Backend schreibt Traefik-Konfiguration), Laufzeitverzeichnisse für uid 5000/gid 5001
rm -rf infra && cp -r "$REPO_DIR/infra" infra
mkdir -p storage/abgabebox-uploads storage-local/thumbnails storage-local/work backups/storage backups/borg-work results
chgrp -R 5001 storage storage-local infra/traefik/dynamic backups
chmod -R g+rwX,o-rwx storage storage-local infra/traefik/dynamic backups
find storage storage-local infra/traefik/dynamic backups -type d -exec chmod g+s {} +

echo "==> Images bauen ($SHA)"
docker build -q -t "$HOCX_BACKEND_IMAGE" "$REPO_DIR/backend" >/dev/null
docker build -q -t "$HOCX_ABGABEBOX_BACKEND_IMAGE" "$REPO_DIR/abgabebox-backend" >/dev/null

DC=(docker compose -p "$LT_PROJECT" --project-directory "$LT_DIR" --env-file "$LT_DIR/.env"
    -f "$REPO_DIR/docker-compose.release.yml" -f "$REPO_DIR/docker-compose.clamav.yml"
    -f "$REPO_DIR/loadtest/stack/docker-compose.loadtest.yml")
{ echo '#!/usr/bin/env bash'; printf 'exec'; printf ' %q' "${DC[@]}"; echo ' "$@"'; } > "$LT_DIR/dc.sh"
chmod +x "$LT_DIR/dc.sh"

echo "==> Datenbank und Objektspeicher"
"${DC[@]}" up -d db redis local-s3
"${DC[@]}" up storage-init
"${DC[@]}" run --rm --no-deps backend alembic upgrade head

echo "==> Dienste starten"
"${DC[@]}" up -d "${SERVICES[@]}"
for _ in $(seq 1 90); do
  if docker exec "$LT_PROJECT-backend-1" python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health', timeout=5)" 2>/dev/null; then
    echo "Backend bereit. Compose-Aufruf: $LT_DIR/dc.sh"; exit 0
  fi
  sleep 2
done
echo "Backend nicht bereit" >&2; exit 1
