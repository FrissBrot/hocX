"""Globale Suche (Ctrl+K im Frontend, components/search/global-search.tsx).

Menüs und Einstellungen sucht das Frontend selbst (aus der Navigation, ohne Server). Hier nur, was
in der Datenbank steht - und nur Gruppen, deren Seite die Person auch öffnen darf:
- Personen mit participants.manage (Seite /participants),
- Dateien und Fotos mit files.manage (Seiten /files, /photos), über dieselbe Abfrage wie die
  Dateiliste (FileService.list_tenant_files) und damit mit derselben Mandantentrennung.
POST statt GET, obwohl nur gelesen wird: der Suchtext (oft ein Personenname) gehört nicht in
Adresszeile und Zugriffslogs. Rate-Limit je Konto, weil das Frontend beim Tippen (verzögert)
abfragt.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.permissions import P
from app.core.rate_limit import enforce_rate_limit
from app.core.security import CurrentUser, get_current_user, require_any_permission
from app.models.entities import Participant
from app.schemas.search import GlobalSearchQuery, GlobalSearchRead, SearchFile, SearchPerson
from app.services.file_service import FileService

router = APIRouter()

GROUP_LIMIT = 5
# Umlaute und Akzente gleich behandeln («Mueller» findet nicht «Müller», aber «muller» und
# «müller» finden beide): beide Seiten klein schreiben und Zeichen mit Akzent ersetzen.
_ACCENTS_FROM = "äöüàâáéèêëíìîïóòôúùûçñß"
_ACCENTS_TO = "aouaaaeeeeiiiiooouuucns"


def _fold(column):
    return func.translate(func.lower(column), _ACCENTS_FROM, _ACCENTS_TO)


def fold_text(value: str) -> str:
    """Gleiche Faltung wie _fold, für den Suchbegriff (in Python)."""
    return value.lower().translate(str.maketrans(_ACCENTS_FROM, _ACCENTS_TO))


def _like_pattern(query: str) -> str:
    # % und _ aus der Eingabe sind Text, keine Platzhalter
    escaped = fold_text(query).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def search_people(db: Session, tenant_id: int, query: str, limit: int = GROUP_LIMIT) -> list[SearchPerson]:
    pattern = _like_pattern(query)
    prefix = _like_pattern(query)[1:]  # «beginnt mit» zuerst
    name = _fold(Participant.display_name)
    rows = db.execute(
        select(Participant.public_id, Participant.display_name, Participant.email, Participant.is_active)
        .where(
            Participant.tenant_id == tenant_id,
            or_(
                name.like(pattern, escape="\\"),
                _fold(func.coalesce(Participant.first_name, "")).like(pattern, escape="\\"),
                _fold(func.coalesce(Participant.last_name, "")).like(pattern, escape="\\"),
                _fold(func.coalesce(Participant.email, "")).like(pattern, escape="\\"),
            ),
        )
        .order_by(
            Participant.is_active.desc(),
            name.like(prefix, escape="\\").desc(),
            Participant.display_name.asc(),
            Participant.id.asc(),
        )
        .limit(limit)
    ).all()
    return [SearchPerson(id=row.public_id, name=row.display_name, email=row.email, is_active=row.is_active) for row in rows]


def search_files(db: Session, tenant_id: int, query: str, limit: int = GROUP_LIMIT) -> list[SearchFile]:
    service = FileService()
    documents = service.list_tenant_files(db, tenant_id, limit=limit, exclude_images=True, search=query)
    images = service.list_tenant_files(db, tenant_id, limit=limit, only_images=True, search=query)
    return [
        SearchFile(id=item.id, name=item.original_name, is_image=item.is_image, context=item.origin_tag or item.ref_label or "")
        for item in [*documents, *images]
    ]


@router.post("/search", response_model=GlobalSearchRead)
def global_search(
    payload: GlobalSearchQuery,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_any_permission(user, P.PARTICIPANTS_MANAGE, P.FILES_MANAGE)
    tenant_id = user.current_tenant_id
    if tenant_id is None:
        raise HTTPException(status_code=400, detail="No active tenant")
    enforce_rate_limit(f"global-search:{user.user_id}", limit=120, period_seconds=60)
    query = " ".join(payload.q.split())
    if len(query) < 2:
        return GlobalSearchRead(people=[], files=[])
    return GlobalSearchRead(
        people=search_people(db, tenant_id, query) if user.can(P.PARTICIPANTS_MANAGE) else [],
        files=search_files(db, tenant_id, query) if user.can(P.FILES_MANAGE) else [],
    )
