"""Concurrency-Audit CONC-005: keine Lost Updates in der Blockkonfiguration.

- Anwesenheit: gleichzeitige Klicks (eigene Sessions, echte Commits) gehen nie verloren.
- Konfigurations-PATCH: optimistische Sperre über config_version (Trigger, Migration 0149);
  veralteter Stand -> 409 config_conflict mit dem aktuellen Stand.
"""

from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, text
from sqlalchemy.orm import Session

from app.api.routes import protocol_elements
from app.core.db import engine
from app.models import ProtocolElementBlock, Tenant
from app.schemas.protocol import ProtocolElementBlockUpdate
from app.services.protocol_element_service import ProtocolElementService
from tests.factories import (
    make_current_user,
    make_participant,
    make_protocol,
    make_protocol_element,
    make_protocol_element_block,
    make_template,
    make_tenant,
)


def _block(db, config=None):
    tenant = make_tenant(db)
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id, status="geplant")
    element = make_protocol_element(db, protocol.id)
    block = make_protocol_element_block(db, element.id, configuration_snapshot_json=config or {}, element_type_code="matrix")
    return tenant, block, make_current_user(tenant.id)


def test_trigger_counts_only_real_config_changes(db):
    _tenant, block, _user = _block(db, {"a": 1})
    start = db.scalar(text("SELECT config_version FROM protocol_element_block WHERE id = :id"), {"id": block.id})
    db.execute(text("UPDATE protocol_element_block SET sort_index = sort_index + 1 WHERE id = :id"), {"id": block.id})
    assert db.scalar(text("SELECT config_version FROM protocol_element_block WHERE id = :id"), {"id": block.id}) == start
    db.execute(text("UPDATE protocol_element_block SET configuration_snapshot_json = '{\"a\": 2}' WHERE id = :id"), {"id": block.id})
    assert db.scalar(text("SELECT config_version FROM protocol_element_block WHERE id = :id"), {"id": block.id}) == start + 1


def test_patch_with_stale_version_returns_409_with_current_state(db, monkeypatch):
    monkeypatch.setattr(protocol_elements, "_ensure_block_not_locked_by_other", lambda *args: None)
    _tenant, block, user = _block(db, {"cells": {"r1c1": "alt"}})
    first = protocol_elements.patch_protocol_element_block(
        block.public_id, ProtocolElementBlockUpdate(configuration_snapshot_json={"cells": {"r1c1": "Anna"}}, expected_config_version=0), db=db, user=user
    )
    assert first.config_version == 1

    with pytest.raises(HTTPException) as conflict:
        # Zweite Person ging noch vom Stand 0 aus und ändert eine andere Zelle.
        protocol_elements.patch_protocol_element_block(
            block.public_id, ProtocolElementBlockUpdate(configuration_snapshot_json={"cells": {"r1c1": "alt", "r2c1": "Bruno"}}, expected_config_version=0), db=db, user=user
        )
    assert conflict.value.status_code == 409
    detail = conflict.value.detail
    assert detail["code"] == "config_conflict"
    assert detail["config_version"] == 1
    assert detail["configuration_snapshot_json"]["cells"] == {"r1c1": "Anna"}

    # Mit aktuellem Stand klappt es, ohne Version (ältere Clients) wie bisher.
    second = protocol_elements.patch_protocol_element_block(
        block.public_id, ProtocolElementBlockUpdate(configuration_snapshot_json={"cells": {"r1c1": "Anna", "r2c1": "Bruno"}}, expected_config_version=1), db=db, user=user
    )
    assert second.config_version == 2
    legacy = protocol_elements.patch_protocol_element_block(
        block.public_id, ProtocolElementBlockUpdate(configuration_snapshot_json={"cells": {}}), db=db, user=user
    )
    assert legacy.config_version == 3


def test_concurrent_attendance_clicks_are_never_lost():
    """Echte Nebenläufigkeit: eigene Sessions und Commits je Klick (wie zwei Requests)."""
    with Session(engine) as setup:
        tenant, block, _user = _block(setup)
        participants = [make_participant(setup, tenant.id, f"Person {index}") for index in range(8)]
        setup.commit()
        block_id, tenant_id = block.id, tenant.id
        targets = [(participant.id, participant.display_name) for participant in participants]

    def click(target):
        participant_id, name = target
        with Session(engine) as db:
            ProtocolElementService().set_attendance_status(db, block_id, participant_id, name, "present")

    try:
        with ThreadPoolExecutor(len(targets)) as pool:
            list(pool.map(click, targets))
        with Session(engine) as check:
            config = check.get(ProtocolElementBlock, block_id).configuration_snapshot_json
        assert sorted(entry["participant_id"] for entry in config["attendance_entries"]) == sorted(pid for pid, _ in targets)
    finally:
        with Session(engine) as cleanup:
            cleanup.execute(delete(Tenant).where(Tenant.id == tenant_id))
            cleanup.commit()
