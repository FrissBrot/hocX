"""Dokument-Engine: Rendern, Vorschau, Zusatzformate, Katalog, Hausstile, Stil-Assets, Rezepte.

Fehler: kuratierte Meldungen in der Sprache des Benutzers (documentPdf/apiError.*, error.*).
Renderfehler gehen mit ``from exc`` an den globalen Handler und damit ins Admin-Log
(system_error_log), samt Typst-Diagnose und Blockname.
"""
from __future__ import annotations

import base64
import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.locale_config_generated import SUPPORTED_LOCALES
from app.core.security import CurrentUser, get_current_user, require_admin, require_reader, require_writer
from app.documents import exports as extra_formats
from app.core.config import settings
from app.documents import service as document_service
from app.documents import style_service
from app.documents.builder import BlockSpecError
from app.documents.catalog import BlockSpec, catalog_payload, validate_spec
from app.documents.context import DocumentNotFoundError, DocumentPermissionError
from app.documents.doc_types import document_types
from app.documents.renderer import DocumentRenderError
from app.documents.service import DocumentRequest
from app.documents.strings import normalize_language, text
from app.documents.style_tokens import STYLE_KEYS, DocumentStyleTokens, ExportOptions, default_tokens
from app.models import DocumentExport, DocumentRecipe, DocumentStyle, DocumentStyleAsset, Protocol, StoredFile, Tenant
from app.services import public_id_service
from app.services.access_service import AccessService
from app.services.audit_service import AuditService

router = APIRouter()
audit = AuditService()
access_service = AccessService()


def _lang(user: CurrentUser) -> str:
    return normalize_language(user.preferred_language)


def _http_error(user: CurrentUser, exc: Exception) -> HTTPException:
    """Erwartete Fehler der Engine → kuratierte HTTP-Fehler (ohne Admin-Log)."""
    language = _lang(user)
    if isinstance(exc, DocumentPermissionError):
        return HTTPException(status_code=403, detail=text(language, "apiError.permission"))
    if isinstance(exc, DocumentNotFoundError):
        return HTTPException(status_code=404, detail=text(language, "apiError.notFound"))
    if isinstance(exc, BlockSpecError):
        return HTTPException(status_code=422, detail=text(language, "apiError.invalidBlock", detail=str(exc)))
    if isinstance(exc, style_service.StyleValidationError):
        return HTTPException(status_code=422, detail=text(language, str(exc)))
    if isinstance(exc, ValueError):
        key = {"protocol_required": "apiError.protocolRequired", "unknown_document_type": "apiError.unknownType", "noTable": "apiError.noTable"}.get(str(exc), "apiError.invalidBlock")
        return HTTPException(status_code=422, detail=text(language, key, detail=str(exc)))
    raise exc


def _render_error(user: CurrentUser, exc: DocumentRenderError) -> HTTPException:
    language = _lang(user)
    if exc.key == "error.block":
        return HTTPException(status_code=422, detail=text(language, "error.block", block=exc.block_label or ""))
    if exc.key == "error.timeout":
        return HTTPException(status_code=503, detail=text(language, "error.timeout"))
    return HTTPException(status_code=500, detail=text(language, "error.render"))


# ── Rendern ─────────────────────────────────────────────────────────────────


class DocumentExportRead(BaseModel):
    id: uuid.UUID
    document_type: str
    title: str | None
    version_label: str | None
    # Kurz-ID und Prüf-Link, wie sie im PDF stehen
    short_id: str
    verify_url: str
    language: str | None
    style_key: str | None
    generated_file_id: uuid.UUID | None
    content_url: str | None
    created_at: datetime


def _export_read(db: Session, export: DocumentExport) -> DocumentExportRead:
    stored = db.get(StoredFile, export.stored_file_id) if export.stored_file_id else None
    return DocumentExportRead(
        id=export.public_id,
        document_type=export.document_type,
        title=export.title,
        version_label=export.version_label,
        short_id=document_service.short_document_id(export.public_id),
        verify_url=f"{settings.verify_base_url}?id={export.public_id}",
        language=export.language,
        style_key=export.style_key,
        generated_file_id=stored.public_id if stored else None,
        content_url=f"/api/stored-files/{stored.public_id}/content" if stored else None,
        created_at=export.created_at,
    )


@router.post("/documents/render", response_model=DocumentExportRead)
async def render_document(body: DocumentRequest, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    require_reader(user)
    try:
        result = await document_service.render(db, user, user.current_tenant_id, body)
    except DocumentRenderError as exc:
        db.rollback()
        raise _render_error(user, exc) from exc
    except (DocumentPermissionError, DocumentNotFoundError, ValueError) as exc:
        db.rollback()
        raise _http_error(user, exc) from exc
    audit.log(
        db,
        action="document.render",
        actor=user,
        entity_type="document_export",
        entity_id=result.export.id,
        details={"document_type": result.export.document_type, "version": result.export.version_label, "protocol_id": str(body.protocol_id) if body.protocol_id else None},
    )
    return _export_read(db, result.export)


class PreviewRead(BaseModel):
    pages: list[str]


@router.post("/documents/preview", response_model=PreviewRead)
async def preview_document(
    body: DocumentRequest,
    max_pages: int = Query(default=3, ge=1, le=8),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_reader(user)
    try:
        pages = await document_service.preview(db, user, user.current_tenant_id, body, max_pages=max_pages)
    except DocumentRenderError as exc:
        raise _render_error(user, exc) from exc
    except (DocumentPermissionError, DocumentNotFoundError, ValueError) as exc:
        raise _http_error(user, exc) from exc
    return PreviewRead(pages=["data:image/png;base64," + base64.b64encode(page).decode("ascii") for page in pages])


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
    """CSV/XLSX aus den Tabellen-Blöcken, ICS aus Termin-Blöcken, Markdown aus Todo-Blöcken."""
    require_reader(user)
    request = DocumentRequest.model_validate(body.model_dump(exclude={"format"}))
    savepoint = db.begin_nested()
    try:
        prepared = document_service.prepare(db, user, user.current_tenant_id, request)
        content = _format_content(db, user, body.format, prepared, request)
    except (DocumentPermissionError, DocumentNotFoundError, ValueError) as exc:
        raise _http_error(user, exc) from exc
    finally:
        if savepoint.is_active:
            savepoint.rollback()
    audit.log(db, action=f"document.export_{body.format}", actor=user, details={"document_type": prepared.document_type})
    media_type, extension = _FORMAT_TYPES[body.format]
    filename = f"{document_service._filename(prepared.document.meta.title, None)[:-4]}.{extension}"
    return Response(content=content, media_type=media_type, headers={"Content-Disposition": f'attachment; filename="{filename}"'})


def _format_content(db: Session, user: CurrentUser, fmt: str, prepared, request: DocumentRequest) -> bytes:
    document = prepared.document
    if fmt == "csv":
        return extra_formats.to_csv(document)
    if fmt == "xlsx":
        return extra_formats.to_xlsx(document)
    specs = request.blocks or [BlockSpec.model_validate(item) for item in (prepared.recipe.blocks_json if prepared.recipe else [])] or document_types()[prepared.document_type].blocks
    specs = document_service._merge_params(list(specs), request.params) if request.blocks is None and prepared.recipe is None else specs
    from app.documents.context import BuildContext
    from app.documents.providers import events, todos

    ctx = BuildContext(db=db, tenant_id=user.current_tenant_id, language=prepared.language, user=user, protocol=prepared.protocol)
    if fmt == "ics":
        selected = []
        for spec in specs:
            if spec.type in ("event_table", "event_calendar_month", "event_agenda"):
                selected.extend(events.select_events(ctx, validate_spec(spec)))
        if not selected and not any(spec.type.startswith("event") for spec in specs):
            raise ValueError("noTable")
        tenant = db.get(Tenant, user.current_tenant_id)
        unique = {event.id: event for event in selected}
        return events.ics(sorted(unique.values(), key=lambda event: (event.event_date, event.id)), tenant_name=tenant.name if tenant else "").encode("utf-8")
    rows: list[Any] = []
    group_by_person = False
    show_status = False
    found = False
    for spec in specs:
        if spec.type == "todo_table":
            found = True
            params = validate_spec(spec)
            rows.extend(todos.filter_rows(ctx, todos.list_tenant_todo_rows(ctx), params))
            group_by_person = group_by_person or params.group_by == "person"
            show_status = show_status or params.status != "open"
    if not found:
        raise ValueError("noTable")
    return todos.markdown(rows, strings=document.strings, title=document.meta.title, group_by_person=group_by_person, show_status=show_status, today=ctx.today).encode("utf-8")


@router.get("/documents/exports", response_model=list[DocumentExportRead])
def list_document_exports(
    protocol_id: uuid.UUID | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_reader(user)
    statement = select(DocumentExport).where(DocumentExport.tenant_id == user.current_tenant_id)
    if protocol_id is not None:
        internal = public_id_service.resolve_internal_id(db, Protocol, protocol_id, tenant_id=user.current_tenant_id)
        if internal is None:
            raise HTTPException(status_code=404, detail=text(_lang(user), "apiError.notFound"))
        access_service.ensure_can_read_protocol(db, user, internal)
        statement = statement.where(DocumentExport.protocol_id == internal)
    elif access_service.is_restricted_reader(db, user):
        statement = statement.where(DocumentExport.created_by == user.user_id)
    exports = db.scalars(statement.order_by(DocumentExport.created_at.desc(), DocumentExport.id.desc()).limit(limit))
    return [_export_read(db, export) for export in exports]


# ── Katalog ─────────────────────────────────────────────────────────────────


@router.get("/documents/catalog")
def get_catalog(user: CurrentUser = Depends(get_current_user)) -> dict:
    require_reader(user)
    types = document_types()
    return {
        "blocks": catalog_payload(),
        "document_types": [
            {"key": item.key, "needs_protocol": item.needs_protocol, "blocks": [spec.model_dump(mode="json") for spec in item.blocks]}
            for item in types.values()
        ],
        "style_keys": list(STYLE_KEYS),
        "languages": sorted(SUPPORTED_LOCALES),
        "token_schema": DocumentStyleTokens.model_json_schema(),
        "options_schema": ExportOptions.model_json_schema(),
    }


# ── Dokumenteinstellungen des Mandanten ─────────────────────────────────────


class DocumentSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    language: str | None = None


@router.get("/document-settings", response_model=DocumentSettings)
def get_document_settings(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    require_reader(user)
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


# ── Hausstile ───────────────────────────────────────────────────────────────


class DocumentStyleRead(BaseModel):
    id: uuid.UUID
    name: str
    style_key: str
    tokens: DocumentStyleTokens
    is_default: bool
    version: int
    updated_at: datetime


class DocumentStyleWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(None, max_length=120)
    style_key: Literal["modern", "classic", "compact"] | None = None
    tokens: DocumentStyleTokens | None = None
    is_default: bool | None = None


def _style_read(style: DocumentStyle) -> DocumentStyleRead:
    try:
        tokens = style_service.parse_tokens(style.tokens_json)
    except ValueError:
        tokens = default_tokens(style.style_key)
    return DocumentStyleRead(id=style.public_id, name=style.name, style_key=style.style_key, tokens=tokens, is_default=style.is_default, version=style.version, updated_at=style.updated_at)


def _style_or_404(db: Session, user: CurrentUser, style_id: uuid.UUID) -> DocumentStyle:
    style = style_service.get_style(db, user.current_tenant_id, style_id)
    if style is None:
        raise HTTPException(status_code=404, detail=text(_lang(user), "apiError.notFound"))
    return style


@router.get("/document-styles", response_model=list[DocumentStyleRead])
def list_document_styles(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    require_reader(user)
    return [_style_read(style) for style in style_service.list_styles(db, user.current_tenant_id)]


@router.post("/document-styles", response_model=DocumentStyleRead, status_code=201)
def create_document_style(body: DocumentStyleWrite, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    require_admin(user)
    style_key = body.style_key or "modern"
    try:
        style = style_service.create_style(db, user.current_tenant_id, name=body.name or style_key, style_key=style_key, tokens=body.tokens, is_default=bool(body.is_default))
    except style_service.StyleValidationError as exc:
        db.rollback()
        raise _http_error(user, exc) from exc
    db.commit()
    audit.log(db, action="document_style.create", actor=user, entity_type="document_style", entity_id=style.id)
    return _style_read(style)


@router.patch("/document-styles/{style_id}", response_model=DocumentStyleRead)
def update_document_style(style_id: uuid.UUID, body: DocumentStyleWrite, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    require_admin(user)
    style = _style_or_404(db, user, style_id)
    try:
        style_service.update_style(db, style, name=body.name, style_key=body.style_key, tokens=body.tokens, is_default=body.is_default)
    except style_service.StyleValidationError as exc:
        db.rollback()
        raise _http_error(user, exc) from exc
    db.commit()
    audit.log(db, action="document_style.update", actor=user, entity_type="document_style", entity_id=style.id, details={"version": style.version})
    return _style_read(style)


@router.delete("/document-styles/{style_id}", status_code=204)
def delete_document_style(style_id: uuid.UUID, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    require_admin(user)
    style = _style_or_404(db, user, style_id)
    if len(style_service.list_styles(db, user.current_tenant_id)) <= 1:
        raise HTTPException(status_code=409, detail=text(_lang(user), "apiError.lastStyle"))
    style_db_id = style.id
    style_service.delete_style(db, style)
    db.commit()
    audit.log(db, action="document_style.delete", actor=user, entity_type="document_style", entity_id=style_db_id)
    return Response(status_code=204)


# ── Stil-Assets (Schriften, Bilder) ─────────────────────────────────────────


class DocumentStyleAssetRead(BaseModel):
    id: uuid.UUID
    kind: str
    name: str
    original_name: str | None
    mime_type: str | None
    file_size_bytes: int | None
    font_family: str | None
    content_url: str
    created_at: datetime


def _asset_read(asset: DocumentStyleAsset) -> DocumentStyleAssetRead:
    return DocumentStyleAssetRead(
        id=asset.public_id,
        kind=asset.kind,
        name=asset.name,
        original_name=asset.original_name,
        mime_type=asset.mime_type,
        file_size_bytes=asset.file_size_bytes,
        font_family=asset.font_family,
        content_url=f"/api/document-style-assets/{asset.public_id}/content",
        created_at=asset.created_at,
    )


@router.get("/document-style-assets", response_model=list[DocumentStyleAssetRead])
def list_document_style_assets(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    require_reader(user)
    return [_asset_read(asset) for asset in style_service.list_assets(db, user.current_tenant_id)]


@router.post("/document-style-assets", response_model=DocumentStyleAssetRead, status_code=201)
async def upload_document_style_asset(
    kind: Literal["image", "font"] = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_admin(user)
    from app.services.file_service import MAX_UPLOAD_BYTES

    if file.size is not None and file.size > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=text(_lang(user), "apiError.tooLarge"))
    content = await file.read()
    try:
        asset = await style_service.create_asset(db, user.current_tenant_id, kind=kind, filename=file.filename or kind, content=content, user_id=user.user_id)
    except style_service.StyleValidationError as exc:
        db.rollback()
        raise _http_error(user, exc) from exc
    db.commit()
    audit.log(db, action="document_style_asset.upload", actor=user, entity_type="document_style_asset", entity_id=asset.id, details={"kind": kind})
    return _asset_read(asset)


@router.get("/document-style-assets/{asset_id}/content")
def get_document_style_asset_content(asset_id: uuid.UUID, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    require_reader(user)
    asset = style_service.get_asset(db, user.current_tenant_id, asset_id)
    content = style_service.read_asset(asset) if asset is not None else None
    if content is None:
        raise HTTPException(status_code=404, detail=text(_lang(user), "apiError.notFound"))
    return Response(content=content, media_type=asset.mime_type or "application/octet-stream", headers={"Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff"})


@router.delete("/document-style-assets/{asset_id}", status_code=204)
def delete_document_style_asset(asset_id: uuid.UUID, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    require_admin(user)
    asset = style_service.get_asset(db, user.current_tenant_id, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail=text(_lang(user), "apiError.notFound"))
    asset_db_id = asset.id
    try:
        style_service.delete_asset(db, asset)
    except style_service.StyleValidationError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=text(_lang(user), str(exc))) from exc
    db.commit()
    audit.log(db, action="document_style_asset.delete", actor=user, entity_type="document_style_asset", entity_id=asset_db_id)
    return Response(status_code=204)


# ── Rezepte ─────────────────────────────────────────────────────────────────


class DocumentRecipeRead(BaseModel):
    id: uuid.UUID
    name: str
    document_type: str
    blocks: list[BlockSpec]
    options: ExportOptions
    style_id: uuid.UUID | None
    language: str | None
    updated_at: datetime


class DocumentRecipeWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(None, max_length=160)
    document_type: str | None = Field(None, max_length=40)
    blocks: list[BlockSpec] | None = Field(None, max_length=200)
    options: ExportOptions | None = None
    style_id: uuid.UUID | None = None
    language: str | None = None


def _recipe_read(db: Session, recipe: DocumentRecipe) -> DocumentRecipeRead:
    style = db.get(DocumentStyle, recipe.style_id) if recipe.style_id else None
    return DocumentRecipeRead(
        id=recipe.public_id,
        name=recipe.name,
        document_type=recipe.document_type,
        blocks=[BlockSpec.model_validate(item) for item in (recipe.blocks_json or [])],
        options=ExportOptions.model_validate(recipe.options_json or {}),
        style_id=style.public_id if style else None,
        language=recipe.language,
        updated_at=recipe.updated_at,
    )


def _apply_recipe(db: Session, user: CurrentUser, recipe: DocumentRecipe, body: DocumentRecipeWrite) -> None:
    fields = body.model_fields_set
    if body.name is not None:
        recipe.name = body.name.strip() or recipe.name
    if body.document_type is not None:
        if body.document_type not in document_types():
            raise ValueError("unknown_document_type")
        recipe.document_type = body.document_type
    if body.blocks is not None:
        for index, spec in enumerate(body.blocks):
            try:
                validate_spec(spec)
            except ValueError as exc:
                raise BlockSpecError(index, spec.type, str(exc).splitlines()[0]) from exc
        recipe.blocks_json = [spec.model_dump(mode="json") for spec in body.blocks]
    if body.options is not None:
        recipe.options_json = body.options.model_dump(mode="json", exclude_none=True)
    if "style_id" in fields:
        if body.style_id is None:
            recipe.style_id = None
        else:
            style = style_service.get_style(db, user.current_tenant_id, body.style_id)
            if style is None:
                raise DocumentNotFoundError("DocumentStyle")
            recipe.style_id = style.id
    if "language" in fields:
        recipe.language = body.language if body.language in SUPPORTED_LOCALES else None


def _recipe_or_404(db: Session, user: CurrentUser, recipe_id: uuid.UUID) -> DocumentRecipe:
    recipe = db.scalar(select(DocumentRecipe).where(DocumentRecipe.public_id == recipe_id, DocumentRecipe.tenant_id == user.current_tenant_id))
    if recipe is None:
        raise HTTPException(status_code=404, detail=text(_lang(user), "apiError.notFound"))
    return recipe


@router.get("/document-recipes", response_model=list[DocumentRecipeRead])
def list_document_recipes(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    require_reader(user)
    recipes = db.scalars(select(DocumentRecipe).where(DocumentRecipe.tenant_id == user.current_tenant_id).order_by(DocumentRecipe.name.asc()))
    return [_recipe_read(db, recipe) for recipe in recipes]


@router.post("/document-recipes", response_model=DocumentRecipeRead, status_code=201)
def create_document_recipe(body: DocumentRecipeWrite, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    require_writer(user)
    recipe = DocumentRecipe(tenant_id=user.current_tenant_id, name=(body.name or "").strip() or "Dokument", created_by=user.user_id, blocks_json=[], options_json={})
    try:
        _apply_recipe(db, user, recipe, body)
    except (DocumentNotFoundError, ValueError) as exc:
        raise _http_error(user, exc) from exc
    db.add(recipe)
    db.commit()
    audit.log(db, action="document_recipe.create", actor=user, entity_type="document_recipe", entity_id=recipe.id)
    return _recipe_read(db, recipe)


@router.patch("/document-recipes/{recipe_id}", response_model=DocumentRecipeRead)
def update_document_recipe(recipe_id: uuid.UUID, body: DocumentRecipeWrite, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    require_writer(user)
    recipe = _recipe_or_404(db, user, recipe_id)
    try:
        _apply_recipe(db, user, recipe, body)
    except (DocumentNotFoundError, ValueError) as exc:
        db.rollback()
        raise _http_error(user, exc) from exc
    db.commit()
    audit.log(db, action="document_recipe.update", actor=user, entity_type="document_recipe", entity_id=recipe.id)
    return _recipe_read(db, recipe)


@router.delete("/document-recipes/{recipe_id}", status_code=204)
def delete_document_recipe(recipe_id: uuid.UUID, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    require_writer(user)
    recipe = _recipe_or_404(db, user, recipe_id)
    recipe_db_id = recipe.id
    db.delete(recipe)
    db.commit()
    audit.log(db, action="document_recipe.delete", actor=user, entity_type="document_recipe", entity_id=recipe_db_id)
    return Response(status_code=204)


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
