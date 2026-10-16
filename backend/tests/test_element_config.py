"""Altformat-Upgrade (element_config.py) und gemeinsamer Terminfilter (event_filter.py)."""
from datetime import date
from types import SimpleNamespace

from app.services.element_config import (
    derive_fine_tariff,
    upgrade_definition_block,
    upgrade_snapshot_config,
    upgrade_template_element_config,
    validate_block_config,
)
from app.services.event_filter import column_filter_tags, event_matches_filter, normalize_event_filter, sort_and_limit


def _event(event_id, title, start, tag="", end=None, description=""):
    return SimpleNamespace(id=event_id, title=title, event_date=start, event_end_date=end, tag=tag, description=description)


# --- Upgrade --------------------------------------------------------------------------------


def test_event_list_legacy_cycle_and_date_flags_become_event_filter():
    block = upgrade_definition_block({
        "id": 1, "element_type_id": 7, "title": "Termine",
        "configuration_json": {"event_tag_filter": "gv, sitzung", "event_only_current_cycle": True, "event_show_date": False},
    })
    config = block["configuration_json"]
    assert config["event_filter"]["tags"] == ["gv", "sitzung"]
    assert config["event_filter"]["range"]["mode"] == "future"
    assert config["event_filter"]["cycle"] == {"config_id": None, "offset": 0}
    assert config["event_show_date"] is False
    assert "event_tag_filter" not in config
    validate_block_config(7, config)


def test_event_list_cycle_offset_and_before_protocol_date():
    config = upgrade_definition_block({
        "id": 1, "element_type_id": 7, "title": "Termine",
        "configuration_json": {"event_cycle_offset": -1, "event_only_before_protocol_date": True},
    })["configuration_json"]
    assert config["event_filter"]["cycle"] == {"config_id": None, "offset": -1}
    assert config["event_filter"]["range"]["mode"] == "past"


def test_repeat_per_event_window_and_only_before_protocol_date():
    window = upgrade_definition_block({
        "id": 1, "element_type_id": 1, "title": "Pro Termin",
        "configuration_json": {"repeat_source": "event", "event_window_start_days": -7, "event_window_end_days": 21, "event_title_filter": "GV"},
    })["configuration_json"]["repeat_event_filter"]
    assert window["range"] == {"mode": "window", "start_days": -7, "end_days": 21}
    assert window["title"] == "GV"

    clipped = upgrade_definition_block({
        "id": 1, "element_type_id": 1, "title": "Pro Termin",
        "configuration_json": {"repeat_source": "event", "event_window_start_days": -7, "event_window_end_days": 21, "event_only_before_protocol_date": True},
    })["configuration_json"]["repeat_event_filter"]
    assert clipped["range"] == {"mode": "window", "start_days": -7, "end_days": 0}


def test_matrix_legacy_rows_columns_and_auto_source():
    config = upgrade_definition_block({
        "id": 1, "element_type_id": 11, "title": "Matrix",
        "configuration_json": {
            "mode": "auto",
            "matrix_allow_column_management": False,
            "matrix_column_source": "events",
            "matrix_column_source_event_tag": "hock",
            "field_rows": [
                {"id": 1, "title": "Termine", "value_type": "events", "use_column_title_as_tag": False, "hide_past_events": False},
                {"id": 2, "label": "Liste", "embedded_element_type_id": 7, "embedded_configuration_json": {"event_use_column_tag_filter": True}},
                {"id": 3, "label": "Text", "protocol_editable": False, "source_field_event": "title"},
            ],
            "matrix_columns": [{"id": "c1", "title": "Vorstand", "event_tag_filter": "vorstand"}],
        },
    })["configuration_json"]
    assert config["allow_column_management"] is False
    assert config["auto_source"]["type"] == "events"
    assert config["auto_source"]["event_filter"]["tags"] == ["hock"]
    events_row, list_row, text_row = config["rows"]
    assert events_row["label"] == "Termine" and events_row["row_type"] == "events"
    # Spalten-Tag-Filter wirkte bisher immer - bleibt über use_column_filter erhalten.
    assert events_row["row_config"]["event_filter"]["use_column_filter"] is True
    assert events_row["row_config"]["event_filter"]["range"]["mode"] == "all"
    assert list_row["row_type"] == "7"
    assert list_row["row_config"]["event_filter"]["use_column_filter"] is True
    assert text_row["locked_in_protocol"] is True and text_row["auto_source_field"] == "title"
    assert config["columns"][0]["id"] == "c1"
    validate_block_config(11, config)


def test_upgrade_is_idempotent():
    block = {
        "id": 1, "element_type_id": 11, "title": "Matrix",
        "configuration_json": {"field_rows": [{"id": 1, "value_type": "events"}], "matrix_columns": []},
    }
    once = upgrade_definition_block(block)
    assert upgrade_definition_block(once) == once


def test_snapshot_keeps_runtime_form_rows_and_upgrades_embedded_event_lists():
    form = upgrade_snapshot_config(6, {"rows": [{"id": "1", "value_type": "participant", "participant_id": 5}], "event_tag_filter": "x"})
    assert form["rows"] == [{"id": "1", "value_type": "participant", "participant_id": 5}]
    assert "event_tag_filter" not in form

    matrix = upgrade_snapshot_config(11, {
        "title_as_subtitle": False,
        "rows": [{"id": "r1", "row_type": "7", "row_config": {}}],
        "columns": [{"id": "c1", "row_values": {"r1": {"embedded_block": {"element_type_id": 7, "configuration_snapshot_json": {"event_only_from_protocol_date": False}}}}}],
    })
    embedded = matrix["columns"][0]["row_values"]["r1"]["embedded_block"]["configuration_snapshot_json"]
    assert embedded["event_filter"]["range"]["mode"] == "all"
    assert matrix["title_as_subtitle"] is False


def test_attendance_fines_move_to_tariff():
    configs = [
        {"blocks": [{"element_type_id": 9, "configuration_json": {"fine_account_id": 7, "fine_amount_late": 5, "fine_amount_absent": 10}}]},
        {"blocks": [{"element_type_id": 9, "configuration_json": {"fine_account_id": 7, "fine_amount_late": 5, "fine_amount_absent": 10}}]},
        {"blocks": [{"element_type_id": 9, "configuration_json": {"fine_account_id": 8, "fine_amount_late": 2, "fine_amount_absent": 3}}]},
    ]
    assert derive_fine_tariff(configs) == {"account_id": 7, "amount_late": 5.0, "amount_absent": 10.0}
    assert derive_fine_tariff([{"blocks": []}]) is None

    config = upgrade_definition_block({"id": 1, "element_type_id": 9, "title": "Anwesenheit", "configuration_json": configs[2]["blocks"][0]["configuration_json"]})["configuration_json"]
    assert config == {"block_kind": "attendance", "fines_enabled": True}


def test_template_element_legacy_repeat_config():
    config = upgrade_template_element_config({"repeat_source": "event", "event_tag_filter": "lager", "responsibility": {"assignments": []}})
    assert config["repeat_event_filter"]["tags"] == ["lager"]
    assert "event_tag_filter" not in config
    assert config["responsibility"] == {"assignments": []}


def test_finance_transactions_fixed_date_becomes_since_date():
    config = upgrade_definition_block({
        "id": 1, "element_type_id": 13, "title": "Transaktionen",
        "configuration_json": {"finance_filter_type": "since_last_session", "finance_since_date": "2026-01-01"},
    })["configuration_json"]
    assert config["finance_filter_type"] == "since_date"


# --- Terminfilter -----------------------------------------------------------------------------


def test_tags_match_contains_case_insensitive():
    event_filter = normalize_event_filter({"tags": ["sitzung"]})
    assert event_matches_filter(_event(1, "A", date(2026, 1, 1), tag="Vorstandssitzung"), event_filter, protocol_date=None)
    assert not event_matches_filter(_event(2, "B", date(2026, 1, 1), tag="lager"), event_filter, protocol_date=None)


def test_range_modes_relative_to_protocol_date():
    protocol_date = date(2026, 6, 1)
    past = _event(1, "Vorher", date(2026, 5, 1))
    multi_day = _event(2, "Lager", date(2026, 5, 30), end=date(2026, 6, 2))
    later = _event(3, "Später", date(2026, 7, 1))

    def titles(mode, **extra):
        event_filter = normalize_event_filter({"range": {"mode": mode, **extra}})
        return [e.title for e in (past, multi_day, later) if event_matches_filter(e, event_filter, protocol_date=protocol_date)]

    assert titles("all") == ["Vorher", "Lager", "Später"]
    assert titles("future") == ["Lager", "Später"]
    assert titles("past") == ["Vorher"]
    assert titles("window", start_days=-3, end_days=3) == ["Lager"]


def test_column_filter_uses_tag_filter_then_title():
    assert column_filter_tags({"title": "Vorstand", "event_tag_filter": "vs, präsidium"}) == ["vs", "präsidium"]
    assert column_filter_tags({"title": "Vorstand"}) == ["Vorstand"]
    event_filter = normalize_event_filter({"use_column_filter": True})
    assert event_matches_filter(_event(1, "A", date(2026, 1, 1), tag="vorstand"), event_filter, protocol_date=None, column={"title": "Vorstand"})
    assert not event_matches_filter(_event(2, "B", date(2026, 1, 1), tag="lager"), event_filter, protocol_date=None, column={"title": "Vorstand"})


def test_title_description_cycle_sort_and_limit():
    event_filter = normalize_event_filter({"title": "gv", "description": "wahl", "sort": "desc", "limit": 1})
    events = [
        _event(1, "GV 2025", date(2025, 3, 1), description="Wahlen"),
        _event(2, "GV 2026", date(2026, 3, 1), description="Wahlen"),
        _event(3, "Hock", date(2026, 4, 1), description="Wahlen"),
    ]
    matching = [e for e in events if event_matches_filter(e, event_filter, protocol_date=None, cycle_event_ids={1, 2})]
    assert [e.title for e in sort_and_limit(matching, event_filter)] == ["GV 2026"]
    assert not event_matches_filter(events[1], event_filter, protocol_date=None, cycle_event_ids={1})
