#!/usr/bin/env bash
set -euo pipefail
# Das bisherige Objekt-Backup (lokaler Spiegel) darf nicht parallel zum Borg-Backup laufen.
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/bin"
printf '#!/bin/sh\necho "docker darf nicht aufgerufen werden" >&2\nexit 99\n' > "$tmp/bin/docker"
chmod +x "$tmp/bin/docker"
printf 'BACKUP_ENABLED=true\n' > "$tmp/env"
chmod 600 "$tmp/env"
output="$(PATH="$tmp/bin:$PATH" HOCX_ENV_FILE="$tmp/env" bash "$REPO_DIR/scripts/backup_storage.sh")"
grep -q "Borg-Backup ist aktiv" <<<"$output"
printf 'BACKUP_ENABLED=true\nHOCX_LEGACY_BACKUP_FORCE=true\n' > "$tmp/env"
if PATH="$tmp/bin:$PATH" HOCX_ENV_FILE="$tmp/env" bash "$REPO_DIR/scripts/backup_storage.sh" >/dev/null 2>&1; then
  echo "Mit HOCX_LEGACY_BACKUP_FORCE=true muss das alte Skript wieder laufen (hier: am Fake-docker scheitern)." >&2
  exit 1
fi
echo "legacy backup guard tests: ok"
