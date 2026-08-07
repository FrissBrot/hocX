"""Tests for the list-row grouping-variant logic in word_import_service.py - added
after a real imported document ("1. Hock vom 14.10.2026.docx", word_import_document
id=32) showed a "Sponsoring" list row ("Enea" | "Omlin & Partner Gmbh, Felsenheim,
Dolomiten Sport") getting garbled: the template groups this list by the responsible
person (column_two), so the document writes one row per person with all their
sponsors crammed into a single comma-separated cell, but the importer mapped cells
1:1 onto columns and ran the sponsor list through participant-name splitting (which
also incorrectly split on "&", breaking "Omlin & Partner Gmbh" into two pieces).

These are pure unit tests against the private grouping helpers - no DB needed, since
_build_list_row_variants/_score_list_variant/_select_list_row_variant only read plain
attributes off ListDefinition/ListEntry instances that are never persisted here."""
from app.models import ListDefinition, ListEntry
from app.services import word_import_service as svc


def _sponsoring_definition() -> ListDefinition:
    return ListDefinition(
        name="Sponsoring",
        column_one_title="Sponsor",
        column_one_value_type="text",
        column_two_title="Verantwortlich",
        column_two_value_type="participant",
    )


def _sponsoring_entry(sponsor: str, participant_id: int) -> ListEntry:
    return ListEntry(
        column_one_value_json={"text_value": sponsor},
        column_two_value_json={"participant_id": participant_id},
    )


def test_flat_variant_wins_when_document_already_matches_column_order():
    definition = _sponsoring_definition()
    existing = [_sponsoring_entry("Raiffeisen", 2)]
    rows = [["Raiffeisen", "Lauri"]]

    strategy, candidates, needs_manual, _available = svc._select_list_row_variant(rows, definition, existing, {}, None)

    assert strategy == "flat"
    assert needs_manual is False
    assert [(c.column_one_raw, c.column_two_raw) for c in candidates] == [("Raiffeisen", "Lauri")]


def test_explode_variant_resolves_the_real_enea_sponsoring_row():
    definition = _sponsoring_definition()
    enea_id = 7
    existing = [
        _sponsoring_entry("Omlin & Partner Gmbh", enea_id),
        _sponsoring_entry("Felsenheim", enea_id),
        _sponsoring_entry("Dolomiten Sport", enea_id),
        _sponsoring_entry("Raiffeisen", 2),
    ]
    rows = [
        ["Enea", "Omlin & Partner Gmbh, Felsenheim, Dolomiten Sport"],
        ["Lauri", "Raiffeisen"],
    ]

    strategy, candidates, needs_manual, available = svc._select_list_row_variant(rows, definition, existing, {}, None)

    assert strategy == "explode_swap:comma"
    assert needs_manual is False
    assert "explode_swap:comma" in available
    # "/" and ";" never occur in this document column, so they must never be offered.
    assert "explode_swap:slash" not in available
    assert "explode_swap:semicolon" not in available
    enea_rows = {(c.column_one_raw, c.column_two_raw) for c in candidates if c.column_two_raw == "Enea"}
    assert enea_rows == {
        ("Omlin & Partner Gmbh", "Enea"),
        ("Felsenheim", "Enea"),
        ("Dolomiten Sport", "Enea"),
    }
    assert all(c.group_filled for c in candidates if c.column_two_raw == "Enea")


def test_best_delimiter_wins_when_several_are_present_in_the_same_cell():
    """One value ("Müller, Meier & Partner") itself contains a comma, so the document
    separates the two sponsors with a semicolon instead. Both "," and ";" split the
    cell into 2+ parts (so both are legitimate candidates per _present_delimiters),
    but only the semicolon split actually matches the two live entries - this is the
    "die Trennung mit der besten Zuweisungsrate wird übernommen" behaviour."""
    definition = _sponsoring_definition()
    group_id = 9
    existing = [
        _sponsoring_entry("Müller, Meier & Partner", group_id),
        _sponsoring_entry("Huber AG", group_id),
    ]
    rows = [["Nevio", "Müller, Meier & Partner; Huber AG"]]

    strategy, candidates, needs_manual, available = svc._select_list_row_variant(rows, definition, existing, {}, None)

    assert strategy == "explode_swap:semicolon"
    assert needs_manual is False
    assert "explode_swap:comma" in available  # a real, considered-but-rejected candidate
    assert {(c.column_one_raw, c.column_two_raw) for c in candidates} == {
        ("Müller, Meier & Partner", "Nevio"),
        ("Huber AG", "Nevio"),
    }


def test_fill_down_variant_recovers_rows_with_blank_first_cell():
    definition = ListDefinition(
        name="Gruppen",
        column_one_title="Name",
        column_one_value_type="text",
        column_two_title="Leiter",
        column_two_value_type="participants",
    )
    existing = [
        ListEntry(column_one_value_json={"text_value": "Bigfoots"}, column_two_value_json={"participant_ids": [1, 2]}),
    ]
    rows = [
        ["Bigfoots", "Jan"],
        ["", "Archie"],
    ]

    variants = svc._build_list_row_variants(rows, definition)

    assert "fill_down" in variants
    filled = variants["fill_down"]
    assert [(c.column_one_raw, c.column_two_raw, c.group_filled) for c in filled] == [
        ("Bigfoots", "Jan", False),
        ("Bigfoots", "Archie", True),
    ]
    # Today's flat variant drops the blank-first-cell row entirely.
    assert [(c.column_one_raw, c.column_two_raw) for c in variants["flat"]] == [("Bigfoots", "Jan")]


def test_needs_manual_grouping_when_target_list_has_no_entries_yet():
    definition = _sponsoring_definition()
    rows = [["Enea", "Omlin & Partner Gmbh, Felsenheim, Dolomiten Sport"]]

    strategy, candidates, needs_manual, available = svc._select_list_row_variant(rows, definition, [], {}, None)

    assert needs_manual is True
    assert strategy == "flat"
    assert [(c.column_one_raw, c.column_two_raw) for c in candidates] == [
        ("Enea", "Omlin & Partner Gmbh, Felsenheim, Dolomiten Sport")
    ]
    # The manual picker still needs to know an "explode:comma" split exists to offer it.
    assert "explode_swap:comma" in available


def test_forced_strategy_override_skips_scoring():
    definition = _sponsoring_definition()
    existing = [_sponsoring_entry("Raiffeisen", 2)]
    rows = [["Enea", "Omlin & Partner Gmbh, Felsenheim, Dolomiten Sport"]]

    strategy, candidates, needs_manual, _available = svc._select_list_row_variant(rows, definition, existing, {}, "flat")

    assert strategy == "flat"
    assert needs_manual is False
    assert len(candidates) == 1
