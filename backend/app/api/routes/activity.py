"""Verlauf eines Mandanten (Mandanten-Einstellungen → Verlauf, Datenschutz-Audit PRIV-013).

Mandanten-Admins sehen, was in ihrem Verein geändert, gelöscht oder exportiert wurde, wer sich
angemeldet hat (auch Fehlversuche) und wann die Plattform-Administration auf Daten des Vereins
zugegriffen hat. Keine IP-Hashes, keine E-Mail-Adressen; Plattform-Admins erscheinen als
"Plattform", Personen mit ihrem aktuellen Anzeigenamen (gelöschte Personen ohne Namen).
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.schemas.base import MAX_QUERY_OFFSET
from app.core.db import get_db
from app.core.permissions import P
from app.core.security import CurrentUser, get_current_user, require_permission

router = APIRouter()

# Optionale Filter als gebundene Parameter (NULL = kein Filter). Tage in Schweizer Zeit.
# Wer: eine Person (public_id) oder eine Art ohne Person (Plattform, System, gelöschte Person) -
# dieselbe Einteilung wie _actor_kind.
_FILTERS = """
              AND (CAST(:category AS text) IS NULL OR split_part(l.action, '.', 1) = :category)
              AND (CAST(:action AS text) IS NULL OR l.action = :action)
              AND (CAST(:outcome AS text) IS NULL OR l.outcome = :outcome)
              AND (CAST(:date_from AS date) IS NULL OR (l.created_at AT TIME ZONE 'Europe/Zurich')::date >= :date_from)
              AND (CAST(:date_to AS date) IS NULL OR (l.created_at AT TIME ZONE 'Europe/Zurich')::date <= :date_to)
              AND (CAST(:actor_user AS uuid) IS NULL OR u.public_id = :actor_user)
              AND (CAST(:actor_kind AS text) IS NULL
                   OR (:actor_kind = 'deleted' AND l.actor_user_id IS NOT NULL AND u.id IS NULL)
                   OR (:actor_kind = 'platform' AND l.actor_user_id IS NULL AND (l.action LIKE 'admin.%' OR l.actor_email IS NOT NULL))
                   OR (:actor_kind = 'system' AND l.actor_user_id IS NULL AND l.action NOT LIKE 'admin.%' AND l.actor_email IS NULL))"""

_FROM = """
            FROM audit_log l
            LEFT JOIN app_user u ON u.id = l.actor_user_id AND u.tenant_id = l.tenant_id
            WHERE l.tenant_id = :tenant_id"""


class ActivityEntry(BaseModel):
    created_at: datetime
    action: str
    category: str
    outcome: Literal["success", "failure"]
    actor_kind: Literal["user", "platform", "system", "deleted"]
    actor_name: str | None = None
    entity_type: str | None = None


class ActivityActor(BaseModel):
    """Auswahl im Filter «Von»: key = public_id einer Person oder platform/system/deleted."""

    key: str
    kind: Literal["user", "platform", "system", "deleted"]
    name: str | None = None


class ActivityPage(BaseModel):
    items: list[ActivityEntry]
    total: int
    categories: list[str]
    # Auswahllisten für die Spaltenfilter (alles, was im Verlauf dieses Vereins vorkommt)
    actions: list[str] = []
    actors: list[ActivityActor] = []


def _actor_kind(actor_user_id: int | None, actor_name: str | None, actor_email: str | None, action: str) -> str:
    if actor_user_id is not None:
        return "user" if actor_name is not None else "deleted"
    if action.startswith("admin.") or actor_email:
        return "platform"
    return "system"


@router.get("/activity", response_model=ActivityPage)
def list_activity(
    category: str | None = Query(default=None, max_length=60),
    action: str | None = Query(default=None, max_length=120),
    outcome: Literal["success", "failure"] | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    actor: str | None = Query(default=None, max_length=60),
    # Auswahllisten (Vorgänge, Personen) nur bei Bedarf: das Frontend lädt sie mit der ersten Seite
    with_options: bool = True,
    limit: int = Query(50, gt=0, le=200),
    offset: int = Query(0, ge=0, le=MAX_QUERY_OFFSET),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_permission(user, P.ACTIVITY_READ)
    # audit_log hat keine RLS (Plattform-Tabelle): der Mandantenfilter steht hier ausdrücklich.
    actor_user: uuid.UUID | None = None
    actor_kind: str | None = None
    if actor in ("platform", "system", "deleted"):
        actor_kind = actor
    elif actor:
        try:
            actor_user = uuid.UUID(actor)
        except ValueError:
            actor_user = uuid.UUID(int=0)  # unbekannt: keine Treffer statt Fehler
    params = {
        "tenant_id": user.current_tenant_id, "category": category, "action": action, "outcome": outcome,
        "date_from": date_from, "date_to": date_to, "actor_user": actor_user, "actor_kind": actor_kind,
        "limit": limit, "offset": offset,
    }
    rows = db.execute(
        text(
            """
            SELECT l.created_at, l.action, l.outcome, l.actor_user_id, l.actor_email, l.entity_type, u.display_name"""
            + _FROM
            + _FILTERS
            + """
            ORDER BY l.created_at DESC, l.id DESC
            LIMIT :limit OFFSET :offset
            """
        ),
        params,
    ).all()
    total = db.scalar(text("SELECT count(*)" + _FROM + _FILTERS), params) or 0
    tenant_only = {"tenant_id": user.current_tenant_id}
    if not with_options:
        return ActivityPage(items=_items(rows), total=total, categories=[])
    actions = list(
        db.scalars(
            text(
                "SELECT DISTINCT action FROM audit_log WHERE tenant_id = :tenant_id"
                " AND (CAST(:category AS text) IS NULL OR split_part(action, '.', 1) = :category) ORDER BY 1"
            ),
            {**tenant_only, "category": category},
        )
    )
    actor_rows = db.execute(
        text(
            """
            SELECT DISTINCT u.public_id, u.display_name, l.actor_user_id IS NOT NULL AS had_user,
                   (l.action LIKE 'admin.%' OR l.actor_email IS NOT NULL) AS platform"""
            + _FROM
        ),
        tenant_only,
    ).all()
    people = sorted({(row.public_id, row.display_name) for row in actor_rows if row.public_id is not None}, key=lambda item: (item[1] or "").casefold())
    actors = [ActivityActor(key=str(public_id), kind="user", name=name) for public_id, name in people]
    for kind, present in (
        ("platform", any(not row.had_user and row.platform for row in actor_rows)),
        ("system", any(not row.had_user and not row.platform for row in actor_rows)),
        ("deleted", any(row.had_user and row.public_id is None for row in actor_rows)),
    ):
        if present:
            actors.append(ActivityActor(key=kind, kind=kind))
    categories = list(
        db.scalars(
            text("SELECT DISTINCT split_part(action, '.', 1) FROM audit_log WHERE tenant_id = :tenant_id ORDER BY 1"),
            {"tenant_id": user.current_tenant_id},
        )
    )
    return ActivityPage(items=_items(rows), total=total, categories=categories, actions=actions, actors=actors)


def _items(rows) -> list[ActivityEntry]:
    return [
        ActivityEntry(
            created_at=row.created_at,
            action=row.action,
            category=row.action.split(".", 1)[0],
            outcome=row.outcome,
            actor_kind=_actor_kind(row.actor_user_id, row.display_name, row.actor_email, row.action),
            actor_name=row.display_name,
            entity_type=row.entity_type,
        )
        for row in rows
    ]
