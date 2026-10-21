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

# MAIN-OPS-005: Redis haengt nur im internen Netz "cache", das ausser Redis nur das Backend nutzt.
assert_redis_isolated() {
  python3 -c '
import json, sys
services = json.load(sys.stdin)["services"]
redis = sorted((services["redis"].get("networks") or {}).keys())
assert redis == ["cache"], f"redis-Netze: {redis}"
users = sorted(n for n, s in services.items() if "cache" in (s.get("networks") or {}))
assert users == ["backend", "redis"], f"cache-Netz genutzt von: {users}"
'
}
docker compose --env-file .env.prod.example "${COMPOSE_FILES[@]}" config --format json | assert_redis_isolated
docker compose -p hocx-e2e --env-file .env.e2e.example -f docker-compose.yml -f docker-compose.dev.yml config --format json | assert_redis_isolated

# MAIN-OPS-005 (Rest): Im Release-Stack verlangt Redis ein Passwort aus dem Secret, das Backend
# bekommt dasselbe Secret; das Passwort steht nie in der Kommandozeile.
docker compose --env-file .env.prod.example "${COMPOSE_FILES[@]}" config --format json | python3 -c '
import json, sys
services = json.load(sys.stdin)["services"]
redis, backend = services["redis"], services["backend"]
assert any(s["source"] == "redis_password" for s in redis.get("secrets", [])), "redis ohne Secret"
command = " ".join(redis["command"])
assert "requirepass" in command and "/run/secrets/redis_password" in command, command
assert "--requirepass" not in command, "Passwort als Argument"
assert backend["environment"].get("REDIS_PASSWORD_FILE") == "/run/secrets/redis_password"
assert any(s["source"] == "redis_password" for s in backend.get("secrets", [])), "backend ohne Secret"
'
# shellcheck disable=SC2016  # literales Suchmuster
grep -q 'write_secret_file "$secrets_dir" redis_password "$REDIS_PASSWORD"' scripts/deploy.sh

# MAIN-OPS-004: Nur die Socket-Proxys mounten den Docker-Socket; Traefik spricht die API nur
# über seinen Proxy. MAIN-OPS-013: jede Middleware, die traefik_config_service.py für
# Custom-Domains referenziert, ist in den Compose-Labels definiert.
for files in "--env-file .env.prod.example ${COMPOSE_FILES[*]}" "-p hocx-e2e --env-file .env.e2e.example -f docker-compose.yml -f docker-compose.dev.yml"; do
  # shellcheck disable=SC2086  # bewusst in Worte zerlegt
  docker compose $files config --format json | python3 -c '
import json, re, sys
config = json.load(sys.stdin)
services = config["services"]
mounts = sorted(name for name, s in services.items()
                if any("docker.sock" in str(v.get("source", "")) for v in s.get("volumes", [])))
assert all(name.endswith("socket-proxy") for name in mounts), f"docker.sock gemountet von: {mounts}"
if "traefik" in services:
    assert "traefik-socket-proxy" in mounts, mounts
    assert "traefik-docker-api" in (services["traefik"].get("networks") or {}), "traefik ohne Proxy-Netz"
labels = " ".join(str(v) for s in services.values() for v in (s.get("labels") or {}).items())
prefix = services["backend"]["environment"].get("TRAEFIK_MIDDLEWARE_PREFIX", "")
source = open("backend/app/services/traefik_config_service.py").read()
for name in set(re.findall(r"traefik_middleware_prefix\}([a-z-]+)@docker", source)):
    assert f"traefik.http.middlewares.{prefix}{name}." in labels, f"Middleware fehlt: {prefix}{name}"
'
done
grep -q 'endpoint: "tcp://traefik-socket-proxy:2375"' infra/traefik/traefik.yml

# MAIN-OPS-012: Fremd-Images per Digest, Actions per Commit-SHA gepinnt (Updates via Dependabot).
unpinned_images="$(grep -hE '^[[:space:]]*image:' docker-compose*.yml | grep -v '@sha256:' | grep -v 'HOCX_' || true)"
test -z "$unpinned_images" || { echo "Images ohne Digest: $unpinned_images" >&2; exit 1; }
unpinned_from="$(git grep -hE '^FROM ' -- '*Dockerfile*' | grep -v '@sha256:' || true)"
test -z "$unpinned_from" || { echo "FROM ohne Digest: $unpinned_from" >&2; exit 1; }
unpinned_actions="$(grep -hE '^[[:space:]]*(- )?uses:' .github/workflows/*.yml | grep -vE '@[0-9a-f]{40}( |$)' || true)"
test -z "$unpinned_actions" || { echo "Actions ohne SHA: $unpinned_actions" >&2; exit 1; }
test -f .github/dependabot.yml

# MAIN-OPS-008: Der Dev-Overlay landet ohne -p nie im Projekt der Server-Instanz (hocx).
dev_project="$(docker compose --env-file .env.e2e.example -f docker-compose.yml -f docker-compose.dev.yml config --format json | python3 -c 'import json,sys; print(json.load(sys.stdin)["name"])')"
test "$dev_project" = hocx-dev || { echo "Dev-Overlay ergibt Projekt '$dev_project' statt hocx-dev" >&2; exit 1; }

# MAIN-OPS-009: Die Quellcode-Instanz kann als Produktion laufen, der Dev-Overlay bleibt development,
# und die .env-Vorlage schaltet den Captcha-Bot-Schutz der Abgabebox nicht ab.
env_of() {
  python3 -c 'import json,sys; s=json.load(sys.stdin)["services"]; print(s[sys.argv[1]]["environment"].get(sys.argv[2], ""))' "$@"
}
test "$(HOCX_ENVIRONMENT=production docker compose -p ops009 --env-file .env.e2e.example -f docker-compose.yml config --format json | env_of backend HOCX_ENVIRONMENT)" = production
test "$(HOCX_ENVIRONMENT=production docker compose -p ops009 --env-file .env.e2e.example -f docker-compose.yml -f docker-compose.dev.yml config --format json | env_of backend HOCX_ENVIRONMENT)" = development
if grep -qE '^ABGABEBOX_ENVIRONMENT=' .env.example; then
  echo ".env.example darf ABGABEBOX_ENVIRONMENT nicht setzen (Captcha fail-open)." >&2
  exit 1
fi

# MAIN-OPS-017: Jeder Build-Kontext hat eine .dockerignore.
for context in backend frontend abgabebox-backend abgabebox-frontend docs-site photo-analysis-worker; do
  test -f "$context/.dockerignore" || { echo "$context/.dockerignore fehlt" >&2; exit 1; }
done

# MAIN-OPS-007: Basis- und Release-Stack verwenden dieselbe Traefik-Version.
base_traefik="$(grep -m1 -E '^    image: traefik:' docker-compose.yml)"
release_traefik="$(grep -m1 -E '^    image: traefik:' docker-compose.traefik.yml)"
test -n "$base_traefik" && test "$base_traefik" = "$release_traefik" || {
  echo "Traefik-Version weicht ab: '$base_traefik' vs. '$release_traefik'" >&2
  exit 1
}

if grep -q 'env_file:' docker-compose.release.yml; then
  echo "Release-Services duerfen nicht die komplette .env erhalten." >&2
  exit 1
fi

test "$(grep -c 'read_only: true' docker-compose.release.yml)" -eq 13  # +local-s3, storage-init, storage-worker (Objektspeicher), backup-worker, document-worker, job-worker

# Der document-worker verarbeitet nicht vertrauenswürdige Dateien: keine Anmelde-/Admin-Secrets
# und keine Owner-Datenbank-URL (Audit DOCMGMT-003, Entscheidung Worker-Secrets).
document_worker_block="$(awk '/^  document-worker:$/{f=1;next} f&&/^  [a-z][a-z0-9-]*:$/{f=0} f&&!/^ *#/' docker-compose.release.yml)"
test -n "$document_worker_block" || { echo "document-worker fehlt in docker-compose.release.yml" >&2; exit 1; }
if grep -Eq 'AUTH_SECRET|auth_secret|DATABASE_URL_FILE: /run/secrets/database_url|- database_url$' <<<"$document_worker_block"; then
  echo "document-worker darf weder AUTH_SECRET/ADMIN_AUTH_SECRET noch die Owner-DB-URL erhalten." >&2
  exit 1
fi
grep -q 'HOCX_PROCESS_KIND: document-worker' <<<"$document_worker_block" || {
  echo "document-worker braucht HOCX_PROCESS_KIND=document-worker." >&2
  exit 1
}
test "$(grep -c 'no-new-privileges:true' docker-compose.release.yml)" -eq 13  # + job-worker

# Audit finding, 2026-08-27: docker-compose.traefik.yml/docker-compose.clamav.yml (the
# actual prod Traefik/ClamAV - deploy.sh/verify_release.sh never include the base
# docker-compose.yml, so its dev-only hardening for these two never applied to prod) had no
# resource limits or container-hardening at all. Assert both are present here so this class
# of gap gets caught going forward.
# Je Dienst einmal: traefik.yml hat seit MAIN-OPS-004 zwei Dienste (traefik, traefik-socket-proxy).
for entry in docker-compose.traefik.yml:2 docker-compose.clamav.yml:1; do
  f="${entry%%:*}"; services="${entry##*:}"
  test "$(grep -c 'read_only: true' "$f")" -eq "$services"
  test "$(grep -c 'no-new-privileges:true' "$f")" -eq "$services"
  test "$(grep -c 'mem_limit:' "$f")" -eq "$services"
  # Anchored (unlike the other three greps above) because this file's own comment
  # explaining CAP_DAC_OVERRIDE mentions "cap_drop:ALL" in prose - an unanchored grep
  # double-counts that as a second directive, permanently red long before this diff
  # (found while adding photo-analysis-worker's docker-compose.release.yml entry, which
  # legitimately changed the read_only:true/no-new-privileges:true counts above from 5 to
  # 6 and prompted actually running this test).
  test "$(grep -c '^[[:space:]]*cap_drop:' "$f")" -eq "$services"
done
grep -q '^USER hocx$' backend/Dockerfile
grep -q '^USER node$' frontend/Dockerfile
grep -q '^USER node$' abgabebox-frontend/Dockerfile
grep -qE '^FROM nginxinc/nginx-unprivileged:alpine(@sha256:[0-9a-f]{64})?$' docs-site/Dockerfile
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
# MAIN-OPS-001: verify_release.sh prueft, dass das Backend in der erwarteten Umgebung laeuft.
grep -q 'run_check "Backend laeuft in der erwarteten Umgebung" check_backend_environment' scripts/verify_release.sh
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

# Keine Dokumentsignatur mehr: weder Zertifikate noch Signatur-Konfiguration im Release.
if grep -q 'DOCUMENT_SIGNING\|hocx-signing' docker-compose.release.yml scripts/deploy.sh; then
  echo "Signatur-Konfiguration ist entfernt (Hash-Prüfung über die Abgabebox)." >&2
  exit 1
fi
grep -q 'DOCUMENT_VERIFY_BASE_URL' docker-compose.release.yml

# Backup (BorgBackup): eigener Worker mit den Borg-Secrets; das Backend bekommt sie nie.
grep -q '^  backup-worker:$' docker-compose.release.yml
grep -q 'BACKUP_SSH_KEY_FILE: /run/secrets/backup_ssh_key' docker-compose.release.yml
if awk '/^  backend:$/,/^  photo-analysis-worker:$/' docker-compose.release.yml | grep -q 'backup_ssh_key\|backup_passphrase'; then
  echo "Das Backend darf keine Borg-Secrets erhalten." >&2
  exit 1
fi
if grep -q 'app.backup.cli init' scripts/deploy.sh; then
  echo "deploy.sh darf ein Backup-Repository nie initialisieren." >&2
  exit 1
fi

# Worker mit dem Backend-Image (Release 1.2.0): im Release-Manifest vermerkt, beim Rollback auf
# ein Release ohne sie gestoppt statt mit dem neuen Image weiterlaufend.
grep -q '^BACKEND_IMAGE_WORKERS=(storage-worker backup-worker document-worker job-worker)$' scripts/deploy.sh
grep -q 'HOCX_BACKEND_WORKERS=' scripts/deploy.sh
for worker in storage-worker backup-worker document-worker; do
  grep -q "^  ${worker}:$" docker-compose.release.yml || { echo "$worker fehlt in docker-compose.release.yml" >&2; exit 1; }
  awk "/^  ${worker}:\$/{f=1;next} f&&/^  [a-z][a-z0-9-]*:\$/{f=0} f" docker-compose.release.yml | grep -q 'HOCX_BACKEND_IMAGE' \
    || { echo "$worker muss das Backend-Image nutzen (sonst stimmt der Rollback nicht)" >&2; exit 1; }
done

echo "release config tests: ok"
