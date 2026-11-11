"""GET /protocols/{id}/pdf-coverage (Markierung «Nicht im PDF» im Editor): dieselben Prüfungen
wie das Lesen des Protokolls (meetings.read, Mandant); fremde oder unbekannte Protokolle ergeben
404. Die Logik selbst prüft tests/documents/test_pdf_integrity.py."""
from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from app.api.routes import protocols as protocols_route
from app.documents.system_templates import sync_system_templates
from tests.factories import make_current_user, make_protocol, make_protocol_element, make_protocol_element_block, make_protocol_text, make_template, make_tenant


def _protocol(db, tenant_id: int):
    template = make_template(db, tenant_id)
    protocol = make_protocol(db, tenant_id, template.id)
    element = make_protocol_element(db, protocol.id)
    block = make_protocol_element_block(db, element.id, {}, element_type_code="text")
    block.export_visible_snapshot = False
    make_protocol_text(db, block.id, "Nur im Editor")
    db.flush()
    return protocol, block


def test_writer_sees_blocks_missing_from_the_pdf(db):
    sync_system_templates(db)
    tenant = make_tenant(db, "Abdeckung")
    protocol, block = _protocol(db, tenant.id)

    result = protocols_route.get_protocol_pdf_coverage(protocol.public_id, db=db, user=make_current_user(tenant.id, role="writer"))

    assert result["blocks"] == [{"id": str(block.public_id), "reason": "block_not_exported"}]
    assert result["elements"] == []


def test_foreign_or_unknown_protocol_is_404(db):
    tenant_a = make_tenant(db, "Tenant A")
    tenant_b = make_tenant(db, "Tenant B")
    protocol, _ = _protocol(db, tenant_a.id)
    for protocol_id, user in ((protocol.public_id, make_current_user(tenant_b.id)), (uuid.uuid4(), make_current_user(tenant_a.id))):
        with pytest.raises(HTTPException) as error:
            protocols_route.get_protocol_pdf_coverage(protocol_id, db=db, user=user)
        assert error.value.status_code == 404
