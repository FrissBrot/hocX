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

if grep -q 'env_file:' docker-compose.release.yml; then
  echo "Release-Services duerfen nicht die komplette .env erhalten." >&2
  exit 1
fi

test "$(grep -c 'read_only: true' docker-compose.release.yml)" -eq 5
test "$(grep -c 'no-new-privileges:true' docker-compose.release.yml)" -eq 5
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

echo "release config tests: ok"
