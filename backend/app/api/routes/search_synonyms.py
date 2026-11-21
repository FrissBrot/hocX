"""Synonymliste der Suche je Mandant (Mandanten-Einstellungen › Suche).

Lesen und Ändern nur mit settings.manage: die Liste ist eine Vereinseinstellung. Die Suche selbst
nutzt die Synonyme serverseitig für jede Person des Mandanten, ohne eigene Berechtigung (sie gibt
nur Treffer zurück, die die Person ohnehin sehen darf)."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.permissions import P
from app.core.security import CurrentUser, get_current_user, require_permission
from app.schemas.search_synonyms import SearchSynonymsRead, SearchSynonymsUpdate
from app.services import search_synonyms
from app.services.audit_service import AuditService

router = APIRouter()
audit = AuditService()


def _read(db: Session, tenant_id: int) -> SearchSynonymsRead:
    return SearchSynonymsRead(
        groups=search_synonyms.list_groups(db, tenant_id),
        builtin=[list(group) for group in search_synonyms.builtin_groups_display()],
    )


@router.get("/search-synonyms", response_model=SearchSynonymsRead)
def get_search_synonyms(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    require_permission(user, P.SETTINGS_MANAGE)
    if user.current_tenant_id is None:
        raise HTTPException(status_code=400, detail="No active tenant")
    return _read(db, user.current_tenant_id)


@router.put("/search-synonyms", response_model=SearchSynonymsRead)
def put_search_synonyms(
    payload: SearchSynonymsUpdate, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)
):
    require_permission(user, P.SETTINGS_MANAGE)
    if user.current_tenant_id is None:
        raise HTTPException(status_code=400, detail="No active tenant")
    try:
        saved = search_synonyms.replace_groups(db, user.current_tenant_id, payload.groups)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    audit.log(
        db, action="tenant.search_synonyms_updated", actor=user, entity_type="tenant",
        entity_id=user.current_tenant_id, details={"groups": len(saved)}, commit=False,
    )
    db.commit()
    return _read(db, user.current_tenant_id)
