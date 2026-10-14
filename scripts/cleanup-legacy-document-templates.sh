#!/usr/bin/env bash
# Räumt nach dem Update auf die Dokument-Engine (Migration 0115) die Dateien der früheren
# Dokumentvorlagen auf. Hochgeladene Schriften und Bilder bleiben: die Migration hat sie als
# Hausstil-Assets übernommen und zeigt weiterhin auf ihren bisherigen Speicherort.
#
#   ./scripts/cleanup-legacy-document-templates.sh [--dry-run] [storage-root]
#   (Vorgabe storage-root: ./storage relativ zum Repo)
#
# Entfernt:
#   - <storage>/document_templates/          (materialisierte Vorlagen, nur Code)
#   - <storage>/document_template_snapshots/ (Snapshots je Protokoll, nur Code)
#   - <storage>/latex_templates/             (Startvorlage)
#   - Vorlagen-Code unter <storage>/document_template_parts/ (Dateiendungen .tex, .sty,
#     .cls); Bilder und Schriften in diesem Verzeichnis bleiben unangetastet.
# Erst nach erfolgreicher Migration ausführen (alembic current zeigt 0115 oder neuer).
set -euo pipefail

DRY_RUN=0
if [[ "${1:-}" == "--dry-run" ]]; then
  DRY_RUN=1
  shift
fi
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STORAGE="${1:-$ROOT/storage}"

if [[ ! -d "$STORAGE" ]]; then
  echo "Speicherverzeichnis nicht gefunden: $STORAGE" >&2
  exit 1
fi

remove() {
  local target="$1"
  if [[ -e "$target" ]]; then
    if [[ "$DRY_RUN" == "1" ]]; then
      echo "würde entfernen: $target"
    else
      rm -rf -- "$target"
      echo "entfernt: $target"
    fi
  fi
}

for dir in document_templates document_template_snapshots latex_templates; do
  remove "$STORAGE/$dir"
done

if [[ -d "$STORAGE/document_template_parts" ]]; then
  while IFS= read -r -d '' file; do
    remove "$file"
  done < <(find "$STORAGE/document_template_parts" -type f \( -name '*.tex' -o -name '*.sty' -o -name '*.cls' \) -print0)
  if [[ "$DRY_RUN" == "0" ]]; then
    find "$STORAGE/document_template_parts" -type d -empty -delete
  fi
fi
