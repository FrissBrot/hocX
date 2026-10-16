#!/usr/bin/env bash
# Kopiert den gemeinsamen Objektspeicher-Client aus backend/app/core/objstore_client.py in die
# Dienste, die keinen Backend-Code importieren dürfen (Abgabebox: Isolationsgrenze, Foto-Worker:
# eigenes Image). Gleiches Muster wie sync-design-tokens.sh: Quelle einmal ändern, synchronisieren,
# Kopien nie von Hand bearbeiten.
#
#   scripts/sync-objstore-client.sh          # Kopien aktualisieren
#   scripts/sync-objstore-client.sh --check  # nur prüfen (CI), Exit 1 bei Abweichung
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE="$REPO_DIR/backend/app/core/objstore_client.py"
TARGETS=("$REPO_DIR/abgabebox-backend/app/objstore_client.py" "$REPO_DIR/photo-analysis-worker/app/objstore_client.py")
HEADER="# GENERIERT aus backend/app/core/objstore_client.py - nicht von Hand bearbeiten, siehe scripts/sync-objstore-client.sh"

expected="$(printf '%s\n' "$HEADER"; cat "$SOURCE")"
status=0
for target in "${TARGETS[@]}"; do
  if [ "${1:-}" = "--check" ]; then
    if [ ! -f "$target" ] || [ "$(cat "$target")" != "$expected" ]; then
      echo "Nicht synchron: ${target#"$REPO_DIR"/} (scripts/sync-objstore-client.sh ausführen)" >&2
      status=1
    fi
  else
    printf '%s\n' "$expected" > "$target"
    echo "aktualisiert: ${target#"$REPO_DIR"/}"
  fi
done
[ "${1:-}" = "--check" ] && [ "$status" -eq 0 ] && echo "objstore_client: synchron"
exit "$status"
