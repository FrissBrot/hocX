#!/usr/bin/env bash
# Kopiert gemeinsamen Backend-Code in die Dienste, die keinen Backend-Code importieren dürfen
# (Abgabebox: Isolationsgrenze, Foto-Worker: eigenes Image). Gleiches Muster wie
# sync-design-tokens.sh: Quelle einmal ändern, synchronisieren, Kopien nie von Hand bearbeiten.
#
# - backend/app/core/objstore_client.py -> Abgabebox, Foto-Worker (Objektspeicher-Client)
# - backend/app/services/gps_strip.py   -> Abgabebox (GPS beim Upload weglassen, Paket 9.3)
#
#   scripts/sync-objstore-client.sh          # Kopien aktualisieren
#   scripts/sync-objstore-client.sh --check  # nur prüfen (CI), Exit 1 bei Abweichung
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Quelle|Ziel (relativ zum Repo)
PAIRS=(
  "backend/app/core/objstore_client.py|abgabebox-backend/app/objstore_client.py"
  "backend/app/core/objstore_client.py|photo-analysis-worker/app/objstore_client.py"
  "backend/app/services/gps_strip.py|abgabebox-backend/app/gps_strip.py"
)

status=0
for pair in "${PAIRS[@]}"; do
  source_rel="${pair%%|*}"
  target_rel="${pair##*|}"
  header="# GENERIERT aus $source_rel - nicht von Hand bearbeiten, siehe scripts/sync-objstore-client.sh"
  expected="$(printf '%s\n' "$header"; cat "$REPO_DIR/$source_rel")"
  target="$REPO_DIR/$target_rel"
  if [ "${1:-}" = "--check" ]; then
    if [ ! -f "$target" ] || [ "$(cat "$target")" != "$expected" ]; then
      echo "Nicht synchron: $target_rel (scripts/sync-objstore-client.sh ausführen)" >&2
      status=1
    fi
  else
    printf '%s\n' "$expected" > "$target"
    echo "aktualisiert: $target_rel"
  fi
done
[ "${1:-}" = "--check" ] && [ "$status" -eq 0 ] && echo "objstore_client: synchron"
exit "$status"
