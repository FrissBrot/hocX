"""Terminsuche im Protokoll (Terminübersicht/Kandidaten-Popup): % und _ sind Text
(Bug-Bounty 2026-11-19, termine/eingaben). Bisher landeten sie ungeschützt im ILIKE-Muster,
«_» fand jeden Termin, «100%» auch «100 Jahre»."""
from __future__ import annotations

from datetime import date

from app.repositories.event_repository import EventRepository
from tests.factories import make_event, make_tenant


def _titles(db, tenant_id: int, search: str) -> set[str]:
    items, total = EventRepository().list_filtered(db, tenant_id=tenant_id, search=search)
    assert total == len(items)
    return {event.title for event in items}


def test_like_wildcards_in_the_search_are_literal(db):
    tenant = make_tenant(db)
    make_event(db, tenant.id, title="Jubiläum 100 Jahre", event_date=date(2026, 3, 1))
    make_event(db, tenant.id, title="Aktion 100% Einsatz", event_date=date(2026, 3, 2))
    make_event(db, tenant.id, title="Hock_Planung", event_date=date(2026, 3, 3))
    make_event(db, tenant.id, title="Back\\slash", event_date=date(2026, 3, 4))
    db.flush()

    assert _titles(db, tenant.id, "_") == {"Hock_Planung"}
    assert _titles(db, tenant.id, "100%") == {"Aktion 100% Einsatz"}
    assert _titles(db, tenant.id, "%") == {"Aktion 100% Einsatz"}
    assert _titles(db, tenant.id, "k\\s") == {"Back\\slash"}
    assert _titles(db, tenant.id, "hock") == {"Hock_Planung"}
