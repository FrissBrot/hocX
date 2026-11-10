#!/usr/bin/env bash
# Echter Durchlauf von scripts/lib/pg_upgrade.sh mit Docker: PostgreSQL-16-Volume mit Rollen,
# RLS, Erweiterungen und Daten -> PostgreSQL 18, danach Wiederholung (No-op), Fehlerfall mit
# Wiederherstellung und unvollständiges Zielvolume.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=scripts/lib/pg_upgrade.sh
source "$REPO_DIR/scripts/lib/pg_upgrade.sh"

TARGET_IMAGE="$(sed -n 's/^    image: \(postgres:18@sha256:[0-9a-f]*\)$/\1/p' "$REPO_DIR/docker-compose.release.yml" | head -n 1)"
[ -n "$TARGET_IMAGE" ] || { echo "postgres:18-Image in docker-compose.release.yml nicht gefunden" >&2; exit 1; }
docker pull -q "$TARGET_IMAGE" > /dev/null
docker pull -q "$PG_UPGRADE_LEGACY_IMAGE" > /dev/null

PREFIX="hocxpgtest$$"
APP_PASSWORD="app-$(openssl rand -hex 12)"
SUPER_PASSWORD="super-$(openssl rand -hex 12)"

cleanup() {
  docker ps -aq --filter "label=hocx-pg-upgrade-test=$PREFIX" | xargs -r docker rm -f > /dev/null 2>&1 || true
  docker volume ls -q --filter "label=hocx-pg-upgrade-test=$PREFIX" | xargs -r docker volume rm > /dev/null 2>&1 || true
  docker volume ls -q | grep "^${PREFIX}" | xargs -r docker volume rm > /dev/null 2>&1 || true
}
trap cleanup EXIT

fail() { echo "FEHLER: $*" >&2; exit 1; }

# Legt ein Projekt wie unter 1.1.x an: Volume postgres_data mit befülltem 16er-Cluster, dazu
# ein laufender "backend"- und "traefik"-Container mit Compose-Labels.
make_legacy_project() {
  local project="$1" volume="${1}_postgres_data" seed
  docker volume create --label "com.docker.compose.project=$project" --label "com.docker.compose.volume=postgres_data" \
    --label "hocx-pg-upgrade-test=$PREFIX" "$volume" > /dev/null
  seed="$(docker run -d --label "hocx-pg-upgrade-test=$PREFIX" -e POSTGRES_USER=hocx -e POSTGRES_DB=hocx \
    -e POSTGRES_PASSWORD="$SUPER_PASSWORD" -v "$volume:/var/lib/postgresql/data" "$PG_UPGRADE_LEGACY_IMAGE")"
  pg_upgrade_wait "$seed" hocx "-h 127.0.0.1" || fail "Seed-Server startet nicht"
  docker exec -i "$seed" psql -X -q -v ON_ERROR_STOP=1 -U hocx -d hocx > /dev/null <<SQL
CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA public;
CREATE EXTENSION IF NOT EXISTS pg_stat_statements WITH SCHEMA public;
CREATE ROLE hocx_app LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD '$APP_PASSWORD';
ALTER ROLE hocx_app SET statement_timeout = '30s';
CREATE TABLE tenant (id bigserial PRIMARY KEY, name text NOT NULL);
CREATE TABLE note (id bigserial PRIMARY KEY, tenant_id bigint NOT NULL REFERENCES tenant(id), body text, secret bytea);
ALTER TABLE note ENABLE ROW LEVEL SECURITY;
ALTER TABLE note FORCE ROW LEVEL SECURITY;
CREATE POLICY note_tenant ON note USING (tenant_id = current_setting('app.tenant_id')::bigint);
INSERT INTO tenant (name) VALUES ('Turnverein Seedorf'), ('Männerchor Zürich');
INSERT INTO note (tenant_id, body, secret) SELECT 1 + (g % 2), 'Notiz ' || g || ' äöü', gen_random_bytes(16) FROM generate_series(1, 1500) g;
CREATE FUNCTION public.note_count(p bigint) RETURNS bigint LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog, public
  AS 'SELECT count(*) FROM public.note WHERE tenant_id = p';
REVOKE ALL ON FUNCTION public.note_count(bigint) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.note_count(bigint) TO hocx_app;
GRANT SELECT, INSERT ON tenant, note TO hocx_app;
CREATE DATABASE second_db;
SQL
  docker rm -f "$seed" > /dev/null
  docker run -d --label "hocx-pg-upgrade-test=$PREFIX" --label "com.docker.compose.project=$project" \
    --label com.docker.compose.service=backend --name "${project}-backend-1" "$PG_UPGRADE_LEGACY_IMAGE" sleep 600 > /dev/null
  docker run -d --label "hocx-pg-upgrade-test=$PREFIX" --label "com.docker.compose.project=$project" \
    --label com.docker.compose.service=traefik --name "${project}-traefik-1" "$PG_UPGRADE_LEGACY_IMAGE" sleep 600 > /dev/null
}

running() { [ "$(docker inspect -f '{{.State.Running}}' "$1")" = true ]; }

echo "== Upgrade 16 -> 18"
P1="${PREFIX}a"
make_legacy_project "$P1"
pg_upgrade_major_if_needed "$P1" hocx hocx "$TARGET_IMAGE" || fail "Upgrade meldet Fehler"
! running "${P1}-backend-1" || fail "backend wurde nicht gestoppt"
running "${P1}-traefik-1" || fail "traefik wurde gestoppt"
[ "${#PG_UPGRADE_STOPPED_CONTAINERS[@]}" -eq 1 ] || fail "gestoppte Container nicht gemeldet"
[ "$(pg_upgrade_volume_of "$P1" postgres18_data)" = "${P1}_postgres18_data" ] || fail "Zielvolume ohne Compose-Labels"
docker run --rm -v "${P1}_postgres_data:/old:ro" --entrypoint cat "$PG_UPGRADE_LEGACY_IMAGE" /old/PG_VERSION | grep -qx 16 || fail "altes Volume veraendert"

# Neuen Server so starten wie der Compose-Dienst (Volume unter /var/lib/postgresql) und prüfen.
check="$(docker run -d --label "hocx-pg-upgrade-test=$PREFIX" -e POSTGRES_PASSWORD=ignored \
  -v "${P1}_postgres18_data:/var/lib/postgresql" "$TARGET_IMAGE" postgres -c shared_preload_libraries=pg_stat_statements)"
pg_upgrade_wait "$check" hocx "-h 127.0.0.1" || fail "Server auf dem neuen Volume startet nicht"
q() { docker exec -e PGPASSWORD="$1" "$check" psql -X -q -At -v ON_ERROR_STOP=1 -h 127.0.0.1 -U "$2" -d hocx -c "$3"; }
[ "$(q "$SUPER_PASSWORD" hocx 'SHOW server_version_num' | cut -c1-2)" = 18 ] || fail "nicht PostgreSQL 18"
[ "$(q "$SUPER_PASSWORD" hocx 'SELECT count(*) FROM note')" = 1500 ] || fail "Zeilen fehlen"
[ "$(q "$SUPER_PASSWORD" hocx "SELECT name FROM tenant WHERE id = 2")" = "Männerchor Zürich" ] || fail "Umlaute kaputt"
[ "$(q "$APP_PASSWORD" hocx_app "SET app.tenant_id = '1'; SELECT count(*) FROM note")" = 750 ] || fail "RLS/Login hocx_app"
[ "$(q "$APP_PASSWORD" hocx_app 'SELECT public.note_count(2)')" = 750 ] || fail "SECURITY-DEFINER-Funktion"
[ "$(q "$APP_PASSWORD" hocx_app 'SHOW statement_timeout')" = 30s ] || fail "Rollen-Einstellung fehlt"
q "$SUPER_PASSWORD" hocx 'SELECT count(*) FROM pg_stat_statements' > /dev/null || fail "pg_stat_statements"
[ "$(q "$SUPER_PASSWORD" hocx "SELECT count(*) FROM pg_database WHERE datname = 'second_db'")" = 1 ] || fail "zweite Datenbank fehlt"
docker rm -f "$check" > /dev/null

echo "== Wiederholung ist ein No-op"
out="$(pg_upgrade_major_if_needed "$P1" hocx hocx "$TARGET_IMAGE")" || fail "Wiederholung meldet Fehler"
grep -q "kann nach einer Pruefung entfernt werden" <<< "$out" || fail "Wiederholung erkennt fertiges Upgrade nicht: $out"

echo "== Altes Volume nach dem Upgrade weiter benutzt (Rueckweg auf 1.1.x)"
reuse="$(docker run -d --label "hocx-pg-upgrade-test=$PREFIX" -v "${P1}_postgres_data:/var/lib/postgresql/data" "$PG_UPGRADE_LEGACY_IMAGE")"
pg_upgrade_wait "$reuse" hocx "" || fail "alter Server startet nicht erneut"
docker exec "$reuse" psql -X -q -U hocx -d hocx -c "INSERT INTO tenant (name) VALUES ('nach Rueckweg')" > /dev/null
docker stop "$reuse" > /dev/null
if pg_upgrade_major_if_needed "$P1" hocx hocx "$TARGET_IMAGE" 2> /dev/null; then
  fail "veraltetes Zielvolume nach weiterer Nutzung des alten Volumes akzeptiert"
fi

echo "== Ohne altes Volume nichts zu tun"
pg_upgrade_major_if_needed "${PREFIX}fresh" hocx hocx "$TARGET_IMAGE" || fail "frische Installation"

echo "== Fehlerfall: alter Zustand wird wiederhergestellt"
P2="${PREFIX}b"
make_legacy_project "$P2"
if pg_upgrade_major_if_needed "$P2" hocx hocx "postgres:18-does-not-exist-$PREFIX" 2> /dev/null; then
  fail "Upgrade mit fehlendem Image meldet Erfolg"
fi
running "${P2}-backend-1" || fail "backend nach Fehler nicht wieder gestartet"
[ -z "$(pg_upgrade_volume_of "$P2" postgres18_data)" ] || fail "halb gefuelltes Zielvolume nicht entfernt"

echo "== Zielvolume mit Daten, aber ohne Abschlussmarke"
docker volume create --label "com.docker.compose.project=$P2" --label com.docker.compose.volume=postgres18_data \
  "${P2}_postgres18_data" > /dev/null
docker run --rm -v "${P2}_postgres18_data:/t" --entrypoint sh "$TARGET_IMAGE" -c 'mkdir -p /t/18/docker && echo 18 > /t/18/docker/PG_VERSION'
if pg_upgrade_major_if_needed "$P2" hocx hocx "$TARGET_IMAGE" 2> /dev/null; then
  fail "unvollstaendiges Zielvolume wird als fertig behandelt"
fi
running "${P2}-backend-1" || fail "backend gestoppt, obwohl nichts zu tun war"

echo "== Ungueltiger Superuser-Name"
if pg_upgrade_major_if_needed "$P2" 'x; DROP' hocx "$TARGET_IMAGE" 2> /dev/null; then
  fail "ungueltiger Name akzeptiert"
fi

echo "pg_upgrade: ok"
