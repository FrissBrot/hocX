import pytest
from fastapi import HTTPException

from app.api.routes import protocol_elements
from app.schemas.protocol import ProtocolTextUpdate
from tests.factories import (
    make_current_user,
    make_protocol,
    make_protocol_element,
    make_protocol_element_block,
    make_template,
    make_tenant,
)


def test_text_update_rejects_stale_expected_content(db, monkeypatch):
    tenant = make_tenant(db)
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id)
    element = make_protocol_element(db, protocol.id)
    block = make_protocol_element_block(db, element.id)
    user = make_current_user(tenant.id)
    monkeypatch.setattr(protocol_elements, "_ensure_block_not_locked_by_other", lambda *args: None)

    saved = protocol_elements.put_protocol_text(
        block.id, ProtocolTextUpdate(content="erste Version", expected_content=""), db=db, user=user
    )
    assert saved.content == "erste Version"

    with pytest.raises(HTTPException) as exc_info:
        protocol_elements.put_protocol_text(
            block.id, ProtocolTextUpdate(content="veralteter Entwurf", expected_content=""), db=db, user=user
        )

    assert exc_info.value.status_code == 409
    assert "lokale Entwurf bleibt erhalten" in exc_info.value.detail
