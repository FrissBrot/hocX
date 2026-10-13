"""Inhalts-Hash für die Versionierung.

Gehasht wird die kanonische JSON-Serialisierung von Inhalt und Meta: ``schema_version``,
``meta`` ohne Version, Sprache und Status, ``blocks`` und die SHA-256 der eingebetteten Bilder. Nicht
gehasht werden Hausstil, Optionen (Titelseite, TOC …), die Texte der Sprache und die
Render-Angaben (Dokument-ID, Zeitpunkt, Signatur). Ein neuer Hausstil oder eine andere Sprache
allein ändert die Version also nicht.
"""
from __future__ import annotations

import hashlib
import json

from app.documents.model import Document


def canonical_content(document: Document, assets: dict[str, bytes] | None = None) -> str:
    # Status (Entwurf/abgeschlossen) zählt nicht als Inhalt: dafür gibt es die getrennten Zähler.
    meta = document.meta.model_dump(mode="json", exclude={"version", "language", "status"})
    payload = {
        "schema_version": document.schema_version,
        "meta": meta,
        "blocks": [block.model_dump(mode="json") for block in document.blocks],
        "assets": {path: hashlib.sha256(content).hexdigest() for path, content in sorted((assets or {}).items())},
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def content_hash(document: Document, assets: dict[str, bytes] | None = None) -> str:
    return hashlib.sha256(canonical_content(document, assets).encode("utf-8")).hexdigest()
