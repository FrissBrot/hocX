"""Dokumente: Export (PDF), Vorschau, Zusatzformate, Exporthistorie (Export Center),
Auswahlquellen und Dokumenteinstellungen des Mandanten.

Gestaltung (Vorlagen, Brand-Profile, Assets) liegt in document_studio.py. Fehler: kuratierte
Meldungen in der Sprache des Benutzers (documentPdf/apiError.*, error.*). Renderfehler gehen mit
``from exc`` an den globalen Handler und damit ins Admin-Log (system_error_log), samt
Typst-Diagnose und Knotenname.
"""
from __future__ import annotations

import base64
import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.core.locale_config_generated import SUPPORTED_LOCALES
from app.core.security import CurrentUser, get_current_user, require_admin, require_reader, require_writer
from app.documents import exports as extra_formats
from app.documents import permissions
from app.documents import service as document_service
from app.documents.compiler import CompileError
from app.documents.context import DocumentNotFoundError, DocumentPermissionError
from app.documents.doc_types import DOCUMENT_TYPES
from app.documents.renderer import DocumentRenderError
from app.documents.service import DocumentRequest
from app.documents.strings import normalize_language, text
from app.documents.template_service import TemplateStateError
from app.models import DocumentExport, DocumentTemplate, DocumentTemplateRevision, Protocol, StoredFile, Tenant
from app.services import public_id_service
from app.services.access_service import AccessService
from app.services.audit_service import AuditService

router = APIRouter()
audit = AuditService()
access_service = AccessService()


def _lang(user: CurrentUser) -> str:
    return normalize_language(user.preferred_language)


_VALUE_ERRORS = {
    "protocol_required": "apiError.protocolRequired",
    "unknown_document_type": "apiError.unknownType",
    "noTable": "apiError.noTable",
    "previewOnly": "apiError.previewOnly",
}


def http_error(user: CurrentUser, exc: Exception) -> HTTPException:
    """Erwartete Fehler → kuratierte HTTP-Fehler (ohne Admin-Log)."""
    language = _lang(user)
    if isinstance(exc, DocumentPermissionError):
        return HTTPException(status_code=403, detail=text(language, "apiError.permission"))
    if isinstance(exc, DocumentNotFoundError):
        return HTTPException(status_code=404, detail=text(language, "apiError.notFound"))
    if isinstance(exc, CompileError):
        return HTTPException(status_code=422, detail={"message": text(language, "apiError.templateInvalid"), "code": exc.code, "node_id": exc.node_id, "detail": exc.detail})
    if isinstance(exc, TemplateStateError):
        return HTTPException(status_code=422, detail=text(language, str(exc)))
    if isinstance(exc, ValueError):
        key = _VALUE_ERRORS.get(str(exc), "apiError.invalidBlock")
        return HTTPException(status_code=422, detail=text(language, key, detail=str(exc)))
    raise exc


def render_error(user: CurrentUser, exc: DocumentRenderError) -> HTTPException:
    language = _lang(user)
    if exc.key == "error.block":
        return HTTPException(status_code=422, detail={"message": text(language, "error.block", block=exc.block_label or ""), "node_id": exc.node_id})
    if exc.key == "error.timeout":
        return HTTPException(status_code=503, detail=text(language, "error.timeout"))
    return HTTPException(status_code=500, detail=text(language, "error.render"))


def check_preview_rights(user: CurrentUser, body: DocumentRequest) -> None:
    """Studio-Vorschau: ungespeicherte Vorlage/Revision nur mit Bearbeitungsrecht,
    ungespeichertes Brand-Profil nur mit Brand-Recht."""
    if body.content is not None or body.revision_id is not None:
        permissions.require_edit(user)
    if body.brand_tokens is not None:
        permissions.require_brand(user)


# ── Export und Vorschau ─────────────────────────────────────────────────────


class DocumentExportRead(BaseModel):
    id: uuid.UUID
    document_type: str
    title: str | None
    version_label: str | None
    # Kurz-ID und Prüf-Link, wie sie im PDF stehen
    short_id: str
    verify_url: str
    language: str | None
    template_id: uuid.UUID | None = None
    template_name: str | None = None
    template_system_key: str | None = None
    template_revision: int | None = None
    content_hash: str | None = None
    design_hash: str | None = None
    generated_file_id: uuid.UUID | None
    content_url: str | None
    created_at: datetime


def export_read(db: Session, export: DocumentExport) -> DocumentExportRead:
    stored = db.get(StoredFile, export.stored_file_id) if export.stored_file_id else None
    template = db.get(DocumentTemplate, export.template_id) if export.template_id else None
    revision = db.get(DocumentTemplateRevision, export.template_revision_id) if export.template_revision_id else None
    return DocumentExportRead(
        id=export.public_id,
        document_type=export.document_type,
        title=export.title,
        version_label=export.version_label,
        short_id=document_service.short_document_id(export.public_id),
        verify_url=f"{settings.verify_base_url}?id={export.public_id}",
        language=export.language,
        template_id=template.public_id if template else None,
        template_name=template.name if template else None,
        template_system_key=template.system_key if template else None,
        template_revision=revision.revision_no if revision else None,
        content_hash=export.content_hash,
        design_hash=export.design_hash,
        generated_file_id=stored.public_id if stored else None,
        content_url=f"/api/stored-files/{stored.public_id}/content" if stored else None,
        created_at=export.created_at,
    )


@router.post("/documents/render", response_model=DocumentExportRead)
async def render_document(body: DocumentRequest, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    permissions.require_export(user)
    try:
        result = await document_service.render(db, user, user.current_tenant_id, body)
    except DocumentRenderError as exc:
        db.rollback()
        raise render_error(user, exc) from exc
    except (DocumentPermissionError, DocumentNotFoundError, ValueError) as exc:
        db.rollback()
        raise http_error(user, exc) from exc
    audit.log(
        db,
        action="document.render",
        actor=user,
        entity_type="document_export",
        entity_id=result.export.id,
        details={
            "document_type": result.export.document_type,
            "version": result.export.version_label,
            "protocol_id": str(body.protocol_id) if body.protocol_id else None,
            "template_id": str(body.template_id) if body.template_id else None,
        },
    )
    return export_read(db, result.export)


class DiagnosticRead(BaseModel):
    node_id: str | None
    severity: str
    code: str
    detail: str = ""


class PreviewRead(BaseModel):
    pages: list[str]
    page_count: int
    diagnostics: list[DiagnosticRead]
    template_id: uuid.UUID | None = None
    template_source: str | None = None
    design_hash: str | None = None


@router.post("/documents/preview", response_model=PreviewRead)
async def preview_document(
    body: DocumentRequest,
    max_pages: int = Query(default=4, ge=1, le=20),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    permissions.require_view(user)
    check_preview_rights(user, body)
    try:
        result = await document_service.preview(db, user, user.current_tenant_id, body, max_pages=max_pages)
    except DocumentRenderError as exc:
        raise render_error(user, exc) from exc
    except (DocumentPermissionError, DocumentNotFoundError, ValueError) as exc:
        raise http_error(user, exc) from exc
    return PreviewRead(
        pages=["data:image/png;base64," + base64.b64encode(page).decode("ascii") for page in result.pages],
        page_count=result.page_count,
        diagnostics=[DiagnosticRead(**item.as_dict()) for item in result.diagnostics],
        template_id=result.template_id,
        template_source=result.template_source,
        design_hash=result.design_hash,
    )


class FormatExportRequest(DocumentRequest):
    format: Literal["csv", "xlsx", "ics", "markdown"] = "csv"


_FORMAT_TYPES = {
    "csv": ("text/csv; charset=utf-8", "csv"),
    "xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"),
    "ics": ("text/calendar; charset=utf-8", "ics"),
    "markdown": ("text/markdown; charset=utf-8", "md"),
}


@router.post("/documents/export")
def export_document_format(body: FormatExportRequest, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    """CSV/XLSX aus den Tabellen, ICS aus den Termin-Komponenten, Markdown aus den
    Aufgaben-Komponenten der aufgelösten Vorlage - immer aus den fachlichen Daten."""
    permissions.require_export(user)
    request = DocumentRequest.model_validate(body.model_dump(exclude={"format"}))
    savepoint = db.begin_nested()
    try:
        prepared = document_service.prepare(db, user, user.current_tenant_id, request)
        if body.format in ("csv", "xlsx"):
            tables = extra_formats.all_tables(prepared.compiled.blocks, prepared.compiled.data, prepared.compiled.data["strings"])
            content = extra_formats.to_csv(tables) if body.format == "csv" else extra_formats.to_xlsx(tables)
        elif body.format == "ics":
            content = extra_formats.ics_content(prepared)
        else:
            content = extra_formats.markdown_content(prepared)
    except (DocumentPermissionError, DocumentNotFoundError, ValueError) as exc:
        raise http_error(user, exc) from exc
    finally:
        if savepoint.is_active:
            savepoint.rollback()
    audit.log(db, action=f"document.export_{body.format}", actor=user, details={"document_type": prepared.document_type})
    media_type, extension = _FORMAT_TYPES[body.format]
    filename = f"{document_service._filename(prepared.meta.title, None)[:-4]}.{extension}"
    return Response(content=content, media_type=media_type, headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/documents/exports", response_model=list[DocumentExportRead])
def list_document_exports(
    protocol_id: uuid.UUID | None = None,
    document_type: str | None = Query(default=None, max_length=40),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    permissions.require_view(user)
    statement = select(DocumentExport).where(DocumentExport.tenant_id == user.current_tenant_id)
    if protocol_id is not None:
        internal = public_id_service.resolve_internal_id(db, Protocol, protocol_id, tenant_id=user.current_tenant_id)
        if internal is None:
            raise HTTPException(status_code=404, detail=text(_lang(user), "apiError.notFound"))
        access_service.ensure_can_read_protocol(db, user, internal)
        statement = statement.where(DocumentExport.protocol_id == internal)
    elif access_service.is_restricted_reader(db, user):
        statement = statement.where(DocumentExport.created_by == user.user_id)
    if document_type:
        statement = statement.where(DocumentExport.document_type == document_type)
    exports = db.scalars(statement.order_by(DocumentExport.created_at.desc(), DocumentExport.id.desc()).offset(offset).limit(limit))
    return [export_read(db, export) for export in exports]


# ── Dokumenteinstellungen des Mandanten ─────────────────────────────────────


class DocumentSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    language: str | None = None


@router.get("/document-settings", response_model=DocumentSettings)
def get_document_settings(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    permissions.require_view(user)
    tenant = db.get(Tenant, user.current_tenant_id)
    return DocumentSettings(language=normalize_language(tenant.document_language if tenant else None))


@router.patch("/document-settings", response_model=DocumentSettings)
def update_document_settings(body: DocumentSettings, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    require_admin(user)
    tenant = db.get(Tenant, user.current_tenant_id)
    if body.language is not None and body.language not in SUPPORTED_LOCALES:
        raise HTTPException(status_code=422, detail=text(_lang(user), "apiError.invalidBlock", detail="language"))
    tenant.document_language = body.language
    db.commit()
    audit.log(db, action="document_settings.update", actor=user, details={"language": body.language})
    return DocumentSettings(language=normalize_language(tenant.document_language))


# ── Auswahlquellen für die Parameterformulare ───────────────────────────────


class SourceOption(BaseModel):
    id: uuid.UUID
    label: str
    detail: str | None = None


SOURCES = {"participants", "protocols", "protocol_elements", "protocol_blocks", "images", "cycles", "templates", "lists", "events", "finance_accounts"}


@router.get("/documents/sources/{source}", response_model=list[SourceOption])
def list_source_options(
    source: str,
    protocol_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Optionen für Referenzfelder (``x-source`` im Katalog-Schema), mandantengebunden und mit
    denselben Rechten wie die Blöcke, die sie füllen."""
    from app.core.security import require_finance_read
    from app.documents.context import format_date
    from app.models import CycleConfig, Event, FinanceAccount, ListDefinition, Participant, ProtocolElement, ProtocolElementBlock, Template

    require_reader(user)
    tenant_id = user.current_tenant_id
    if source not in SOURCES:
        raise HTTPException(status_code=404, detail=text(_lang(user), "apiError.notFound"))
    if source == "participants":
        rows = db.scalars(select(Participant).where(Participant.tenant_id == tenant_id, Participant.is_active.is_(True)).order_by(Participant.display_name))
        return [SourceOption(id=row.public_id, label=row.display_name) for row in rows]
    if source == "protocols":
        rows = db.scalars(select(Protocol).where(Protocol.tenant_id == tenant_id).order_by(Protocol.protocol_date.desc()).limit(300))
        return [
            SourceOption(id=row.public_id, label=row.title or row.protocol_number, detail=f"{row.protocol_number} · {format_date(row.protocol_date)}")
            for row in rows
            if access_service.can_read_protocol(db, user, row.id)
        ]
    if source in ("protocol_elements", "protocol_blocks"):
        internal = public_id_service.resolve_internal_id(db, Protocol, protocol_id, tenant_id=tenant_id) if protocol_id else None
        if internal is None:
            return []
        access_service.ensure_can_read_protocol(db, user, internal)
        elements = list(db.scalars(select(ProtocolElement).where(ProtocolElement.protocol_id == internal).order_by(ProtocolElement.sort_index)))
        if source == "protocol_elements":
            return [SourceOption(id=element.public_id, label=element.section_name_snapshot) for element in elements]
        options: list[SourceOption] = []
        for element in elements:
            for block in db.scalars(select(ProtocolElementBlock).where(ProtocolElementBlock.protocol_element_id == element.id).order_by(ProtocolElementBlock.sort_index)):
                options.append(SourceOption(id=block.public_id, label=block.block_title_snapshot or block.title_snapshot, detail=element.section_name_snapshot))
        return options
    if source == "images":
        if access_service.is_restricted_reader(db, user):
            return []
        rows = db.scalars(
            select(StoredFile)
            .where(StoredFile.tenant_id == tenant_id, StoredFile.mime_type.like("image/%"), StoredFile.scan_status == "clean")
            .order_by(StoredFile.created_at.desc())
            .limit(300)
        )
        return [SourceOption(id=row.public_id, label=row.original_name) for row in rows]
    if source == "cycles":
        rows = db.scalars(select(CycleConfig).where(CycleConfig.tenant_id == tenant_id).order_by(CycleConfig.name))
        return [SourceOption(id=row.public_id, label=row.name) for row in rows]
    if source == "templates":
        rows = db.scalars(select(Template).where(Template.tenant_id == tenant_id, Template.status == "active").order_by(Template.name))
        return [SourceOption(id=row.public_id, label=row.name) for row in rows if access_service.can_read_template(db, user, row.id)]
    if source == "lists":
        rows = db.scalars(select(ListDefinition).where(ListDefinition.tenant_id == tenant_id, ListDefinition.is_active.is_(True)).order_by(ListDefinition.name))
        return [SourceOption(id=row.public_id, label=row.name) for row in rows]
    if source == "events":
        rows = db.scalars(select(Event).where(Event.tenant_id == tenant_id, Event.is_session_marker.is_(False)).order_by(Event.event_date.desc()).limit(500))
        return [SourceOption(id=row.public_id, label=row.title, detail=format_date(row.event_date)) for row in rows]
    require_finance_read(user)
    rows = db.scalars(select(FinanceAccount).where(FinanceAccount.tenant_id == tenant_id).order_by(FinanceAccount.name))
    return [SourceOption(id=row.public_id, label=row.name) for row in rows]
