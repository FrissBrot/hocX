#!/usr/bin/env bash
# Bekannte Hotfixes in docker-compose.local.yml werden beim Update entfernt, sobald das Release
# die Korrektur selbst enthält (scripts/lib/env.sh::retire_local_compose_hotfixes).
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=scripts/lib/env.sh
source "$REPO_DIR/scripts/lib/env.sh"
WORK="$(mktemp -d)"
trap 'rm -rf -- "$WORK"' EXIT
HOTFIX='services:\n  abgabebox-backend:\n    labels:\n      - "traefik.docker.network=hocx_default"\n'

# 1. Release ohne Korrektur: Hotfix bleibt, auch beim Aufräumen
# shellcheck disable=SC2016 # Literal aus der Compose-Datei
grep -v 'traefik.docker.network=${COMPOSE_PROJECT_NAME}_' "$REPO_DIR/docker-compose.release.yml" > "$WORK/docker-compose.release.yml" || true
printf '%b' "$HOTFIX" > "$WORK/docker-compose.local.yml"
args=(); append_local_compose_override "$WORK" args
retire_local_compose_hotfixes "$WORK" 2> /dev/null || true
[ "${args[*]}" = "-f $WORK/docker-compose.local.yml" ] && [ -e "$WORK/docker-compose.local.yml" ] || { echo "Fall 1: Hotfix fälschlich entfernt" >&2; exit 1; }

# 2. Release mit Korrektur im Standardnetz (1.4.1/1.4.2): Laden lässt die Datei unangetastet
#    (Rollback braucht sie noch); erst retire_local_compose_hotfixes (deploy.sh nach erfolgreichem
#    Update) verschiebt sie nach backups/
sed 's/traefik.docker.network=${COMPOSE_PROJECT_NAME}_edge/traefik.docker.network=${COMPOSE_PROJECT_NAME}_default/' \
  "$REPO_DIR/docker-compose.release.yml" > "$WORK/docker-compose.release.yml"
args=(); append_local_compose_override "$WORK" args 2> /dev/null
[ "${args[*]}" = "-f $WORK/docker-compose.local.yml" ] || { echo "Fall 2a: Hotfix beim Laden angetastet" >&2; exit 1; }
retire_local_compose_hotfixes "$WORK" 2> /dev/null || true
[ ! -e "$WORK/docker-compose.local.yml" ] || { echo "Fall 2b: Hotfix nach dem Update nicht entfernt" >&2; exit 1; }
ls "$WORK"/backups/docker-compose.local.yml.hotfix-* > /dev/null

# 2c. Release ab 1.4.3 (Traefik nur im Netz edge): der Hotfix würde die Abgabebox auf das alte Netz
#     zwingen (504) - er wird nicht mehr geladen und nach dem Update entfernt
rm -rf "$WORK/backups"
cp "$REPO_DIR/docker-compose.release.yml" "$WORK/"
grep -q 'traefik.docker.network=${COMPOSE_PROJECT_NAME}_edge' "$WORK/docker-compose.release.yml" || { echo "Fall 2c: Release setzt kein Netz edge" >&2; exit 1; }
printf '%b' "$HOTFIX" > "$WORK/docker-compose.local.yml"
args=(); append_local_compose_override "$WORK" args 2> /dev/null
[ "${#args[@]}" -eq 0 ] || { echo "Fall 2c: Hotfix trotz Netz edge geladen" >&2; exit 1; }
retire_local_compose_hotfixes "$WORK" 2> /dev/null || true
[ ! -e "$WORK/docker-compose.local.yml" ] || { echo "Fall 2c: Hotfix nach dem Update nicht entfernt" >&2; exit 1; }

# 3. Datei mit weiteren Einstellungen bleibt unverändert
printf '%b  traefik:\n    ports: []\n' "$HOTFIX" > "$WORK/docker-compose.local.yml"
retire_local_compose_hotfixes "$WORK" 2> /dev/null || true
[ -e "$WORK/docker-compose.local.yml" ] || { echo "Fall 3: eigene Datei angetastet" >&2; exit 1; }
echo "Hotfix-Bereinigung: ok"
