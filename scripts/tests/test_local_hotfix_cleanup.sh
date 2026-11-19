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

# 1. Release ohne Korrektur: Hotfix bleibt und wird geladen
# shellcheck disable=SC2016 # Literal aus der Compose-Datei
grep -v 'traefik.docker.network=${COMPOSE_PROJECT_NAME}_default' "$REPO_DIR/docker-compose.release.yml" > "$WORK/docker-compose.release.yml" || true
printf '%b' "$HOTFIX" > "$WORK/docker-compose.local.yml"
args=(); append_local_compose_override "$WORK" args
[ "${args[*]}" = "-f $WORK/docker-compose.local.yml" ] || { echo "Fall 1: Hotfix fälschlich entfernt" >&2; exit 1; }

# 2. Release mit Korrektur: genau der Hotfix wird nach backups/ verschoben und nicht geladen
cp "$REPO_DIR/docker-compose.release.yml" "$WORK/"
args=(); append_local_compose_override "$WORK" args 2> /dev/null
[ "${#args[@]}" -eq 0 ] && [ ! -e "$WORK/docker-compose.local.yml" ] || { echo "Fall 2: Hotfix nicht entfernt" >&2; exit 1; }
ls "$WORK"/backups/docker-compose.local.yml.hotfix-* > /dev/null

# 3. Datei mit weiteren Einstellungen bleibt unverändert
printf '%b  traefik:\n    ports: []\n' "$HOTFIX" > "$WORK/docker-compose.local.yml"
args=(); append_local_compose_override "$WORK" args 2> /dev/null
[ "${args[*]}" = "-f $WORK/docker-compose.local.yml" ] || { echo "Fall 3: eigene Datei angetastet" >&2; exit 1; }
echo "Hotfix-Bereinigung: ok"
