#!/usr/bin/env bash
# Lasttest-Stack samt Volumes, Daten und Images entfernen.
set -euo pipefail
LT_PROJECT="${LT_PROJECT:-hocx-loadtest}"
LT_DIR="${LT_DIR:-/docker/loadtest-stack}"
case "$LT_PROJECT" in *loadtest*) ;; *) echo "LT_PROJECT muss 'loadtest' enthalten" >&2; exit 1 ;; esac
# Nur ein von up.sh angelegtes Verzeichnis leeren (Schutz vor Tippfehlern wie LT_DIR=/docker)
case "$LT_DIR" in *loadtest*) ;; *) echo "LT_DIR muss 'loadtest' enthalten" >&2; exit 1 ;; esac
[[ -f "$LT_DIR/dc.sh" && -f "$LT_DIR/.env" ]] || { echo "$LT_DIR ist kein Lasttest-Stack (dc.sh/.env fehlen)" >&2; exit 1; }
"$LT_DIR/dc.sh" down --volumes --remove-orphans
docker images --format '{{.Repository}}:{{.Tag}}' | grep "^$LT_PROJECT-" | xargs -r docker rmi
# results/ bleibt erhalten
find "$LT_DIR" -mindepth 1 -maxdepth 1 ! -name results -exec rm -rf {} +
