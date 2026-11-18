"""Kontext-Freigaben (Plan «Berechtigungen», Phase 5, Migration 0196).

- Organisation › Einstellungen › Datenschutz: Modul-Standards (nur ``settings.manage``).
- «Fotos aus Abgaben»: Bilder, die Kontext-Freigaben dem Konto zeigen (jedes Konto mit Login und
  ``meetings.read`` - wie die Datei-Routen /api/stored-files/*, über die Inhalt und Vorschau laufen).

Der Override je Abgabe-Auftrag läuft über Anlegen/Ändern des Auftrags (``file_visibility``,
api/routes/submission_assignments.py, nur ``submissions.manage``).
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.permissions import P
from app.core.security import CurrentUser, get_current_user, require_permission
from app.models import StoredFile, SubmissionAssignment
from app.services import context_visibility_service as visibility
from app.services.audit_service import AuditService

router = APIRouter()
audit = AuditService()

Module = Literal["abgabe", "protokoll", "album"]
Audience = Literal["role_only", "all_participants", "own_submissions"]
FileFilter = Literal["all", "images"]


class ContextVisibilityModuleRead(BaseModel):
    module: Module
    audience: Audience
    file_filter: FileFilter
    # Protokolle: fest «nur Rolle» (Entwurfsschutz)
    fixed: bool = False
    # Erlaubte Zielgruppen dieses Moduls
    audiences: list[Audience]


class ContextVisibilityWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    audience: Audience
    file_filter: FileFilter


class ContextPhotoRead(BaseModel):
    id: uuid.UUID
    original_name: str
    mime_type: str | None
    created_at: datetime
    assignment_title: str | None
    content_url: str
    thumbnail_url: str


class ContextPhotoPage(BaseModel):
    items: list[ContextPhotoRead]
    total: int


def _audiences(module: str) -> list[str]:
    if module == "protokoll":
        return ["role_only"]
    if module == "album":
        return ["role_only", "all_participants"]
    return list(visibility.AUDIENCES)


def _read_all(db: Session, tenant_id: int) -> list[ContextVisibilityModuleRead]:
    rules = visibility.module_rules(db, tenant_id)
    return [
        ContextVisibilityModuleRead(
            module=module, audience=rules[module].audience, file_filter=rules[module].file_filter,
            fixed=module == "protokoll", audiences=_audiences(module),
        )
        for module in visibility.MODULES
    ]


@router.get("/context-visibility", response_model=list[ContextVisibilityModuleRead])
def get_context_visibility(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    require_permission(user, P.SETTINGS_MANAGE)
    return _read_all(db, user.current_tenant_id)


@router.put("/context-visibility/{module}", response_model=list[ContextVisibilityModuleRead])
def put_context_visibility(
    module: Module, body: ContextVisibilityWrite, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)
):
    require_permission(user, P.SETTINGS_MANAGE)
    try:
        before, after = visibility.set_module_rule(db, user, module, visibility.Rule(body.audience, body.file_filter))
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if before != after:
        audit.log(
            db, action="context_visibility.changed", actor=user, entity_type="tenant", entity_id=user.current_tenant_id,
            details={"module": module, "before": before.as_dict(), "after": after.as_dict()}, commit=False,
        )
    db.commit()
    return _read_all(db, user.current_tenant_id)


@router.get("/context-files/submission-photos", response_model=ContextPhotoPage)
def list_shared_submission_photos(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=60, ge=1, le=200),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """«Fotos aus Abgaben»: nur Bilder, die eine Kontext-Freigabe dem Konto zeigt (unabhängig von
    Rollenrechten - wer photos.read hat, sieht sie ohnehin in der Galerie)."""
    require_permission(user, P.MEETINGS_READ)
    if user.current_tenant_id is None:
        raise HTTPException(status_code=400, detail="No active tenant")
    visible = visibility.visible_files_query(db, user, module="abgabe", only_images=True).subquery()
    total = db.scalar(select(func.count()).select_from(visible)) or 0
    files = db.scalars(
        select(StoredFile).where(StoredFile.id.in_(select(visible.c.id))).order_by(StoredFile.created_at.desc(), StoredFile.id.desc()).offset(skip).limit(limit)
    ).all()
    titles: dict[int, str] = {}
    if files:
        links = visibility.abgabe_links(include_withdrawn=False)
        for file_id, title in db.execute(
            select(links.c.stored_file_id, SubmissionAssignment.title)
            .join(SubmissionAssignment, SubmissionAssignment.id == links.c.assignment_id)
            .where(links.c.stored_file_id.in_([file.id for file in files]), SubmissionAssignment.tenant_id == user.current_tenant_id)
            .order_by(SubmissionAssignment.id)
        ):
            titles.setdefault(file_id, title)
    return ContextPhotoPage(
        total=total,
        items=[
            ContextPhotoRead(
                id=file.public_id, original_name=file.original_name, mime_type=file.mime_type, created_at=file.created_at,
                assignment_title=titles.get(file.id),
                content_url=f"/api/stored-files/{file.public_id}/content",
                thumbnail_url=f"/api/stored-files/{file.public_id}/thumbnail",
            )
            for file in files
        ],
    )
