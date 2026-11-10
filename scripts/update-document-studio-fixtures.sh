#!/usr/bin/env bash
# Erzeugt die Testdaten der Frontend-Tests des Document Studio aus dem Backend (Katalog der
# Knotentypen, Bibliothek, Bindungen, Fachkomponenten und die Standard-Brand-Tokens), damit die
# Komponententests mit echten Strukturen statt handgeschriebener Attrappen laufen.
#   ./scripts/update-document-studio-fixtures.sh
# Nach Änderungen an backend/app/documents/{components,catalog,bindings,brand}.py ausführen
# und frontend/lib/documents/test/studio-catalog.generated.json committen.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
TARGET="frontend/lib/documents/test/studio-catalog.generated.json"
# Image zuerst bauen (Ausgabe nach stderr), damit stdout nur das JSON enthält
docker compose -f docker-compose.tests.yml --profile tests build backend-test >&2
docker compose -f docker-compose.tests.yml --profile tests run --rm --no-deps -T \
  -e DATABASE_URL=postgresql+psycopg://unused:unused@localhost/unused \
  backend-test python - > "$TARGET" <<'PY'
import json

from app.documents.brand import BRAND_PRESETS, BUILTIN_FONTS, BrandTokens, color_references
from app.documents.components import catalog_payload

tokens = BrandTokens()
catalog = catalog_payload()
catalog["color_references"] = color_references(tokens)
catalog["fonts"] = list(BUILTIN_FONTS.values())
catalog["brand_presets"] = list(BRAND_PRESETS)
print(json.dumps({"catalog": catalog, "brand_tokens": tokens.model_dump(mode="json")}, ensure_ascii=False, indent=1, sort_keys=True))
PY
echo "Aktualisiert: $TARGET"
