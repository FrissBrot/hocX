"""PDF-Abdeckung eines Protokolls: was im Editor Inhalt hat, aber nicht im PDF erscheint.

Grundlage ist die Herkunft (``origin``) der Dokumentblöcke: jeder Block aus einem Protokollblock
trägt dessen public_id (providers/protocol.py). Verglichen werden drei Stände:

1. Die Blöcke des Protokolls im Editor (ohne im Editor entfernte Termine).
2. Der kanonische Protokollinhalt (``protocol_element`` ohne Filter, Grundlage des
   Inhalts-Hashes): fehlt ein Block hier, ist er in der Vorlage vom Export ausgenommen
   (``export_visible``) oder leer.
3. Was die Protokoll-Vorlage (Document Studio) tatsächlich setzt: fehlt ein kanonischer Block
   hier, lässt ihn die Vorlage weg (Inhaltsfilter, fehlender Traktanden-Baustein …).

Dieselbe Funktion nutzen die Markierung im Editor (``GET /protocols/{id}/pdf-coverage``) und der
Integritäts-Audit der CI (tests/documents/test_pdf_integrity.py).

Bilder werden dafür nicht geladen (``_MetadataAssets``): nur der Virenscan-Status zählt, damit
die Abfrage auch bei vielen Fotos billig bleibt.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from sqlalchemy.orm import Session

from app.core.element_types import element_type_code
from app.core.security import CurrentUser
from app.documents.catalog import BlockSpec
from app.documents.context import AssetCollector, BuildContext, DocumentNotFoundError, DocumentPermissionError
from app.documents.model import ImageRef, ProtocolElementBlock as ElementModel
from app.documents.providers.protocol import SESSION_NOTES_SECTION, map_block, removed_in_editor, trim_section_name
from app.models import Protocol

Reason = Literal["element_not_exported", "session_notes", "block_not_exported", "omitted_by_layout", "image_unavailable"]


class _MetadataAssets(AssetCollector):
    """Bilder nicht laden: für die Abdeckung zählt nur, ob ein Bild verwendbar ist."""

    def add_image(self, source: Any, *, key: str | None = None, caption: str | None = None) -> ImageRef:  # noqa: ARG002
        return ImageRef(path="assets/missing.png", caption=caption)


@dataclass
class CoverageEntry:
    id: str
    reason: Reason
    count: int | None = None

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"id": self.id, "reason": self.reason}
        if self.count is not None:
            out["count"] = self.count
        return out


@dataclass
class Coverage:
    elements: list[CoverageEntry] = field(default_factory=list)
    blocks: list[CoverageEntry] = field(default_factory=list)
    # False, wenn keine Protokoll-Vorlage aufgelöst werden konnte (dann nur Schritte 1-2)
    layout_checked: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "elements": [entry.as_dict() for entry in self.elements],
            "blocks": [entry.as_dict() for entry in self.blocks],
            "layout_checked": self.layout_checked,
        }


def collect_origins(blocks: list[Any]) -> set[str]:
    """public_ids aller Protokollblöcke/-elemente in einer Blockliste (rekursiv)."""
    found: set[str] = set()
    for block in blocks:
        origin = getattr(block, "origin", None)
        if origin:
            found.add(origin)
        children = getattr(block, "children", None)
        if children:
            found |= collect_origins(children)
    return found


def _missing_images(block: Any) -> int:
    images = getattr(block, "images", None) or []
    return sum(1 for image in images if getattr(image, "missing", False))


def _layout_origins(db: Session, user: CurrentUser | None, tenant_id: int, protocol: Protocol, content: dict | None) -> set[str] | None:
    """Herkunft aller Blöcke, die die Protokoll-Vorlage setzt (ohne PDF-Compile). ``content``:
    ungespeichertes Layout statt der Vorlage des Mandanten (Tests)."""
    from app.documents.service import DocumentRequest, prepare

    try:
        prepared = prepare(
            db, user, tenant_id, DocumentRequest(protocol_id=protocol.public_id, document_type="protocol", content=content),
            preview=True, assets=_MetadataAssets(), skip_version=True,
        )
    except (ValueError, DocumentNotFoundError, DocumentPermissionError):
        # Keine (lesbare) Protokoll-Vorlage, oder sie verweist auf Inhalte ohne Leserecht: die
        # Vorlagenprüfung entfällt, die übrige Abdeckung bleibt
        return None
    return collect_origins(prepared.compiled.blocks)


def protocol_pdf_coverage(db: Session, user: CurrentUser | None, tenant_id: int, protocol: Protocol, *, layout_content: dict | None = None) -> Coverage:
    """Abdeckung berechnen. Ändert nichts: der Export frischt Mitgliedschaftsblöcke auf, das
    läuft hier in einem Savepoint, der zurückgerollt wird."""
    from app.documents.compiler import run_component

    savepoint = db.begin_nested()
    try:
        ctx = BuildContext(db=db, tenant_id=tenant_id, language="de", user=user, protocol=protocol, assets=_MetadataAssets())
        canonical = run_component(ctx, BlockSpec(type="protocol_element"))
        canonical_origins = collect_origins(canonical)
        canonical_blocks = {child.origin: child for element in canonical if isinstance(element, ElementModel) for child in element.children if child.origin}
        layout_origins = _layout_origins(db, user, tenant_id, protocol, layout_content)

        coverage = Coverage(layout_checked=layout_origins is not None)
        content = ctx.protocol_content(protocol)
        elements = content.elements
        for element in elements:
            element_id = str(element.public_id)
            blocks = [block for block in content.blocks(element.id) if not removed_in_editor(block)]
            if not element.export_visible_snapshot:
                coverage.elements.append(CoverageEntry(element_id, "element_not_exported"))
                continue
            if trim_section_name(element.section_name_snapshot).lower() == SESSION_NOTES_SECTION:
                coverage.elements.append(CoverageEntry(element_id, "session_notes"))
                continue
            for block in blocks:
                block_id = str(block.public_id)
                if element_type_code(block.element_type_id) == "display":
                    continue
                if block_id in canonical_origins:
                    if layout_origins is not None and block_id not in layout_origins:
                        coverage.blocks.append(CoverageEntry(block_id, "omitted_by_layout"))
                        continue
                    missing = _missing_images(canonical_blocks.get(block_id))
                    if missing:
                        coverage.blocks.append(CoverageEntry(block_id, "image_unavailable", count=missing))
                    continue
                if not block.export_visible_snapshot:
                    # Nur melden, wenn der Block Inhalt hat: ein leerer Block verliert nichts.
                    mapped = map_block(ctx, protocol, block)
                    if mapped is not None and not mapped.is_empty():
                        coverage.blocks.append(CoverageEntry(block_id, "block_not_exported"))
        return coverage
    finally:
        if savepoint.is_active:
            savepoint.rollback()
