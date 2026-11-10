#!/usr/bin/env bash
# Aktualisiert die Golden-Bilder der Dokument-Engine bewusst (nach einer gewollten
# Layout-Änderung). Läuft im Backend-Testcontainer, damit Schriften und Typst-Version exakt
# denen der CI entsprechen.
#   ./scripts/update-document-goldens.sh
# Danach die geänderten Dateien unter backend/tests/documents/goldens/ ansehen und committen.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
docker compose -f docker-compose.tests.yml --profile tests run --rm --no-deps \
  -e DATABASE_URL=postgresql+psycopg://unused:unused@localhost/unused \
  -e UPDATE_GOLDENS=1 \
  backend-test python -m pytest tests/documents/test_goldens.py -q -p no:cacheprovider
echo "Goldens aktualisiert: backend/tests/documents/goldens/"
