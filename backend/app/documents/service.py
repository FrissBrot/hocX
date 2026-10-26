"""Orchestrierung: Anfrage → Vorlage + Brand + Daten → Layout-Compiler → Typst → XMP → Register.

Ablauf (``prepare``): Mandant, Protokoll (Leserecht) und Sprache bestimmen, Vorlage nach der
Prioritätsregel auflösen (template_service.resolve_template), Brand-Revision auflösen, Inhalts-
Hash und Version berechnen, Layout kompilieren (compiler.py). ``preview`` rendert PNG-Seiten
ohne Seiteneffekte, ``render`` erzeugt das PDF/A-2b, ergänzt das XMP und trägt es im
Dokumentenregister ein.

Jedes ausgelieferte PDF wird im Dokumentenregister (document_registry) mit dem SHA-256 der
exakt ausgelieferten Bytes eingetragen. Die Dokument-ID steht vorher fest und im PDF (Prüfvermerk,
QR-Code, XMP); die öffentliche Prüfseite der Abgabebox vergleicht nur den Hash.

Versionierung (nur Dokumenttyp «protocol»): v0.x für Entwürfe, v1.x für abgeschlossene
Protokolle mit getrennten Zählern. Weicht der Inhalts-Hash (hashing.py, kanonischer Inhalt
unabhängig von der Vorlage) vom letzten Protokoll-Export ab, steigt der passende Zähler **vor**
dem Rendern. Gleicher Inhalt ergibt dieselbe Version; eine andere Vorlage, ein anderes
Brand-Profil oder eine andere Sprache allein ändern sie nie.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.config import settings
from app.core.db import SessionLocal
from app.core.security import CurrentUser
from app.core.storage import MAIN, InvalidObjectKey, StorageError, StorageWriteFenced, get_object_store, key_from_legacy_path, validate_key
from app.documents import brand_service, template_service
from app.documents.brand import BrandTokens, apply_overrides
from app.documents.catalog import BlockSpec
from app.documents.compiler import CompiledDocument, CompileInput, Diagnostic, compile_document
from app.documents.context import AssetCollector, BuildContext, DocumentNotFoundError, DocumentPermissionError
from app.documents.doc_types import get_type
from app.documents.hashing import content_hash, design_hash
from app.documents.layout import LayoutJson, TemplateContent, content_json, parse_content
from app.documents.model import DocumentMeta, RenderInfo
from app.documents.providers.common import PROTOCOL_STATUS_CODES
from app.documents.locking import lock_row
from app.documents.renderer import DocumentRenderError, RenderAssets, RenderOutput, get_renderer
from app.documents.strings import normalize_language, strings_for
from app.documents.xmp import DocumentXmp, add_document_xmp
from app.services import verify_domain_service
from app.models import (
    DocumentBrandRevision,
    DocumentExport,
    DocumentRegistry,
    DocumentTemplate,
    DocumentTemplateRevision,
    Protocol,
    StorageObject,
    StoredFile,
    Template,
    Tenant,
)
from app.models.document_entities import DocumentFile

logger = logging.getLogger(__name__)

GENERATED_DIR = "generated"
PROTOCOL_CONTEXT_TYPES = ("protocol", "invitation", "agenda", "attendance")


class ExportOptions(BaseModel):
    """Optionen pro Export (Export Center). Leer = aus Vorlage bzw. automatisch."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(None, max_length=300)
    subtitle: str | None = Field(None, max_length=300)
    # auto = Wasserzeichen «Entwurf» bei nicht abgeschlossenen Protokollen
    watermark: Literal["auto", "on", "off"] = "auto"


class DocumentRequest(BaseModel):
    """Body von ``POST /api/documents/render`` und ``/preview``.

    ``content``, ``revision_id``, ``brand_tokens`` und ``data_mode="sample"`` sind nur für die
    Vorschau im Document Studio (Designer, Brand Studio) und nie beim Export erlaubt."""

    model_config = ConfigDict(extra="forbid")

    document_type: str | None = Field(None, max_length=40)
    protocol_id: uuid.UUID | None = None
    template_id: uuid.UUID | None = None
    revision_id: uuid.UUID | None = None
    content: LayoutJson | None = None
    brand_id: uuid.UUID | None = None
    brand_tokens: dict[str, Any] | None = None
    # Seitenkontext (z. B. aktive Filter der Todo-Seite, gewählte Liste)
    params: dict[str, Any] = Field(default_factory=dict)
    options: ExportOptions = Field(default_factory=ExportOptions)
    language: str | None = Field(None, max_length=10)
    data_mode: Literal["data", "sample"] = "data"
    # Vorlagen-Editor: Traktanden aus dieser Sitzungsvorlage, Inhalte aus ``protocol_id`` bzw.
    # der letzten Sitzung der Vorlage (nur Vorschau)
    protocol_template_id: uuid.UUID | None = None

    def is_studio_preview(self) -> bool:
        return (
            self.content is not None or self.revision_id is not None or self.brand_tokens is not None
            or self.data_mode == "sample" or self.protocol_template_id is not None
        )


@dataclass
class PreparedDocument:
    compiled: CompiledDocument
    meta: DocumentMeta
    document_type: str
    protocol: Protocol | None
    template: DocumentTemplate | None
    revision: DocumentTemplateRevision | None
    template_source: str | None
    brand_revision: DocumentBrandRevision | None
    content_hash: str
    design_hash: str
    version: tuple[int, int, int] | None  # (major, minor, final_minor) nach diesem Export
    language: str
    ctx: BuildContext
    content: TemplateContent
    params: dict[str, Any] = field(default_factory=dict)
    diagnostics: list[Diagnostic] = field(default_factory=list)
    # Protokolltitel beim Export überschrieben (STUDIO-007): im Register vermerkt
    title_overridden: bool = False


@dataclass
class RenderResult:
    export: DocumentExport
    stored_file: StoredFile


def version_label(major: int, minor: int) -> str | None:
    return f"v{major}.{minor}" if (major > 0 or minor > 0) else None


def _public_base_url() -> str | None:
    return f"https://{settings.traefik_domain}" if settings.traefik_domain else None


def latest_protocol_export(db: Session, protocol_id: int, *, major: int | None = None) -> DocumentExport | None:
    """Letzter versionierter Protokoll-Export; mit ``major`` nur Entwürfe (0) bzw. Endfassungen (1)."""
    query = select(DocumentExport).where(
        DocumentExport.protocol_id == protocol_id,
        DocumentExport.document_type == "protocol",
        DocumentExport.content_hash.is_not(None),
    )
    if major is not None:
        query = query.where(DocumentExport.version_major == major)
    return db.scalar(query.order_by(DocumentExport.created_at.desc(), DocumentExport.id.desc()))


def next_version(db: Session, protocol: Protocol, new_hash: str) -> tuple[int, int, int]:
    is_final = protocol.status == "abgeschlossen"
    # Verglichen wird nur mit dem letzten Export desselben Status: die erste Endfassung ist
    # immer v1.0, auch wenn sich der Inhalt seit dem letzten Entwurfs-Export geändert hat.
    previous = latest_protocol_export(db, protocol.id, major=1 if is_final else 0)
    minor = protocol.version_minor
    final_minor = protocol.version_final_minor
    if previous is not None and previous.content_hash != new_hash:
        if is_final:
            final_minor += 1
        else:
            minor += 1
    return (1 if is_final else 0, minor, final_minor)


def short_document_id(document_id: str | uuid.UUID) -> str:
    """Kurz-ID im Prüfvermerk: letzte 8 Hex-Zeichen (zufälliger Teil der UUIDv7), gruppiert."""
    tail = uuid.UUID(str(document_id)).hex[-8:].upper()
    return f"{tail[:4]}-{tail[4:]}"


def verify_render_info(document_id: uuid.UUID | None, *, preview: bool = False, base: str | None = None) -> RenderInfo:
    """``base``: Prüfseite des Mandanten (verify_domain_service.tenant_verify_base_url), sonst
    die zentrale Prüfseite."""
    base = (base or settings.verify_base_url).rstrip("/")
    display = re.sub(r"^https?://", "", base)
    if preview or document_id is None:
        return RenderInfo(preview=True, short_id="VORSCHAU", verify_display=display, verify_link=base)
    return RenderInfo(
        document_id=str(document_id),
        short_id=short_document_id(document_id),
        verify_display=display,
        verify_link=f"{base}?id={document_id}",
    )


def _protocol_meta(protocol: Protocol, document_type: str, strings: dict[str, str], tenant_name: str, language: str) -> DocumentMeta:
    from app.documents.context import format_date

    return DocumentMeta(
        document_type=document_type,
        title=protocol.title or protocol.protocol_number or strings.get(f"docType.{document_type}", ""),
        number=protocol.protocol_number,
        date=format_date(protocol.protocol_date),
        status=PROTOCOL_STATUS_CODES.get(protocol.status),
        tenant_name=tenant_name,
        language=language,
    )


def canonical_protocol_hash(ctx: BuildContext, protocol: Protocol, strings: dict[str, str], tenant_name: str) -> str:
    """Inhalts-Hash eines Protokolls über alle exportsichtbaren Elemente - unabhängig von der
    Vorlage (siehe hashing.py). Eigene Bildsammlung, damit nur Inhaltsbilder zählen."""
    from app.documents.compiler import run_component

    probe = BuildContext(db=ctx.db, tenant_id=ctx.tenant_id, language=ctx.language, user=ctx.user, today=ctx.today, protocol=protocol, public_base_url=ctx.public_base_url, assets=AssetCollector())
    blocks = run_component(probe, BlockSpec(type="protocol_element"))
    meta = _protocol_meta(protocol, "protocol", strings, tenant_name, ctx.language)
    return content_hash(meta, blocks, probe.assets.files)


def _latest_readable_protocol(db: Session, user: CurrentUser | None, template: Template) -> Protocol | None:
    """Letzte Sitzung einer Sitzungsvorlage, die der Benutzer lesen darf (Vorschau mit echten Daten)."""
    from app.services.access_service import AccessService

    access = AccessService()
    candidates = db.scalars(
        select(Protocol)
        .where(Protocol.template_id == template.id, Protocol.tenant_id == template.tenant_id)
        .order_by(Protocol.protocol_date.desc(), Protocol.id.desc())
        .limit(20)
    )
    for protocol in candidates:
        if user is None or access.can_read_protocol(db, user, protocol.id):
            return protocol
    return None


def _resolve_explicit_template(db: Session, tenant_id: int, request: DocumentRequest) -> DocumentTemplate | None:
    if request.template_id is None:
        return None
    template = template_service.get_template(db, tenant_id, request.template_id)
    if template is None:
        raise DocumentNotFoundError("DocumentTemplate")
    return template


def prepare(
    db: Session,
    user: CurrentUser | None,
    tenant_id: int,
    request: DocumentRequest,
    *,
    today: date | None = None,
    preview: bool = False,
    render_info: RenderInfo | None = None,
) -> PreparedDocument:
    if not preview and request.is_studio_preview():
        raise ValueError("previewOnly")
    tenant = db.get(Tenant, tenant_id)
    tenant_name = tenant.name if tenant else ""
    protocol = None
    if request.protocol_id is not None:
        protocol = db.scalar(select(Protocol).where(Protocol.public_id == request.protocol_id, Protocol.tenant_id == tenant_id))
        if protocol is None:
            raise DocumentNotFoundError("Protocol")

    session_template = None
    if request.protocol_template_id is not None:
        session_template = db.scalar(select(Template).where(Template.public_id == request.protocol_template_id, Template.tenant_id == tenant_id))
        if session_template is None:
            raise DocumentNotFoundError("Template")
        if user is not None:
            from app.services.access_service import AccessService

            if not AccessService().can_read_template(db, user, session_template.id):
                raise DocumentNotFoundError("Template")
        if protocol is None and request.data_mode == "data":
            protocol = _latest_readable_protocol(db, user, session_template)
        elif protocol is not None and protocol.template_id != session_template.id:
            raise DocumentNotFoundError("Protocol")

    explicit = _resolve_explicit_template(db, tenant_id, request)
    document_type = request.document_type or (explicit.document_type if explicit is not None else None) or ("protocol" if protocol else "custom")
    doc_type = get_type(document_type)
    sample = request.data_mode == "sample"
    if doc_type.needs_protocol and protocol is None and not sample and session_template is None:
        raise ValueError("protocol_required")

    # Fremde oder unbekannte Brand vor allem anderen ablehnen (Security-Audit SEC-018): die
    # Vorlagenauflösung darf mit ihren eigenen Fehlern die Mandantenprüfung nicht verdecken.
    explicit_brand = brand_service.get_brand(db, tenant_id, request.brand_id) if request.brand_id else None
    if request.brand_id and explicit_brand is None:
        raise DocumentNotFoundError("DocumentBrand")

    # Vorlage: ungespeicherter Inhalt (Designer) > bestimmte Revision > Prioritätsregel
    resolved = None
    revision: DocumentTemplateRevision | None = None
    template: DocumentTemplate | None = explicit
    template_source = None
    if request.revision_id is not None:
        if explicit is None:
            raise ValueError("unknown_document_type")
        revision = template_service.get_revision(db, explicit, request.revision_id)
        if revision is None:
            raise DocumentNotFoundError("DocumentTemplateRevision")
        template_source = "revision"
    if request.content is None and revision is None:
        resolved = template_service.resolve_template(
            db, tenant_id, document_type, explicit=explicit, protocol_template_id=session_template.id if session_template is not None else protocol.template_id if protocol is not None else None
        )
        template, revision, template_source = resolved.template, resolved.revision, resolved.source
    if request.content is not None:
        content = TemplateContent.model_validate(request.content)
        template_source = "unsaved"
    else:
        content = template_service.revision_content(revision)

    language = normalize_language(content.settings.language or request.language or (tenant.document_language if tenant else None))
    strings = strings_for(language)
    ctx = BuildContext(db=db, tenant_id=tenant_id, language=language, user=user, today=today or date.today(), protocol=protocol, public_base_url=_public_base_url(), session_template=session_template)
    if protocol is not None:
        ctx.ensure_can_read_protocol(protocol.id)

    # Brand: ungespeicherte Tokens (Brand Studio) > explizit > Zuweisung > Vorlage > Standard
    # (explicit_brand ist oben bereits mandantengebunden geladen.)
    if resolved is None and template is not None and revision is not None:
        resolved = template_service.ResolvedTemplate(template=template, revision=revision, source=template_source or "explicit", brand_id=None)
    brand_revision = template_service.resolve_brand_revision(db, tenant_id, resolved, explicit_brand=explicit_brand)
    override_tokens = BrandTokens.model_validate(request.brand_tokens) if request.brand_tokens is not None else None
    base_tokens = override_tokens if override_tokens is not None else brand_service.tokens_of(brand_revision)
    effective_tokens = apply_overrides(base_tokens, content.settings.brand_overrides)
    brand = brand_service.resolve_brand(db, tenant_id, brand_revision, tokens=effective_tokens)

    # Meta (fachliche Angaben, Grundlage des Inhalts-Hashes)
    options = request.options
    title_overridden = False
    if protocol is not None and document_type in PROTOCOL_CONTEXT_TYPES:
        meta = _protocol_meta(protocol, document_type, strings, tenant_name, language)
        if options.title:
            title_overridden = options.title != meta.title
            meta.title = options.title
        meta.subtitle = options.subtitle
        if document_type != "protocol":
            meta.status = None
    else:
        from app.documents.context import format_date

        meta = DocumentMeta(
            document_type=document_type,
            title=options.title or strings.get(f"docType.{document_type}", strings.get("docType.custom", "")),
            subtitle=options.subtitle,
            date=format_date(ctx.today),
            tenant_name=tenant_name,
            language=language,
        )

    version = None
    protocol_hash = None
    if protocol is not None and document_type == "protocol" and not sample:
        protocol_hash = canonical_protocol_hash(ctx, protocol, strings, tenant_name)
        version = next_version(db, protocol, protocol_hash)
        major, minor, final_minor = version
        meta.version = version_label(major, final_minor if major else minor)

    protocol_draft = protocol is not None and document_type == "protocol" and protocol.status != "abgeschlossen"
    is_draft = protocol_draft
    if options.watermark == "on":
        is_draft = True
    elif options.watermark == "off":
        # Entwürfe ohne Kennzeichnung nur mit Schreibrecht (STUDIO-007); Leser behalten das
        # Wasserzeichen. user None = Systemaufruf ohne Benutzer.
        can_write = user is None or user.current_role in {"writer", "admin"}
        if not protocol_draft or can_write:
            is_draft = False

    render = render_info or verify_render_info(None, preview=True, base=verify_domain_service.tenant_verify_base_url(db, tenant_id))
    document_env = {
        "title": meta.title,
        "subtitle": meta.subtitle,
        "type": strings.get(f"docType.{document_type}", ""),
        "date": protocol.protocol_date if protocol is not None and document_type in PROTOCOL_CONTEXT_TYPES else ctx.today,
        "number": meta.number,
        "version": meta.version,
        "status": strings.get(f"protocolStatus.{meta.status}", "") if meta.status else "",
        "language": language,
        "is_draft": is_draft,
        "short_id": render.short_id,
        "created_by": user.display_name if user is not None else "",
    }
    compiled = compile_document(
        db,
        CompileInput(
            content=content,
            brand=brand,
            ctx=ctx,
            meta=meta,
            strings=strings,
            render=render,
            mode=request.data_mode,
            strict=not preview,
            params=request.params,
            is_draft=is_draft,
            document_env=document_env,
        ),
    )
    digest = protocol_hash or content_hash(meta, compiled.blocks, ctx.assets.files)
    design = design_hash(content_json(content), brand.tokens.model_dump(mode="json"), {**brand.asset_checksums, **compiled.template_asset_checksums})
    return PreparedDocument(
        compiled=compiled,
        meta=meta,
        document_type=document_type,
        protocol=protocol,
        template=template,
        revision=revision if request.content is None else None,
        template_source=template_source,
        brand_revision=brand_revision if override_tokens is None else None,
        content_hash=digest,
        design_hash=design,
        version=version,
        language=language,
        ctx=ctx,
        content=content,
        params=dict(request.params),
        diagnostics=compiled.diagnostics,
        title_overridden=title_overridden,
    )


@dataclass
class PreviewResult:
    pages: list[bytes]
    diagnostics: list[Diagnostic]
    page_count: int
    template_id: uuid.UUID | None
    template_source: str | None
    design_hash: str


async def _prepare_off_loop(db: Session, user: CurrentUser | None, tenant_id: int, request: DocumentRequest, **kwargs: Any) -> PreparedDocument:
    """``prepare`` (Provider-Abfragen, Bildnormalisierung mit Pillow) im Threadpool, damit die
    Event-Loop des Workers währenddessen andere Requests und WebSockets bedient (TYPST-004). Die
    Session wird dabei nie gleichzeitig benutzt: die Route wartet auf das Ergebnis."""
    return await run_in_threadpool(prepare, db, user, tenant_id, request, **kwargs)


async def preview(db: Session, user: CurrentUser | None, tenant_id: int, request: DocumentRequest, *, max_pages: int | None = None) -> PreviewResult:
    """Seiten als PNG: ohne Register-Eintrag, ohne Speicherung, ohne Versionserhöhung."""

    def prepare_and_release() -> tuple[PreparedDocument, uuid.UUID | None]:
        # Die Vorschau darf nichts verändern (z. B. nachgeführte Mitgliedschaftsblöcke): alles in
        # einem Savepoint, der sofort zurückgerollt wird. Danach endet die Transaktion, damit die
        # Verbindung nicht über Warteschlange und Compile (bis 80 s) belegt bleibt (CONC-003).
        savepoint = db.begin_nested()
        try:
            prepared = prepare(db, user, tenant_id, request, preview=True)
            template_public_id = prepared.template.public_id if prepared.template is not None else None
        finally:
            if savepoint.is_active:
                savepoint.rollback()
        db.commit()
        return prepared, template_public_id

    prepared, template_public_id = await run_in_threadpool(prepare_and_release)
    compiled = prepared.compiled
    output = await get_renderer().render_preview(compiled.data, RenderAssets(files=compiled.files, fonts=compiled.fonts), max_pages=max_pages, tenant_id=tenant_id)
    return PreviewResult(
        pages=output.pages,
        diagnostics=prepared.diagnostics,
        page_count=output.page_count or len(output.pages),
        template_id=template_public_id,
        template_source=prepared.template_source,
        design_hash=prepared.design_hash,
    )


# Ausschnitte der Arbeitsfläche: höchstens so viele je Anfrage, höchstens so hoch (mm)
CANVAS_MAX_SNIPPETS = 24
CANVAS_SNIPPET_MAX_HEIGHT_MM = 600
# Rand oben/unten je Ausschnitt (Ober-/Unterlängen); die Arbeitsfläche zieht ihn wieder ab
CANVAS_SNIPPET_PAD_MM = 2


@dataclass
class CanvasResult:
    hints: dict[str, Any]
    brand: dict[str, Any]
    numbering: bool
    snippets: dict[str, bytes]
    diagnostics: list[Diagnostic]
    snippet_pad: float = CANVAS_SNIPPET_PAD_MM


def _area_width(content: TemplateContent, area: str) -> float:
    """Breite des Inhaltsbereichs in mm (Ausschnitte werden in dieser Breite gesetzt)."""
    width, _ = content.page.dimensions_mm()
    if area == "title_page":
        master = content.master(content.title_page.master) if content.title_page.master else None
    else:
        master = content.master(content.settings.default_master)
    if master is not None and master.orientation is not None:
        short, long = sorted(content.page.dimensions_mm())
        width = long if master.orientation == "landscape" else short
    margins = master.margins if master is not None and master.margins is not None else content.page.margins
    usable = width - margins.left - margins.right
    if area == "body" and content.page.columns > 1:
        usable = (usable - content.page.column_gap * (content.page.columns - 1)) / content.page.columns
    return max(usable, 10)


def _heading_counter(headings: list[dict[str, Any]]) -> list[int]:
    """Stand des Überschriftenzählers (wie Typsts counter(heading)) nach diesen Überschriften,
    damit die Nummern im Ausschnitt an der richtigen Stelle weiterzählen."""
    counts: list[int] = []
    for heading in headings:
        level = max(1, int(heading.get("level", 1)))
        while len(counts) < level:
            counts.append(0)
        counts = counts[:level]
        counts[level - 1] += 1
    return counts


def _without_breaks(node: Any) -> Any:
    """Seitenumbrüche entfernen: ein Ausschnitt ist genau eine Seite."""
    if isinstance(node, dict):
        return {key: _without_breaks(value) for key, value in node.items() if key != "break"} if node.get("t") != "pagebreak" else {"t": "stack", "id": node.get("id"), "s": {}, "children": [], "gap": 0}
    if isinstance(node, list):
        return [_without_breaks(item) for item in node]
    return node


async def canvas(db: Session, user: CurrentUser | None, tenant_id: int, request: DocumentRequest) -> CanvasResult:
    """Werte für die Arbeitsfläche des Designers: dieselbe Kompilierung wie die Vorschau, aber statt
    ganzer Seiten die aufgelösten Texte/Sichtbarkeiten (CanvasHints) und Fachkomponenten bzw.
    Tabellen als einzeln gerenderte SVG-Ausschnitte."""

    def prepare_and_release() -> PreparedDocument:
        # Wie preview(): nichts verändern, Verbindung vor dem Compile wieder freigeben.
        savepoint = db.begin_nested()
        try:
            prepared = prepare(db, user, tenant_id, request, preview=True)
        finally:
            if savepoint.is_active:
                savepoint.rollback()
        db.commit()
        return prepared

    prepared = await run_in_threadpool(prepare_and_release)
    compiled = prepared.compiled
    hints = compiled.canvas
    entries = list(hints.snippets.items())[:CANVAS_MAX_SNIPPETS]
    snippets: dict[str, bytes] = {}
    if entries:
        document = {
            **compiled.data,
            "snippets": [
                {
                    "width": _area_width(prepared.content, area),
                    "max_height": CANVAS_SNIPPET_MAX_HEIGHT_MM,
                    "pad": CANVAS_SNIPPET_PAD_MM,
                    "headings": _heading_counter(hints.headings[:before]),
                    "node": _without_breaks(node),
                }
                for _, (area, node, before) in entries
            ],
        }
        try:
            output = await get_renderer().render_svg(document, RenderAssets(files=compiled.files, fonts=compiled.fonts), tenant_id=tenant_id)
        except DocumentRenderError:
            # Erwartet bei fehlerhaften Vorlagen: die Vorschau meldet den Fehler am Element, die
            # Arbeitsfläche zeigt dann ihre Platzhalter.
            output = None
        if output is not None and len(output.pages) == len(entries):
            snippets = {key: page for (key, _), page in zip(entries, output.pages)}
    return CanvasResult(
        hints=hints.as_dict(),
        brand=compiled.data["brand"],
        numbering=compiled.data["settings"]["numbering"],
        snippets=snippets,
        diagnostics=prepared.diagnostics,
    )


def _filename(title: str, version: str | None) -> str:
    base = re.sub(r"[^A-Za-z0-9._ -]+", "-", (title or "").strip()).strip(" .-_") or "dokument"
    return f"{base}-{version}.pdf" if version else f"{base}.pdf"


def _generated_prefix() -> str:
    """Key-Präfix der erzeugten PDFs im Objektspeicher (Namespace «main», relativ zu STORAGE_ROOT)."""
    return key_from_legacy_path(str(Path(settings.export_root) / GENERATED_DIR))


def _store_pdf(db: Session, tenant_id: int, pdf: bytes, filename: str, user_id: int | None) -> StoredFile:
    """Legt das PDF im Objektspeicher ab und registriert es in der Transaktion des Aufrufers.
    Rollt der Aufrufer zurück, entfernt er das Objekt mit ``_discard_pdf``."""
    key = validate_key(f"{_generated_prefix()}/{uuid.uuid4().hex}-{filename}")
    store = get_object_store()
    store.put_bytes(db, MAIN, key, pdf, content_type="application/pdf")
    stored = StoredFile(
        tenant_id=tenant_id,
        original_name=filename,
        mime_type="application/pdf",
        storage_path=key,
        file_size_bytes=len(pdf),
        checksum_sha256=hashlib.sha256(pdf).hexdigest(),
        created_by=user_id,
    )
    db.add(stored)
    try:
        db.flush()
    except Exception:
        _discard_pdf(key)
        raise
    return stored


def _discard_pdf(key: str) -> None:
    """Objekt eines zurückgerollten Exports entfernen (die Registrierung ist mit zurückgerollt)."""
    try:
        get_object_store().discard_unregistered(MAIN, key)
    except StorageError as exc:
        logger.warning("Objekt %s eines abgebrochenen Exports nicht entfernt: %s", key, exc)


async def render(db: Session, user: CurrentUser | None, tenant_id: int, request: DocumentRequest) -> RenderResult:
    """PDF erzeugen und registrieren. DB-Arbeit (Vorbereitung, Speichern, Register) läuft im
    Threadpool, nur der Compile wird im Event-Loop erwartet (CONC-001/-003). Ändert sich die
    Protokollversion zwischen Vorbereitung und Speichern (paralleler Export), wird einmal neu
    gerendert - sonst trügen zwei PDFs dieselbe Versionsnummer (CONC-019)."""
    for attempt in range(2):
        export_public_id = _uuid7()
        # Prüfseite einmal festlegen: Vermerk, QR-Code, XMP und Export müssen dieselbe URL tragen.
        render_info = await run_in_threadpool(
            lambda: verify_render_info(export_public_id, base=verify_domain_service.tenant_verify_base_url(db, tenant_id))
        )
        prepared = await _prepare_off_loop(db, user, tenant_id, request, render_info=render_info)
        compiled = prepared.compiled
        output = await get_renderer().render_pdf(compiled.data, RenderAssets(files=compiled.files, fonts=compiled.fonts), tenant_id=tenant_id)
        result = await run_in_threadpool(
            _finalize_render, db, user, tenant_id, request, prepared, output, export_public_id, render_info, retry_allowed=attempt == 0
        )
        if result is not None:
            return result
    raise RuntimeError("Protokollversion änderte sich während des Exports wiederholt")


def _finalize_render(
    db: Session,
    user: CurrentUser | None,
    tenant_id: int,
    request: DocumentRequest,
    prepared: PreparedDocument,
    output: RenderOutput,
    export_public_id: uuid.UUID,
    render_info: RenderInfo,
    *,
    retry_allowed: bool,
) -> RenderResult | None:
    """Nacharbeit eines Renders im Threadpool. None: Version hat sich inzwischen geändert, der
    Aufrufer rendert neu."""
    meta = prepared.meta
    if prepared.version is not None and prepared.protocol is not None:
        # Versionsvergabe serialisieren: Sperre bis zum Commit unten, dann mit dem aktuellen Stand
        # vergleichen.
        locked = lock_row(db, prepared.protocol)
        if next_version(db, locked, prepared.content_hash) != prepared.version and retry_allowed:
            db.rollback()
            return None
    tenant = db.get(Tenant, tenant_id)
    pdf = add_document_xmp(
        output.pdf or b"",
        DocumentXmp(
            document_id=str(export_public_id),
            # Mandanten-ID nur, wenn der Mandant seine Anzeige auf der Prüfseite freigegeben hat.
            tenant_id=str(tenant.public_id) if tenant is not None and tenant.verify_show_identity else "",
            document_type=prepared.document_type,
            version=meta.version or "",
            content_hash=prepared.content_hash,
            design_hash=prepared.design_hash,
            template_revision=str(prepared.revision.public_id) if prepared.revision is not None else "",
            verify_url=render_info.verify_link or "",
        ),
    )
    # Hash über genau die Bytes, die ausgeliefert werden.
    sha256 = hashlib.sha256(pdf).hexdigest()

    major = minor = None
    protocol = prepared.protocol
    if prepared.version is not None and protocol is not None:
        major, new_minor, new_final = prepared.version
        protocol.version_major = major
        protocol.version_minor = new_minor
        protocol.version_final_minor = new_final
        minor = new_final if major else new_minor
        db.add(protocol)
    # Datei, StoredFile, Export und Register-Eintrag gemeinsam: scheitert ein Teil, gibt es
    # nichts (die Datei wird beim Rollback entfernt).
    stored = _store_pdf(db, tenant_id, pdf, _filename(meta.title, meta.version), user.user_id if user else None)
    try:
        export = DocumentExport(
            public_id=export_public_id,
            tenant_id=tenant_id,
            protocol_id=protocol.id if protocol is not None else None,
            document_type=prepared.document_type,
            title=meta.title,
            version_label=meta.version,
            version_major=major,
            version_minor=minor,
            content_hash=prepared.content_hash,
            design_hash=prepared.design_hash,
            template_id=prepared.template.id if prepared.template is not None else None,
            template_revision_id=prepared.revision.id if prepared.revision is not None else None,
            brand_revision_id=prepared.brand_revision.id if prepared.brand_revision is not None else None,
            options_json={
                "options": request.options.model_dump(mode="json"),
                "params": request.params,
                "template_source": prepared.template_source,
                # Prüf-Link genau wie im PDF (Prüf-Domain des Mandanten kann später wechseln)
                "verify_url": render_info.verify_link,
            },
            language=prepared.language,
            stored_file_id=stored.id,
            created_by=user.user_id if user else None,
        )
        db.add(export)
        db.add(
            DocumentRegistry(
                public_id=export_public_id,
                tenant_id=tenant_id,
                sha256=sha256,
                document_type=prepared.document_type,
                title=meta.title,
                status_code=protocol.status if protocol is not None and prepared.document_type == "protocol" else None,
                version_major=major,
                version_minor=minor,
                version_label=meta.version,
                content_hash=prepared.content_hash,
                design_hash=prepared.design_hash,
                source_public_id=protocol.public_id if protocol is not None else None,
                title_overridden=prepared.title_overridden,
                created_by=user.user_id if user else None,
            )
        )
        db.flush()
        if protocol is not None:
            # Logisches Dokument im Dateien-Tab (feature/document-management): neuer Inhalt = neue
            # Version, gleicher Inhalt ersetzt nur die Darstellung. Vor dem Freigeben älterer
            # Dateien, damit der Backfill sie noch als Versionen übernehmen kann.
            from app.services import protocol_export_document_service

            protocol_export_document_service.record_export(db, protocol=protocol, export=export, stored_file=stored)
        # Ältere Dateien als Tombstones in derselben Transaktion (S3-008); physisch löscht der
        # Job storage_purge nach dem Commit. Dateien von Dokumentversionen bleiben (_release_files).
        _prune_superseded_files(db, export)
        db.commit()
    except Exception:
        db.rollback()
        _discard_pdf(stored.storage_path)
        raise
    db.refresh(export)
    return RenderResult(export=export, stored_file=stored)


def _without_document_versions(db: Session, exports: list[DocumentExport]) -> list[DocumentExport]:
    """Exporte, deren Datei zu einer Version eines logischen Dokuments gehört (document_file,
    Dateien-Tab), werden nie freigegeben - sonst verschwände die Version still aus der Historie."""
    candidate_ids = {export.stored_file_id for export in exports if export.stored_file_id is not None}
    if not candidate_ids:
        return exports
    versioned = set(db.scalars(select(DocumentFile.stored_file_id).where(DocumentFile.stored_file_id.in_(candidate_ids))))
    return [export for export in exports if export.stored_file_id not in versioned]


def _release_files(db: Session, exports: list[DocumentExport]) -> list[str]:
    """Löst die PDF-Datei (StoredFile) von Exporten; Export-Zeile und Register-Eintrag bleiben
    (Verlauf und Echtheitsprüfung über den Hash). Die Objekte werden in der Transaktion des
    Aufrufers als gelöscht registriert (Tombstone, S3-008) - ein Rollback nimmt beides zurück,
    physisch entfernt sie der Job storage_purge nach dem Commit. Gibt die Keys zurück."""
    exports = _without_document_versions(db, exports)
    file_ids = {export.stored_file_id for export in exports if export.stored_file_id is not None}
    for export in exports:
        export.stored_file_id = None
    db.flush()
    keys: list[str] = []
    store = get_object_store()
    for file_id in file_ids:
        still_used = db.scalar(select(DocumentExport.id).where(DocumentExport.stored_file_id == file_id).limit(1))
        stored = db.get(StoredFile, file_id)
        if still_used is not None or stored is None:
            continue
        keys.append(stored.storage_path)
        db.delete(stored)
    db.flush()
    for key in keys:
        try:
            store.delete(db, MAIN, key)
        except InvalidObjectKey:
            logger.warning("Ungültiger Speicher-Key eines Exports übersprungen: %s", key)
    return keys


def _prune_superseded_files(db: Session, export: DocumentExport) -> list[str]:
    """Audit MAIN-BE-004 (aus main übernommen): Jeder Export legte eine neue Datei samt StoredFile
    an, die nie gelöscht wurde - das Speicherkontingent wuchs mit jedem Export. Bei Protokollen
    bleibt nur die Datei des neuesten Exports; Auszüge und andere Dokumente sind jeweils eigene
    Dokumente und laufen über die Altersfrist (cleanup_old_generated_exports)."""
    if export.protocol_id is None or export.document_type != "protocol":
        return []
    older = list(db.scalars(
        select(DocumentExport).where(
            DocumentExport.protocol_id == export.protocol_id,
            DocumentExport.document_type == "protocol",
            DocumentExport.id != export.id,
            DocumentExport.stored_file_id.is_not(None),
        )
    ))
    return _release_files(db, older)


def supersede_closed_exports(db: Session, protocol: Protocol) -> list[str]:
    """Erneuter Abschluss nach einer Korrektur (Datenschutz-Audit F, Paket 7): die PDFs des
    früheren Abschlusses zeigen den alten, ggf. falschen Inhalt. Ihre Dateien werden sofort
    gelöscht (nicht erst nach der Aufbewahrungsfrist), die Register-Einträge behalten nur den
    Hash - ohne Titel. Die Prüfseite meldet sie über is_superseded als ersetzt, sobald das neue PDF
    erzeugt ist. In Dokumentenverwaltung übernommene Versionen bleiben (_without_document_versions).
    In der Transaktion des Aufrufers; gibt die gelöschten Keys zurück."""
    previous = select(DocumentRegistry.public_id).where(
        DocumentRegistry.tenant_id == protocol.tenant_id,
        DocumentRegistry.source_public_id == protocol.public_id,
        DocumentRegistry.document_type == "protocol",
        DocumentRegistry.status_code == "abgeschlossen",
    )
    exports = list(db.scalars(
        select(DocumentExport).where(
            DocumentExport.protocol_id == protocol.id,
            DocumentExport.document_type == "protocol",
            DocumentExport.public_id.in_(previous),
            DocumentExport.stored_file_id.is_not(None),
        )
    ))
    keys = _release_files(db, exports) if exports else []
    db.execute(
        update(DocumentRegistry)
        .where(DocumentRegistry.public_id.in_(previous), DocumentRegistry.title.is_not(None))
        .values(title=None)
        .execution_options(synchronize_session=False)
    )
    return keys


def _protected_export_ids(db: Session) -> set[int]:
    """Neuester Protokoll-Export abgeschlossener Protokolle: das finale PDF bleibt über die
    Aufbewahrungsfrist hinaus abrufbar (MAIN-BE-004)."""
    ranked = (
        select(
            DocumentExport.id,
            func.row_number()
            .over(partition_by=DocumentExport.protocol_id, order_by=(DocumentExport.created_at.desc(), DocumentExport.id.desc()))
            .label("rank"),
        )
        .join(Protocol, Protocol.id == DocumentExport.protocol_id)
        .where(Protocol.status == "abgeschlossen", DocumentExport.document_type == "protocol")
        .subquery()
    )
    return set(db.scalars(select(ranked.c.id).where(ranked.c.rank == 1)))


def _uuid7() -> uuid.UUID:
    """UUIDv7 wie die DB-Vorgabe (uuidv7()), damit die Dokument-ID vor dem Rendern feststeht."""
    import os
    import time

    timestamp_ms = int(time.time() * 1000) & ((1 << 48) - 1)
    rand_a = int.from_bytes(os.urandom(2), "big") & 0xFFF
    rand_b = int.from_bytes(os.urandom(8), "big") & ((1 << 62) - 1)
    return uuid.UUID(int=(timestamp_ms << 80) | (0x7 << 76) | (rand_a << 64) | (0b10 << 62) | rand_b)


def cleanup_old_generated_exports(db: Session | None = None, *, retention_days: int | None = None) -> dict:
    """Retention-Job (main.py export_cleanup_loop): löscht alte Objekte unter
    EXPORT_ROOT/generated im Objektspeicher. Das Dokumentenregister bleibt unangetastet:
    ausgelieferte PDFs sind über ihren Hash dauerhaft prüfbar.

    Mit ``db`` (Hintergrund-Loop, MAIN-BE-004 aus main) zuerst auf DB-Basis: Exporte älter als
    die Frist verlieren ihre Datei samt StoredFile (sonst blieben die Bytes im
    Speicherkontingent und ein Link zeigte auf eine fehlende Datei), ausgenommen der neueste
    Export abgeschlossener Protokolle. Danach entfernt der Objekt-Sweep verwaiste Objekte ohne
    Zeile, ebenfalls ohne die geschützten. Löschungen sind Tombstones, die der Job
    storage_purge nach dem Commit physisch entfernt; bei einem Write-Fence (Cutover/Wartung)
    ist für diesen Lauf Schluss (S3-008)."""
    retention = retention_days if retention_days is not None else settings.export_retention_days
    cutoff_timestamp = datetime.now(UTC).timestamp() - retention * 86400
    released = 0
    protected_keys: set[str] = set()
    session = db if db is not None else SessionLocal()
    store = get_object_store()
    try:
        if db is not None:
            protected = _protected_export_ids(db)
            cutoff = datetime.fromtimestamp(cutoff_timestamp, tz=UTC)
            expired = _without_document_versions(db, [
                export
                for export in db.scalars(
                    select(DocumentExport).where(DocumentExport.created_at < cutoff, DocumentExport.stored_file_id.is_not(None))
                )
                if export.id not in protected
            ])
            try:
                _release_files(db, expired)
                db.commit()
            except StorageWriteFenced:
                db.rollback()
                return {"deleted": 0, "released": 0}
            released = len(expired)
            if protected:
                protected_keys = set(
                    db.scalars(
                        select(StoredFile.storage_path)
                        .join(DocumentExport, DocumentExport.stored_file_id == StoredFile.id)
                        .where(DocumentExport.id.in_(protected))
                    )
                )
        deleted = 0
        try:
            prefix = _generated_prefix() + "/"
        except ValueError:
            prefix = None
        if prefix is not None:
            referenced = set(session.scalars(select(StoredFile.storage_path).where(StoredFile.storage_path.startswith(prefix))))
            stale = [
                info.key
                for info in store.list(MAIN, prefix)
                if info.last_modified is not None
                and info.last_modified.timestamp() < cutoff_timestamp
                and info.key not in protected_keys
                and info.key not in referenced
            ]
            if stale:
                # Schon gelöscht, nur physisch noch nicht entfernt: nicht erneut registrieren.
                pending = set(session.scalars(select(StorageObject.key).where(
                    StorageObject.namespace == MAIN, StorageObject.status == "deleted",
                    StorageObject.purge_pending.is_(True), StorageObject.key.in_(stale))))
                stale = [key for key in stale if key not in pending]
            try:
                for key in stale:
                    store.delete(session, MAIN, key)
                session.commit()
                deleted = len(stale)
            except StorageWriteFenced:
                session.rollback()
    finally:
        if db is None:
            session.close()
    if db is not None:
        return {"deleted": deleted, "released": released}
    return {"deleted": deleted}


__all__ = [
    "DocumentPermissionError",
    "DocumentRequest",
    "ExportOptions",
    "PreparedDocument",
    "PreviewResult",
    "RenderResult",
    "canonical_protocol_hash",
    "cleanup_old_generated_exports",
    "content_json",
    "parse_content",
    "prepare",
    "preview",
    "render",
    "short_document_id",
    "verify_render_info",
]
