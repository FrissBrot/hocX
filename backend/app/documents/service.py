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
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import CurrentUser
from app.documents import brand_service, template_service
from app.documents.brand import BrandTokens, apply_overrides
from app.documents.catalog import BlockSpec
from app.documents.compiler import CompiledDocument, CompileInput, Diagnostic, compile_document
from app.documents.context import AssetCollector, BuildContext, DocumentNotFoundError, DocumentPermissionError
from app.documents.doc_types import get_type
from app.documents.hashing import content_hash, design_hash
from app.documents.layout import TemplateContent, content_json, parse_content
from app.documents.model import DocumentMeta, RenderInfo
from app.documents.providers.common import PROTOCOL_STATUS_CODES
from app.documents.renderer import RenderAssets, get_renderer
from app.documents.strings import normalize_language, strings_for
from app.documents.xmp import DocumentXmp, add_document_xmp
from app.models import (
    DocumentBrandRevision,
    DocumentExport,
    DocumentRegistry,
    DocumentTemplate,
    DocumentTemplateRevision,
    Protocol,
    StoredFile,
    Tenant,
)

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
    content: dict[str, Any] | None = None
    brand_id: uuid.UUID | None = None
    brand_tokens: dict[str, Any] | None = None
    # Seitenkontext (z. B. aktive Filter der Todo-Seite, gewählte Liste)
    params: dict[str, Any] = Field(default_factory=dict)
    options: ExportOptions = Field(default_factory=ExportOptions)
    language: str | None = Field(None, max_length=10)
    data_mode: Literal["data", "sample"] = "data"

    def is_studio_preview(self) -> bool:
        return self.content is not None or self.revision_id is not None or self.brand_tokens is not None or self.data_mode == "sample"


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


@dataclass
class RenderResult:
    export: DocumentExport
    stored_file: StoredFile


def version_label(major: int, minor: int) -> str | None:
    return f"v{major}.{minor}" if (major > 0 or minor > 0) else None


def _public_base_url() -> str | None:
    return f"https://{settings.traefik_domain}" if settings.traefik_domain else None


def latest_protocol_export(db: Session, protocol_id: int) -> DocumentExport | None:
    return db.scalar(
        select(DocumentExport)
        .where(DocumentExport.protocol_id == protocol_id, DocumentExport.document_type == "protocol", DocumentExport.content_hash.is_not(None))
        .order_by(DocumentExport.created_at.desc(), DocumentExport.id.desc())
    )


def next_version(db: Session, protocol: Protocol, new_hash: str) -> tuple[int, int, int]:
    previous = latest_protocol_export(db, protocol.id)
    is_final = protocol.status == "abgeschlossen"
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


def verify_render_info(document_id: uuid.UUID | None, *, preview: bool = False) -> RenderInfo:
    base = settings.verify_base_url
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

    explicit = _resolve_explicit_template(db, tenant_id, request)
    document_type = request.document_type or (explicit.document_type if explicit is not None else None) or ("protocol" if protocol else "custom")
    doc_type = get_type(document_type)
    sample = request.data_mode == "sample"
    if doc_type.needs_protocol and protocol is None and not sample:
        raise ValueError("protocol_required")

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
            db, tenant_id, document_type, explicit=explicit, protocol_template_id=protocol.template_id if protocol is not None else None
        )
        template, revision, template_source = resolved.template, resolved.revision, resolved.source
    if request.content is not None:
        content = TemplateContent.model_validate(request.content)
        template_source = "unsaved"
    else:
        content = template_service.revision_content(revision)

    language = normalize_language(content.settings.language or request.language or (tenant.document_language if tenant else None))
    strings = strings_for(language)
    ctx = BuildContext(db=db, tenant_id=tenant_id, language=language, user=user, today=today or date.today(), protocol=protocol, public_base_url=_public_base_url())
    if protocol is not None:
        ctx.ensure_can_read_protocol(protocol.id)

    # Brand: ungespeicherte Tokens (Brand Studio) > explizit > Zuweisung > Vorlage > Standard
    explicit_brand = brand_service.get_brand(db, tenant_id, request.brand_id) if request.brand_id else None
    if request.brand_id and explicit_brand is None:
        raise DocumentNotFoundError("DocumentBrand")
    if resolved is None and template is not None and revision is not None:
        resolved = template_service.ResolvedTemplate(template=template, revision=revision, source=template_source or "explicit", brand_id=None)
    brand_revision = template_service.resolve_brand_revision(db, tenant_id, resolved, explicit_brand=explicit_brand)
    override_tokens = BrandTokens.model_validate(request.brand_tokens) if request.brand_tokens is not None else None
    base_tokens = override_tokens if override_tokens is not None else brand_service.tokens_of(brand_revision)
    effective_tokens = apply_overrides(base_tokens, content.settings.brand_overrides)
    brand = brand_service.resolve_brand(db, tenant_id, brand_revision, tokens=effective_tokens)

    # Meta (fachliche Angaben, Grundlage des Inhalts-Hashes)
    options = request.options
    if protocol is not None and document_type in PROTOCOL_CONTEXT_TYPES:
        meta = _protocol_meta(protocol, document_type, strings, tenant_name, language)
        if options.title:
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

    is_draft = protocol is not None and document_type == "protocol" and protocol.status != "abgeschlossen"
    if options.watermark != "auto":
        is_draft = options.watermark == "on"

    render = render_info or verify_render_info(None, preview=True)
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
    )


@dataclass
class PreviewResult:
    pages: list[bytes]
    diagnostics: list[Diagnostic]
    page_count: int
    template_id: uuid.UUID | None
    template_source: str | None
    design_hash: str


async def preview(db: Session, user: CurrentUser | None, tenant_id: int, request: DocumentRequest, *, max_pages: int | None = None) -> PreviewResult:
    """Seiten als PNG: ohne Register-Eintrag, ohne Speicherung, ohne Versionserhöhung."""
    # Die Vorschau darf nichts verändern (z. B. nachgeführte Mitgliedschaftsblöcke): alles in
    # einem Savepoint, der am Ende zurückgerollt wird.
    savepoint = db.begin_nested()
    try:
        prepared = prepare(db, user, tenant_id, request, preview=True)
        compiled = prepared.compiled
        output = await get_renderer().render_preview(compiled.data, RenderAssets(files=compiled.files, fonts=compiled.fonts), max_pages=max_pages)
        return PreviewResult(
            pages=output.pages,
            diagnostics=prepared.diagnostics,
            page_count=output.page_count or len(output.pages),
            template_id=prepared.template.public_id if prepared.template is not None else None,
            template_source=prepared.template_source,
            design_hash=prepared.design_hash,
        )
    finally:
        if savepoint.is_active:
            savepoint.rollback()


def _filename(title: str, version: str | None) -> str:
    base = re.sub(r"[^A-Za-z0-9._ -]+", "-", (title or "").strip()).strip(" .-_") or "dokument"
    return f"{base}-{version}.pdf" if version else f"{base}.pdf"


def _store_pdf(db: Session, tenant_id: int, pdf: bytes, filename: str, user_id: int | None) -> tuple[StoredFile, Path]:
    target_dir = Path(settings.export_root) / GENERATED_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{uuid.uuid4().hex}-{filename}"
    target.write_bytes(pdf)
    stored = StoredFile(
        tenant_id=tenant_id,
        original_name=filename,
        mime_type="application/pdf",
        storage_path=str(target.relative_to(settings.storage_root)),
        file_size_bytes=len(pdf),
        checksum_sha256=hashlib.sha256(pdf).hexdigest(),
        created_by=user_id,
    )
    db.add(stored)
    try:
        db.flush()
    except Exception:
        # Datei und Datensatz teilen keine Transaktion; ohne Zeile bliebe die Datei verwaist.
        target.unlink(missing_ok=True)
        raise
    return stored, target


async def render(db: Session, user: CurrentUser | None, tenant_id: int, request: DocumentRequest) -> RenderResult:
    export_public_id = _uuid7()
    prepared = prepare(db, user, tenant_id, request, render_info=verify_render_info(export_public_id))
    compiled = prepared.compiled
    meta = prepared.meta

    output = await get_renderer().render_pdf(compiled.data, RenderAssets(files=compiled.files, fonts=compiled.fonts))
    tenant = db.get(Tenant, tenant_id)
    render_info = verify_render_info(export_public_id)
    pdf = add_document_xmp(
        output.pdf or b"",
        DocumentXmp(
            document_id=str(export_public_id),
            tenant_id=str(tenant.public_id) if tenant else "",
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
    stored, target = _store_pdf(db, tenant_id, pdf, _filename(meta.title, meta.version), user.user_id if user else None)
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
            options_json={"options": request.options.model_dump(mode="json"), "params": request.params, "template_source": prepared.template_source},
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
                created_by=user.user_id if user else None,
            )
        )
        db.flush()
        db.commit()
    except Exception:
        db.rollback()
        target.unlink(missing_ok=True)
        raise
    db.refresh(export)
    return RenderResult(export=export, stored_file=stored)


def _uuid7() -> uuid.UUID:
    """UUIDv7 wie die DB-Vorgabe (uuidv7()), damit die Dokument-ID vor dem Rendern feststeht."""
    import os
    import time

    timestamp_ms = int(time.time() * 1000) & ((1 << 48) - 1)
    rand_a = int.from_bytes(os.urandom(2), "big") & 0xFFF
    rand_b = int.from_bytes(os.urandom(8), "big") & ((1 << 62) - 1)
    return uuid.UUID(int=(timestamp_ms << 80) | (0x7 << 76) | (rand_a << 64) | (0b10 << 62) | rand_b)


def cleanup_old_generated_exports(*, retention_days: int | None = None) -> dict:
    """Retention-Job (main.py export_cleanup_loop): löscht alte Dateien unter
    EXPORT_ROOT/generated. Der StoredFile-Datensatz bleibt; ein alter Link liefert dann 404.
    Das Dokumentenregister bleibt unangetastet: ausgelieferte PDFs sind dauerhaft prüfbar."""
    retention = retention_days if retention_days is not None else settings.export_retention_days
    target_dir = Path(settings.export_root) / GENERATED_DIR
    if not target_dir.is_dir():
        return {"deleted": 0}
    cutoff = datetime.now(UTC).timestamp() - retention * 86400
    deleted = 0
    for path in target_dir.iterdir():
        if path.is_file() and path.stat().st_mtime < cutoff:
            path.unlink()
            deleted += 1
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
