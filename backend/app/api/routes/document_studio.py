"""Document Studio: Template Library, Visual Designer (Entwürfe, Revisionen, Veröffentlichung),
Brand Studio (Brand-Profile, Assets), wiederverwendbare Komponenten, Zuweisungen, Katalog.

Rechte siehe app/documents/permissions.py. Jede ID wird mandantengebunden aufgelöst;
Systemvorlagen sind für Mandanten nur lesbar. Fehler: kuratierte Meldungen (documentPdf
``apiError.*``), Konflikte beim Autosave als HTTP 409 mit aktueller ``lock_version``.
"""
from __future__ import annotations

import asyncio
import hashlib
import threading
import uuid
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.api.routes.documents import http_error, render_error
from app.core.config import settings
from app.core.db import get_db
from app.core.security import CurrentUser, get_current_user
from app.documents import assets as asset_service
from app.documents import brand_service, permissions, template_service
from app.documents import service as document_service
from app.documents.brand import BRAND_PRESETS, BrandTokens, color_references
from app.documents.compiler import validate_template
from app.documents.components import catalog_payload
from app.documents.context import DocumentNotFoundError, DocumentPermissionError
from app.documents.layout import LayoutJson, LayoutValidationError, TemplateContent, layout_error_of, parse_content
from app.documents.renderer import DocumentRenderError, get_renderer
from app.documents.strings import normalize_language, text
from app.models import (
    AppUser,
    DocumentAsset,
    DocumentBrand,
    DocumentBrandRevision,
    DocumentComponent,
    DocumentTemplate,
    DocumentTemplateAssignment,
    DocumentTemplateRevision,
    Template,
)
from app.services import public_id_service
from app.services.audit_service import AuditService
from app.core.offload import run_coroutine_in_thread

router = APIRouter()
audit = AuditService()


def _lang(user: CurrentUser) -> str:
    return normalize_language(user.preferred_language)


def _not_found(user: CurrentUser) -> HTTPException:
    return HTTPException(status_code=404, detail=text(_lang(user), "apiError.notFound"))


def _curated(user: CurrentUser, key: str, status: int = 422) -> HTTPException:
    return HTTPException(status_code=status, detail=text(_lang(user), key))


def _conflict(user: CurrentUser, lock_version: int) -> HTTPException:
    return HTTPException(status_code=409, detail={"message": text(_lang(user), "apiError.conflict"), "lock_version": lock_version})


def _validation_error(user: CurrentUser, exc: Exception) -> HTTPException:
    layout_error = layout_error_of(exc)
    if layout_error is not None:
        exc = layout_error
    if isinstance(exc, LayoutValidationError):
        return HTTPException(status_code=422, detail={"message": text(_lang(user), "apiError.templateInvalid"), "code": exc.code, "node_id": exc.node_id, "detail": exc.detail})
    if isinstance(exc, ValidationError):
        errors = exc.errors()
        first = errors[0] if errors else {}
        return HTTPException(status_code=422, detail={"message": text(_lang(user), "apiError.templateInvalid"), "code": "schema", "location": [str(part) for part in first.get("loc", [])], "detail": first.get("msg", "")})
    return http_error(user, exc)


def _user_name(db: Session, user_id: int | None) -> str | None:
    if user_id is None:
        return None
    row = db.get(AppUser, user_id)
    return row.display_name if row is not None else None


# ── Fähigkeiten und Katalog ──────────────────────────────────────────────────


@router.get("/document-studio/capabilities")
def get_capabilities(user: CurrentUser = Depends(get_current_user)) -> dict[str, bool]:
    permissions.require_view(user)
    return permissions.capabilities(user)


@router.get("/document-studio/catalog")
def get_studio_catalog(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    permissions.require_view(user)
    payload = catalog_payload()
    brand = brand_service.ensure_default_brand(db, user.current_tenant_id)
    tokens = brand_service.tokens_of(brand_service.current_revision(db, brand))
    payload["color_references"] = color_references(tokens)
    from app.documents.brand import BUILTIN_FONTS

    fonts = list(BUILTIN_FONTS.values())
    fonts += [row.font_family for row in asset_service.list_assets(db, user.current_tenant_id, kind="font") if row.font_family and row.font_family not in fonts]
    payload["fonts"] = fonts
    payload["brand_presets"] = list(BRAND_PRESETS)
    db.commit()
    return payload


# ── Vorlagen ─────────────────────────────────────────────────────────────────


class RevisionRead(BaseModel):
    id: uuid.UUID
    revision_no: int
    status: str
    lock_version: int
    brand_mode: str
    schema_version: int
    note: str | None
    created_at: datetime
    updated_at: datetime
    published_at: datetime | None
    created_by_name: str | None = None
    published_by_name: str | None = None


def _revision_read(db: Session, revision: DocumentTemplateRevision | None, names: dict[int, str] | None = None) -> RevisionRead | None:
    if revision is None:
        return None
    name = (lambda user_id: names.get(user_id) if user_id is not None else None) if names is not None else (lambda user_id: _user_name(db, user_id))
    return RevisionRead(
        id=revision.public_id,
        revision_no=revision.revision_no,
        status=revision.status,
        lock_version=revision.lock_version,
        brand_mode=revision.brand_mode,
        schema_version=revision.schema_version,
        note=revision.note,
        created_at=revision.created_at,
        updated_at=revision.updated_at,
        published_at=revision.published_at,
        created_by_name=name(revision.created_by),
        published_by_name=name(revision.published_by),
    )


class TemplateRead(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    document_type: str
    variant: str | None
    category: str
    origin: str
    system_key: str | None
    source_system_key: str | None = None
    status: str
    editable: bool
    is_default: bool
    brand_id: uuid.UUID | None
    published_revision: RevisionRead | None
    draft_revision: RevisionRead | None
    created_at: datetime
    updated_at: datetime


class TemplateDetail(TemplateRead):
    content: dict[str, Any]
    working_revision_id: uuid.UUID | None
    diagnostics: list[dict[str, Any]] = Field(default_factory=list)


@dataclass
class _Prefetched:
    """Vorab geladene Bezüge für viele Vorlagen (Bibliothek, STUDIO-015)."""

    brands: dict[int, DocumentBrand]
    sources: dict[int, DocumentTemplate]
    published: dict[int, DocumentTemplateRevision]
    drafts: dict[int, DocumentTemplateRevision]
    names: dict[int, str]


def _prefetch(db: Session, templates: list[DocumentTemplate]) -> _Prefetched:
    def by_id(model, ids):
        ids = {item for item in ids if item}
        return {row.id: row for row in db.scalars(select(model).where(model.id.in_(ids)))} if ids else {}

    published = by_id(DocumentTemplateRevision, (template.published_revision_id for template in templates))
    template_ids = [template.id for template in templates]
    drafts = {
        row.template_id: row
        for row in db.scalars(
            select(DocumentTemplateRevision).where(DocumentTemplateRevision.template_id.in_(template_ids), DocumentTemplateRevision.status == "draft")
        )
    } if template_ids else {}
    user_ids = {user_id for revision in (*published.values(), *drafts.values()) for user_id in (revision.created_by, revision.published_by) if user_id}
    names = dict(db.execute(select(AppUser.id, AppUser.display_name).where(AppUser.id.in_(user_ids))).all()) if user_ids else {}
    return _Prefetched(
        brands=by_id(DocumentBrand, (template.brand_id for template in templates)),
        sources=by_id(DocumentTemplate, (template.source_template_id for template in templates)),
        published=published,
        drafts=drafts,
        names=names,
    )


def _template_read(
    db: Session, user: CurrentUser, template: DocumentTemplate, defaults: dict[str, int] | None = None, prefetched: _Prefetched | None = None,
) -> TemplateRead:
    defaults = defaults if defaults is not None else template_service.default_template_ids(db, user.current_tenant_id)
    if prefetched is None:
        prefetched = _prefetch(db, [template])
    brand = prefetched.brands.get(template.brand_id) if template.brand_id else None
    source = prefetched.sources.get(template.source_template_id) if template.source_template_id else None
    return TemplateRead(
        id=template.public_id,
        name=template.name,
        description=template.description,
        document_type=template.document_type,
        variant=template.variant,
        category=template.category,
        origin=template.origin,
        system_key=template.system_key,
        source_system_key=source.system_key if source is not None else None,
        status=template.status,
        editable=template.tenant_id == user.current_tenant_id and user.current_role in {"writer", "admin"},
        is_default=defaults.get(template.document_type) == template.id,
        brand_id=brand.public_id if brand is not None else None,
        published_revision=_revision_read(db, prefetched.published.get(template.published_revision_id), prefetched.names),
        draft_revision=_revision_read(db, prefetched.drafts.get(template.id), prefetched.names),
        created_at=template.created_at,
        updated_at=template.updated_at,
    )


def _sees_drafts(user: CurrentUser) -> bool:
    """Entwürfe (Arbeitsstand) sehen nur Personen, die Vorlagen bearbeiten dürfen; alle anderen
    sehen die veröffentlichte Revision - wie bei der Vorschau mit ``revision_id``."""
    return permissions.capabilities(user)["edit_templates"]


def _visible_revision(db: Session, user: CurrentUser, template: DocumentTemplate) -> DocumentTemplateRevision | None:
    return template_service.working_revision(db, template) if _sees_drafts(user) else template_service.published_revision(db, template)


def _visible_revision_by_id(db: Session, user: CurrentUser, template: DocumentTemplate, revision_id: uuid.UUID) -> DocumentTemplateRevision | None:
    revision = template_service.get_revision(db, template, revision_id)
    if revision is not None and revision.status == "draft" and not _sees_drafts(user):
        return None
    return revision


def _template_detail(db: Session, user: CurrentUser, template: DocumentTemplate, *, diagnostics: list[Any] | None = None) -> TemplateDetail:
    base = _template_read(db, user, template)
    working = _visible_revision(db, user, template)
    content = template_service.revision_content(working) if working is not None else TemplateContent()
    if diagnostics is None:
        diagnostics = validate_template(db, template.tenant_id or user.current_tenant_id, content, document_type=template.document_type)
    return TemplateDetail(
        **base.model_dump(),
        content=content.model_dump(mode="json"),
        working_revision_id=working.public_id if working is not None else None,
        diagnostics=[item.as_dict() for item in diagnostics],
    )


def _template_or_404(db: Session, user: CurrentUser, template_id: uuid.UUID) -> DocumentTemplate:
    template = template_service.get_template(db, user.current_tenant_id, template_id)
    if template is None:
        raise _not_found(user)
    return template


def _editable_template(db: Session, user: CurrentUser, template_id: uuid.UUID) -> DocumentTemplate:
    permissions.require_edit(user)
    template = _template_or_404(db, user, template_id)
    if template.tenant_id != user.current_tenant_id:
        raise _curated(user, "apiError.systemTemplate", 403)
    return template


@router.get("/document-templates", response_model=list[TemplateRead])
def list_document_templates(
    document_type: str | None = Query(default=None, max_length=40),
    include_archived: bool = False,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    permissions.require_view(user)
    defaults = template_service.default_template_ids(db, user.current_tenant_id)
    templates = template_service.list_templates(db, user.current_tenant_id, document_type=document_type, include_archived=include_archived)
    prefetched = _prefetch(db, templates)
    return [_template_read(db, user, template, defaults, prefetched) for template in templates]


class TemplateCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=160)
    document_type: str = Field(..., max_length=40)
    description: str | None = Field(None, max_length=600)
    # Ausgangspunkt: Kopie einer bestehenden Vorlage (System oder eigene); leer = leere Vorlage
    from_template_id: uuid.UUID | None = None
    content: LayoutJson | None = None


@router.post("/document-templates", response_model=TemplateDetail, status_code=201)
def create_document_template(body: TemplateCreate, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    permissions.require_edit(user)
    try:
        if body.from_template_id is not None:
            source = _template_or_404(db, user, body.from_template_id)
            template, _revision = template_service.duplicate_template(db, user.current_tenant_id, source, name=body.name, user_id=user.user_id)
            if body.description is not None:
                template.description = body.description
        else:
            content = TemplateContent.model_validate(body.content) if body.content is not None else None
            template, _revision = template_service.create_template(db, user.current_tenant_id, name=body.name, document_type=body.document_type, description=body.description, content=content, user_id=user.user_id)
        db.commit()
    except (ValidationError, LayoutValidationError) as exc:
        db.rollback()
        raise _validation_error(user, exc) from exc
    except ValueError as exc:
        db.rollback()
        raise http_error(user, exc) from exc
    audit.log(db, action="document_template.create", actor=user, entity_type="document_template", entity_id=template.id, details={"document_type": template.document_type})
    return _template_detail(db, user, template)


@router.get("/document-templates/{template_id}", response_model=TemplateDetail)
def get_document_template(template_id: uuid.UUID, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    permissions.require_view(user)
    return _template_detail(db, user, _template_or_404(db, user, template_id))


class TemplateMetaUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(None, max_length=160)
    description: str | None = Field(None, max_length=600)
    category: str | None = Field(None, max_length=60)
    brand_id: uuid.UUID | None = None
    clear_brand: bool = False


@router.patch("/document-templates/{template_id}", response_model=TemplateRead)
def update_document_template(template_id: uuid.UUID, body: TemplateMetaUpdate, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    template = _editable_template(db, user, template_id)
    brand: uuid.UUID | None | Literal["unset"] = None if body.clear_brand else (body.brand_id if body.brand_id is not None else "unset")
    if brand != "unset" and template.published_revision_id is not None:
        # Das Brand-Profil wirkt sofort auf Exporte der veröffentlichten Revision
        # (brand_mode=follow) - wie Veröffentlichen nur mit Veröffentlichungsrecht
        permissions.require_publish(user)
    try:
        template_service.update_template_meta(db, template, name=body.name, description=body.description, category=body.category, brand_id=brand, user_id=user.user_id)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise http_error(user, exc) from exc
    return _template_read(db, user, template)


@router.delete("/document-templates/{template_id}", status_code=204)
def delete_document_template(template_id: uuid.UUID, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    template = _editable_template(db, user, template_id)
    permissions.require_publish(user)
    try:
        template_service.delete_template(db, template)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise http_error(user, exc) from exc
    audit.log(db, action="document_template.delete", actor=user, details={"template_id": str(template_id)})
    return Response(status_code=204)


class DuplicateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=160)


@router.post("/document-templates/{template_id}/duplicate", response_model=TemplateDetail, status_code=201)
def duplicate_document_template(template_id: uuid.UUID, body: DuplicateBody, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    permissions.require_edit(user)
    source = _template_or_404(db, user, template_id)
    try:
        template, _revision = template_service.duplicate_template(db, user.current_tenant_id, source, name=body.name, user_id=user.user_id)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise http_error(user, exc) from exc
    audit.log(db, action="document_template.duplicate", actor=user, entity_type="document_template", entity_id=template.id, details={"source": str(template_id)})
    return _template_detail(db, user, template)


class DraftSave(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: LayoutJson
    # lock_version des Entwurfs, den der Designer zuletzt geladen hat (None = neuer Entwurf)
    lock_version: int | None = None
    brand_mode: Literal["follow", "pinned"] | None = None
    note: str | None = Field(None, max_length=300)


class DraftSaved(BaseModel):
    revision: RevisionRead
    diagnostics: list[dict[str, Any]]


@router.put("/document-templates/{template_id}/draft", response_model=DraftSaved)
def save_document_template_draft(template_id: uuid.UUID, body: DraftSave, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    """Autosave des Designers. Ungültiges JSON wird nie gespeichert (Schemaprüfung);
    fachliche Hinweise (unbekannte Bindung, fehlendes Asset …) kommen als Diagnosen zurück."""
    template = _editable_template(db, user, template_id)
    try:
        content = TemplateContent.model_validate(body.content)
        revision = template_service.save_draft(db, template, content, expected_lock_version=body.lock_version, user_id=user.user_id, brand_mode=body.brand_mode, note=body.note)
        db.commit()
    except template_service.TemplateConflictError as exc:
        db.rollback()
        raise _conflict(user, exc.current_lock_version) from exc
    except (ValidationError, LayoutValidationError) as exc:
        db.rollback()
        raise _validation_error(user, exc) from exc
    except ValueError as exc:
        db.rollback()
        raise http_error(user, exc) from exc
    diagnostics = validate_template(db, user.current_tenant_id, content, document_type=template.document_type)
    return DraftSaved(revision=_revision_read(db, revision), diagnostics=[item.as_dict() for item in diagnostics])


@router.delete("/document-templates/{template_id}/draft", response_model=TemplateDetail)
def discard_document_template_draft(template_id: uuid.UUID, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    template = _editable_template(db, user, template_id)
    try:
        template_service.discard_draft(db, template)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise http_error(user, exc) from exc
    return _template_detail(db, user, template)


class ValidateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: LayoutJson
    document_type: str | None = Field(None, max_length=40)


@router.post("/document-templates/validate")
def validate_document_template(body: ValidateBody, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    permissions.require_view(user)
    try:
        content = TemplateContent.model_validate(body.content)
    except (ValidationError, LayoutValidationError) as exc:
        raise _validation_error(user, exc) from exc
    diagnostics = validate_template(db, user.current_tenant_id, content, document_type=body.document_type)
    return {"diagnostics": [item.as_dict() for item in diagnostics]}


class PublishBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: str | None = Field(None, max_length=300)


@router.post("/document-templates/{template_id}/publish", response_model=TemplateDetail)
def publish_document_template(template_id: uuid.UUID, body: PublishBody, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    template = _editable_template(db, user, template_id)
    permissions.require_publish(user)
    try:
        revision = template_service.publish(db, template, user_id=user.user_id, note=body.note)
        db.commit()
    except template_service.TemplatePublishError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail={"message": text(_lang(user), "apiError.templateInvalid"), "diagnostics": [item.as_dict() for item in exc.diagnostics]}) from exc
    except ValueError as exc:
        db.rollback()
        raise http_error(user, exc) from exc
    audit.log(db, action="document_template.publish", actor=user, entity_type="document_template", entity_id=template.id, details={"revision": revision.revision_no})
    return _template_detail(db, user, template)


class ArchiveBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    archived: bool


@router.post("/document-templates/{template_id}/archive", response_model=TemplateRead)
def archive_document_template(template_id: uuid.UUID, body: ArchiveBody, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    template = _editable_template(db, user, template_id)
    permissions.require_publish(user)
    template_service.set_archived(db, template, body.archived, user_id=user.user_id)
    db.commit()
    audit.log(db, action="document_template.archive" if body.archived else "document_template.unarchive", actor=user, entity_type="document_template", entity_id=template.id)
    return _template_read(db, user, template)


@router.get("/document-templates/{template_id}/revisions", response_model=list[RevisionRead])
def list_document_template_revisions(template_id: uuid.UUID, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    permissions.require_view(user)
    template = _template_or_404(db, user, template_id)
    drafts = _sees_drafts(user)
    return [_revision_read(db, revision) for revision in template_service.list_revisions(db, template) if drafts or revision.status != "draft"]


@router.get("/document-templates/{template_id}/revisions/{revision_id}")
def get_document_template_revision(template_id: uuid.UUID, revision_id: uuid.UUID, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    permissions.require_view(user)
    template = _template_or_404(db, user, template_id)
    revision = _visible_revision_by_id(db, user, template, revision_id)
    if revision is None:
        raise _not_found(user)
    return {"revision": _revision_read(db, revision).model_dump(mode="json"), "content": template_service.revision_content(revision).model_dump(mode="json")}


@router.post("/document-templates/{template_id}/revisions/{revision_id}/restore", response_model=TemplateDetail)
def restore_document_template_revision(template_id: uuid.UUID, revision_id: uuid.UUID, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    template = _editable_template(db, user, template_id)
    revision = template_service.get_revision(db, template, revision_id)
    if revision is None:
        raise _not_found(user)
    template_service.restore_revision(db, template, revision, user_id=user.user_id)
    db.commit()
    audit.log(db, action="document_template.restore", actor=user, entity_type="document_template", entity_id=template.id, details={"revision": revision.revision_no})
    return _template_detail(db, user, template)


@router.get("/document-templates/{template_id}/compare")
def compare_document_template_revisions(
    template_id: uuid.UUID,
    from_revision: uuid.UUID = Query(..., alias="from"),
    to_revision: uuid.UUID = Query(..., alias="to"),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    permissions.require_view(user)
    template = _template_or_404(db, user, template_id)
    old = _visible_revision_by_id(db, user, template, from_revision)
    new = _visible_revision_by_id(db, user, template, to_revision)
    if old is None or new is None:
        raise _not_found(user)
    return template_service.compare_revisions(template_service.revision_content(old), template_service.revision_content(new))


# Vorschaubilder der Bibliothek: Beispieldaten, erste Seite, kleine Auflösung. Zwei Ebenen
# (STUDIO-015): im Prozess (LRU) und auf Platte je Mandant, damit ein Neustart oder ein anderer
# Worker nicht jede Vorlage neu rendert. Der Schlüssel enthält Revision, Bearbeitungsstand und
# Brand-Revision - ein geänderter Stand erzeugt eine neue Datei, alte verdrängt das Limit.
_THUMBNAILS: OrderedDict[str, bytes] = OrderedDict()
_THUMBNAIL_LOCK = threading.Lock()
_THUMBNAIL_LIMIT = 300
_THUMBNAIL_FILES_PER_TENANT = 500
THUMBNAIL_DIR = "document_thumbnails"


def _thumbnail_file(tenant_id: int, key: str) -> Path:
    return Path(settings.storage_root) / THUMBNAIL_DIR / f"tenant-{tenant_id}" / f"{key}.png"


def _store_thumbnail_file(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_bytes(content)
    temp.replace(path)
    files = sorted(path.parent.glob("*.png"), key=lambda item: item.stat().st_mtime)
    for stale in files[: max(0, len(files) - _THUMBNAIL_FILES_PER_TENANT)]:
        stale.unlink(missing_ok=True)


@router.get("/document-templates/{template_id}/thumbnail")
async def get_document_template_thumbnail(template_id: uuid.UUID, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    permissions.require_view(user)

    def resolve() -> tuple[str, Path, bytes | None, str, uuid.UUID, uuid.UUID]:
        # Synchrone DB- und Datei-Arbeit nicht im Event-Loop (CONC-001).
        template = _template_or_404(db, user, template_id)
        revision = _visible_revision(db, user, template)
        if revision is None:
            raise _not_found(user)
        brand_revision = template_service.resolve_brand_revision(db, user.current_tenant_id, template_service.ResolvedTemplate(template=template, revision=revision, source="explicit", brand_id=None))
        key = hashlib.sha256(f"{user.current_tenant_id}:{revision.id}:{revision.lock_version}:{brand_revision.id if brand_revision else 0}:{_lang(user)}".encode()).hexdigest()
        with _THUMBNAIL_LOCK:
            cached = _THUMBNAILS.get(key)
        disk_file = _thumbnail_file(user.current_tenant_id, key)
        if cached is None and disk_file.is_file():
            cached = disk_file.read_bytes()
            with _THUMBNAIL_LOCK:
                _THUMBNAILS[key] = cached
        return key, disk_file, cached, template.document_type, template.public_id, revision.public_id

    key, disk_file, cached, document_type, template_public_id, revision_public_id = await run_in_threadpool(resolve)
    if cached is None:
        request = document_service.DocumentRequest(document_type=document_type, template_id=template_public_id, revision_id=revision_public_id, data_mode="sample", language=user.preferred_language)

        def prepare_and_release():
            # Savepoint sofort zurückrollen und Transaktion beenden: keine Verbindung über den
            # Compile halten (CONC-003).
            savepoint = db.begin_nested()
            try:
                return document_service.prepare(db, user, user.current_tenant_id, request, preview=True)
            finally:
                if savepoint.is_active:
                    savepoint.rollback()
                db.commit()

        try:
            prepared = await run_in_threadpool(prepare_and_release)
            output = await get_renderer().render(prepared.compiled.data, document_service.RenderAssets(files=prepared.compiled.files, fonts=prepared.compiled.fonts), fmt="png", max_pages=1, ppi=40)
        except DocumentRenderError as exc:
            raise render_error(user, exc) from exc
        except (DocumentPermissionError, DocumentNotFoundError, ValueError) as exc:
            raise http_error(user, exc) from exc
        cached = output.pages[0] if output.pages else b""
        if cached:
            await run_in_threadpool(_store_thumbnail_file, disk_file, cached)
        with _THUMBNAIL_LOCK:
            _THUMBNAILS[key] = cached
            while len(_THUMBNAILS) > _THUMBNAIL_LIMIT:
                _THUMBNAILS.popitem(last=False)
    return Response(content=cached, media_type="image/png", headers={"Cache-Control": "private, max-age=300"})


# ── Zuweisungen ──────────────────────────────────────────────────────────────


class AssignmentRead(BaseModel):
    document_type: str
    protocol_template_id: uuid.UUID | None
    protocol_template_name: str | None
    template_id: uuid.UUID | None
    brand_id: uuid.UUID | None


def _assignment_read(db: Session, row: DocumentTemplateAssignment) -> AssignmentRead:
    protocol_template = db.get(Template, row.protocol_template_id) if row.protocol_template_id else None
    template = db.get(DocumentTemplate, row.document_template_id) if row.document_template_id else None
    brand = db.get(DocumentBrand, row.brand_id) if row.brand_id else None
    return AssignmentRead(
        document_type=row.document_type,
        protocol_template_id=protocol_template.public_id if protocol_template else None,
        protocol_template_name=protocol_template.name if protocol_template else None,
        template_id=template.public_id if template else None,
        brand_id=brand.public_id if brand else None,
    )


@router.get("/document-template-assignments", response_model=list[AssignmentRead])
def list_document_template_assignments(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    permissions.require_view(user)
    return [_assignment_read(db, row) for row in template_service.list_assignments(db, user.current_tenant_id)]


class AssignmentWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_type: str = Field(..., max_length=40)
    protocol_template_id: uuid.UUID | None = None
    template_id: uuid.UUID | None = None
    brand_id: uuid.UUID | None = None


@router.put("/document-template-assignments", response_model=AssignmentRead | None)
def set_document_template_assignment(body: AssignmentWrite, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    """Standardvorlage (und optional Brand-Profil) je Dokumenttyp bzw. Protokollvorlage setzen;
    ohne Vorlage und Brand wird die Zuweisung entfernt."""
    permissions.require_publish(user)
    tenant_id = user.current_tenant_id
    template = _template_or_404(db, user, body.template_id) if body.template_id else None
    brand = brand_service.get_brand(db, tenant_id, body.brand_id) if body.brand_id else None
    if body.brand_id and brand is None:
        raise _not_found(user)
    protocol_template = None
    if body.protocol_template_id is not None:
        protocol_template = public_id_service.get_by_public_id(db, Template, body.protocol_template_id, tenant_id=tenant_id)
        if protocol_template is None:
            raise _not_found(user)
    try:
        row = template_service.set_assignment(db, tenant_id, document_type=body.document_type, template=template, brand=brand, protocol_template=protocol_template, user_id=user.user_id)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise http_error(user, exc) from exc
    audit.log(db, action="document_template.assign", actor=user, details={"document_type": body.document_type, "template_id": str(body.template_id) if body.template_id else None, "protocol_template_id": str(body.protocol_template_id) if body.protocol_template_id else None})
    return _assignment_read(db, row) if row is not None else None


# ── Brand-Profile ────────────────────────────────────────────────────────────


class BrandRead(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    is_default: bool
    archived: bool
    revision: int
    lock_version: int
    tokens: dict[str, Any]
    updated_at: datetime


def _brand_read(db: Session, brand: DocumentBrand) -> BrandRead:
    return BrandRead(
        id=brand.public_id,
        name=brand.name,
        description=brand.description,
        is_default=brand.is_default,
        archived=brand.archived_at is not None,
        revision=brand.current_revision,
        lock_version=brand.lock_version,
        tokens=brand_service.tokens_of(brand_service.current_revision(db, brand)).model_dump(mode="json"),
        updated_at=brand.updated_at,
    )


def _brand_or_404(db: Session, user: CurrentUser, brand_id: uuid.UUID) -> DocumentBrand:
    brand = brand_service.get_brand(db, user.current_tenant_id, brand_id)
    if brand is None:
        raise _not_found(user)
    return brand


def _brand_error(user: CurrentUser, exc: Exception) -> HTTPException:
    if isinstance(exc, brand_service.BrandConflictError):
        return _conflict(user, exc.current_lock_version)
    if isinstance(exc, ValidationError):
        return _validation_error(user, exc)
    if isinstance(exc, brand_service.BrandValidationError):
        return _curated(user, str(exc))
    return http_error(user, exc)


@router.get("/document-brands", response_model=list[BrandRead])
def list_document_brands(include_archived: bool = False, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    permissions.require_view(user)
    brand_service.ensure_default_brand(db, user.current_tenant_id)
    db.commit()
    return [_brand_read(db, brand) for brand in brand_service.list_brands(db, user.current_tenant_id, include_archived=include_archived)]


class BrandCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=120)
    description: str | None = Field(None, max_length=600)
    preset: str | None = Field(None, max_length=40)
    from_brand_id: uuid.UUID | None = None
    tokens: dict[str, Any] | None = None
    is_default: bool = False


@router.post("/document-brands", response_model=BrandRead, status_code=201)
def create_document_brand(body: BrandCreate, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    permissions.require_brand(user)
    try:
        if body.from_brand_id is not None:
            brand = brand_service.duplicate_brand(db, _brand_or_404(db, user, body.from_brand_id), name=body.name, user_id=user.user_id)
        else:
            tokens = BrandTokens.model_validate(body.tokens) if body.tokens is not None else None
            brand = brand_service.create_brand(db, user.current_tenant_id, name=body.name, tokens=tokens, preset=body.preset if body.preset in BRAND_PRESETS else None, description=body.description, is_default=body.is_default, user_id=user.user_id)
        db.commit()
    except (ValidationError, ValueError) as exc:
        db.rollback()
        raise _brand_error(user, exc) from exc
    audit.log(db, action="document_brand.create", actor=user, entity_type="document_brand", entity_id=brand.id)
    return _brand_read(db, brand)


@router.get("/document-brands/{brand_id}", response_model=BrandRead)
def get_document_brand(brand_id: uuid.UUID, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    permissions.require_view(user)
    return _brand_read(db, _brand_or_404(db, user, brand_id))


class BrandUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lock_version: int
    name: str | None = Field(None, max_length=120)
    description: str | None = Field(None, max_length=600)
    tokens: dict[str, Any] | None = None
    is_default: bool | None = None
    note: str | None = Field(None, max_length=300)


@router.patch("/document-brands/{brand_id}", response_model=BrandRead)
def update_document_brand(brand_id: uuid.UUID, body: BrandUpdate, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    permissions.require_brand(user)
    brand = _brand_or_404(db, user, brand_id)
    try:
        tokens = BrandTokens.model_validate(body.tokens) if body.tokens is not None else None
        brand_service.update_brand(db, brand, expected_lock_version=body.lock_version, name=body.name, description=body.description, tokens=tokens, is_default=body.is_default, note=body.note, user_id=user.user_id)
        db.commit()
    except (brand_service.BrandConflictError, ValidationError, ValueError) as exc:
        db.rollback()
        raise _brand_error(user, exc) from exc
    audit.log(db, action="document_brand.update", actor=user, entity_type="document_brand", entity_id=brand.id, details={"revision": brand.current_revision})
    return _brand_read(db, brand)


@router.post("/document-brands/{brand_id}/archive", response_model=BrandRead)
def archive_document_brand(brand_id: uuid.UUID, body: ArchiveBody, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    permissions.require_brand(user)
    brand = _brand_or_404(db, user, brand_id)
    try:
        brand_service.archive_brand(db, brand, archived=body.archived)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise _brand_error(user, exc) from exc
    return _brand_read(db, brand)


@router.delete("/document-brands/{brand_id}", status_code=204)
def delete_document_brand(brand_id: uuid.UUID, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    permissions.require_brand(user)
    brand = _brand_or_404(db, user, brand_id)
    try:
        brand_service.delete_brand(db, brand)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise _brand_error(user, exc) from exc
    audit.log(db, action="document_brand.delete", actor=user, details={"brand_id": str(brand_id)})
    return Response(status_code=204)


class BrandRevisionRead(BaseModel):
    id: uuid.UUID
    revision: int
    note: str | None
    created_at: datetime
    created_by_name: str | None


@router.get("/document-brands/{brand_id}/revisions", response_model=list[BrandRevisionRead])
def list_document_brand_revisions(brand_id: uuid.UUID, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    permissions.require_view(user)
    brand = _brand_or_404(db, user, brand_id)
    return [
        BrandRevisionRead(id=row.public_id, revision=row.revision, note=row.note, created_at=row.created_at, created_by_name=_user_name(db, row.created_by))
        for row in brand_service.list_revisions(db, brand)
    ]


@router.post("/document-brands/{brand_id}/revisions/{revision_id}/restore", response_model=BrandRead)
def restore_document_brand_revision(brand_id: uuid.UUID, revision_id: uuid.UUID, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    permissions.require_brand(user)
    brand = _brand_or_404(db, user, brand_id)
    revision = db.scalar(select(DocumentBrandRevision).where(DocumentBrandRevision.brand_id == brand.id, DocumentBrandRevision.public_id == revision_id))
    if revision is None:
        raise _not_found(user)
    try:
        brand_service.restore_revision(db, brand, revision, user_id=user.user_id)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise _brand_error(user, exc) from exc
    return _brand_read(db, brand)


# ── Assets ───────────────────────────────────────────────────────────────────


class AssetRead(BaseModel):
    id: uuid.UUID
    kind: str
    category: str
    name: str
    original_name: str | None
    mime_type: str | None
    file_size_bytes: int | None
    width_px: int | None
    height_px: int | None
    font_family: str | None
    content_url: str
    created_at: datetime


def _asset_read(asset: DocumentAsset) -> AssetRead:
    return AssetRead(
        id=asset.public_id,
        kind=asset.kind,
        category=asset.category,
        name=asset.name,
        original_name=asset.original_name,
        mime_type=asset.mime_type,
        file_size_bytes=asset.file_size_bytes,
        width_px=asset.width_px,
        height_px=asset.height_px,
        font_family=asset.font_family,
        content_url=f"/api/document-assets/{asset.public_id}/content",
        created_at=asset.created_at,
    )


def _asset_or_404(db: Session, user: CurrentUser, asset_id: uuid.UUID) -> DocumentAsset:
    asset = asset_service.get_asset(db, user.current_tenant_id, asset_id)
    if asset is None:
        raise _not_found(user)
    return asset


@router.get("/document-assets", response_model=list[AssetRead])
def list_document_assets(kind: Literal["image", "font"] | None = None, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    permissions.require_view(user)
    return [_asset_read(asset) for asset in asset_service.list_assets(db, user.current_tenant_id, kind=kind)]


@router.post("/document-assets", response_model=AssetRead, status_code=201)
async def upload_document_asset(
    kind: Literal["image", "font"] = Form(...),
    category: str | None = Form(None),
    name: str | None = Form(None),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    # Ganze Verarbeitung im Worker-Thread (Concurrency-Audit CONC-001): sie mischt synchrone
    # DB-Zugriffe mit awaits und blockierte sonst den Event-Loop des ganzen Workers.
    return await run_coroutine_in_thread(_upload_document_asset_impl, kind=kind, category=category, name=name, file=file, db=db, user=user)


async def _upload_document_asset_impl(  # loop-ok: nur über run_coroutine_in_thread (core/offload.py)
    kind: Literal["image", "font"] = Form(...),
    category: str | None = Form(None),
    name: str | None = Form(None),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    permissions.require_brand(user)
    content = await file.read()
    try:
        asset = await asset_service.create_asset(db, user.current_tenant_id, kind=kind, filename=file.filename or "", content=content, user_id=user.user_id, category=category, name=name)
        db.commit()
    except asset_service.AssetValidationError as exc:
        db.rollback()
        raise _curated(user, str(exc)) from exc
    audit.log(db, action="document_asset.upload", actor=user, entity_type="document_asset", entity_id=asset.id, details={"kind": kind})
    return _asset_read(asset)


class AssetUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(None, max_length=120)
    category: str | None = Field(None, max_length=40)


@router.patch("/document-assets/{asset_id}", response_model=AssetRead)
def update_document_asset(asset_id: uuid.UUID, body: AssetUpdate, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    permissions.require_brand(user)
    asset = _asset_or_404(db, user, asset_id)
    asset_service.rename_asset(asset, name=body.name, category=body.category)
    db.commit()
    return _asset_read(asset)


@router.get("/document-assets/{asset_id}/content")
def get_document_asset_content(asset_id: uuid.UUID, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    permissions.require_view(user)
    asset = _asset_or_404(db, user, asset_id)
    content = asset_service.read_asset(asset)
    if content is None:
        raise _not_found(user)
    return Response(content=content, media_type=asset.mime_type or "application/octet-stream", headers={"Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff"})


@router.get("/document-assets/{asset_id}/references")
def get_document_asset_references(asset_id: uuid.UUID, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)) -> list[dict[str, Any]]:
    permissions.require_view(user)
    return asset_service.asset_references(db, _asset_or_404(db, user, asset_id))


@router.delete("/document-assets/{asset_id}", status_code=204)
def delete_document_asset(asset_id: uuid.UUID, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    permissions.require_brand(user)
    asset = _asset_or_404(db, user, asset_id)
    try:
        asset_service.delete_asset(db, asset)
        db.commit()
    except asset_service.AssetValidationError as exc:
        db.rollback()
        raise _curated(user, str(exc)) from exc
    audit.log(db, action="document_asset.delete", actor=user, details={"asset_id": str(asset_id)})
    return Response(status_code=204)


# ── Wiederverwendbare Komponenten ────────────────────────────────────────────


class ComponentRead(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    category: str
    lock_version: int
    node: dict[str, Any]
    updated_at: datetime


def _component_read(component: DocumentComponent) -> ComponentRead:
    return ComponentRead(id=component.public_id, name=component.name, description=component.description, category=component.category, lock_version=component.lock_version, node=component.node_json, updated_at=component.updated_at)


class ComponentWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(None, max_length=120)
    description: str | None = Field(None, max_length=600)
    category: str | None = Field(None, max_length=60)
    node: LayoutJson | None = None
    lock_version: int | None = None


@router.get("/document-components", response_model=list[ComponentRead])
def list_document_components(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    permissions.require_view(user)
    return [_component_read(row) for row in template_service.list_components(db, user.current_tenant_id)]


@router.post("/document-components", response_model=ComponentRead, status_code=201)
def create_document_component(body: ComponentWrite, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    permissions.require_edit(user)
    try:
        component = template_service.save_component(db, user.current_tenant_id, component=None, name=body.name, node=body.node, description=body.description, category=body.category, user_id=user.user_id)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise http_error(user, exc) from exc
    return _component_read(component)


@router.patch("/document-components/{component_id}", response_model=ComponentRead)
def update_document_component(component_id: uuid.UUID, body: ComponentWrite, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    permissions.require_edit(user)
    component = template_service.get_component(db, user.current_tenant_id, component_id)
    if component is None:
        raise _not_found(user)
    try:
        template_service.save_component(db, user.current_tenant_id, component=component, name=body.name, node=body.node, description=body.description, category=body.category, expected_lock_version=body.lock_version, user_id=user.user_id)
        db.commit()
    except template_service.TemplateConflictError as exc:
        db.rollback()
        raise _conflict(user, exc.current_lock_version) from exc
    except ValueError as exc:
        db.rollback()
        raise http_error(user, exc) from exc
    return _component_read(component)


@router.delete("/document-components/{component_id}", status_code=204)
def delete_document_component(component_id: uuid.UUID, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    permissions.require_edit(user)
    component = template_service.get_component(db, user.current_tenant_id, component_id)
    if component is None:
        raise _not_found(user)
    try:
        template_service.delete_component(db, component)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise http_error(user, exc) from exc
    return Response(status_code=204)


__all__ = ["router", "asyncio", "parse_content"]
