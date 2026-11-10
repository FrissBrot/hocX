"""Adminportal: Systemvorlagen des Document Studio verwalten (Plattform-Admins).

Der Inhalt der Systemvorlagen kommt aus dem Code (app/documents/system_templates.py) und wird
beim Start synchronisiert. Plattform-Admins steuern, welche Systemvorlagen Mandanten angeboten
werden (archivieren/reaktivieren) und welche je Dokumenttyp der Plattform-Standard ist.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.admin_security import CurrentAdmin, get_current_admin, require_admin_write
from app.core.db import get_db
from app.documents import template_service
from app.models import DocumentExport, DocumentTemplate, DocumentTemplateRevision
from app.services.audit_service import AuditService

router = APIRouter()
audit = AuditService()


class SystemTemplateRead(BaseModel):
    id: uuid.UUID
    system_key: str | None
    name: str
    description: str | None
    document_type: str
    variant: str | None
    status: str
    is_platform_default: bool
    revision: int | None
    published_at: datetime | None
    copies: int
    exports: int


def _read(db: Session, template: DocumentTemplate) -> SystemTemplateRead:
    revision = db.get(DocumentTemplateRevision, template.published_revision_id) if template.published_revision_id else None
    return SystemTemplateRead(
        id=template.public_id,
        system_key=template.system_key,
        name=template.name,
        description=template.description,
        document_type=template.document_type,
        variant=template.variant,
        status=template.status,
        is_platform_default=template.is_platform_default,
        revision=revision.revision_no if revision else None,
        published_at=revision.published_at if revision else None,
        copies=db.scalar(select(func.count(DocumentTemplate.id)).where(DocumentTemplate.source_template_id == template.id)) or 0,
        exports=db.scalar(select(func.count(DocumentExport.id)).where(DocumentExport.template_id == template.id)) or 0,
    )


def _system_or_404(db: Session, template_id: uuid.UUID) -> DocumentTemplate:
    template = template_service.get_template(db, None, template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="Systemvorlage nicht gefunden")
    return template


@router.get("/document-templates", response_model=list[SystemTemplateRead])
def list_system_templates(db: Session = Depends(get_db), admin: CurrentAdmin = Depends(get_current_admin)):
    rows = db.scalars(select(DocumentTemplate).where(DocumentTemplate.tenant_id.is_(None)).order_by(DocumentTemplate.document_type, DocumentTemplate.sort_index))
    return [_read(db, row) for row in rows]


class StatusBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    archived: bool


@router.post("/document-templates/{template_id}/archive", response_model=SystemTemplateRead)
def archive_system_template(template_id: uuid.UUID, body: StatusBody, db: Session = Depends(get_db), admin: CurrentAdmin = Depends(require_admin_write)):
    template = _system_or_404(db, template_id)
    if body.archived and template.is_platform_default:
        raise HTTPException(status_code=422, detail="Der Plattform-Standard kann nicht archiviert werden")
    template_service.set_archived(db, template, body.archived, user_id=None)
    db.commit()
    audit.log(db, action="admin.document_template.archive" if body.archived else "admin.document_template.unarchive", actor_email=admin.email, details={"system_key": template.system_key})
    return _read(db, template)


@router.post("/document-templates/{template_id}/platform-default", response_model=SystemTemplateRead)
def set_platform_default(template_id: uuid.UUID, db: Session = Depends(get_db), admin: CurrentAdmin = Depends(require_admin_write)):
    template = _system_or_404(db, template_id)
    if template.status != "active":
        raise HTTPException(status_code=422, detail="Archivierte Vorlagen können nicht Standard sein")
    template_service.clear_platform_default(db, template.document_type)
    template.is_platform_default = True
    db.commit()
    audit.log(db, action="admin.document_template.platform_default", actor_email=admin.email, details={"system_key": template.system_key, "document_type": template.document_type})
    return _read(db, template)
