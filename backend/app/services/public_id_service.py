"""Central translation layer between internal BIGINT primary keys and the public
UUIDv7 `public_id` every entity table now also carries (see alembic migrations
0065-0068 and the public_id column added to every model in app/models/entities.py).

Kept as one small explicit helper rather than SQLAlchemy relationship()-based
auto-resolution, matching this codebase's existing style: repositories and schemas are
hand-written per entity, not built on shared ORM/base-class magic.

Callers at the API boundary MUST scope every public_id lookup supplied by a client to the
current tenant - a bare public_id lookup would let a valid UUID from one tenant read/act
on another tenant's row (public_id is unguessable but is not itself an authorization
check). Two cases:

- The model has its own tenant_id column (Protocol, Event, Template, StoredFile,
  ProtocolTodo, ...): pass tenant_id= here and it's filtered in the same query.
- The model is only transitively tenant-scoped through a parent FK (ProtocolElement,
  ProtocolElementBlock, ProtocolImage, ProtocolText, ProtocolDisplaySnapshot, ...):
  tenant_id= here is a no-op (the column doesn't exist), so the caller must still run
  the existing app.repositories.access_repository lookups (tenant_id_for_protocol,
  protocol_id_for_block, tenant_id_for_stored_file, ...) on the resolved internal id,
  exactly as routers already do today for the numeric-id path params these replace.

  (security-audit TEN-02, 2026-09-30: StoredFile/ProtocolTodo used to be transitively
  scoped and are listed as such in some older callers' comments - both gained their own
  tenant_id column since. Check app/models/entities.py before assuming either list.)
"""

from __future__ import annotations

import uuid
from typing import TypeVar

from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.db.base import Base

ModelT = TypeVar("ModelT", bound=Base)

# Zuordnung interne ID -> public_id je Session (also je Request). Sie ändert sich nie, deshalb darf
# sie die ganze Session über gelten. Ohne Cache lud resolve_public_id für jede Zeile einer Liste
# dasselbe Objekt neu (die Identity-Map hält Objekte nur schwach - das per db.get geladene Objekt
# war gleich wieder weg): 20 Protokolle eines Mandanten = 20 identische Abfragen nach Mandant und
# Vorlage. Fehlende Zeilen werden nicht gemerkt (könnten später in der Session entstehen).
_CACHE_KEY = "public_id_cache"


def _cache(db: Session) -> dict[tuple[type, int], uuid.UUID]:
    return db.info.setdefault(_CACHE_KEY, {})


@event.listens_for(Session, "after_rollback")
def _forget_after_rollback(session: Session) -> None:
    # Nach einem Rollback könnten gemerkte Zeilen nie existiert haben.
    session.info.pop(_CACHE_KEY, None)


def get_by_public_id(
    db: Session,
    model: type[ModelT],
    public_id: uuid.UUID,
    *,
    tenant_id: int | None = None,
) -> ModelT | None:
    """Look up a single row by its public_id. Pass tenant_id whenever the public_id came
    from a client request - see module docstring."""
    statement = select(model).where(model.public_id == public_id)  # type: ignore[attr-defined]
    if tenant_id is not None and hasattr(model, "tenant_id"):
        statement = statement.where(model.tenant_id == tenant_id)  # type: ignore[attr-defined]
    return db.scalars(statement).first()


def resolve_internal_id(
    db: Session,
    model: type[ModelT],
    public_id: uuid.UUID,
    *,
    tenant_id: int | None = None,
) -> int | None:
    """Like get_by_public_id, but returns just the internal id - the common case at the
    top of a route handler that immediately needs the numeric id for further queries."""
    row = get_by_public_id(db, model, public_id, tenant_id=tenant_id)
    return row.id if row is not None else None  # type: ignore[attr-defined]


def resolve_public_id(db: Session, model: type[ModelT], internal_id: int) -> uuid.UUID | None:
    """Translate a single internal FK int into its public_id, for embedding a related
    entity's id in a response schema. For lists, prefer resolve_public_ids() to avoid
    one query per row."""
    cache = _cache(db)
    key = (model, internal_id)
    if key in cache:
        return cache[key]
    row = db.get(model, internal_id)
    public_id = row.public_id if row is not None else None  # type: ignore[attr-defined]
    if public_id is not None:
        cache[key] = public_id
    return public_id


def resolve_internal_ids(
    db: Session,
    model: type[ModelT],
    public_ids: list[uuid.UUID],
    *,
    tenant_id: int | None = None,
) -> dict[uuid.UUID, int]:
    """Batch variant of resolve_internal_id - one query for a whole list of client-
    supplied public ids instead of one per id. Pass tenant_id whenever the ids came from
    a client request (see module docstring). Ids not found (or not owned by tenant_id)
    are simply absent from the returned dict - callers use that to reject unknown/foreign
    ids the same way a single resolve_internal_id() miss would."""
    unique_ids = {i for i in public_ids if i is not None}
    if not unique_ids:
        return {}
    statement = select(model.public_id, model.id).where(model.public_id.in_(unique_ids))  # type: ignore[attr-defined]
    if tenant_id is not None and hasattr(model, "tenant_id"):
        statement = statement.where(model.tenant_id == tenant_id)  # type: ignore[attr-defined]
    return dict(db.execute(statement).all())


def resolve_public_ids(db: Session, model: type[ModelT], internal_ids: list[int]) -> dict[int, uuid.UUID]:
    """Batch variant of resolve_public_id - one query for a whole list/page of rows
    instead of N+1. Ids not found (or None) are simply absent from the returned dict."""
    cache = _cache(db)
    unique_ids = {i for i in internal_ids if i is not None}
    missing = {i for i in unique_ids if (model, i) not in cache}
    if missing:
        statement = select(model.id, model.public_id).where(model.id.in_(missing))  # type: ignore[attr-defined]
        for internal_id, public_id in db.execute(statement).all():
            cache[(model, internal_id)] = public_id
    return {i: cache[(model, i)] for i in unique_ids if (model, i) in cache}


def prime_public_ids(db: Session, model: type[ModelT], internal_ids) -> None:
    """Lädt die public_ids einer ganzen Liste mit einer Abfrage in den Session-Cache, damit die
    anschliessende Umwandlung Zeile für Zeile (resolve_public_id, PublicIdModel) keine weitere
    Abfrage braucht."""
    resolve_public_ids(db, model, list(internal_ids))
