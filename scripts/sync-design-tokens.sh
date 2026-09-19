#!/usr/bin/env bash
# Kopiert design/tokens.css (einzige Quelle) in die Build-Kontexte der Apps.
#   ./scripts/sync-design-tokens.sh          kopieren
#   ./scripts/sync-design-tokens.sh --check  nur pruefen (Exit 1 bei Abweichung), fuer CI
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$ROOT/design/tokens.css"
TARGETS=(
  "$ROOT/frontend/app/tokens.css"
  "$ROOT/abgabebox-frontend/app/tokens.css"
)

status=0
for target in "${TARGETS[@]}"; do
  if [[ "${1:-}" == "--check" ]]; then
    if ! cmp -s "$SRC" "$target"; then
      echo "Design-Tokens abweichend: ${target#"$ROOT"/} (./scripts/sync-design-tokens.sh ausfuehren)" >&2
      status=1
    fi
  else
    cp "$SRC" "$target"
    echo "synchronisiert: ${target#"$ROOT"/}"
  fi
done
exit "$status"
