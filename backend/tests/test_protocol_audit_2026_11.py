"""Bereichs-Audit 2026-11, Protokolle: Sperre abgeschlossener Protokolle im PATCH, Audit-Log beim
Zurückstufen, einheitlicher Schreib-Guard (404 statt 403), WS-Statusprüfung, Schweizer Datum,
Nummernvergabe unter Lock."""
from __future__ import annotations

from datetime import date

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from app.api.routes import collaboration_ws, protocol_elements, protocols as protocols_route
from app.core.permissions import P
from app.schemas.protocol import ProtocolElementUpdate, ProtocolUpdate
from app.services import protocol_period_service, todo_fine_service
from app.services.protocol_service import lock_protocol_numbering
from tests.factories import make_current_user, make_protocol, make_protocol_element, make_template, make_tenant


def _closed_protocol(db):
    tenant = make_tenant(db)
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id, status="abgeschlossen")
    protocol.title = "Eingefroren"
    db.flush()
    return tenant, protocol


@pytest.mark.parametrize(
    "payload",
    [
        ProtocolUpdate(title="Nachträglich geändert"),
        ProtocolUpdate(protocol_date=date(2026, 1, 2)),
        ProtocolUpdate(session_notes="neu"),
        ProtocolUpdate(session_notes="neu", expected_session_notes=""),
        ProtocolUpdate(track_changes_enabled=True),
        ProtocolUpdate(status="abgeschlossen", title="Mitgeschickt"),
    ],
)
def test_patch_rejects_content_changes_on_closed_protocol(db, payload):
    tenant, protocol = _closed_protocol(db)
    user = make_current_user(tenant.id)

    with pytest.raises(HTTPException) as exc_info:
        protocols_route.patch_protocol(protocol.public_id, payload, db=db, user=user)

    assert exc_info.value.status_code == 409
    db.refresh(protocol)
    assert protocol.title == "Eingefroren"


def test_patch_still_allows_reverting_status_of_closed_protocol(db):
    tenant, protocol = _closed_protocol(db)
    user = make_current_user(tenant.id)

    result = protocols_route.patch_protocol(protocol.public_id, ProtocolUpdate(status="durchgeführt"), db=db, user=user)

    assert result.status == "durchgeführt"


def test_patch_open_protocol_still_changes_title(db):
    tenant = make_tenant(db)
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id, status="durchgeführt")
    user = make_current_user(tenant.id)

    result = protocols_route.patch_protocol(protocol.public_id, ProtocolUpdate(title="Neu"), db=db, user=user)

    assert result.title == "Neu"


def test_revert_status_audit_log_records_real_previous_status(db):
    tenant, protocol = _closed_protocol(db)
    user = make_current_user(tenant.id)

    result = protocols_route.revert_protocol_status(protocol.public_id, db=db, user=user)

    assert result.status == "durchgeführt"
    row = db.execute(
        text(
            "SELECT details_json FROM audit_log WHERE entity_type = 'protocol' AND action = 'protocol.status_reverted' "
            "AND entity_id = :id ORDER BY id DESC LIMIT 1"
        ),
        {"id": protocol.id},
    ).one()
    assert row.details_json == {"from": "abgeschlossen", "to": "durchgeführt"}


def test_second_close_does_not_rerun_transition_hooks(db, monkeypatch):
    tenant = make_tenant(db)
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id, status="durchgeführt")
    user = make_current_user(tenant.id)
    enqueued: list[int] = []
    monkeypatch.setattr(protocols_route.document_render_jobs, "enqueue_protocol_pdf", lambda db, protocol: enqueued.append(protocol.id))

    protocols_route.patch_protocol(protocol.public_id, ProtocolUpdate(status="abgeschlossen"), db=db, user=user)
    # Zweiter Klick (z. B. andere Person, wartete auf die Zeilensperre): sieht den neuen Status.
    protocols_route.patch_protocol(protocol.public_id, ProtocolUpdate(status="abgeschlossen"), db=db, user=user)

    assert enqueued == [protocol.id]


def _editor_without_draft_read(tenant_id: int):
    # Schreibrecht ohne Entwurfs-Leserecht kommt mit den Standardrollen nicht vor (meetings.edit
    # impliziert read_drafts); der Guard soll trotzdem ohne Existenz-Orakel antworten.
    return make_current_user(tenant_id, permissions=frozenset({P.MEETINGS_READ, P.MEETINGS_EDIT}))


def test_write_routes_answer_404_for_unreadable_draft(db):
    tenant = make_tenant(db)
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id, status="geplant")
    element = make_protocol_element(db, protocol.id)
    user = _editor_without_draft_read(tenant.id)

    calls = [
        lambda: protocols_route.patch_protocol(protocol.public_id, ProtocolUpdate(title="x"), db=db, user=user),
        lambda: protocols_route.revert_protocol_status(protocol.public_id, db=db, user=user),
        lambda: protocols_route.delete_protocol(protocol.public_id, db=db, user=user),
        lambda: protocol_elements.patch_protocol_element(element.public_id, ProtocolElementUpdate(), db=db, user=user),
    ]
    for call in calls:
        with pytest.raises(HTTPException) as exc_info:
            call()
        assert exc_info.value.status_code == 404


def test_ws_only_relays_known_statuses():
    assert "abgeschlossen" in collaboration_ws._PROTOCOL_STATUSES
    assert "Frei erfundener Text" not in collaboration_ws._PROTOCOL_STATUSES


def test_this_year_filter_uses_swiss_today(monkeypatch):
    monkeypatch.setattr(todo_fine_service, "today", lambda: date(2027, 1, 1))
    config = {"finance_filter_type": "this_year"}

    assert protocol_period_service.transaction_matches(date(2027, 1, 1), config, protocol_date=None, period={})
    assert not protocol_period_service.transaction_matches(date(2026, 12, 31), config, protocol_date=None, period={})


def test_protocol_numbering_lock_is_transaction_scoped(db):
    tenant = make_tenant(db)
    template = make_template(db, tenant.id)

    lock_protocol_numbering(db, template.id)
    held = db.execute(
        text("SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND classid = :ns AND objid = :tid AND granted"),
        {"ns": 909100011, "tid": template.id},
    ).scalar_one()
    assert held == 1
