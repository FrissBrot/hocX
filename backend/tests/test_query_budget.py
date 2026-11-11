"""Performance-Audit der CI: Abfragebudget der wichtigsten Endpunkte (nur Erkennung).

Gemessen wird die Zahl der SQL-Abfragen bei 1 und bei 20 Einträgen (Punkte, Blöcke, Zeilen). Das
ist auf jedem Rechner gleich - anders als Laufzeiten - und erkennt die häufigste Ursache echter
Langsamkeit: Abfragen in Schleifen (N+1), die erst mit vielen Daten auffallen.

Das Budget steht in ``tests/query_budget.json``. Mehr Abfragen als dort erlaubt lassen den Test
scheitern. Stand bei der Einführung (2026-11-11) ist der Ausgangswert, auch wo ein Endpunkt
heute noch mit der Zahl der Einträge wächst (``per_item`` > 0 im Budget): das ist dann sichtbar
und darf nicht schlimmer werden. Wird ein Endpunkt schneller, das Budget mit
``UPDATE_QUERY_BUDGET=1`` senken; wird er bewusst teurer, anheben und im Commit begründen.
"""
from __future__ import annotations

import json
import os
from collections.abc import Callable
from datetime import date
from pathlib import Path

import pytest

from app.api.routes import protocol_elements as elements_route
from app.api.routes import protocols as protocols_route
from app.api.routes import files as files_route
from app.api.routes import todos as todos_route
from app.documents.catalog import BlockSpec
from app.documents.compiler import run_component
from app.documents.context import BuildContext
from app.documents.export_coverage import protocol_pdf_coverage
from tests.factories import (
    make_current_user,
    make_event,
    make_protocol,
    make_protocol_element,
    make_protocol_element_block,
    make_protocol_text,
    make_protocol_todo,
    make_template,
    make_tenant,
)
from tests.test_list_query_counts import _events, _participants, _protocols, _query_count, _templates, _todos

BUDGET_FILE = Path(__file__).parent / "query_budget.json"
SIZES = (1, 20)


def _protocol_with(db, n: int, *, per_element: bool = False):
    """Protokoll mit ``n`` Text- und ``n`` Aufgabenblöcken - in einem Punkt oder (``per_element``)
    je Paar ein eigener Punkt."""
    tenant = make_tenant(db, f"Budget {n} {per_element}")
    protocol = make_protocol(db, tenant.id, make_template(db, tenant.id).id, protocol_number=f"Q-{n}")
    element = make_protocol_element(db, protocol.id, section_name="Punkt")
    for index in range(n):
        if per_element:
            element = make_protocol_element(db, protocol.id, sort_index=index + 1, section_name=f"Punkt {index}")
        text = make_protocol_element_block(db, element.id, {}, sort_index=2 * index, element_type_code="text")
        make_protocol_text(db, text.id, f"Text {index}")
        todo = make_protocol_element_block(db, element.id, {}, sort_index=2 * index + 1, element_type_code="todo")
        make_protocol_todo(db, todo.id, task=f"Aufgabe {index}")
    db.flush()
    return tenant, protocol, make_current_user(tenant.id, role="admin")


def _protocol_detail(db, n):
    _tenant, protocol, user = _protocol_with(db, n, per_element=True)
    return lambda: protocols_route.get_protocol(protocol.public_id, db=db, user=user)


def _protocol_elements(db, n):
    _tenant, protocol, user = _protocol_with(db, n, per_element=True)
    return lambda: elements_route.list_protocol_elements(protocol.public_id, db=db, user=user)


def _block_todos(db, n):
    _tenant, protocol, user = _protocol_with(db, n)
    return lambda: todos_route.list_protocol_block_todos(protocol.public_id, db=db, user=user)


def _block_images(db, n):
    _tenant, protocol, user = _protocol_with(db, n)
    return lambda: files_route.list_protocol_block_images(protocol.public_id, db=db, user=user)


def _rich_protocol(db, n: int):
    """Protokoll mit ``n`` Punkten, jeder mit Text, Aufgaben (mit Tag des Punkts), Bild,
    Terminliste, Formular und Aufzählung - die üblichen Bausteine eines Protokolls."""
    from app.models import ProtocolImage, StoredFile

    tenant = make_tenant(db, f"Budget reich {n}")
    protocol = make_protocol(db, tenant.id, make_template(db, tenant.id).id, protocol_number=f"R-{n}")
    for index in range(3):
        make_event(db, tenant.id, title=f"Termin {index}", event_date=date(2026, 2, 1 + index))
    for index in range(n):
        element = make_protocol_element(db, protocol.id, sort_index=index, section_name=f"Punkt {index}")
        text = make_protocol_element_block(db, element.id, {}, sort_index=0, element_type_code="text")
        make_protocol_text(db, text.id, f"Text {index}")
        todo = make_protocol_element_block(db, element.id, {}, sort_index=1, element_type_code="todo")
        make_protocol_todo(db, todo.id, task=f"Aufgabe {index}").tags = [f"punkt {index}"]
        image = make_protocol_element_block(db, element.id, {}, sort_index=2, element_type_code="image")
        stored = StoredFile(tenant_id=tenant.id, original_name="a.jpg", mime_type="image/jpeg", storage_path=f"budget/{n}/{index}.jpg", file_size_bytes=1, checksum_sha256="0" * 64, scan_status="pending")
        db.add(stored)
        db.flush()
        db.add(ProtocolImage(protocol_element_block_id=image.id, stored_file_id=stored.id))
        make_protocol_element_block(db, element.id, {"event_filter": {"range": {"mode": "future"}}}, sort_index=3, element_type_code="event_list")
        make_protocol_element_block(db, element.id, {"rows": [{"label": "Ort", "value_type": "text", "text_value": "Heim"}]}, sort_index=4, element_type_code="form")
        make_protocol_element_block(db, element.id, {"bullet_items": ["a", "b"]}, sort_index=5, element_type_code="bullet_list")
    db.flush()
    return tenant, protocol, make_current_user(tenant.id, role="admin")


def _pdf_content(db, n):
    """Inhalt des Protokoll-PDFs (alle Punkte und Blöcke, ohne Typst)."""
    tenant, protocol, _user = _rich_protocol(db, n)
    return lambda: run_component(BuildContext(db=db, tenant_id=tenant.id, language="de", protocol=protocol), BlockSpec(type="protocol_element"))


def _pdf_coverage(db, n):
    """«Nicht im PDF» im Editor (fragt nach Änderungen erneut ab)."""
    from app.documents.system_templates import sync_system_templates

    sync_system_templates(db)
    tenant, protocol, user = _rich_protocol(db, n)
    return lambda: protocol_pdf_coverage(db, user, tenant.id, protocol)


SCENARIOS: dict[str, Callable] = {
    "protocol_detail": _protocol_detail,
    "protocol_elements": _protocol_elements,
    "protocol_block_todos": _block_todos,
    "protocol_block_images": _block_images,
    "pdf_content": _pdf_content,
    "pdf_coverage": _pdf_coverage,
    "list_protocols": _protocols,
    "list_todos": _todos,
    "list_events": _events,
    "list_participants": _participants,
    "list_templates": _templates,
}


def _measure(db, name: str) -> dict[str, int]:
    counts = {str(size): _query_count(db, SCENARIOS[name](db, size)) for size in SIZES}
    return counts


def _budget() -> dict:
    return json.loads(BUDGET_FILE.read_text()) if BUDGET_FILE.exists() else {"endpoints": {}}


@pytest.mark.parametrize("name", list(SCENARIOS))
def test_query_budget(db, name):
    measured = _measure(db, name)
    if os.environ.get("UPDATE_QUERY_BUDGET") == "1":
        budget = _budget()
        low, high = measured[str(SIZES[0])], measured[str(SIZES[-1])]
        budget.setdefault("endpoints", {})[name] = {**measured, "per_item": round((high - low) / (SIZES[-1] - SIZES[0]), 2)}
        budget["endpoints"] = dict(sorted(budget["endpoints"].items()))
        BUDGET_FILE.write_text(json.dumps(budget, ensure_ascii=False, indent=2) + "\n")
        return
    limits = _budget()["endpoints"].get(name)
    assert limits is not None, f"Kein Abfragebudget für {name} (UPDATE_QUERY_BUDGET=1)"
    over = {size: f"{count} > {limits[size]}" for size, count in measured.items() if count > limits[size]}
    assert over == {}, f"{name}: mehr SQL-Abfragen als im Budget (bei n Einträgen: Ist > Budget)"


def test_every_budget_has_a_scenario():
    assert set(_budget()["endpoints"]) == set(SCENARIOS)
