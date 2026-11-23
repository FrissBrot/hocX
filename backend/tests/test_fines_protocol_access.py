"""Bussen-Routen prüfen den Zugriff auf das Protokoll, nicht nur den Mandanten.

``fines.py::_resolve_protocol_id`` löste die Protokoll-ID nur im eigenen Mandanten auf. Wer
Bussen sehen (reports.personal) oder verwalten (fines.manage) darf, aber Entwürfe nicht lesen
darf (ohne meetings.read_drafts) oder als eingeschränkter Leser nur zugeordnete Protokolle sieht,
konnte so Bussen von Protokollen lesen und anlegen, die er nicht öffnen darf - und an der Antwort
(200 statt 404) erkennen, dass es den Entwurf gibt. Erwartet: dieselben Regeln wie
access_service.can_read_protocol, nicht lesbar = unbekannt (gleiche 404), nichts angelegt."""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.api.routes import fines as fine_routes
from app.models import AttendanceFine
from app.models.entities import UserProtocolAccess, UserTemplateAccess
from app.schemas.fines import AttendanceFineCreate, CollectFinePayload, DeleteFinePayload
from tests.factories import make_app_user, make_current_user, make_finance_account, make_fine, make_protocol, make_template, make_tenant

# Eigene Rolle: Bussen sehen und verwalten, Protokolle aber nur abgeschlossen lesen
FINES_WITHOUT_DRAFTS = frozenset({"meetings.read", "reports.personal", "fines.manage", "finances.read"})


def _error(call) -> tuple[int, object]:
    with pytest.raises(HTTPException) as exc:
        call()
    return exc.value.status_code, exc.value.detail


@pytest.fixture
def setup(db):
    tenant = make_tenant(db, "Bussen Protokollzugriff")
    template = make_template(db, tenant.id)
    other_template = make_template(db, tenant.id, name="Andere Vorlage")
    draft = make_protocol(db, tenant.id, template.id, protocol_number="E-1", status="geplant")
    final = make_protocol(db, tenant.id, template.id, protocol_number="A-1", status="abgeschlossen")
    other_draft = make_protocol(db, tenant.id, other_template.id, protocol_number="E-2", status="geplant")
    account = make_finance_account(db, tenant.id)
    fines = {protocol.id: make_fine(db, protocol.id, account.id, amount=Decimal("5.00")) for protocol in (draft, final, other_draft)}
    return {"tenant": tenant, "template": template, "draft": draft, "final": final, "other_draft": other_draft, "account": account, "fines": fines}


def _restricted(db, setup, protocol_ids: list[int]):
    """Eingeschränkter Leser (nur zugeordnete Protokolle) mit Bussenrechten."""
    tenant_id = setup["tenant"].id
    account = make_app_user(db, email=f"bussen-{uuid.uuid4().hex[:8]}@example.com", tenant_id=tenant_id)
    db.add(UserTemplateAccess(user_id=account.id, tenant_id=tenant_id, template_id=setup["template"].id))
    for protocol_id in protocol_ids:
        db.add(UserProtocolAccess(user_id=account.id, tenant_id=tenant_id, protocol_id=protocol_id))
    db.flush()
    return make_current_user(tenant_id, user_id=account.id, permissions=FINES_WITHOUT_DRAFTS)


def _create_payload(setup, protocol_public_id) -> AttendanceFineCreate:
    return AttendanceFineCreate(
        protocol_id=protocol_public_id, participant_name_snapshot="Gast", fine_type="late", amount=Decimal("5.00"), account_id=setup["account"].public_id,
    )


def _fine_count(db, protocol_id: int) -> int:
    return db.scalar(select(func.count(AttendanceFine.id)).where(AttendanceFine.protocol_id == protocol_id))


@pytest.mark.parametrize("route", [fine_routes.list_protocol_fines, fine_routes.list_pending_fines])
def test_draft_fines_hidden_like_unknown_protocol_without_read_drafts(db, setup, route):
    user = make_current_user(setup["tenant"].id, permissions=FINES_WITHOUT_DRAFTS)
    hidden = _error(lambda: route(setup["draft"].public_id, db=db, user=user))
    assert hidden == (404, "Protocol not found")
    assert hidden == _error(lambda: route(uuid.uuid4(), db=db, user=user))
    # Abgeschlossene Protokolle darf diese Rolle lesen - deren Bussen auch
    assert [fine.id for fine in fine_routes.list_protocol_fines(setup["final"].public_id, db=db, user=user)] == [setup["fines"][setup["final"].id].public_id]


def test_create_fine_on_unreadable_draft_is_refused_like_unknown(db, setup):
    user = make_current_user(setup["tenant"].id, permissions=FINES_WITHOUT_DRAFTS)
    before = _fine_count(db, setup["draft"].id)
    hidden = _error(lambda: fine_routes.create_fine(_create_payload(setup, setup["draft"].public_id), db=db, user=user))
    assert hidden[0] == 404
    assert hidden == _error(lambda: fine_routes.create_fine(_create_payload(setup, uuid.uuid4()), db=db, user=user))
    assert _fine_count(db, setup["draft"].id) == before


def test_create_fine_with_tariff_on_unreadable_draft_is_refused(db, setup):
    user = make_current_user(setup["tenant"].id, permissions=FINES_WITHOUT_DRAFTS)
    payload = _create_payload(setup, setup["draft"].public_id).model_copy(update={"amount": None, "use_tariff": True})
    before = _fine_count(db, setup["draft"].id)
    assert _error(lambda: fine_routes.create_fine(payload, db=db, user=user))[0] == 404
    assert _fine_count(db, setup["draft"].id) == before


def test_fines_manage_without_meetings_read_cannot_write_into_protocols(db, setup):
    user = make_current_user(setup["tenant"].id, permissions=frozenset({"fines.manage", "finances.read"}))
    before = _fine_count(db, setup["draft"].id)
    assert _error(lambda: fine_routes.create_fine(_create_payload(setup, setup["draft"].public_id), db=db, user=user))[0] == 404
    assert _fine_count(db, setup["draft"].id) == before


def test_collect_and_delete_context_must_be_readable(db, setup):
    user = make_current_user(setup["tenant"].id, permissions=FINES_WITHOUT_DRAFTS)
    fine = setup["fines"][setup["final"].id]
    collect = _error(lambda: fine_routes.collect_fine(fine.public_id, payload=CollectFinePayload(collecting_protocol_id=setup["draft"].public_id), db=db, user=user))
    assert collect == (404, "Protocol not found")
    delete = _error(lambda: fine_routes.delete_fine(fine.public_id, payload=DeleteFinePayload(reason="Fehler", protocol_id=setup["draft"].public_id), db=db, user=user))
    assert delete == (404, "Protocol not found")
    db.expire_all()
    assert db.get(AttendanceFine, fine.id).status == "pending"


def test_restricted_reader_only_reaches_assigned_protocols(db, setup):
    user = _restricted(db, setup, [setup["draft"].id])
    # Zugeordneter Entwurf: lesen und anlegen erlaubt
    assert [fine.id for fine in fine_routes.list_protocol_fines(setup["draft"].public_id, db=db, user=user)] == [setup["fines"][setup["draft"].id].public_id]
    created = fine_routes.create_fine(_create_payload(setup, setup["draft"].public_id), db=db, user=user)
    assert created.protocol_id == setup["draft"].public_id
    # Nicht zugeordnet: wie unbekannt
    other = setup["other_draft"]
    assert _error(lambda: fine_routes.list_protocol_fines(other.public_id, db=db, user=user)) == (404, "Protocol not found")
    before = _fine_count(db, other.id)
    assert _error(lambda: fine_routes.create_fine(_create_payload(setup, other.public_id), db=db, user=user))[0] == 404
    assert _fine_count(db, other.id) == before


def test_kassier_keeps_working_on_drafts(db, setup):
    user = make_current_user(setup["tenant"].id, role="kassier")
    assert len(fine_routes.list_protocol_fines(setup["draft"].public_id, db=db, user=user)) == 1
    assert fine_routes.list_pending_fines(setup["draft"].public_id, db=db, user=user) is not None
    created = fine_routes.create_fine(_create_payload(setup, setup["draft"].public_id), db=db, user=user)
    assert created.protocol_id == setup["draft"].public_id


def test_foreign_tenant_protocol_answers_like_unknown(db, setup):
    other_tenant = make_tenant(db, "Fremder Verein Bussen-Protokoll")
    user = make_current_user(other_tenant.id, role="kassier")
    assert _error(lambda: fine_routes.list_protocol_fines(setup["draft"].public_id, db=db, user=user)) == _error(
        lambda: fine_routes.list_protocol_fines(uuid.uuid4(), db=db, user=user)
    )
    assert _error(lambda: fine_routes.create_fine(_create_payload(setup, setup["draft"].public_id), db=db, user=user))[0] == 404


@pytest.mark.parametrize(("action", "status"), [("delete", "pending"), ("collect", "pending"), ("restore", "deleted"), ("reopen", "collected")])
def test_fine_of_unreadable_draft_answers_like_unknown_fine(db, setup, action, status):
    """Auch über die Bussen-ID (aus GET /fines) kein Zugriff auf Bussen nicht lesbarer Protokolle."""
    user = make_current_user(setup["tenant"].id, permissions=FINES_WITHOUT_DRAFTS)
    fine = setup["fines"][setup["draft"].id]
    fine.status = status
    if status == "deleted":
        fine.delete_comment = "Erfassungsfehler"
    db.flush()

    def call(fine_id):
        if action == "delete":
            return lambda: fine_routes.delete_fine(fine_id, payload=None, db=db, user=user)
        if action == "collect":
            return lambda: fine_routes.collect_fine(fine_id, payload=CollectFinePayload(), db=db, user=user)
        if action == "restore":
            return lambda: fine_routes.restore_fine(fine_id, db=db, user=user)
        return lambda: fine_routes.reopen_fine(fine_id, db=db, user=user)

    assert _error(call(fine.public_id)) == _error(call(uuid.uuid4())) == (404, "Fine not found")
    db.expire_all()
    assert db.get(AttendanceFine, fine.id).status == status


@pytest.mark.parametrize("route", [fine_routes.list_protocol_fines, fine_routes.list_pending_fines])
def test_foreign_tenant_protocol_lists_answer_like_unknown(db, setup, route):
    other_tenant = make_tenant(db, "Fremder Verein Bussen-Listen")
    user = make_current_user(other_tenant.id, role="kassier")
    assert _error(lambda: route(setup["draft"].public_id, db=db, user=user)) == _error(lambda: route(uuid.uuid4(), db=db, user=user))


def test_kassier_can_collect_into_draft_context(db, setup):
    user = make_current_user(setup["tenant"].id, role="kassier")
    fine = setup["fines"][setup["final"].id]
    result = fine_routes.collect_fine(fine.public_id, payload=CollectFinePayload(collecting_protocol_id=setup["draft"].public_id), db=db, user=user)
    assert result.status == "collected"


def test_tenant_fine_list_and_summary_skip_unreadable_drafts(db, setup):
    """Security-Review 1.5.2: die Bussenliste (reports.personal) und die offene Summe verrieten
    Entwürfe, deren Einzelrouten 404 liefern (ID, Nummer, Datum, Betrag)."""
    user = make_current_user(setup["tenant"].id, permissions=FINES_WITHOUT_DRAFTS)
    listed = fine_routes.list_fines(skip=0, limit=50, fine_status=None, db=db, user=user)
    assert [item.id for item in listed] == [setup["fines"][setup["final"].id].public_id]
    summary = fine_routes.open_fines_summary(db=db, user=user)
    assert summary.count == 1
    # Mit meetings.read_drafts weiterhin alle
    full = make_current_user(setup["tenant"].id, permissions=FINES_WITHOUT_DRAFTS | {"meetings.read_drafts"})
    assert len(fine_routes.list_fines(skip=0, limit=50, fine_status=None, db=db, user=full)) == 3
