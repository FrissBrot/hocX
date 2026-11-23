from __future__ import annotations

import uuid
from typing import Annotated, Literal

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.schemas.base import MAX_QUERY_OFFSET
from app.core.db import get_db
from app.core.permissions import P
from app.core.security import CurrentUser, get_current_user, require_feature, require_permission
from app.models.entities import AttendanceFine, Participant, Protocol
from app.repositories.fines_repository import DuplicateFineError, FineDeleteError, FinesRepository
from app.schemas.fines import (
    AttendanceFineCreate,
    AttendanceFineListItem,
    AttendanceFineRead,
    CollectFinePayload,
    DeleteFinePayload,
    FineTariffRead,
    FineTariffUpdate,
    OpenFinesSummary,
)
from app.services import fine_tariff_service, public_id_service
from app.services.access_service import AccessService
from app.services.audit_service import AuditService

router = APIRouter()
repo = FinesRepository()
audit = AuditService()
access_service = AccessService()


@router.get("/fines", response_model=list[AttendanceFineListItem])
def list_fines(
    skip: int = Query(default=0, ge=0, le=MAX_QUERY_OFFSET),
    # 500 wie fetchAllPages im Frontend (Mobile lädt alle Seiten; mit le=200 kam 422)
    limit: int = Query(default=50, ge=1, le=500),
    # Annotated statt Query-Default: direkte Aufrufe (Tests) bekommen None statt eines Query-Objekts
    fine_status: Annotated[Literal["pending", "collected", "deleted"] | None, Query(alias="status")] = None,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Ohne reports.personal nur die eigenen Bussen (eigene Daten, keine Permission nötig).
    Reine Leseroute: bleibt nach einem Downgrade («nur lesen») erreichbar (write=False).

    Mit reports.personal alle Bussen des Mandanten; ändern nur mit finances.manage (unten).
    """
    require_feature(user, "finance", write=False)
    if not user.can(P.REPORTS_PERSONAL):
        return repo.list_fines_for_user(db, user.current_tenant_id, user.user_id, skip=skip, limit=limit, status=fine_status)
    return repo.list_fines_for_tenant(db, user.current_tenant_id, skip=skip, limit=limit, status=fine_status)


@router.get("/fines/open-summary", response_model=OpenFinesSummary)
def open_fines_summary(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Summe der offenen Bussen je Währung (Dashboard). Gleiche Sichtbarkeit wie GET /fines:
    ohne reports.personal nur die eigenen. Reine Leseroute (auch im Nur-Lesen-Zustand)."""
    require_feature(user, "finance", write=False)
    own_only = not user.can(P.REPORTS_PERSONAL)
    summary = repo.open_fines_summary(db, user.current_tenant_id, user_id=user.user_id if own_only else None)
    return OpenFinesSummary(**summary, own_only=own_only)


def _readable_protocol_id(db: Session, protocol_id: uuid.UUID, user: CurrentUser) -> int | None:
    """Protokoll für Bussen-Routen: Mandant plus dieselben Ressourcenregeln wie beim Lesen des
    Protokolls (access_service.can_read_protocol: Entwürfe nur mit meetings.read_drafts,
    eingeschränkte Leser nur zugeordnete, ohne meetings.read keines). Vorher genügte der
    Mandant: wer Bussen sehen (reports.personal) oder verwalten (fines.manage) darf, las und
    schrieb so Bussen von Entwürfen bzw. nicht zugeordneten Protokollen, die er nicht öffnen darf.

    Schreiben ist strenger: die Schreibrouten prüfen vorher fines.manage, das Repository nimmt
    nur offene Protokolle an. Fremd, nicht lesbar und nicht vorhanden ergeben dieselbe 404
    (kein Existenz-Orakel, SECURITY-RULES 1.6)."""
    internal_id = public_id_service.resolve_internal_id(db, Protocol, protocol_id, tenant_id=user.current_tenant_id)
    if internal_id is None or not access_service.can_read_protocol(db, user, internal_id):
        return None
    return internal_id


def _resolve_protocol_id(db: Session, protocol_id: uuid.UUID, user: CurrentUser) -> int:
    internal_id = _readable_protocol_id(db, protocol_id, user)
    if internal_id is None:
        raise HTTPException(status_code=404, detail="Protocol not found")
    return internal_id


def _resolve_fine_id(db: Session, fine_id: uuid.UUID, user: CurrentUser) -> int:
    # AttendanceFine hat keine eigene tenant_id (tenant_id= an public_id_service wäre wirkungslos):
    # über das Ursprungsprotokoll auf den eigenen Mandanten einschränken. Vorher lieferte eine
    # fremde Busse eine andere 404-Meldung als eine unbekannte ID (Existenz-Orakel,
    # SECURITY-RULES 1.6); die Repository-Methoden prüfen den Mandanten zusätzlich selbst.
    row = db.execute(
        select(AttendanceFine.id, AttendanceFine.protocol_id)
        .join(Protocol, Protocol.id == AttendanceFine.protocol_id)
        .where(AttendanceFine.public_id == fine_id, Protocol.tenant_id == user.current_tenant_id)
    ).one_or_none()
    # Wie _readable_protocol_id: Bussen eines Protokolls, das der Benutzer nicht lesen darf
    # (Entwurf ohne meetings.read_drafts, nicht zugeordnet), gelten als unbekannt
    if row is None or not access_service.can_read_protocol(db, user, row.protocol_id):
        raise HTTPException(status_code=404, detail="Fine not found")
    return row.id


@router.get("/fines/tariff", response_model=FineTariffRead)
def get_fine_tariff(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Zentraler Bussentarif des Mandanten (Konto + Beträge für «zu spät»/«abwesend»)."""
    require_permission(user, P.MEETINGS_READ)
    require_feature(user, "finance", write=False)
    return fine_tariff_service.read_tariff(db, user.current_tenant_id)


@router.put("/fines/tariff", response_model=FineTariffRead)
def update_fine_tariff(
    payload: FineTariffUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_permission(user, P.FINES_MANAGE)
    require_feature(user, "finance")
    try:
        result = fine_tariff_service.update_tariff(db, user.current_tenant_id, payload)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    audit.log(
        db, action="fine_tariff.updated", actor=user, entity_type="fine_tariff", entity_id=user.current_tenant_id,
        details={"amount_late": float(result.amount_late), "amount_absent": float(result.amount_absent)},
    )
    return result


@router.get("/protocols/{protocol_id}/pending-fines", response_model=list[AttendanceFineListItem])
def list_pending_fines(
    protocol_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_permission(user, P.REPORTS_PERSONAL)
    require_feature(user, "finance", write=False)
    internal_id = _resolve_protocol_id(db, protocol_id, user)
    return repo.list_pending_fines_for_protocol(db, internal_id, user.current_tenant_id)


@router.get("/protocols/{protocol_id}/fines", response_model=list[AttendanceFineRead])
def list_protocol_fines(
    protocol_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_permission(user, P.REPORTS_PERSONAL)
    require_feature(user, "finance", write=False)
    internal_id = _resolve_protocol_id(db, protocol_id, user)
    return repo.list_fines_for_protocol(db, internal_id, user.current_tenant_id)


@router.post("/fines", response_model=AttendanceFineRead, status_code=status.HTTP_201_CREATED)
def create_fine(
    payload: AttendanceFineCreate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_permission(user, P.FINES_MANAGE)
    # Gleiche 404 wie die Repository-Prüfung unten (Mandant, abgeschlossen)
    if _readable_protocol_id(db, payload.protocol_id, user) is None:
        raise HTTPException(status_code=404, detail="Protocol, account or participant not found")
    if payload.use_tariff:
        # Betrag nach Tarif der Person (0172); 0 = für diese Person keine Busse (204, nichts angelegt)
        protocol = public_id_service.get_by_public_id(db, Protocol, payload.protocol_id, tenant_id=user.current_tenant_id)
        if protocol is None:
            raise HTTPException(status_code=404, detail="Protocol, account or participant not found")
        participant_id = (
            public_id_service.resolve_internal_id(db, Participant, payload.participant_id, tenant_id=user.current_tenant_id)
            if payload.participant_id is not None else None
        )
        amount = fine_tariff_service.amount_for_participant(db, user.current_tenant_id, protocol.template_id, participant_id, payload.fine_type)
        if amount <= 0:
            return Response(status_code=status.HTTP_204_NO_CONTENT)
        payload = payload.model_copy(update={"amount": amount})
    try:
        result = repo.create_fine(db, payload, user.current_tenant_id)
    except DuplicateFineError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Fine could not be created") from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Protocol, account or participant not found")
    result_internal_id = public_id_service.resolve_internal_id(db, AttendanceFine, result.id)
    audit.log(
        db, action="fine.created", actor=user, entity_type="attendance_fine", entity_id=result_internal_id,
        details={"protocol_id": str(result.protocol_id), "amount": float(result.amount), "fine_type": result.fine_type},
    )
    return result


@router.delete("/fines/{fine_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_fine(
    fine_id: uuid.UUID,
    payload: DeleteFinePayload | None = None,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Offene Busse löschen. Im offenen Ursprungsprotokoll hart, sonst mit Begründung
    (Status `deleted`, aufgeführt im Protokoll `protocol_id` bzw. im nächsten offenen)."""
    require_permission(user, P.FINES_MANAGE)
    internal_id = _resolve_fine_id(db, fine_id, user)
    payload = payload or DeleteFinePayload()
    protocol_context_id = None
    if payload.protocol_id is not None:
        protocol_context_id = _resolve_protocol_id(db, payload.protocol_id, user)
    try:
        outcome = repo.delete_fine(
            db, internal_id, user.current_tenant_id,
            actor_user_id=user.user_id, reason=payload.reason, protocol_context_id=protocol_context_id,
        )
    except FineDeleteError as exc:
        db.rollback()
        status_code = 422 if exc.code == "reason_required" else 409
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Fine could not be deleted") from exc
    if outcome is None:
        raise HTTPException(status_code=404, detail="Fine not found or already collected")
    if outcome == "soft":
        audit.log(
            db, action="fine.deleted_with_reason", actor=user, entity_type="attendance_fine", entity_id=internal_id,
            details={"reason": (payload.reason or "").strip()},
        )
    else:
        audit.log(db, action="fine.deleted", actor=user, entity_type="attendance_fine", entity_id=internal_id)


@router.post("/fines/{fine_id}/restore", response_model=AttendanceFineRead)
def restore_fine(
    fine_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_permission(user, P.FINES_MANAGE)
    internal_id = _resolve_fine_id(db, fine_id, user)
    try:
        result = repo.restore_fine(db, internal_id, user.current_tenant_id)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Fine could not be restored") from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Fine not found, not deleted or already finalized")
    audit.log(db, action="fine.restored", actor=user, entity_type="attendance_fine", entity_id=internal_id)
    return result


@router.post("/fines/{fine_id}/collect", response_model=AttendanceFineRead)
def collect_fine(
    fine_id: uuid.UUID,
    payload: CollectFinePayload = CollectFinePayload(),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_permission(user, P.FINES_MANAGE)
    internal_id = _resolve_fine_id(db, fine_id, user)
    collecting_protocol_internal_id = None
    if payload.collecting_protocol_id is not None:
        collecting_protocol_internal_id = _resolve_protocol_id(db, payload.collecting_protocol_id, user)
    try:
        result = repo.collect_fine(db, internal_id, user.current_tenant_id, user.user_id, collecting_protocol_internal_id)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Fine could not be collected") from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Fine not found or already collected")
    audit.log(db, action="fine.collected", actor=user, entity_type="attendance_fine", entity_id=internal_id)
    return result


@router.post("/fines/{fine_id}/reopen", response_model=AttendanceFineRead)
def reopen_fine(
    fine_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_permission(user, P.FINES_MANAGE)
    internal_id = _resolve_fine_id(db, fine_id, user)
    try:
        result = repo.reopen_fine(db, internal_id, user.current_tenant_id)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Fine could not be reopened") from exc
    if result is None:
        raise HTTPException(
            status_code=404,
            detail="Fine not found, not collected, or already finalized in its protocol",
        )
    audit.log(db, action="fine.reopened", actor=user, entity_type="attendance_fine", entity_id=internal_id)
    return result
