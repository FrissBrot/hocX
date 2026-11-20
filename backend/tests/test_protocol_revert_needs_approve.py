"""Zurückstufen eines abgeschlossenen Protokolls hebt die Freigabe auf.

Abschliessen = freigeben braucht meetings.approve (Plan «Berechtigungen», Phase 3). Ein Konto mit
nur meetings.edit (Vorlage «Aktuar»: Sitzungen bearbeiten ohne Freigeben, Vier-Augen mit dem
Präsidenten) darf die Freigabe deshalb auch nicht wieder aufheben - sonst könnte es ein
freigegebenes Protokoll zurückstufen, den Inhalt ändern und es vor Lesern ohne Entwurfsrecht
verbergen. Rückstufen zwischen den Vorstufen (vorbereitet/durchgeführt) bleibt meetings.edit.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api.routes import protocols as protocol_routes
from tests.factories import make_current_user, make_protocol, make_template, make_tenant


def _editor_without_approve(tenant_id: int):
    user = make_current_user(tenant_id, role="writer")
    return make_current_user(tenant_id, permissions=user.permissions - {"meetings.approve"})


def test_revert_of_closed_protocol_requires_approve(db):
    tenant = make_tenant(db, "Rückstufen Freigabe")
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id, status="abgeschlossen")

    with pytest.raises(HTTPException) as denied:
        protocol_routes.revert_protocol_status(protocol.public_id, db=db, user=_editor_without_approve(tenant.id))
    assert denied.value.status_code == 403
    db.refresh(protocol)
    assert protocol.status == "abgeschlossen"

    approver = make_current_user(tenant.id, role="writer")
    reverted = protocol_routes.revert_protocol_status(protocol.public_id, db=db, user=approver)
    assert reverted.status == "durchgeführt"


def test_revert_of_open_stages_keeps_working_with_edit_only(db):
    tenant = make_tenant(db, "Rückstufen Vorstufe")
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id, status="durchgeführt")

    reverted = protocol_routes.revert_protocol_status(protocol.public_id, db=db, user=_editor_without_approve(tenant.id))
    assert reverted.status == "vorbereitet"
