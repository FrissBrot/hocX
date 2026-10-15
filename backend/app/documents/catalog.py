"""Katalog der Fachkomponenten (``data_block``-Knoten des Document Studio): jede Komponente mit
Gruppe, Parametern (Pydantic), Zugriffsrecht und Provider.

``GET /api/document-studio/catalog`` liefert daraus Gruppen und JSON-Schemata, damit der
Designer die Parameterformulare generieren kann. Referenzfelder tragen ``x-source`` (z. B.
``participants``), damit das Frontend die passende Auswahl lädt. Strukturelemente (Überschrift,
Text, Abstand, Tabelle, QR-Code …) sind keine Katalogeinträge, sondern Layoutknoten (layout.py).

Neue Fachkomponente (siehe docs-site/docs/technik/document-studio.md):
1. Modell in model.py (Block-Union), 2. Parameter + Eintrag hier, 3. Provider in providers/,
4. Basis-Komponente in typst/base/blocks.typ, 5. Beispieldaten in samples.py, 6. Texte
``blockType.<typ>`` und ``empty.<typ>`` in frontend/messages/<locale>/documentPdf.json,
Parameter-Labels in documentStudio.json. ``scripts/check-document-catalog.py`` prüft das.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.documents.model import BLOCK_MODELS

BlockGroup = Literal["protocol", "people", "tasks", "events", "lists", "finance", "statistics", "forms"]
Access = Literal["reader", "writer", "finance"]


def _source(name: str) -> dict:
    return {"x-source": name}


class BlockSpec(BaseModel):
    """Ein Block in einem Rezept bzw. einer Render-Anfrage (noch ohne Daten)."""

    model_config = ConfigDict(extra="forbid")

    type: str
    title: str | None = Field(None, max_length=300)
    hide_if_empty: bool = True
    level: int = Field(1, ge=1, le=4)
    params: dict[str, Any] = Field(default_factory=dict)


class _Params(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NoParams(_Params):
    pass


# ── Struktur ────────────────────────────────────────────────────────────────










# ── Protokoll ───────────────────────────────────────────────────────────────


class ProtocolRefParams(_Params):
    """Leer = Protokoll des Kontexts (beim Protokoll-Export)."""

    protocol_id: uuid.UUID | None = Field(None, json_schema_extra=_source("protocols"))


class ProtocolElementParams(ProtocolRefParams):
    """Leeres ``element_id`` = alle exportsichtbaren Elemente. ``titles_only`` ergibt eine
    Traktandenliste (nur die Abschnittstitel) statt der Inhalte. ``content`` filtert die Blöcke
    der Elemente: ``text`` (nur Texte, Listen, Formulare - Kurz-/Beschlussprotokoll),
    ``text_and_todos`` (zusätzlich Aufgaben)."""

    element_id: uuid.UUID | None = Field(None, json_schema_extra=_source("protocol_elements"))
    include_session_todos: bool = True
    titles_only: bool = False
    content: Literal["all", "text", "text_and_todos"] = "all"
    include_images: bool = True


class SessionDateParams(ProtocolRefParams):
    session_date: date | None = None
    label: str | None = Field(None, max_length=120)


class FormRowParam(_Params):
    label: str = Field("", max_length=200)
    value: str = Field("", max_length=2000)


class FormParams(_Params):
    label_heading: str | None = Field(None, max_length=120)
    value_heading: str | None = Field(None, max_length=120)
    rows: list[FormRowParam] = Field(default_factory=list, max_length=100)




class ProtocolBlockRefParams(_Params):
    protocol_block_id: uuid.UUID | None = Field(None, json_schema_extra=_source("protocol_blocks"))


class EntryExitParams(_Params):
    """Ein-/Austritte aus den Mitgliederdaten (Eintritts-/Austrittsdatum) im Zeitraum."""

    date_from: date | None = None
    date_to: date | None = None


class ImageParams(_Params):
    file_id: uuid.UUID | None = Field(None, json_schema_extra=_source("images"))
    caption: str | None = Field(None, max_length=300)


class ImageGalleryParams(ProtocolRefParams):
    file_ids: list[uuid.UUID] = Field(default_factory=list, max_length=60, json_schema_extra=_source("images"))
    columns: int = Field(2, ge=1, le=3)


# ── Personen ────────────────────────────────────────────────────────────────


RelativePeriod = Literal["", "current_year", "last_year", "last_12_months", "current_month", "last_month"]


class PeriodParams(_Params):
    """Zeitraum: relativ zu heute (``relative``), Zyklus relativ zu heute (wie in der
    Statistik) oder feste Daten - in dieser Priorität."""

    relative: RelativePeriod = ""
    cycle_config_id: uuid.UUID | None = Field(None, json_schema_extra=_source("cycles"))
    cycle_offset: int = Field(0, ge=-3, le=0)
    date_from: date | None = None
    date_to: date | None = None


class AttendanceMatrixParams(PeriodParams):
    template_id: uuid.UUID | None = Field(None, json_schema_extra=_source("templates"))
    show_rates: bool = True


MemberColumn = Literal["email", "role", "joined_at", "left_at", "status"]


class MemberListParams(_Params):
    active_only: bool = True
    columns: list[MemberColumn] = Field(default_factory=lambda: ["email", "joined_at"])
    template_id: uuid.UUID | None = Field(None, json_schema_extra=_source("templates"))


class SignatureFieldParam(_Params):
    label: str | None = Field(None, max_length=120)
    name: str | None = Field(None, max_length=120)


class SignatureFieldsParams(_Params):
    fields: list[SignatureFieldParam] = Field(default_factory=lambda: [SignatureFieldParam(), SignatureFieldParam()], max_length=12)
    with_place_date: bool = True


class AttendanceSheetParams(_Params):
    source: Literal["active_members", "template", "protocol"] = "active_members"
    template_id: uuid.UUID | None = Field(None, json_schema_extra=_source("templates"))
    protocol_id: uuid.UUID | None = Field(None, json_schema_extra=_source("protocols"))
    columns: list[str] = Field(default_factory=list, max_length=6)
    blank_rows: int = Field(3, ge=0, le=50)


# ── Aufgaben ────────────────────────────────────────────────────────────────

TodoColumn = Literal["status", "assignee", "due", "protocol", "tags"]


class TodoTableParams(_Params):
    status: Literal["all", "open", "done"] = "open"
    participant_id: uuid.UUID | None = Field(None, json_schema_extra=_source("participants"))
    tag: str | None = Field(None, max_length=120)
    due_until: date | None = None
    protocol_id: uuid.UUID | None = Field(None, json_schema_extra=_source("protocols"))
    group_by: Literal["none", "person", "status", "tag"] = "none"
    columns: list[TodoColumn] = Field(default_factory=lambda: ["status", "assignee", "due", "protocol"])


# ── Termine ─────────────────────────────────────────────────────────────────

EventColumn = Literal["date", "tag", "title", "description", "participant_count", "location", "organizers", "cancelled"]


class EventSelectionParams(_Params):
    tags: list[str] = Field(default_factory=list, max_length=30)
    date_from: date | None = None
    date_to: date | None = None
    include_cancelled: bool = True
    # Gespeicherter Terminfilter wie im Element-Editor (event_filter.py); hat Vorrang.
    event_filter: dict[str, Any] | None = Field(None, json_schema_extra={"x-widget": "hidden"})


class EventTableParams(EventSelectionParams):
    columns: list[EventColumn] = Field(default_factory=lambda: ["date", "tag", "title", "description"])
    gray_past: bool = True
    show_tag_colors: bool = False


class EventCalendarParams(EventSelectionParams):
    pass


class EventAgendaParams(EventSelectionParams):
    show_location: bool = True


# ── Listen ──────────────────────────────────────────────────────────────────


class ListTableParams(_Params):
    list_id: uuid.UUID | None = Field(None, json_schema_extra=_source("lists"))
    group_by: Literal["", "column_one", "column_two"] = ""
    sort_by: Literal["", "column_one", "column_two"] = ""
    sort_direction: Literal["asc", "desc"] = "asc"
    filter_column: Literal["", "column_one", "column_two"] = ""
    filter_participant_id: uuid.UUID | None = Field(None, json_schema_extra=_source("participants"))
    filter_event_id: uuid.UUID | None = Field(None, json_schema_extra=_source("events"))
    filter_text: str | None = Field(None, max_length=200)
    highlight_empty: bool = False


# ── Finanzen ────────────────────────────────────────────────────────────────


class FinanceBalanceParams(_Params):
    account_ids: list[uuid.UUID] = Field(default_factory=list, max_length=30, json_schema_extra=_source("finance_accounts"))
    as_of: date | None = None


class FinanceTransactionsParams(_Params):
    """Ohne Konto: eine Buchungsliste je Konto."""

    account_id: uuid.UUID | None = Field(None, json_schema_extra=_source("finance_accounts"))
    relative: RelativePeriod = ""
    date_from: date | None = None
    date_to: date | None = None
    subtotals: Literal["none", "month", "year"] = "month"
    last_n: int | None = Field(None, ge=1, le=1000)


class FinesParams(ProtocolRefParams):
    status: Literal["all", "open"] = "all"
    relative: RelativePeriod = ""
    date_from: date | None = None
    date_to: date | None = None
    group_by_person: bool = False


# ── Statistik ───────────────────────────────────────────────────────────────

KpiKey = Literal["sessions", "attendanceRate", "openTodos", "doneTodos", "events", "members", "finesTotal"]
ChartType = Literal[
    "attendance_over_time",
    "attendance_by_participant",
    "finance_by_month",
    "fines_by_participant",
    "fines_by_type",
    "todos",
    "groups_sessions",
    "groups_avg",
]
StatTableType = Literal["attendance_by_participant", "fines_by_participant", "groups", "finance_by_month"]


class KpiTilesParams(PeriodParams):
    tiles: list[KpiKey] = Field(default_factory=lambda: ["sessions", "attendanceRate", "openTodos", "events"], max_length=8)


class ChartParams(PeriodParams):
    chart_type: ChartType = "attendance_over_time"
    cycle_key: str | None = Field(None, max_length=200, json_schema_extra={"x-widget": "hidden"})


class StatTableParams(PeriodParams):
    table: StatTableType = "attendance_by_participant"


# ── Sonstiges ───────────────────────────────────────────────────────────────






# ── Register ────────────────────────────────────────────────────────────────

ProviderFn = Callable[[Any, BlockSpec, Any], list[Any]]


@dataclass(frozen=True)
class CatalogEntry:
    type: str
    group: BlockGroup
    params: type[_Params]
    access: Access = "reader"


CATALOG: dict[str, CatalogEntry] = {
    entry.type: entry
    for entry in (
        CatalogEntry("protocol_element", "protocol", ProtocolElementParams),
        CatalogEntry("session_date", "protocol", SessionDateParams),
        CatalogEntry("session_notes", "protocol", ProtocolRefParams),
        CatalogEntry("form", "forms", FormParams),
        CatalogEntry("matrix", "protocol", ProtocolBlockRefParams),
        CatalogEntry("entry_exit", "protocol", EntryExitParams, access="writer"),
        CatalogEntry("image", "protocol", ImageParams),
        CatalogEntry("image_gallery", "protocol", ImageGalleryParams),
        CatalogEntry("attendance", "people", ProtocolRefParams),
        CatalogEntry("attendance_matrix", "people", AttendanceMatrixParams),
        CatalogEntry("member_list", "people", MemberListParams, access="writer"),
        CatalogEntry("signature_fields", "forms", SignatureFieldsParams),
        CatalogEntry("attendance_sheet", "people", AttendanceSheetParams, access="writer"),
        CatalogEntry("todo_table", "tasks", TodoTableParams),
        CatalogEntry("event_table", "events", EventTableParams),
        CatalogEntry("event_calendar_month", "events", EventCalendarParams),
        CatalogEntry("event_agenda", "events", EventAgendaParams),
        CatalogEntry("list_table", "lists", ListTableParams),
        CatalogEntry("finance_balance", "finance", FinanceBalanceParams, access="finance"),
        CatalogEntry("finance_transactions", "finance", FinanceTransactionsParams, access="finance"),
        CatalogEntry("fines", "finance", FinesParams, access="finance"),
        CatalogEntry("kpi_tiles", "statistics", KpiTilesParams),
        CatalogEntry("chart", "statistics", ChartParams),
        CatalogEntry("stat_table", "statistics", StatTableParams),
    )
}

# Block-Modelle ohne eigene Katalog-Komponente: entstehen nur als Kinder eines Protokollelements
CHILD_ONLY_BLOCKS = frozenset({"richtext", "static_text", "bullet_list"})
assert set(CATALOG) | CHILD_ONLY_BLOCKS == set(BLOCK_MODELS), "Katalog und Dokumentmodell passen nicht zusammen"


def validate_spec(spec: BlockSpec) -> _Params:
    """Parameter eines Blocks gegen das Katalog-Schema prüfen (ValueError bei Fehlern)."""
    entry = CATALOG.get(spec.type)
    if entry is None:
        raise ValueError(f"Unbekannter Block-Typ: {spec.type}")
    return entry.params.model_validate(spec.params)


def catalog_payload() -> list[dict[str, Any]]:
    return [
        {
            "type": entry.type,
            "group": entry.group,
            "access": entry.access,
            "needs_protocol": entry.type in NEEDS_PROTOCOL,
            "params_schema": entry.params.model_json_schema(),
        }
        for entry in CATALOG.values()
    ]


# Komponenten, die ohne Protokoll im Kontext (oder Protokollreferenz) leer bleiben
NEEDS_PROTOCOL = frozenset({"protocol_element", "session_notes", "attendance", "matrix"})
