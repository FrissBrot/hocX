"""Nachtlauf 2026-11-25 (protokolle/eingaben): Blockkonfiguration in falscher Form.

``configuration_snapshot_json`` ist ein freies Objekt. ``attendance_entries: 5`` wurde per PATCH
gespeichert, danach scheiterte ``GET /protocols/{id}/elements`` für alle dauerhaft mit 500 (und
der PDF-Export). Andere Formfehler, zu grosse Zahlen oder «²» als Personen-ID liessen den PATCH
mit 500 und einem Eintrag im Fehlerprotokoll scheitern; sort_index über INTEGER ebenso (400 plus
Fehlerprotokoll). Jetzt: 400 ``invalid_block_config`` bzw. 422, nichts gespeichert."""

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.routes import protocol_elements
from app.documents.context import BuildContext
from app.documents.providers.protocol import map_block
from app.schemas.protocol import ProtocolElementBlockUpdate, ProtocolElementUpdate
from tests.factories import (
    make_current_user,
    make_participant,
    make_protocol,
    make_protocol_element,
    make_protocol_element_block,
    make_template,
    make_tenant,
)


def _setup(db, monkeypatch, code):
    monkeypatch.setattr(protocol_elements, "_ensure_block_not_locked_by_other", lambda *args: None)
    tenant = make_tenant(db)
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id, status="geplant")
    element = make_protocol_element(db, protocol.id)
    block = make_protocol_element_block(db, element.id, configuration_snapshot_json={}, element_type_code=code)
    return tenant, protocol, block, make_current_user(tenant.id)


BAD_CONFIGS = [
    ("attendance", {"attendance_entries": 5}),
    ("attendance", {"attendance_entries": ["x"]}),
    ("attendance", {"attendance_entries": None}),
    ("entry_exit", {"entries": 5}),
    ("form", {"rows": 5}),
    ("form", {"rows": [{"row_config": "x"}]}),
    ("form", {"columns": 5}),
    ("form", {"auto_source": "x"}),
    ("form", {"event_fields": 5}),
    ("form", {"finance_account_id": 10**30}),
    ("form", {"label": "a\x00b"}),
    ("matrix", {"rows": ["x"]}),
    ("matrix", {"rows": [{"id": "a", "sort_index": "b"}, {"id": "c", "sort_index": 1}]}),
    ("bullet_list", {"bullet_items": 5}),
    ("session_date", {"selected_date": 5}),
]


@pytest.mark.parametrize(("code", "config"), BAD_CONFIGS)
def test_patch_rejects_config_in_wrong_shape(db, monkeypatch, code, config):
    _tenant, protocol, block, user = _setup(db, monkeypatch, code)

    with pytest.raises(HTTPException) as rejected:
        protocol_elements.patch_protocol_element_block(
            block.public_id, ProtocolElementBlockUpdate(configuration_snapshot_json=config), db=db, user=user
        )

    assert rejected.value.status_code == 400
    assert rejected.value.detail["code"] == "invalid_block_config"
    # Erwarteter Fehler: kein Fehlerprotokoll (Ursache ist ein ValueError)
    assert isinstance(rejected.value.__cause__, ValueError)
    db.expire_all()
    assert protocol_elements.list_protocol_elements(protocol.public_id, db=db, user=user)


@pytest.mark.parametrize(
    "value",
    ["99999999999999999999999", "²"],
)
def test_participant_value_that_cannot_be_an_id_is_ignored(db, monkeypatch, value):
    _tenant, protocol, block, user = _setup(db, monkeypatch, "form")

    result = protocol_elements.patch_protocol_element_block(
        block.public_id,
        ProtocolElementBlockUpdate(configuration_snapshot_json={"rows": [{"participant_id": value}], "linked_list_id": value}),
        db=db,
        user=user,
    )

    assert result.participant_names == {}


def test_matrix_card_id_beyond_bigint_is_ignored(db, monkeypatch):
    _tenant, protocol, block, user = _setup(db, monkeypatch, "matrix")

    result = protocol_elements.patch_protocol_element_block(
        block.public_id,
        ProtocolElementBlockUpdate(configuration_snapshot_json={"columns": [{"id": "gen-l-99999999999999999999999"}]}),
        db=db,
        user=user,
    )

    assert result.public_reference_ids["list_entries"] == {}


def test_valid_editor_config_still_saves_and_exports(db, monkeypatch):
    tenant, protocol, block, user = _setup(db, monkeypatch, "attendance")
    person = make_participant(db, tenant.id, "Anna Muster")
    config = {
        "attendance_entries": [{"participant_id": str(person.public_id), "participant_name": "Anna Muster", "status": "present"}],
        "attendance_excluded_participant_ids": [],
        "rows": [{"id": "r1", "sort_index": 0, "row_config": {}}],
        "columns": [{"id": "c1", "sort_index": 1.5}],
        "event_fields": None,
        "selected_date": "2026-11-25",
        "bullet_items": ["a", 1],
        "auto_source": {},
    }

    saved = protocol_elements.patch_protocol_element_block(
        block.public_id, ProtocolElementBlockUpdate(configuration_snapshot_json=config), db=db, user=user
    )

    assert saved.configuration_snapshot_json["attendance_entries"][0]["status"] == "present"
    db.expire_all()
    assert map_block(BuildContext(db=db, tenant_id=tenant.id, language="de"), protocol, block) is not None


@pytest.mark.parametrize("field", ["sort_index", "render_order"])
def test_block_integer_fields_are_bounded(field):
    with pytest.raises(ValidationError):
        ProtocolElementBlockUpdate(**{field: 2**31})
    assert getattr(ProtocolElementBlockUpdate(**{field: 2**31 - 1}), field) == 2**31 - 1


@pytest.mark.parametrize("field", ["sort_index", "section_order_snapshot"])
def test_element_integer_fields_are_bounded(field):
    with pytest.raises(ValidationError):
        ProtocolElementUpdate(**{field: -(2**31) - 1})


def test_shape_check_rejects_non_finite_numbers_and_long_digit_strings_are_no_ids():
    """Security-Review 2026-11-25: NaN/Infinity lehnt JSONB ab; über 4300 Ziffern wirft int()."""
    import pytest as _pytest

    from app.services.block_config_shape import BlockConfigShapeError, bigint_digits, check_block_config_shape

    for value in (float("nan"), float("inf")):
        with _pytest.raises(BlockConfigShapeError):
            check_block_config_shape({"bullet_items": [value]})
    assert bigint_digits("9" * 5000) is None
    assert bigint_digits("12345") == 12345
