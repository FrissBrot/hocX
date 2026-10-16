"""Audit MAIN-BE-011: Konfliktprüfung und Speichern eines Textblocks sind atomar.

Wie test_fines_collect_race.py bewusst ohne die db-Fixture: echte Zeilensperren brauchen zwei
echte Verbindungen; aufgeräumt wird explizit über DELETE FROM tenant (Cascade)."""
from __future__ import annotations

import threading
import time

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.db import engine
from app.models import ProtocolElementBlock, ProtocolText
from app.services.autosave_service import AutosaveService, TextConflictError
from tests.factories import make_protocol, make_protocol_element, make_protocol_element_block, make_protocol_text, make_template, make_tenant


def _fixture() -> dict[str, int]:
    conn = engine.connect()
    session = Session(bind=conn, autoflush=False, future=True)
    tenant = make_tenant(session, "Autosave Race Tenant")
    template = make_template(session, tenant.id)
    protocol = make_protocol(session, tenant.id, template.id, protocol_number=f"AUTOSAVE-{tenant.id}")
    element = make_protocol_element(session, protocol.id)
    block = make_protocol_element_block(session, element.id, configuration_snapshot_json={}, element_type_code="text")
    make_protocol_text(session, block.id, content="alt")
    session.commit()
    ids = {"tenant_id": tenant.id, "block_id": block.id}
    session.close()
    conn.close()
    return ids


def _cleanup(tenant_id: int) -> None:
    with engine.connect() as conn:
        conn.execute(text("DELETE FROM tenant WHERE id = :tid"), {"tid": tenant_id})
        conn.commit()


def test_concurrent_save_with_stale_expected_content_is_rejected():
    ids = _fixture()
    block_id = ids["block_id"]
    holder_locked = threading.Event()
    try:
        def holder():
            # Simuliert einen laufenden Save: Block gesperrt, Text geändert, noch nicht committet.
            with engine.connect() as conn:
                session = Session(bind=conn, autoflush=False, future=True)
                session.execute(select(ProtocolElementBlock.id).where(ProtocolElementBlock.id == block_id).with_for_update())
                row = session.scalar(select(ProtocolText).where(ProtocolText.protocol_element_block_id == block_id))
                row.content = "von Tab A"
                session.flush()
                holder_locked.set()
                time.sleep(0.4)
                session.commit()
                session.close()

        thread = threading.Thread(target=holder)
        thread.start()
        assert holder_locked.wait(timeout=5)

        with engine.connect() as conn:
            session = Session(bind=conn, autoflush=False, future=True)
            with pytest.raises(TextConflictError):
                AutosaveService().save_text_block(
                    session, block_id, "von Tab B", tenant_id=ids["tenant_id"], expected_content="alt"
                )
            session.close()
        thread.join(timeout=5)

        with engine.connect() as conn:
            content = conn.execute(
                text("SELECT content FROM protocol_text WHERE protocol_element_block_id = :bid"), {"bid": block_id}
            ).scalar_one()
        assert content == "von Tab A"
    finally:
        _cleanup(ids["tenant_id"])


def test_save_with_matching_expected_content_succeeds():
    ids = _fixture()
    try:
        with engine.connect() as conn:
            session = Session(bind=conn, autoflush=False, future=True)
            result = AutosaveService().save_text_block(
                session, ids["block_id"], "neu", tenant_id=ids["tenant_id"], expected_content="alt"
            )
            session.close()
        assert result["content"] == "neu"
    finally:
        _cleanup(ids["tenant_id"])
