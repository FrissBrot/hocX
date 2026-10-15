"""Orchestrierung: Anfrage → Dokument → Version → Typst → XMP → Register → StoredFile.

Jedes ausgelieferte PDF wird im Dokumentenregister (document_registry) mit dem SHA-256 der
exakt ausgelieferten Bytes eingetragen. Die Dokument-ID steht vorher fest und im PDF (Fusszeile,
QR-Code, XMP); die öffentliche Prüfseite der Abgabebox vergleicht nur den Hash.

Versionierung (nur Dokumenttyp «protocol»): Schema bleibt v0.x für Entwürfe und v1.x für
abgeschlossene Protokolle mit getrennten Zählern. Weicht der Inhalts-Hash (hashing.py) vom
letzten Protokoll-Export ab, steigt der passende Zähler **vor** dem Rendern, damit das PDF die
neue Nummer trägt. Gleicher Inhalt ergibt dieselbe Version; ein anderer Hausstil oder eine andere
Sprache allein ändern sie nicht.

Versioniert und als «protocol» registriert wird nur der kanonische Protokoll-Export (Standardblöcke
des Typs, ohne eigenen Titel/Untertitel). Eine frei zusammengestellte Fassung eines Protokolls
(eigene Blöcke, eigener Titel) ist ein «protocol_excerpt»: ohne Versionsnummer, ohne Verweis auf
das Protokoll im Register und ohne Einfluss auf die Versionszähler – sonst könnte jede lesende
Person ein «echtes» Protokoll beliebigen Inhalts erzeugen und die verteilte Fassung öffentlich als
überholt erscheinen lassen.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.config import settings
from app.core.security import CurrentUser
from app.documents import style_service
from app.documents.builder import build_document
from app.documents.catalog import BlockSpec, validate_spec
from app.documents.context import BuildContext, DocumentNotFoundError
from app.documents.doc_types import document_types
from app.documents.hashing import content_hash
from app.documents.model import Document, RenderInfo
from app.documents.renderer import RenderAssets, get_renderer
from app.documents.strings import normalize_language
from app.documents.style_tokens import DocumentStyleTokens, ExportOptions
from app.documents.xmp import DocumentXmp, add_document_xmp
from app.models import DocumentExport, DocumentRecipe, DocumentRegistry, DocumentStyle, Protocol, StoredFile, Template, Tenant

logger = logging.getLogger(__name__)

GENERATED_DIR = "generated"
# Registertyp für frei zusammengestellte Fassungen eines Protokolls (siehe Modul-Docstring)
PROTOCOL_EXCERPT_TYPE = "protocol_excerpt"


class StyleOverride(BaseModel):
    model_config = ConfigDict(extra="forbid")

    style_key: Literal["modern", "classic", "compact"] = "modern"
    tokens: DocumentStyleTokens = Field(default_factory=DocumentStyleTokens)


class DocumentRequest(BaseModel):
    """Body von ``POST /api/documents/render`` und ``/preview``."""

    model_config = ConfigDict(extra="forbid")

    document_type: str | None = Field(None, max_length=40)
    recipe_id: uuid.UUID | None = None
    protocol_id: uuid.UUID | None = None
    blocks: list[BlockSpec] | None = Field(None, max_length=200)
    # Parameter für die Standardblöcke eines Dokumenttyps (z. B. aktive Filter der Todo-Seite).
    params: dict[str, Any] = Field(default_factory=dict)
    style_id: uuid.UUID | None = None
    # Ungespeicherte Hausstil-Tokens (Live-Vorschau in den Hausstil-Einstellungen). Assets werden
    # wie bei gespeicherten Stilen mandantengebunden aufgelöst.
    style_override: StyleOverride | None = None
    options: ExportOptions = Field(default_factory=ExportOptions)
    language: str | None = Field(None, max_length=10)


@dataclass
class PreparedDocument:
    document: Document
    assets: RenderAssets
    document_type: str
    protocol: Protocol | None
    recipe: DocumentRecipe | None
    style: DocumentStyle | None
    content_hash: str
    version: tuple[int, int, int] | None  # (major, minor, final_minor) nach diesem Export
    language: str
    # Typ für Export, Register und XMP (weicht nur beim Protokollauszug vom Dokumenttyp ab)
    register_type: str = ""

    def __post_init__(self) -> None:
        if not self.register_type:
            self.register_type = self.document_type


@dataclass
class RenderResult:
    export: DocumentExport
    stored_file: StoredFile


def version_label(major: int, minor: int) -> str | None:
    return f"v{major}.{minor}" if (major > 0 or minor > 0) else None


def _public_base_url() -> str | None:
    return f"https://{settings.traefik_domain}" if settings.traefik_domain else None


def _merge_params(specs: list[BlockSpec], params: dict[str, Any]) -> list[BlockSpec]:
    """Seitenkontext (z. B. Filter der Todo-Seite) auf passende Standardblöcke anwenden."""
    if not params:
        return specs
    merged: list[BlockSpec] = []
    for spec in specs:
        candidate = spec.model_copy(update={"params": {**spec.params, **params}})
        try:
            validate_spec(candidate)
        except ValueError:
            allowed = {key: value for key, value in params.items() if key in _param_fields(spec.type)}
            candidate = spec.model_copy(update={"params": {**spec.params, **allowed}})
        merged.append(candidate)
    return merged


def _param_fields(block_type: str) -> set[str]:
    from app.documents.catalog import CATALOG

    entry = CATALOG.get(block_type)
    return set(entry.params.model_fields) if entry else set()


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


def _spec_key(spec: BlockSpec, protocol: Protocol | None) -> tuple:
    """Vergleichsschlüssel eines Blocks: Parameter mit Vorgabewerten, Kontext-Protokoll = leer."""
    try:
        params = validate_spec(spec).model_dump(mode="json")
    except ValueError:
        params = spec.params
    if protocol is not None and params.get("protocol_id") == str(protocol.public_id):
        params = {**params, "protocol_id": None}
    return (spec.type, spec.title, spec.hide_if_empty, spec.level, json.dumps(params, sort_keys=True, default=str))


def is_canonical_protocol_export(specs: list[BlockSpec], options: ExportOptions, protocol: Protocol | None, default_specs: list[BlockSpec]) -> bool:
    """Nur der unveränderte Protokoll-Export (Standardblöcke, kein eigener Titel) wird versioniert."""
    if options.title or options.subtitle:
        return False
    return [_spec_key(spec, protocol) for spec in specs] == [_spec_key(spec, protocol) for spec in default_specs]


def _resolve_style(db: Session, ctx: BuildContext, request: DocumentRequest, recipe: DocumentRecipe | None, protocol: Protocol | None) -> DocumentStyle | None:
    if request.style_id is not None:
        style = style_service.get_style(db, ctx.tenant_id, request.style_id)
        if style is None:
            raise DocumentNotFoundError("DocumentStyle")
        return style
    for style_id in (
        recipe.style_id if recipe is not None else None,
        protocol.document_style_id if protocol is not None else None,
    ):
        if style_id:
            style = db.get(DocumentStyle, style_id)
            if style is not None and style.tenant_id == ctx.tenant_id:
                return style
    if protocol is not None:
        template = db.get(Template, protocol.template_id)
        if template is not None and template.document_style_id:
            style = db.get(DocumentStyle, template.document_style_id)
            if style is not None and style.tenant_id == ctx.tenant_id:
                return style
    return style_service.default_style(db, ctx.tenant_id)


def prepare(db: Session, user: CurrentUser | None, tenant_id: int, request: DocumentRequest, *, today: date | None = None) -> PreparedDocument:
    tenant = db.get(Tenant, tenant_id)
    protocol = None
    if request.protocol_id is not None:
        protocol = db.scalar(select(Protocol).where(Protocol.public_id == request.protocol_id, Protocol.tenant_id == tenant_id))
        if protocol is None:
            raise DocumentNotFoundError("Protocol")
    recipe = None
    if request.recipe_id is not None:
        recipe = db.scalar(select(DocumentRecipe).where(DocumentRecipe.public_id == request.recipe_id, DocumentRecipe.tenant_id == tenant_id))
        if recipe is None:
            raise DocumentNotFoundError("DocumentRecipe")

    language = normalize_language(request.language or (recipe.language if recipe else None) or (tenant.document_language if tenant else None))
    ctx = BuildContext(db=db, tenant_id=tenant_id, language=language, user=user, today=today or date.today(), protocol=protocol, public_base_url=_public_base_url())
    if protocol is not None:
        ctx.ensure_can_read_protocol(protocol.id)

    types = document_types(ctx.today)
    document_type = request.document_type or (recipe.document_type if recipe else None) or ("protocol" if protocol else "custom")
    if document_type not in types:
        raise ValueError("unknown_document_type")
    if types[document_type].needs_protocol and protocol is None:
        raise ValueError("protocol_required")

    if request.blocks is not None:
        specs = list(request.blocks)
    elif recipe is not None:
        specs = [BlockSpec.model_validate(item) for item in (recipe.blocks_json or [])]
    else:
        specs = _merge_params(list(types[document_type].blocks), request.params)

    options = request.options
    if recipe is not None and not request.options.model_fields_set:
        options = ExportOptions.model_validate(recipe.options_json or {})

    style = _resolve_style(db, ctx, request, recipe, protocol)
    if request.style_override is not None:
        # Transienter Stil (nie gespeichert): gleiche Auflösung wie ein gespeicherter.
        style = DocumentStyle(
            tenant_id=tenant_id,
            name="preview",
            style_key=request.style_override.style_key,
            tokens_json=request.style_override.tokens.model_dump(mode="json"),
            version=(style.version if style is not None else 1),
        )
    resolved_style, tokens, fonts, style_files = style_service.resolve(db, tenant_id, style)
    document = build_document(
        ctx,
        document_type=document_type,
        specs=specs,
        style=resolved_style,
        tokens=tokens,
        options=options,
        tenant_name=tenant.name if tenant else "",
    )
    # Nur Inhaltsbilder zählen zum Inhalt; Logo/Fussbild gehören zum Hausstil.
    digest = content_hash(document, ctx.assets.files)
    version = None
    register_type = document_type
    if protocol is not None and document_type == "protocol":
        if is_canonical_protocol_export(specs, options, protocol, list(types[document_type].blocks)):
            version = next_version(db, protocol, digest)
            major, minor, final_minor = version
            document.meta.version = version_label(major, final_minor if major else minor)
        else:
            register_type = PROTOCOL_EXCERPT_TYPE
    return PreparedDocument(
        document=document,
        assets=RenderAssets(files={**ctx.assets.files, **style_files}, fonts=fonts),
        document_type=document_type,
        protocol=protocol,
        recipe=recipe,
        style=style,
        content_hash=digest,
        version=version,
        language=language,
        register_type=register_type,
    )


async def preview(db: Session, user: CurrentUser | None, tenant_id: int, request: DocumentRequest, *, max_pages: int | None = None) -> list[bytes]:
    """Erste Seiten als PNG: ohne Register-Eintrag, ohne Speicherung, ohne Versionserhöhung."""
    # Die Vorschau darf nichts verändern (z. B. nachgeführte Mitgliedschaftsblöcke): alles in
    # einem Savepoint, der am Ende zurückgerollt wird.
    savepoint = db.begin_nested()
    try:
        prepared = await _prepare_off_loop(db, user, tenant_id, request)
        prepared.document.render = verify_render_info(None, preview=True)
        output = await get_renderer().render_preview(prepared.document, prepared.assets, max_pages=max_pages)
        return output.pages
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


def short_document_id(document_id: str | uuid.UUID) -> str:
    """Kurz-ID für die Fusszeile: letzte 8 Hex-Zeichen (zufälliger Teil der UUIDv7), gruppiert."""
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


async def _prepare_off_loop(db: Session, user: CurrentUser | None, tenant_id: int, request: DocumentRequest) -> PreparedDocument:
    """``prepare`` (Provider-Abfragen, Bildnormalisierung mit Pillow) im Threadpool, damit die
    Event-Loop des Workers währenddessen andere Requests und WebSockets bedient. Die Session
    wird dabei nie gleichzeitig benutzt: die Route wartet auf das Ergebnis."""
    return await run_in_threadpool(prepare, db, user, tenant_id, request)


async def render(db: Session, user: CurrentUser | None, tenant_id: int, request: DocumentRequest) -> RenderResult:
    prepared = await _prepare_off_loop(db, user, tenant_id, request)
    document = prepared.document
    export_public_id = _uuid7()
    document.render = verify_render_info(export_public_id)

    output = await get_renderer().render_pdf(document, prepared.assets)
    tenant = db.get(Tenant, tenant_id)
    pdf = await run_in_threadpool(
        add_document_xmp,
        output.pdf or b"",
        DocumentXmp(
            document_id=str(export_public_id),
            tenant_id=str(tenant.public_id) if tenant else "",
            document_type=prepared.register_type,
            version=document.meta.version or "",
            content_hash=prepared.content_hash,
            verify_url=document.render.verify_link or "",
        ),
    )
    # Hash über genau die Bytes, die ausgeliefert werden.
    sha256 = hashlib.sha256(pdf).hexdigest()

    major = minor = None
    if prepared.version is not None and prepared.protocol is not None:
        major, new_minor, new_final = prepared.version
        protocol = prepared.protocol
        protocol.version_major = major
        protocol.version_minor = new_minor
        protocol.version_final_minor = new_final
        minor = new_final if major else new_minor
        db.add(protocol)
    protocol = prepared.protocol
    # Datei, StoredFile, Export und Register-Eintrag gemeinsam: scheitert ein Teil, gibt es
    # nichts (die Datei wird beim Rollback entfernt).
    stored, target = _store_pdf(db, tenant_id, pdf, _filename(document.meta.title, document.meta.version), user.user_id if user else None)
    try:
        export = DocumentExport(
            public_id=export_public_id,
            tenant_id=tenant_id,
            protocol_id=protocol.id if protocol is not None else None,
            document_type=prepared.register_type,
            recipe_id=prepared.recipe.id if prepared.recipe is not None else None,
            title=document.meta.title,
            version_label=document.meta.version,
            version_major=major,
            version_minor=minor,
            content_hash=prepared.content_hash,
            style_id=prepared.style.id if prepared.style is not None and prepared.style.id else None,
            style_key=document.style.key,
            style_version=document.style.version,
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
                document_type=prepared.register_type,
                title=document.meta.title,
                status_code=protocol.status if protocol is not None and prepared.register_type == "protocol" else None,
                version_major=major,
                version_minor=minor,
                version_label=document.meta.version,
                content_hash=prepared.content_hash,
                # Ein Protokollauszug verweist nicht auf seine Quelle (keine Basis für «überholt»).
                source_public_id=protocol.public_id if protocol is not None and prepared.register_type != PROTOCOL_EXCERPT_TYPE else None,
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
