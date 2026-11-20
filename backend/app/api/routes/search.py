"""Globale Suche (Ctrl+K im Frontend, components/search/global-search.tsx).

Menüs und Einstellungen sucht das Frontend selbst (aus der Navigation, ohne Server). Hier nur, was
in der Datenbank steht - und nur Gruppen, deren Seite die Person auch öffnen darf:
- Personen mit participants.manage (Seite /participants),
- Dateien und Fotos mit files.manage (Seiten /files, /photos), über dieselbe Abfrage wie die
  Dateiliste (FileService.list_tenant_files) und damit mit derselben Mandantentrennung,
- Elemente der Bibliothek und ihre Blöcke mit templates.edit (Seite /elements).
Rollen sucht das Frontend selbst (GET /api/roles, übersetzte Namen der Standardrollen).
POST statt GET, obwohl nur gelesen wird: der Suchtext (oft ein Personenname) gehört nicht in
Adresszeile und Zugriffslogs. Rate-Limit je Konto, weil das Frontend beim Tippen (verzögert)
abfragt.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.permissions import P
from app.core.rate_limit import enforce_rate_limit
from app.core.security import CurrentUser, get_current_user, require_any_permission
from app.models.entities import ElementDefinition, Participant
from app.schemas.search import GlobalSearchQuery, GlobalSearchRead, SearchBlock, SearchElement, SearchFile, SearchPerson
from app.services.file_service import FileService
from app.services import context_visibility_service
from app.core.sql_like import contains_pattern

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
    return contains_pattern(fold_text(query))


def search_people(db: Session, tenant_id: int, query: str, limit: int = GROUP_LIMIT, *, by_email: bool = True) -> list[SearchPerson]:
    """by_email=False ohne participants.contacts: sonst verriete ein Treffer die Adresse."""
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
                *([_fold(func.coalesce(Participant.email, "")).like(pattern, escape="\\")] if by_email else []),
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


def search_files(
    db: Session, tenant_id: int, query: str, limit: int = GROUP_LIMIT, *, documents: bool = True, images: bool = True,
    readable_assignment_ids: set[int] | None = None,
) -> list[SearchFile]:
    """Dokumente nur mit files.read, Fotos nur mit photos.read (getrennte Rechte, Phase 3);
    Abgabe-Dateien nur aus lesbaren Aufträgen (Reichweite «nur zugewiesene», Phase 4/5)."""
    service = FileService()
    # Beste Treffer zuerst (tolerante Fotosuche, services/photo_search.py)
    scope = {"readable_assignment_ids": readable_assignment_ids, "sort_by": "relevance"}
    document_items = service.list_tenant_files(db, tenant_id, limit=limit, exclude_images=True, search=query, **scope) if documents else []
    image_items = service.list_tenant_files(db, tenant_id, limit=limit, only_images=True, search=query, **scope) if images else []
    return [
        SearchFile(id=item.id, name=item.original_name, is_image=item.is_image, context=item.origin_tag or item.ref_label or "")
        for item in [*document_items, *image_items]
    ]


def search_elements(db: Session, tenant_id: int, query: str, limit: int = GROUP_LIMIT) -> list[SearchElement]:
    pattern = _like_pattern(query)
    title = _fold(ElementDefinition.title)
    rows = db.execute(
        select(ElementDefinition.public_id, ElementDefinition.title, ElementDefinition.display_title, ElementDefinition.description)
        .where(
            ElementDefinition.tenant_id == tenant_id,
            ElementDefinition.is_library.is_(True),
            ElementDefinition.is_active.is_(True),
            or_(
                title.like(pattern, escape="\\"),
                _fold(func.coalesce(ElementDefinition.display_title, "")).like(pattern, escape="\\"),
                _fold(func.coalesce(ElementDefinition.description, "")).like(pattern, escape="\\"),
            ),
        )
        .order_by(title.like(pattern[1:], escape="\\").desc(), ElementDefinition.title.asc(), ElementDefinition.id.asc())
        .limit(limit)
    ).all()
    return [SearchElement(id=row.public_id, title=row.display_title or row.title, description=row.description) for row in rows]


# Blöcke stehen als JSON-Liste in configuration_json.blocks (Titel, Blocktitel). Nur gebundene
# Parameter; die Faltung entspricht _fold.
_BLOCK_SQL = text(
    """
    SELECT ed.public_id AS element_id, COALESCE(NULLIF(ed.display_title, ''), ed.title) AS element_title,
           (block ->> 'id') AS block_id,
           COALESCE(NULLIF(block ->> 'title', ''), NULLIF(block ->> 'block_title', ''), '') AS title
    FROM element_definition ed
    CROSS JOIN LATERAL jsonb_array_elements(
        CASE WHEN jsonb_typeof(ed.configuration_json -> 'blocks') = 'array' THEN ed.configuration_json -> 'blocks' ELSE '[]'::jsonb END
    ) AS block
    WHERE ed.tenant_id = :tenant_id AND ed.is_library AND ed.is_active
      AND (block ->> 'id') ~ '^[0-9]+$'
      AND (translate(lower(COALESCE(block ->> 'title', '')), :accents_from, :accents_to) LIKE :pattern ESCAPE '\\'
           OR translate(lower(COALESCE(block ->> 'block_title', '')), :accents_from, :accents_to) LIKE :pattern ESCAPE '\\')
    ORDER BY ed.title, ed.id, (block ->> 'id')
    LIMIT :limit
    """
)


def search_blocks(db: Session, tenant_id: int, query: str, limit: int = GROUP_LIMIT) -> list[SearchBlock]:
    rows = db.execute(
        _BLOCK_SQL,
        {"tenant_id": tenant_id, "pattern": _like_pattern(query), "accents_from": _ACCENTS_FROM, "accents_to": _ACCENTS_TO, "limit": limit},
    ).all()
    return [
        SearchBlock(element_id=row.element_id, element_title=row.element_title, block_id=int(row.block_id), title=row.title or row.element_title)
        for row in rows
    ]


def _without_contacts(people: list[SearchPerson], user: CurrentUser) -> list[SearchPerson]:
    """E-Mail-Adressen nur mit participants.contacts (Plan «Berechtigungen», Phase 3)."""
    if user.can(P.PARTICIPANTS_CONTACTS):
        return people
    return [person.model_copy(update={"email": None}) for person in people]


@router.post("/search", response_model=GlobalSearchRead)
def global_search(
    payload: GlobalSearchQuery,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_any_permission(user, P.PARTICIPANTS_READ, P.FILES_READ, P.PHOTOS_READ, P.TEMPLATES_EDIT)
    tenant_id = user.current_tenant_id
    if tenant_id is None:
        raise HTTPException(status_code=400, detail="No active tenant")
    enforce_rate_limit(f"global-search:{user.user_id}", limit=120, period_seconds=60)
    query = " ".join(payload.q.split())
    if len(query) < 2:
        return GlobalSearchRead(people=[], files=[])
    templates = user.can(P.TEMPLATES_EDIT)
    return GlobalSearchRead(
        people=_without_contacts(search_people(db, tenant_id, query, by_email=user.can(P.PARTICIPANTS_CONTACTS)), user) if user.can(P.PARTICIPANTS_READ) else [],
        files=(
            search_files(
                db, tenant_id, query, documents=user.can(P.FILES_READ), images=user.can(P.PHOTOS_READ),
                readable_assignment_ids=context_visibility_service.readable_assignment_ids(db, user),
            )
            if user.can(P.FILES_READ) or user.can(P.PHOTOS_READ) else []
        ),
        elements=search_elements(db, tenant_id, query) if templates else [],
        blocks=search_blocks(db, tenant_id, query) if templates else [],
    )
