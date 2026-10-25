"""Schema der Block-Konfiguration (configuration_json) pro Elementtyp.

Zwei Aufgaben:

1. upgrade_*: hebt Altformate auf das aktuelle Schema. Idempotent, wird von der Migration
   0113_element_config_schema, beim Speichern einer Elementdefinition und beim
   Mandanten-Import genutzt. Danach muss kein Leser mehr Altformate umdeuten.
2. validate_block_config: prüft die Konfiguration eines Blocks gegen das Schema seines Typs
   (unbekannte oder falsch getippte Schlüssel werden abgelehnt statt ungeprüft gespeichert).

Altformate, die upgrade_block_config auflöst:
- field_rows → rows, matrix_columns → columns, matrix_column_source* → auto_source,
  matrix_allow_column_management → allow_column_management
- Zeilen: value_type/embedded_element_type_id → row_type, protocol_editable →
  locked_in_protocol, embedded_configuration_json + verstreute Filterschlüssel → row_config,
  source_field_* → auto_source_field
- Terminfilter: event_tag_filter, event_title_filter, event_description_filter,
  event_window_*, event_date_mode, event_only_*, event_cycle_offset, use_column_title_as_tag,
  hide_past_events, event_use_column_tag_filter, auto_source.event_tag_filter/cycle_* →
  event_filter / repeat_event_filter / auto_source.event_filter (siehe event_filter.py)
- block_type_code (Duplikat von block_kind), cycle_key im Diagramm (nur Protokoll-Zustand)
- title_as_subtitle → Feld des Blocks wie die übrigen Verhaltens-Schalter
- fine_account_id/fine_amount_* → fines_enabled (Tarif zentral in fine_tariff)
- finance_filter_type "since_last_session" mit festem Datum → "since_date"
"""
from __future__ import annotations

from datetime import time
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.core.element_types import element_type, element_type_code, is_known_element_type
from app.services.event_filter import normalize_event_filter, split_tags

# --- Altformat → aktuelles Schema ---------------------------------------------------------

_LEGACY_EVENT_KEYS = (
    "event_tag_filter",
    "event_title_filter",
    "event_description_filter",
    "event_window_start_days",
    "event_window_end_days",
    "event_date_mode",
    "event_only_from_protocol_date",
    "event_only_before_protocol_date",
    "event_only_current_cycle",
    "event_cycle_offset",
)
_LEGACY_ROW_FILTER_KEYS = ("event_tag_filter", "event_title_filter", "use_column_title_as_tag", "hide_past_events")
_EVENT_LIST_DISPLAY_KEYS = (
    "event_gray_past",
    "event_allow_end_date",
    "event_show_date",
    "event_show_tag",
    "event_show_tag_colors",
    "event_show_title",
    "event_show_description",
    "event_show_participant_count",
    "event_show_cancelled",
)
_SIMPLE_ROW_TYPES = {"text", "participant", "participants", "event", "events", "list_entry"}


def _event_list_filter_from_legacy(config: dict) -> dict:
    """Terminliste (7) und eingebettete Terminliste: ab/vor Protokolldatum + Zyklus-Offset."""
    if config.get("event_only_before_protocol_date") is True:
        mode = "past"
    elif config.get("event_only_from_protocol_date", True) is False:
        mode = "all"
    else:
        mode = "future"
    offset = config.get("event_cycle_offset")
    if isinstance(offset, (int, float)) and not isinstance(offset, bool):
        cycle: dict | None = {"config_id": None, "offset": int(offset)}
    elif config.get("event_only_current_cycle") is True:
        cycle = {"config_id": None, "offset": 0}
    else:
        cycle = None
    return normalize_event_filter(
        {
            "tags": split_tags(config.get("event_tag_filter")),
            "title": config.get("event_title_filter") or "",
            "range": {"mode": mode},
            "cycle": cycle,
            "use_column_filter": config.get("event_use_column_tag_filter") is True,
        }
    )


def _repeat_filter_from_legacy(config: dict) -> dict:
    """Wiederholung «Pro Termin»: Zeitfenster bzw. «alle künftigen», plus «nur vor Protokolldatum»."""
    try:
        start_days = int(config.get("event_window_start_days") or 0)
        end_days = int(config.get("event_window_end_days") if config.get("event_window_end_days") is not None else 14)
    except (TypeError, ValueError):
        start_days, end_days = 0, 14
    all_future = str(config.get("event_date_mode") or "relative_window") == "all_future"
    if config.get("event_only_before_protocol_date") is True:
        # Bisher: Termine nach dem Protokolldatum fallen weg. Als Fenster, das spätestens am
        # Protokolldatum endet (bei «alle künftigen» bleibt nur das Protokolldatum selbst).
        end_days = 0 if all_future else min(end_days, 0)
        start_days = 0 if all_future else min(start_days, end_days)
        event_range = {"mode": "window", "start_days": start_days, "end_days": end_days}
    elif all_future:
        event_range = {"mode": "future"}
    else:
        event_range = {"mode": "window", "start_days": start_days, "end_days": end_days}
    return normalize_event_filter(
        {
            "tags": split_tags(config.get("event_tag_filter")),
            "title": config.get("event_title_filter") or "",
            "description": config.get("event_description_filter") or "",
            "range": event_range,
        }
    )


def _matrix_events_row_filter_from_legacy(row_config: dict, *, columns_have_tag_filter: bool) -> dict:
    hide_past = row_config.get("hide_past_events", True) is not False
    use_column_title = row_config.get("use_column_title_as_tag", True) is not False
    return normalize_event_filter(
        {
            "tags": split_tags(row_config.get("event_tag_filter")),
            "title": row_config.get("event_title_filter") or "",
            "range": {"mode": "future" if hide_past else "all"},
            # Bisher wirkte der Spalten-Tag-Filter immer und der Spaltentitel optional - jetzt
            # ein Mechanismus: Spalten-Tag-Filter, sonst Spaltentitel.
            "use_column_filter": use_column_title or columns_have_tag_filter,
        }
    )


def _row_type(row: dict) -> str:
    if row.get("row_type"):
        return str(row["row_type"])
    if row.get("embedded_element_type_id"):
        return str(row["embedded_element_type_id"])
    return str(row.get("value_type") or "text")


_DEFINITION_ROW_KEYS = (
    "id",
    "label",
    "row_type",
    "locked_in_protocol",
    "row_config",
    "auto_source_field",
    "template_value",
    "template_participant_id",
    "template_participant_ids",
    "template_event_id",
    "sort_index",
)


def _upgrade_row(row: Any, *, columns_have_tag_filter: bool, definition: bool) -> Any:
    """definition=True: Zeile einer Elementdefinition, nur Schema-Schlüssel bleiben.
    definition=False: Matrixzeile im Protokoll-Snapshot, Laufzeit-Schlüssel bleiben."""
    if not isinstance(row, dict):
        return row
    row = dict(row)
    if not row.get("label") and row.get("title"):
        row["label"] = row["title"]
    row_type = _row_type(row)
    if row_type == "list_entry" and row.get("linked_list_id") and not (row.get("row_config") or {}).get("linked_list_id"):
        row["row_config"] = {**(row.get("row_config") or {}), "linked_list_id": row["linked_list_id"]}
    if isinstance(row.get("row_config"), dict):
        row_config = dict(row["row_config"])
    else:
        row_config = dict(row.get("embedded_configuration_json") or {}) if isinstance(row.get("embedded_configuration_json"), dict) else {}
        for key in _LEGACY_ROW_FILTER_KEYS:
            if key in row:
                row_config.setdefault(key, row[key])
    if row_type == "events" and "event_filter" not in row_config:
        row_config["event_filter"] = _matrix_events_row_filter_from_legacy(row_config, columns_have_tag_filter=columns_have_tag_filter)
    elif row_type == "7" and "event_filter" not in row_config:
        row_config["event_filter"] = _event_list_filter_from_legacy(row_config)
    elif "event_filter" in row_config:
        row_config["event_filter"] = normalize_event_filter(row_config["event_filter"])
    for key in (*_LEGACY_ROW_FILTER_KEYS, *_LEGACY_EVENT_KEYS, "event_use_column_tag_filter", "block_type_code"):
        row_config.pop(key, None)

    upgraded = {
        key: value
        for key, value in row.items()
        if key
        not in {
            "value_type",
            "embedded_element_type_id",
            "embedded_configuration_json",
            "protocol_editable",
            "source_field_participant",
            "source_field_event",
            "source_field_list",
            *_LEGACY_ROW_FILTER_KEYS,
        }
    }
    upgraded["row_type"] = row_type
    upgraded["locked_in_protocol"] = (
        bool(row.get("locked_in_protocol")) if "locked_in_protocol" in row else not bool(row.get("protocol_editable", True))
    )
    upgraded["row_config"] = row_config
    auto_source_field = row.get("auto_source_field") or row.get("source_field_participant") or row.get("source_field_event") or row.get("source_field_list")
    upgraded["auto_source_field"] = auto_source_field or None
    if definition:
        upgraded = {key: upgraded[key] for key in _DEFINITION_ROW_KEYS if key in upgraded}
        upgraded["id"] = str(upgraded.get("id") or "")
    return upgraded


def _upgrade_columns(config: dict) -> list:
    raw = config.get("columns") if isinstance(config.get("columns"), list) else config.get("matrix_columns")
    return list(raw) if isinstance(raw, list) else []


def _upgrade_auto_source(config: dict) -> dict | None:
    auto_source = config.get("auto_source")
    if not isinstance(auto_source, dict):
        legacy_type = config.get("matrix_column_source")
        if not legacy_type:
            return None
        auto_source = {
            "type": legacy_type,
            "list_id": config.get("matrix_column_source_list_id"),
            "event_tag_filter": config.get("matrix_column_source_event_tag"),
        }
    auto_source = dict(auto_source)
    if auto_source.get("type") not in ("participants", "events", "list"):
        return None
    if "event_filter" not in auto_source:
        cycle_config_id = auto_source.get("cycle_config_id")
        auto_source["event_filter"] = normalize_event_filter(
            {
                "tags": split_tags(auto_source.get("event_tag_filter")),
                "cycle": {"config_id": cycle_config_id, "offset": auto_source.get("cycle_offset") or 0} if cycle_config_id else None,
            }
        )
    else:
        auto_source["event_filter"] = normalize_event_filter(auto_source["event_filter"])
    for key in ("event_tag_filter", "cycle_config_id", "cycle_offset"):
        auto_source.pop(key, None)
    if auto_source["type"] != "events":
        auto_source["event_filter"] = None
    if auto_source["type"] != "list":
        auto_source["list_id"] = None
    auto_source.setdefault("list_id", None)
    auto_source.setdefault("sort", "source")
    return auto_source


def upgrade_block_config(element_type_id: int | str | None, config: dict | None, *, snapshot: bool = False) -> dict:
    """Hebt die configuration_json eines Blocks auf das aktuelle Schema. Unbekannte,
    nicht-veraltete Schlüssel bleiben erhalten. snapshot=True für configuration_snapshot_json
    eines Protokollblocks: Tabellenzeilen haben dort ein eigenes Laufzeitformat (value_type,
    text_value, …) und bleiben unverändert, Matrixzeilen behalten ihre Laufzeit-Schlüssel."""
    config = dict(config or {})
    code = element_type_code(element_type_id)
    type_id = int(element_type(element_type_id)["id"])

    # Wiederholung «Pro Termin» (alle Typen)
    if str(config.get("repeat_source") or "none") == "event":
        if "repeat_event_filter" not in config:
            config["repeat_event_filter"] = _repeat_filter_from_legacy(config)
        else:
            config["repeat_event_filter"] = normalize_event_filter(config["repeat_event_filter"])
    else:
        config.pop("repeat_event_filter", None)

    if type_id == 7 or code == "event_list":
        if "event_filter" not in config:
            config["event_filter"] = _event_list_filter_from_legacy(config)
        else:
            config["event_filter"] = normalize_event_filter(config["event_filter"], default_range_mode="future")
    elif code == "session_date":
        if "event_filter" not in config:
            config["event_filter"] = normalize_event_filter({"tags": split_tags(config.get("event_tag_filter"))})
        else:
            config["event_filter"] = normalize_event_filter(config["event_filter"])
    else:
        config.pop("event_filter", None)

    if code == "matrix" or (code == "form" and not snapshot):
        columns = _upgrade_columns(config)
        columns_have_tag_filter = any(isinstance(c, dict) and str(c.get("event_tag_filter") or "").strip() for c in columns)
        raw_rows = config.get("rows") if isinstance(config.get("rows"), list) else config.get("field_rows")
        config["rows"] = [
            _upgrade_row(row, columns_have_tag_filter=columns_have_tag_filter, definition=not snapshot)
            for row in (raw_rows or [])
        ]
        if code == "matrix":
            config["columns"] = columns
            config["mode"] = "auto" if config.get("mode") == "auto" else "manual"
            config["allow_column_management"] = bool(
                config.get("allow_column_management", config.get("matrix_allow_column_management", True))
            )
            config["auto_source"] = _upgrade_auto_source(config)

    if code == "attendance" and "fines_enabled" not in config:
        config["fines_enabled"] = bool(config.get("fine_account_id"))
    if code == "finance_transactions" and config.get("finance_filter_type") == "since_last_session" and config.get("finance_since_date"):
        config["finance_filter_type"] = "since_date"

    if not (snapshot and code == "form"):
        config.pop("field_rows", None)
    for key in (
        *_LEGACY_EVENT_KEYS,
        "matrix_columns",
        "matrix_column_source",
        "matrix_column_source_list_id",
        "matrix_column_source_event_tag",
        "matrix_allow_column_management",
        "block_type_code",
        "fine_account_id",
        "fine_amount_late",
        "fine_amount_absent",
    ):
        config.pop(key, None)
    if code == "chart":
        config.pop("cycle_key", None)
    config["block_kind"] = code
    return config


def upgrade_definition_block(block: dict) -> dict:
    """Ein Block aus element_definition.configuration_json["blocks"]."""
    block = dict(block)
    config = dict(block.get("configuration_json") or {})
    if "title_as_subtitle" not in block:
        block["title_as_subtitle"] = bool(config.get("title_as_subtitle", True))
    config.pop("title_as_subtitle", None)
    upgraded = upgrade_block_config(block.get("element_type_id"), config)
    # Der frühere Editor speicherte alle ~80 Formularfelder bei jedem Typ (ein Textblock
    # trug chart_type, mode, finance_filter_type, …). Nur Schlüssel des Typ-Schemas bleiben.
    model = _CONFIG_MODELS.get(element_type_code(block.get("element_type_id")))
    if model is not None:
        upgraded = {key: value for key, value in upgraded.items() if key in model.model_fields}
    block["configuration_json"] = upgraded
    return block


def upgrade_snapshot_config(element_type_id: int | str | None, config: dict | None) -> dict:
    """configuration_snapshot_json eines Protokollblocks inkl. eingebetteter Blöcke in
    Matrixzellen. Die Snapshot-eigenen Schlüssel (title_as_subtitle, cycle_key im Diagramm,
    erfasste Werte) bleiben erhalten."""
    original = dict(config or {})
    upgraded = upgrade_block_config(element_type_id, original, snapshot=True)
    for key in ("title_as_subtitle", "cycle_key"):
        if key in original:
            upgraded[key] = original[key]
    if element_type_code(element_type_id) == "matrix":
        upgraded["columns"] = [_upgrade_snapshot_column(column) for column in upgraded.get("columns") or []]
    return upgraded


def _upgrade_snapshot_column(column: Any) -> Any:
    if not isinstance(column, dict):
        return column
    column = dict(column)
    for values_key in ("row_values", "values"):
        values = column.get(values_key)
        if not isinstance(values, dict):
            continue
        next_values = {}
        for row_id, cell in values.items():
            if isinstance(cell, dict) and isinstance(cell.get("embedded_block"), dict):
                embedded = dict(cell["embedded_block"])
                embedded["configuration_snapshot_json"] = upgrade_snapshot_config(
                    embedded.get("element_type_id"), embedded.get("configuration_snapshot_json")
                )
                cell = {**cell, "embedded_block": embedded}
            next_values[row_id] = cell
        column[values_key] = next_values
    return column


def upgrade_template_element_config(config: dict | None) -> dict:
    """template_element.configuration_json: ältere Vorlagen trugen die Wiederholung eines
    Ein-Block-Elements hier statt am Block (protocol_service: legacy_repeat_config)."""
    config = dict(config or {})
    if str(config.get("repeat_source") or "none") == "event" and "repeat_event_filter" not in config:
        config["repeat_event_filter"] = _repeat_filter_from_legacy(config)
    for key in _LEGACY_EVENT_KEYS:
        config.pop(key, None)
    return config


# --- Validierung pro Typ -------------------------------------------------------------------


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EventRangeConfig(_Strict):
    mode: Literal["all", "future", "past", "window"] = "all"
    start_days: int = Field(default=0, ge=-3650, le=3650)
    end_days: int = Field(default=14, ge=-3650, le=3650)


class EventCycleConfig(_Strict):
    config_id: str | None = None
    offset: int = Field(default=0, ge=-10, le=10)


class EventFilterConfig(_Strict):
    tags: list[str] = Field(default_factory=list)
    title: str = ""
    description: str = ""
    range: EventRangeConfig = Field(default_factory=EventRangeConfig)
    cycle: EventCycleConfig | None = None
    use_column_filter: bool = False
    sort: Literal["asc", "desc"] = "asc"
    limit: int | None = Field(default=None, ge=1, le=500)


class EventFieldConfig(_Strict):
    field: str
    label: str = ""
    enabled: bool = False


class TableRowConfig(BaseModel):
    # row_config ist je nach Zeilentyp frei (eingebettete Blöcke tragen die Konfiguration
    # ihres Typs, «Zeile aus Liste» die Liste); nur event_filter wird streng geprüft.
    model_config = ConfigDict(extra="allow")
    event_filter: EventFilterConfig | None = None


class TableRow(_Strict):
    id: str | int
    label: str = ""
    row_type: str = "text"
    locked_in_protocol: bool = False
    row_config: TableRowConfig = Field(default_factory=TableRowConfig)
    auto_source_field: str | None = None
    template_value: str | None = ""
    template_participant_id: Any = None
    template_participant_ids: list[Any] = Field(default_factory=list)
    template_event_id: Any = None
    sort_index: int | None = None

    @field_validator("row_type")
    @classmethod
    def _known_row_type(cls, value: str) -> str:
        if value in _SIMPLE_ROW_TYPES:
            return value
        if is_known_element_type(value) and element_type(value)["matrix_embeddable"]:
            return value
        raise ValueError(f"unknown row_type {value!r}")


class MatrixColumn(_Strict):
    id: str
    title: str = ""
    event_tag_filter: str | None = None
    title_placeholder: str | None = None
    sort_index: int | None = None
    row_overrides: dict[str, Any] | None = None


class MatrixAutoSource(_Strict):
    type: Literal["participants", "events", "list"]
    list_id: Any = None
    event_filter: EventFilterConfig | None = None
    # Reihenfolge der automatischen Spalten: wie die Quelle liefert oder alphabetisch
    sort: Literal["source", "alpha", "alpha_desc", "last_name"] = "source"


class BlockConfigBase(_Strict):
    block_kind: str | None = None
    repeat_source: Literal["none", "event", "todo"] = "none"
    repeat_event_filter: EventFilterConfig | None = None
    event_include_unlisted_past: bool = False
    todo_block_title_filter: str | None = None
    todo_task_filter: str | None = None
    todo_open_only: bool = True
    sync_target_field: str | None = None


class TextConfig(BlockConfigBase):
    pass


class TodoConfig(BlockConfigBase):
    todo_due_tag_filter: str | None = None
    todo_assignee_participant_id: Any = None


class FormConfig(BlockConfigBase):
    rows: list[TableRow] = Field(default_factory=list)
    left_column_heading: str | None = None
    value_column_heading: str | None = None
    linked_list_id: Any = None
    linked_list_group_by: Literal["column_one", "column_two"] | None = None
    linked_list_sort_by: Literal["column_one", "column_two"] | None = None
    linked_list_sort_direction: Literal["asc", "desc"] | None = None
    linked_list_highlight_empty: bool = False
    linked_list_filter_column: Literal["column_one", "column_two"] | None = None
    linked_list_filter_text: str | None = None
    event_fields: list[EventFieldConfig] | None = None


class EventDisplayMixin(_Strict):
    event_gray_past: bool = True
    event_allow_end_date: bool = False
    event_show_date: bool = True
    event_show_tag: bool = True
    event_show_tag_colors: bool = False
    event_show_title: bool = True
    event_show_description: bool = True
    event_show_participant_count: bool = False
    event_show_cancelled: bool = False
    event_show_location: bool = False
    event_show_end_date: bool = False
    event_show_organizers: bool = False


class EventListConfig(BlockConfigBase, EventDisplayMixin):
    event_filter: EventFilterConfig = Field(default_factory=EventFilterConfig)


class AttendanceConfig(BlockConfigBase):
    fines_enabled: bool = False
    attendance_excluded_participant_ids: list[Any] = Field(default_factory=list)


class SessionDateConfig(BlockConfigBase):
    event_filter: EventFilterConfig = Field(default_factory=EventFilterConfig)


class MatrixConfig(BlockConfigBase):
    mode: Literal["manual", "auto"] = "manual"
    allow_column_management: bool = True
    auto_source: MatrixAutoSource | None = None
    rows: list[TableRow] = Field(default_factory=list)
    columns: list[MatrixColumn] = Field(default_factory=list)
    left_column_heading: str | None = None
    value_column_heading: str | None = None


class FinanceBalanceConfig(BlockConfigBase):
    finance_account_id: Any = None
    finance_balance_date: Literal["today", "protocol_date"] = "today"


class FinanceTransactionsConfig(BlockConfigBase):
    finance_account_id: Any = None
    finance_filter_type: Literal["all", "since_last_session", "since_date", "this_year", "this_cycle", "last_n"] = "all"
    finance_last_n: int | None = Field(default=None, ge=1, le=1000)
    finance_since_date: str | None = None


class FineListConfig(BlockConfigBase):
    fine_list_account_id: Any = None
    fine_list_status: Literal["all", "open"] = "all"
    fine_list_range: Literal["all", "this_protocol", "this_cycle"] = "all"
    fine_list_group_by: Literal["none", "participant"] = "none"


class ChartConfig(BlockConfigBase):
    chart_type: str | None = None
    cycle_config_id: str | None = None
    cycle_offset: int = Field(default=0, ge=-10, le=10)


class EntryExitConfig(BlockConfigBase):
    entry_exit_first_use_mode: Literal["all", "since_date"] = "all"
    entry_exit_first_use_date: str | None = None


_CONFIG_MODELS: dict[str, type[BlockConfigBase]] = {
    "text": TextConfig,
    "todo": TodoConfig,
    "image": TextConfig,
    "display": TextConfig,
    "static_text": TextConfig,
    "form": FormConfig,
    "event_list": EventListConfig,
    "bullet_list": TextConfig,
    "attendance": AttendanceConfig,
    "session_date": SessionDateConfig,
    "matrix": MatrixConfig,
    "finance_balance": FinanceBalanceConfig,
    "finance_transactions": FinanceTransactionsConfig,
    "fine_list": FineListConfig,
    "chart": ChartConfig,
    "entry_exit": EntryExitConfig,
    "session_notes": TextConfig,
}


def validate_block_config(element_type_id: int | str | None, config: dict | None) -> None:
    """Prüft die (bereits auf das aktuelle Schema gehobene) Konfiguration eines Blocks.

    Wirft ValueError mit einer lesbaren Meldung - die Routen geben ValueError als 400 aus.
    """
    if not is_known_element_type(element_type_id):
        raise ValueError(f"Unbekannter Elementtyp {element_type_id}")
    model = _CONFIG_MODELS[element_type_code(element_type_id)]
    try:
        model.model_validate(config or {})
    except ValidationError as exc:
        first = exc.errors()[0]
        location = ".".join(str(part) for part in first.get("loc", ()))
        raise ValueError(
            f"Ungültige Konfiguration für Elementtyp {element_type_code(element_type_id)}: {location}: {first.get('msg')}"
        ) from None


def event_list_display_keys() -> tuple[str, ...]:
    return _EVENT_LIST_DISPLAY_KEYS


def derive_fine_tariff(definition_configs: list[dict | None]) -> dict | None:
    """Häufigster Bussentarif (Konto, «zu spät», «abwesend») der Anwesenheitsblöcke in den
    noch nicht gehobenen element_definition.configuration_json eines Mandanten. Bei
    Gleichstand gewinnt der zuerst gefundene. None, wenn kein Block Bussen konfiguriert hat."""
    from collections import Counter

    counts: Counter[tuple[Any, float, float]] = Counter()
    for config in definition_configs:
        for block in (config or {}).get("blocks") or []:
            if not isinstance(block, dict) or element_type_code(block.get("element_type_id")) != "attendance":
                continue
            block_config = block.get("configuration_json") or {}
            account_id = block_config.get("fine_account_id")
            if not account_id:
                continue
            counts[(account_id, _amount(block_config.get("fine_amount_late")), _amount(block_config.get("fine_amount_absent")))] += 1
    if not counts:
        return None
    (account_id, amount_late, amount_absent), _ = counts.most_common(1)[0]
    return {"account_id": account_id, "amount_late": amount_late, "amount_absent": amount_absent}


def _amount(value: Any) -> float:
    try:
        return max(0.0, round(float(value or 0), 2))
    except (TypeError, ValueError):
        return 0.0


def parse_session_time(value: object) -> time | None:
    """``selected_time`` des Blocks «Nächste Sitzung» (``HH:MM``) → ``time``; leer oder
    ungültig = keine Uhrzeit (ganztägig), nie ein Abbruch beim Speichern."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = time.fromisoformat(value.strip())
    except ValueError:
        return None
    return parsed.replace(second=0, microsecond=0, tzinfo=None)
