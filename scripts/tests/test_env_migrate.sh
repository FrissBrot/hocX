#!/usr/bin/env bash
set -euo pipefail

# Update-Pfad 1.0.x -> 1.1.0: eine .env, wie deploy.sh sie unter 1.0.0 erzeugt hat
# (fixtures/env.v1.0.0), muss ohne manuelles Nachpflegen von scripts/deploy.sh akzeptiert
# werden. Prueft die .env-Migration (lib/env_migrate.sh), die Deploy-Verdrahtung und - wenn
# Docker verfuegbar ist - dass Compose die migrierte .env ohne fehlende Variablen aufloest.

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=scripts/lib/env.sh
source "$REPO_DIR/scripts/lib/env.sh"
# shellcheck source=scripts/lib/env_migrate.sh
source "$REPO_DIR/scripts/lib/env_migrate.sh"

FIXTURE="$REPO_DIR/scripts/tests/fixtures/env.v1.0.0"
TEST_DIR="$(mktemp -d)"
trap 'rm -rf "$TEST_DIR"' EXIT
ENV_FILE="$TEST_DIR/.env"

fail() {
  echo "FEHLER: $*" >&2
  exit 1
}

fresh_env() {
  rm -f "$TEST_DIR"/.env "$TEST_DIR"/.env.bak-* "$TEST_DIR"/.env.tmp.*
  cp "$FIXTURE" "$ENV_FILE"
  chmod 600 "$ENV_FILE"
}

value_of() {
  ( load_env_file "$1" && printf '%s' "${!2-}" )
}

# --- 1. Der Loader akzeptiert die alte .env (entfernte Variable wird uebersprungen) ------
fresh_env
load_env_file "$ENV_FILE"
test -z "${TRAEFIK_WEB_DOMAIN+x}" || fail "TRAEFIK_WEB_DOMAIN darf nicht geladen werden"
test -z "${PHOTO_WORKER_DB_PASSWORD-}" || fail "Fixture darf noch kein PHOTO_WORKER_DB_PASSWORD enthalten"
unset POSTGRES_DB

# Unbekannte Variablen werden weiterhin abgelehnt.
printf "NOT_A_KNOWN_KEY='x'\n" >> "$ENV_FILE"
if load_env_file "$ENV_FILE" 2> /dev/null; then
  fail "Unbekannte Variable wurde akzeptiert"
fi

# --- 2. Migration: ergaenzt, entfernt, laesst alles andere unveraendert -------------------
fresh_env
migrate_env_file "$ENV_FILE" > "$TEST_DIR/out.txt"
grep -q 'entfernt: TRAEFIK_WEB_DOMAIN' "$TEST_DIR/out.txt" || fail "Entfernen nicht gemeldet"
grep -q 'PHOTO_WORKER_DB_PASSWORD' "$TEST_DIR/out.txt" || fail "Ergaenzen nicht gemeldet"

if grep -q '^TRAEFIK_WEB_DOMAIN=' "$ENV_FILE"; then
  fail "TRAEFIK_WEB_DOMAIN steht noch in der .env"
fi
password="$(value_of "$ENV_FILE" PHOTO_WORKER_DB_PASSWORD)"
[[ "$password" =~ ^[0-9a-f]{64}$ ]] || fail "PHOTO_WORKER_DB_PASSWORD ist kein 64-stelliger Hex-Wert: $password"
test "$(value_of "$ENV_FILE" PHOTO_WORKER_DATABASE_URL)" = \
  "postgresql+psycopg://hocx_photo_worker:${password}@db:5432/hocx" \
  || fail "PHOTO_WORKER_DATABASE_URL passt nicht zum Passwort"

# Git behaelt Modus 600 nicht; fuer den Wertevergleich braucht load_env_file eine 600er Kopie.
cp "$FIXTURE" "$TEST_DIR/original.env"
chmod 600 "$TEST_DIR/original.env"
while IFS='=' read -r key _; do
  [[ "$key" =~ ^[A-Z_]+$ ]] || continue
  [ "$key" != TRAEFIK_WEB_DOMAIN ] || continue
  test "$(value_of "$ENV_FILE" "$key")" = "$(value_of "$TEST_DIR/original.env" "$key")" \
    || fail "Bestehender Wert von $key wurde veraendert"
done < <(grep -E '^[A-Z_]+=' "$FIXTURE")

test "$(stat -c '%a' "$ENV_FILE")" = 600 || fail ".env hat nach der Migration nicht Modus 600"
backups=("$TEST_DIR"/.env.bak-*)
test "${#backups[@]}" -eq 1 || fail "Erwartet genau eine Sicherung, gefunden: ${#backups[@]}"
test "$(stat -c '%a' "${backups[0]}")" = 600 || fail "Sicherung hat nicht Modus 600"
cmp -s "${backups[0]}" "$FIXTURE" || fail "Sicherung entspricht nicht der urspruenglichen .env"
test -z "$(ls "$TEST_DIR" | grep -F '.tmp.' || true)" || fail "Temporaere Datei uebrig geblieben"

# --- 3. Idempotenz: zweiter Lauf aendert nichts, legt keine weitere Sicherung an ---------
cp "$ENV_FILE" "$TEST_DIR/after-first-run"
migrate_env_file "$ENV_FILE" > "$TEST_DIR/out2.txt"
cmp -s "$ENV_FILE" "$TEST_DIR/after-first-run" || fail "Zweiter Lauf hat die .env veraendert"
test ! -s "$TEST_DIR/out2.txt" || fail "Zweiter Lauf sollte nichts ausgeben"
backups=("$TEST_DIR"/.env.bak-*)
test "${#backups[@]}" -eq 1 || fail "Zweiter Lauf hat eine weitere Sicherung angelegt"

# --- 4. Vorhandenes Passwort bleibt bestehen, fehlende URL wird daraus abgeleitet --------
fresh_env
printf "PHOTO_WORKER_DB_PASSWORD='keep-existing-value-xxxxxxxxxxxx'\n" >> "$ENV_FILE"
migrate_env_file "$ENV_FILE" > /dev/null
test "$(value_of "$ENV_FILE" PHOTO_WORKER_DB_PASSWORD)" = "keep-existing-value-xxxxxxxxxxxx" \
  || fail "Vorhandenes Passwort wurde ueberschrieben"
test "$(value_of "$ENV_FILE" PHOTO_WORKER_DATABASE_URL)" = \
  "postgresql+psycopg://hocx_photo_worker:keep-existing-value-xxxxxxxxxxxx@db:5432/hocx" \
  || fail "URL wurde nicht aus dem vorhandenen Passwort abgeleitet"

# --- 5. Unsichere Rechte / Symlink / unbekannte Variable: Abbruch vor jeder Aenderung ----
fresh_env
chmod 644 "$ENV_FILE"
if migrate_env_file "$ENV_FILE" > /dev/null 2>&1; then
  fail "Migration einer weltlesbaren .env wurde akzeptiert"
fi
cmp -s "$ENV_FILE" "$FIXTURE" || fail "Fehlgeschlagene Migration hat die .env veraendert"
fresh_env
ln -s "$ENV_FILE" "$TEST_DIR/link.env"
if migrate_env_file "$TEST_DIR/link.env" > /dev/null 2>&1; then
  fail "Migration eines Symlinks wurde akzeptiert"
fi

# --- 6. Optionale Variable fuer die Mandanten-Aufloesung wird vom Loader akzeptiert -------
fresh_env
printf "HOCX_SINGLE_TENANT_RESOLUTION='auto'\n" >> "$ENV_FILE"
test "$(value_of "$ENV_FILE" HOCX_SINGLE_TENANT_RESOLUTION)" = auto

# --- 7. deploy.sh: Verdrahtung des Update-Pfads --------------------------------------------
DEPLOY="$REPO_DIR/scripts/deploy.sh"
migrate_line="$(grep -n '^  migrate_env_file "\$ENV_FILE"' "$DEPLOY" | head -n 1 | cut -d: -f1)"
load_line="$(grep -n '^load_env_file "\$ENV_FILE"' "$DEPLOY" | head -n 1 | cut -d: -f1)"
test -n "$migrate_line" && test -n "$load_line" && test "$migrate_line" -lt "$load_line" \
  || fail "deploy.sh muss die .env vor dem Laden migrieren"
grep -q 'source "\$REPO_DIR/scripts/lib/env_migrate.sh"' "$DEPLOY" || fail "deploy.sh laedt env_migrate.sh nicht"
grep -q 'HOCX_PHOTO_ANALYSIS_WORKER_IMAGE' "$DEPLOY" || fail "Worker-Image wird nicht aus der Shell entfernt"
test "$(grep -c 'docs photo-analysis-worker' "$DEPLOY")" -ge 4 \
  || fail "photo-analysis-worker fehlt in Signatur-/Manifest-/Rollback-Listen"
grep -q '^prepare_thumbnail_dir$' "$DEPLOY" || fail "prepare_thumbnail_dir wird nicht aufgerufen"
grep -q 'single_tenant_resolution=auto' "$DEPLOY" || fail "Mandanten-Aufloesung fehlt beim Alembic-Aufruf"
grep -q 'storage-local/thumbnails' "$REPO_DIR/scripts/provision_deploy_user.sh" \
  || fail "provision_deploy_user.sh legt storage-local/thumbnails nicht an"
grep -q 'env_migrate.sh' "$REPO_DIR/scripts/update_deploy_code.sh" \
  || fail "update_deploy_code.sh prueft env_migrate.sh nicht"

# Jede Variable, die deploy.sh im Preflight als Secret prueft, muss die Migration liefern.
fresh_env
migrate_env_file "$ENV_FILE" > /dev/null
load_env_file "$ENV_FILE"
for variable in POSTGRES_PASSWORD APP_DB_PASSWORD AUTH_SECRET ADMIN_AUTH_SECRET \
  INITIAL_ADMIN_PASSWORD ABGABEBOX_DB_PASSWORD ABGABEBOX_CAPTCHA_SESSION_SECRET \
  PHOTO_WORKER_DB_PASSWORD PHOTO_WORKER_DATABASE_URL; do
  test -n "${!variable-}" || fail "$variable ist nach der Migration leer"
done

# --- 8. Compose loest die migrierte .env fuer Test und Prod ohne fehlende Variablen auf --
if command -v docker > /dev/null 2>&1 && docker compose version > /dev/null 2>&1; then
  compose_base=(
    -f "$REPO_DIR/docker-compose.release.yml"
    -f "$REPO_DIR/docker-compose.clamav.yml"
    -f "$REPO_DIR/docker-compose.traefik.yml"
  )
  for overlay in prod test; do
    args=("${compose_base[@]}")
    [ "$overlay" = prod ] || args+=(-f "$REPO_DIR/docker-compose.test.yml")
    docker compose --env-file "$ENV_FILE" "${args[@]}" --project-directory "$REPO_DIR" \
      config --services > "$TEST_DIR/services-$overlay.txt" 2> "$TEST_DIR/compose-$overlay.err" \
      || { cat "$TEST_DIR/compose-$overlay.err" >&2; fail "docker compose config ($overlay) schlug fehl"; }
    if grep -qi 'is not set' "$TEST_DIR/compose-$overlay.err"; then
      cat "$TEST_DIR/compose-$overlay.err" >&2
      fail "Compose ($overlay) meldet fehlende Variablen fuer die migrierte .env"
    fi
    grep -qx 'photo-analysis-worker' "$TEST_DIR/services-$overlay.txt" \
      || fail "photo-analysis-worker fehlt im Compose-Stack ($overlay)"
  done
else
  echo "    (Docker nicht verfuegbar: Compose-Aufloesung uebersprungen)"
fi

echo "Env-Migration 1.0.x -> 1.1.0: ok"
