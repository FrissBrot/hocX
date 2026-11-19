"""Nachtlauf 2026-11-19 (Verdacht «ListEntry-Dekodierung in Vorlagen»): ListEntry hat keine eigene
tenant_id, ``resolve_internal_id(..., tenant_id=...)`` ignorierte den Mandanten deshalb. Vorlagen
(Verantwortlichen-Zuweisungen, Zeilen mit fester Listenzeile) nahmen so Einträge fremder Mandanten
oder anderer Listen an. Jetzt nur Einträge der genannten Liste im eigenen Mandanten."""

import pytest

from app.services.block_config_ids import decode_block_config
from app.services.responsible_label_service import resolve_responsible_label
from tests.factories import make_list_definition, make_list_entry, make_participant, make_tenant


def _lists(db):
    tenant = make_tenant(db, "Eigener Verein")
    foreign_tenant = make_tenant(db, "Fremder Verein")
    own_list = make_list_definition(db, tenant.id, name="Ämtli")
    other_list = make_list_definition(db, tenant.id, name="Andere Liste")
    foreign_list = make_list_definition(db, foreign_tenant.id, name="Fremde Liste")
    return (
        tenant,
        own_list,
        make_list_entry(db, own_list.id, first_value={"text_value": "Kasse"}),
        make_list_entry(db, other_list.id, first_value={"text_value": "Anderes"}),
        foreign_list,
        make_list_entry(db, foreign_list.id, first_value={"text_value": "Fremd"}),
    )


def _assignment(list_id, entry_id):
    return {"responsibility": {"assignments": [{"list_definition_id": str(list_id), "list_entry_id": str(entry_id)}]}}


def _row(list_id, entry_id):
    return {"rows": [{"row_config": {"linked_list_id": str(list_id), "linked_list_entry_id": str(entry_id)}}]}


@pytest.mark.parametrize("build", [_assignment, _row])
def test_decode_accepts_entry_of_the_named_own_list(db, build):
    tenant, own_list, own_entry, *_ = _lists(db)

    decoded = decode_block_config(db, build(own_list.public_id, own_entry.public_id), tenant_id=tenant.id)

    assert own_entry.id in (
        [a["list_entry_id"] for a in decoded.get("responsibility", {}).get("assignments", [])]
        + [r["row_config"]["linked_list_entry_id"] for r in decoded.get("rows", [])]
    )


@pytest.mark.parametrize("build", [_assignment, _row])
def test_decode_rejects_entry_of_a_foreign_tenant(db, build):
    tenant, own_list, _own_entry, _other_entry, _foreign_list, foreign_entry = _lists(db)

    with pytest.raises(ValueError):
        decode_block_config(db, build(own_list.public_id, foreign_entry.public_id), tenant_id=tenant.id)


@pytest.mark.parametrize("build", [_assignment, _row])
def test_decode_rejects_entry_of_another_list(db, build):
    tenant, own_list, _own_entry, other_entry, *_ = _lists(db)

    with pytest.raises(ValueError):
        decode_block_config(db, build(own_list.public_id, other_entry.public_id), tenant_id=tenant.id)


def test_responsible_label_ignores_a_foreign_list(db):
    """Auch ohne gültige Personen-ID darf eine fremde Liste nichts beitragen - auch nicht die
    interne ID einer fremden Person als «Teilnehmer <id>»."""
    tenant = make_tenant(db, "Eigener Verein")
    foreign_tenant = make_tenant(db, "Fremder Verein")
    foreign_person = make_participant(db, foreign_tenant.id, "Fritz Fremd")
    foreign_list = make_list_definition(db, foreign_tenant.id, name="Fremde Ämtli", second_title="Wer", second_type="participant")
    foreign_entry = make_list_entry(db, foreign_list.id, first_value={"text_value": "Kasse"}, second_value={"participant_id": foreign_person.id})

    for batch in (False, True):
        label = resolve_responsible_label(
            db,
            [{"list_definition_id": foreign_list.id, "list_entry_id": foreign_entry.id}],
            "display_name",
            live=True,
            tenant_id=tenant.id,
            entries_by_id={foreign_entry.id: foreign_entry} if batch else None,
            definitions_by_id={foreign_list.id: foreign_list} if batch else None,
        )
        assert label == ""
