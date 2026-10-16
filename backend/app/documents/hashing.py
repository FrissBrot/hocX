"""Hashes des Document Studio.

**Inhalts-Hash** (fachlicher Inhalt, Grundlage der Protokollversionierung): kanonische
JSON-Serialisierung von ``schema_version``, ``meta`` ohne Version, Sprache und Status, den
Blöcken des kanonischen Inhalts und den SHA-256 der eingebetteten Inhaltsbilder. Für Protokolle
ist der kanonische Inhalt immer «alle exportsichtbaren Elemente» (``protocol_element``), egal
welche Vorlage exportiert: eine reine Designänderung (andere Vorlage, anderes Brand-Profil,
andere Sprache) erzeugt so nie eine neue fachliche Version. Die Berechnung ist identisch mit
der ersten Dokument-Engine, bestehende Versionszähler bleiben gültig.

**Design-Hash**: Vorlagenrevision (Layout), Brand-Revision (Tokens), Prüfsummen der
verwendeten Brand-/Vorlagen-Assets und die Compiler-Version. Ändert sich bei jeder
gestalterischen Änderung, nie bei reinen Inhaltsänderungen.

**PDF-Hash**: SHA-256 der exakt ausgelieferten Bytes (service.py, Dokumentenregister).
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from app.documents.model import SCHEMA_VERSION, DocumentMeta

# Erhöhen, wenn sich die Übersetzung Vorlage → Typst sichtbar ändert (Design-Hash).
COMPILER_VERSION = 1


def _dumps(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonical_content(meta: DocumentMeta, blocks: list[Any], assets: dict[str, bytes] | None = None) -> str:
    # Status (Entwurf/abgeschlossen) zählt nicht als Inhalt: dafür gibt es die getrennten Zähler.
    payload = {
        "schema_version": SCHEMA_VERSION,
        "meta": meta.model_dump(mode="json", exclude={"version", "language", "status"}),
        "blocks": [block.model_dump(mode="json") for block in blocks],
        "assets": {path: hashlib.sha256(content).hexdigest() for path, content in sorted((assets or {}).items())},
    }
    return _dumps(payload)


def content_hash(meta: DocumentMeta, blocks: list[Any], assets: dict[str, bytes] | None = None) -> str:
    return hashlib.sha256(canonical_content(meta, blocks, assets).encode("utf-8")).hexdigest()


def json_hash(payload: Any) -> str:
    return hashlib.sha256(_dumps(payload).encode("utf-8")).hexdigest()


def design_hash(template_content: dict[str, Any], brand_tokens: dict[str, Any], asset_checksums: dict[str, str]) -> str:
    return json_hash(
        {
            "compiler": COMPILER_VERSION,
            "template": template_content,
            "brand": brand_tokens,
            "assets": dict(sorted(asset_checksums.items())),
        }
    )
