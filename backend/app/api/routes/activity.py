"""Verlauf eines Mandanten (Mandanten-Einstellungen → Verlauf, Datenschutz-Audit PRIV-013).

Mandanten-Admins sehen, was in ihrem Verein geändert, gelöscht oder exportiert wurde, wer sich
angemeldet hat (auch Fehlversuche) und wann die Plattform-Administration auf Daten des Vereins
zugegriffen hat. Keine IP-Hashes, keine E-Mail-Adressen; Plattform-Admins erscheinen als
"Plattform", Personen mit ihrem aktuellen Anzeigenamen (gelöschte Personen ohne Namen).
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.permissions import P
from app.core.security import CurrentUser, get_current_user, require_permission

router = APIRouter()

# Optionale Filter als gebundene Parameter (NULL = kein Filter)
_FILTERS = """
              AND (CAST(:category AS text) IS NULL OR split_part(l.action, '.', 1) = :category)
              AND (CAST(:outcome AS text) IS NULL OR l.outcome = :outcome)"""


class ActivityEntry(BaseModel):
    created_at: datetime
    action: str
    category: str
    outcome: Literal["success", "failure"]
    actor_kind: Literal["user", "platform", "system", "deleted"]
    actor_name: str | None = None
    entity_type: str | None = None


class ActivityPage(BaseModel):
    items: list[ActivityEntry]
    total: int
    categories: list[str]


def _actor_kind(actor_user_id: int | None, actor_name: str | None, actor_email: str | None, action: str) -> str:
    if actor_user_id is not None:
        return "user" if actor_name is not None else "deleted"
    if action.startswith("admin.") or actor_email:
        return "platform"
    return "system"


@router.get("/activity", response_model=ActivityPage)
def list_activity(
    category: str | None = Query(default=None, max_length=60),
    outcome: Literal["success", "failure"] | None = None,
    limit: int = Query(50, gt=0, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_permission(user, P.SETTINGS_MANAGE)
    # audit_log hat keine RLS (Plattform-Tabelle): der Mandantenfilter steht hier ausdrücklich.
    params = {"tenant_id": user.current_tenant_id, "category": category, "outcome": outcome, "limit": limit, "offset": offset}
    rows = db.execute(
        text(
            """
            SELECT l.created_at, l.action, l.outcome, l.actor_user_id, l.actor_email, l.entity_type, u.display_name
            FROM audit_log l
            LEFT JOIN app_user u ON u.id = l.actor_user_id AND u.tenant_id = l.tenant_id
            WHERE l.tenant_id = :tenant_id"""
            + _FILTERS
            + """
            ORDER BY l.created_at DESC, l.id DESC
            LIMIT :limit OFFSET :offset
            """
        ),
        params,
    ).all()
    total = db.scalar(text("SELECT count(*) FROM audit_log l WHERE l.tenant_id = :tenant_id" + _FILTERS), params) or 0
    categories = list(
        db.scalars(
            text("SELECT DISTINCT split_part(action, '.', 1) FROM audit_log WHERE tenant_id = :tenant_id ORDER BY 1"),
            {"tenant_id": user.current_tenant_id},
        )
    )
    items = [
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
    return ActivityPage(items=items, total=total, categories=categories)
