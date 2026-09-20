#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_DIR"

COMPOSE_FILES=(
  -f docker-compose.release.yml
  -f docker-compose.clamav.yml
  -f docker-compose.traefik.yml
)

docker compose --env-file .env.prod.example "${COMPOSE_FILES[@]}" config --quiet
docker compose --env-file .env.test.example "${COMPOSE_FILES[@]}" -f docker-compose.test.yml config --quiet
docker compose -p hocx-tests -f docker-compose.tests.yml --profile tests config --quiet
docker compose -p hocx-e2e --env-file .env.e2e.example -f docker-compose.yml -f docker-compose.dev.yml -f docker-compose.e2e.yml config --quiet

if grep -q 'env_file:' docker-compose.release.yml; then
  echo "Release-Services duerfen nicht die komplette .env erhalten." >&2
  exit 1
fi

test "$(grep -c 'read_only: true' docker-compose.release.yml)" -eq 6
test "$(grep -c 'no-new-privileges:true' docker-compose.release.yml)" -eq 6

# Audit finding, 2026-08-27: docker-compose.traefik.yml/docker-compose.clamav.yml (the
# actual prod Traefik/ClamAV - deploy.sh/verify_release.sh never include the base
# docker-compose.yml, so its dev-only hardening for these two never applied to prod) had no
# resource limits or container-hardening at all. Assert both are present here so this class
# of gap gets caught going forward.
for f in docker-compose.traefik.yml docker-compose.clamav.yml; do
  test "$(grep -c 'read_only: true' "$f")" -eq 1
  test "$(grep -c 'no-new-privileges:true' "$f")" -eq 1
  test "$(grep -c 'mem_limit:' "$f")" -eq 1
  # Anchored (unlike the other three greps above) because this file's own comment
  # explaining CAP_DAC_OVERRIDE mentions "cap_drop:ALL" in prose - an unanchored grep
  # double-counts that as a second directive, permanently red long before this diff
  # (found while adding photo-analysis-worker's docker-compose.release.yml entry, which
  # legitimately changed the read_only:true/no-new-privileges:true counts above from 5 to
  # 6 and prompted actually running this test).
  test "$(grep -c '^[[:space:]]*cap_drop:' "$f")" -eq 1
done
grep -q '^USER hocx$' backend/Dockerfile
grep -q '^USER node$' frontend/Dockerfile
grep -q '^USER node$' abgabebox-frontend/Dockerfile
grep -q '^FROM nginxinc/nginx-unprivileged:alpine$' docs-site/Dockerfile
if grep -q 'alembic upgrade head.*uvicorn' backend/Dockerfile; then
  echo "Release-Backend darf Migration und App-Start nicht koppeln." >&2
  exit 1
fi
grep -q 'Deployments als root sind fuer hocX gesperrt' scripts/deploy.sh
grep -q 'DEPLOY_USER="hocx-deploy"' scripts/provision_deploy_user.sh
grep -q 'Usage:.*provision_deploy_user.sh.*test|prod' scripts/provision_deploy_user.sh
grep -q 'git merge --ff-only refs/remotes/origin/main' scripts/update_deploy_code.sh
grep -q 'require_unprovisioned_dev_host' scripts/dev.sh
grep -q 'alembic -x seed_demo=true upgrade head' docker-compose.dev.yml
if grep -q 'seed_demo=true' docker-compose.release.yml scripts/deploy.sh; then
  echo "Release-Pfade duerfen Demo-Seeding nie aktivieren." >&2
  exit 1
fi
grep -q 'HOCX_ENVIRONMENT:.*production' docker-compose.release.yml
grep -q 'docs_url=None if settings.is_production' backend/app/main.py
grep -q 'Lokale Demo-Admin-Adresse ist in Release-Umgebungen verboten' scripts/deploy.sh

# 1.1.0: photo-analysis-worker (uid 5002) muss den auf Gruppe 5001 gehaerteten Storage lesen
# koennen, und das Backend braucht das immer lokale Thumbnail-Verzeichnis.
grep -q '^  photo-analysis-worker:$' docker-compose.release.yml
grep -q 'group_add:' docker-compose.release.yml
grep -q '^      - "5001"$' docker-compose.release.yml
grep -q '\./storage-local/thumbnails:/app/storage-local/thumbnails' docker-compose.release.yml
grep -q 'THUMBNAIL_ROOT: /app/storage-local/thumbnails' docker-compose.release.yml
grep -q 'PHOTO_WORKER_DB_PASSWORD_FILE: /run/secrets/photo_worker_db_password' docker-compose.release.yml

echo "release config tests: ok"
