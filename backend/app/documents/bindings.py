"""Datenbindungen des Document Studio: typisierte Datenquellen für Texte, Bilder, Tabellen,
Wiederholungen und Bedingungen.

Jede Bindung ist ein fester Pfad aus ``REGISTRY`` (z. B. ``protocol.date``) mit Typ, Gruppe,
Zugriffsrecht und - für Listen - den Feldern ihrer Elemente (``item.<feld>``). Benutzer wählen
Bindungen im Designer aus einer Liste; freie Ausdrücke gibt es nicht. Aufgelöst wird beim
Kompilieren mit den Rechten des **exportierenden** Benutzers (``BuildContext.require`` und das
Protokoll-Leserecht): eine Vorlage kann keine Daten abrufen, die der Exportierende nicht sehen
darf. Die Lader verwenden dieselben Repositories/Provider wie die Fachkomponenten.

Beispieldaten (``mode="sample"``) gibt es nur für die Vorschau im Designer; die Texte stammen
aus documentPdf (``sample.*``), nie aus dem produktiven Exportpfad.

Neue Bindung: Eintrag in ``REGISTRY`` (Gruppe, Typ, Recht, Beispiel), Wert im Lader der Gruppe
(``_load_<gruppe>``), Label ``binding.<pfad>`` in frontend/messages/<locale>/documentStudio.json.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Callable, Literal

from app.documents.context import BuildContext, DocumentPermissionError, format_amount, format_date, format_number

BindingType = Literal["text", "date", "number", "amount", "percent", "image", "bool", "list"]
Access = Literal["reader", "writer", "finance"]


@dataclass(frozen=True)
class ItemField:
    key: str
    type: BindingType
    sample: Any = None


@dataclass(frozen=True)
class BindingDef:
    path: str
    type: BindingType
    group: str
    access: Access = "reader"
    needs_protocol: bool = False
    item_fields: tuple[ItemField, ...] = ()
    # Beispielwert: literal oder ("key", <documentPdf-Schlüssel>) bzw. Liste von Element-dicts
    sample: Any = None

    def item_field(self, key: str) -> ItemField | None:
        return next((item for item in self.item_fields if item.key == key), None)


def _s(key: str) -> tuple[str, str]:
    return ("key", f"sample.{key}")


_SAMPLE_DATE = date(2026, 3, 12)

_PROTOCOL_ELEMENT_FIELDS = (ItemField("title", "text"), ItemField("responsible", "text"), ItemField("index", "number"))
_PARTICIPANT_FIELDS = (ItemField("name", "text"), ItemField("status", "text"), ItemField("status_code", "text"))
_TODO_FIELDS = (ItemField("task", "text"), ItemField("assignee", "text"), ItemField("due", "date"), ItemField("status", "text"), ItemField("protocol", "text"))
_EVENT_FIELDS = (ItemField("date", "date"), ItemField("title", "text"), ItemField("location", "text"), ItemField("tag", "text"), ItemField("description", "text"))
_MEMBER_FIELDS = (ItemField("name", "text"), ItemField("email", "text"), ItemField("joined_at", "date"), ItemField("role", "text"))
_ACCOUNT_FIELDS = (ItemField("name", "text"), ItemField("balance", "amount"), ItemField("currency", "text"))


def _sample_list(prefix: str, count: int, build: Callable[[int], dict[str, Any]]) -> list[dict[str, Any]]:
    return [build(index) for index in range(1, count + 1)]


_DEFINITIONS: list[BindingDef] = [
    # Organisation (aus dem Brand-Profil, Name fällt auf den Mandantennamen zurück)
    BindingDef("organization.name", "text", "organization", sample=_s("organization")),
    BindingDef("organization.address", "text", "organization", sample=_s("address")),
    BindingDef("organization.contact", "text", "organization", sample=_s("contact")),
    BindingDef("organization.website", "text", "organization", sample="www.example.ch"),
    BindingDef("organization.place", "text", "organization", sample=_s("place")),
    # Brand-Profil: Bilder und Schalter
    BindingDef("brand.logo", "image", "brand"),
    BindingDef("brand.logo_alt", "image", "brand"),
    BindingDef("brand.letterhead", "image", "brand"),
    BindingDef("brand.background", "image", "brand"),
    BindingDef("brand.watermark", "image", "brand"),
    BindingDef("brand.footer_image", "image", "brand"),
    BindingDef("brand.footer_text", "text", "brand"),
    BindingDef("brand.header_show_logo", "bool", "brand"),
    BindingDef("brand.header_show_title", "bool", "brand"),
    BindingDef("brand.header_show_date", "bool", "brand"),
    BindingDef("brand.header_line", "bool", "brand"),
    BindingDef("brand.footer_show_number", "bool", "brand"),
    BindingDef("brand.footer_show_pages", "bool", "brand"),
    BindingDef("brand.footer_line", "bool", "brand"),
    BindingDef("brand.title_page", "bool", "brand"),
    BindingDef("brand.toc", "bool", "brand"),
    BindingDef("brand.show_metadata", "bool", "brand"),
    BindingDef("brand.watermark_draft", "bool", "brand"),
    BindingDef("brand.verify_show_url", "bool", "brand"),
    BindingDef("brand.verify_show_id", "bool", "brand"),
    BindingDef("brand.verify_show_qr", "bool", "brand"),
    # Dokument
    BindingDef("document.title", "text", "document", sample=_s("documentTitle")),
    BindingDef("document.subtitle", "text", "document", sample=_s("documentSubtitle")),
    BindingDef("document.type", "text", "document", sample=_s("documentType")),
    BindingDef("document.date", "date", "document", sample=_SAMPLE_DATE),
    BindingDef("document.number", "text", "document", sample="2026-03"),
    BindingDef("document.version", "text", "document", sample="v1.2"),
    BindingDef("document.status", "text", "document", sample=_s("status")),
    BindingDef("document.language", "text", "document", sample="de"),
    BindingDef("document.is_draft", "bool", "document", sample=False),
    BindingDef("document.short_id", "text", "document", sample="7F3A-91C2"),
    BindingDef("document.created_by", "text", "document", sample=_s("person1")),
    # Protokoll / Sitzung
    BindingDef("protocol.title", "text", "protocol", needs_protocol=True, sample=_s("protocolTitle")),
    BindingDef("protocol.number", "text", "protocol", needs_protocol=True, sample="2026-03"),
    BindingDef("protocol.date", "date", "protocol", needs_protocol=True, sample=_SAMPLE_DATE),
    BindingDef("protocol.status", "text", "protocol", needs_protocol=True, sample=_s("status")),
    BindingDef("protocol.status_code", "text", "protocol", needs_protocol=True, sample="held"),
    BindingDef("protocol.version", "text", "protocol", needs_protocol=True, sample="v1.2"),
    BindingDef("protocol.template_name", "text", "protocol", needs_protocol=True, sample=_s("templateName")),
    BindingDef("protocol.event_title", "text", "protocol", needs_protocol=True, sample=_s("eventTitle")),
    BindingDef("protocol.next_session", "date", "protocol", needs_protocol=True, sample=date(2026, 4, 9)),
    BindingDef("protocol.participant_count", "number", "protocol", needs_protocol=True, sample=12),
    BindingDef("protocol.present_count", "number", "protocol", needs_protocol=True, sample=9),
    BindingDef("protocol.excused_count", "number", "protocol", needs_protocol=True, sample=2),
    BindingDef("protocol.absent_count", "number", "protocol", needs_protocol=True, sample=1),
    BindingDef(
        "protocol.elements", "list", "protocol", needs_protocol=True, item_fields=_PROTOCOL_ELEMENT_FIELDS,
        sample=[{"title": ("key", f"sample.section{index}"), "responsible": ("key", f"sample.person{index}") if index % 2 else "", "index": index} for index in range(1, 5)],
    ),
    # Nur Traktanden, die laut Protokollvorlage in Einladung und Traktandenliste erscheinen
    BindingDef(
        "protocol.invitation_elements", "list", "protocol", needs_protocol=True, item_fields=_PROTOCOL_ELEMENT_FIELDS,
        sample=[{"title": ("key", f"sample.section{index}"), "responsible": "", "index": index} for index in range(1, 5)],
    ),
    BindingDef(
        "protocol.participants", "list", "protocol", needs_protocol=True, item_fields=_PARTICIPANT_FIELDS,
        sample=[{"name": ("key", f"sample.person{index}"), "status": ("key", "attendanceStatus.present" if index < 4 else "attendanceStatus.excused"), "status_code": "present" if index < 4 else "excused"} for index in range(1, 6)],
    ),
    BindingDef(
        "protocol.open_todos", "list", "protocol", needs_protocol=True, item_fields=_TODO_FIELDS,
        sample=[{"task": ("key", f"sample.task{index}"), "assignee": ("key", f"sample.person{index}"), "due": date(2026, 4, index * 3), "status": ("key", "todoStatus.open"), "protocol": "2026-03"} for index in range(1, 4)],
    ),
    # In diesem Protokoll erfasste Pendenzen, unabhängig vom heutigen Status
    BindingDef("protocol.new_todos_count", "number", "protocol", needs_protocol=True, sample=4),
    # Aufgaben des Mandanten (sichtbare: eingeschränkte Leser nur ihre Protokolle)
    BindingDef(
        "todos.open", "list", "todos", item_fields=_TODO_FIELDS,
        sample=[{"task": ("key", f"sample.task{index}"), "assignee": ("key", f"sample.person{index}"), "due": date(2026, 4, index * 3), "status": ("key", "todoStatus.open"), "protocol": "2026-03"} for index in range(1, 4)],
    ),
    BindingDef("todos.open_count", "number", "todos", sample=3),
    BindingDef("todos.done_count", "number", "todos", sample=17),
    # Termine
    BindingDef(
        "events.upcoming", "list", "events", item_fields=_EVENT_FIELDS,
        sample=[{"date": date(2026, 4, index * 5), "title": ("key", f"sample.event{index}"), "location": ("key", "sample.place"), "tag": "", "description": ""} for index in range(1, 4)],
    ),
    BindingDef("events.upcoming_count", "number", "events", sample=3),
    # Mitglieder (Personendaten: wie die Mitgliederliste nur für schreibberechtigte Rollen)
    BindingDef(
        "members.active", "list", "members", access="writer", item_fields=_MEMBER_FIELDS,
        sample=[{"name": ("key", f"sample.person{index}"), "email": f"person{index}@example.ch", "joined_at": date(2020 + index, 1, 15), "role": ""} for index in range(1, 6)],
    ),
    BindingDef("members.active_count", "number", "members", sample=24),
    # Finanzen (Feature Finanzen und Leserecht)
    BindingDef(
        "finance.accounts", "list", "finance", access="finance", item_fields=_ACCOUNT_FIELDS,
        sample=[{"name": ("key", f"sample.account{index}"), "balance": 1250.5 * index, "currency": "CHF"} for index in range(1, 3)],
    ),
    BindingDef("finance.total_balance", "amount", "finance", access="finance", sample=3751.5),
    # Statistik (laufendes Kalenderjahr)
    BindingDef("statistics.sessions_count", "number", "statistics", sample=11),
    BindingDef("statistics.attendance_rate", "percent", "statistics", sample=0.86),
    BindingDef("statistics.events_count", "number", "statistics", sample=27),
]

REGISTRY: dict[str, BindingDef] = {definition.path: definition for definition in _DEFINITIONS}
GROUPS: tuple[str, ...] = tuple(dict.fromkeys(definition.group for definition in _DEFINITIONS))

# Dynamische Pfade: eigene Bilder und Farben des Brand-Profils
_DYNAMIC_IMAGE = re.compile(r"^brand\.images\.([a-z0-9_]{1,40})$")


class UnknownBindingError(ValueError):
    def __init__(self, path: str) -> None:
        super().__init__(f"unbekannte Datenbindung: {path}")
        self.path = path


def lookup(path: str) -> BindingDef:
    definition = REGISTRY.get(path)
    if definition is not None:
        return definition
    if _DYNAMIC_IMAGE.match(path):
        return BindingDef(path, "image", "brand")
    raise UnknownBindingError(path)


def validate_path(path: str, *, scope: BindingDef | None = None) -> tuple[BindingType, BindingDef | None]:
    """Typ eines Pfads. ``item.<feld>`` ist nur innerhalb einer Wiederholung (``scope``) gültig."""
    if path.startswith("item."):
        if scope is None:
            raise UnknownBindingError(path)
        field_def = scope.item_field(path.split(".", 1)[1])
        if field_def is None:
            raise UnknownBindingError(path)
        return field_def.type, None
    definition = lookup(path)
    return definition.type, definition


def catalog_payload() -> list[dict[str, Any]]:
    """Bindungen für den Designer (Gruppen, Typen, Rechte, Elementfelder)."""
    return [
        {
            "path": definition.path,
            "type": definition.type,
            "group": definition.group,
            "access": definition.access,
            "needs_protocol": definition.needs_protocol,
            "item_fields": [{"key": item.key, "type": item.type} for item in definition.item_fields],
        }
        for definition in _DEFINITIONS
    ]


# ── Formatierung ─────────────────────────────────────────────────────────────


def _as_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def format_value(value: Any, value_type: str, fmt: Any, strings: dict[str, str]) -> str:
    """Wert → Text in der Dokumentsprache. ``fmt`` ist ein layout.FormatSpec."""
    if value is None or value == "":
        return ""
    if value_type == "date":
        parsed = _as_date(value)
        if parsed is None:
            text = str(value)
        elif fmt.date == "long":
            text = f"{parsed.day}. {strings.get(f'month.{parsed.month}', str(parsed.month))} {parsed.year}"
        elif fmt.date == "weekday":
            text = f"{strings.get(f'weekday.{parsed.weekday()}', '')}, {format_date(parsed)}".lstrip(", ")
        elif fmt.date == "month_year":
            text = f"{strings.get(f'month.{parsed.month}', str(parsed.month))} {parsed.year}"
        elif fmt.date == "year":
            text = str(parsed.year)
        else:
            text = format_date(parsed)
    elif value_type in ("number", "amount", "percent"):
        try:
            number = float(value)
        except (TypeError, ValueError):
            text = str(value)
        else:
            kind = "amount" if value_type == "amount" else ("percent" if value_type == "percent" else fmt.number)
            if kind == "amount":
                text = format_amount(number)
            elif kind == "percent":
                text = f"{round(number * 100 if number <= 1 else number)}%"
            elif kind == "decimal":
                text = format_number(number, 1)
            else:
                text = format_number(number)
    elif value_type == "bool":
        text = strings.get("label.yes", "✓") if value else ""
    elif value_type == "list":
        text = str(len(value)) if isinstance(value, list) else ""
    else:
        text = str(value)
    if fmt.transform == "upper":
        text = text.upper()
    elif fmt.transform == "lower":
        text = text.lower()
    return f"{fmt.prefix}{text}{fmt.suffix}" if text else ""


# ── Auflösung ────────────────────────────────────────────────────────────────


@dataclass
class BindingEnvironment:
    """Werte, die der Compiler vorab kennt: Dokument-Meta, Brand-Werte (inkl. Bildpfade im
    Compile-Root) und Organisationsdaten."""

    document: dict[str, Any] = field(default_factory=dict)
    brand: dict[str, Any] = field(default_factory=dict)
    organization: dict[str, Any] = field(default_factory=dict)


class BindingResolver:
    def __init__(self, ctx: BuildContext | None, env: BindingEnvironment, *, strings: dict[str, str], mode: Literal["data", "sample"] = "data") -> None:
        self.ctx = ctx
        self.env = env
        self.strings = strings
        self.mode = mode
        self._groups: dict[str, dict[str, Any]] = {}
        self.used: set[str] = set()

    # Werte ---------------------------------------------------------------

    def resolve(self, path: str, scope: dict[str, Any] | None = None) -> Any:
        if path.startswith("item."):
            return (scope or {}).get(path.split(".", 1)[1])
        definition = lookup(path)
        self.used.add(path)
        if definition.group in ("organization", "brand", "document"):
            source = {"organization": self.env.organization, "brand": self.env.brand, "document": self.env.document}[definition.group]
            key = path.split(".", 1)[1]
            if definition.group == "document" and self.mode == "sample" and source.get(key) in (None, ""):
                return self._sample(definition)
            if definition.group == "organization" and self.mode == "sample" and not source.get(key):
                return self._sample(definition)
            return source.get(key)
        if self.mode == "sample":
            return self._sample(definition)
        self._check_access(definition)
        if definition.needs_protocol and (self.ctx is None or self.ctx.protocol is None):
            return None
        values = self._load_group(definition.group)
        return values.get(path.split(".", 1)[1])

    def _check_access(self, definition: BindingDef) -> None:
        if self.ctx is None:
            raise DocumentPermissionError(definition.access)
        self.ctx.require(definition.access)

    def _sample(self, definition: BindingDef) -> Any:
        def value(raw: Any) -> Any:
            if isinstance(raw, tuple) and len(raw) == 2 and raw[0] == "key":
                return self.strings.get(raw[1], "")
            if isinstance(raw, dict):
                return {key: value(item) for key, item in raw.items()}
            if isinstance(raw, list):
                return [value(item) for item in raw]
            return raw

        return value(definition.sample)

    def _load_group(self, group: str) -> dict[str, Any]:
        if group not in self._groups:
            loader = _LOADERS.get(group)
            self._groups[group] = loader(self) if loader is not None else {}
        return self._groups[group]


# ── Lader je Gruppe (nur im Datenmodus, Rechte bereits geprüft) ─────────────


def _status_label(strings: dict[str, str], prefix: str, code: str | None) -> str:
    return strings.get(f"{prefix}.{code}", code or "") if code else ""


def _load_protocol(resolver: BindingResolver) -> dict[str, Any]:
    from app.core.element_types import element_type_code
    from app.documents import repository
    from app.documents.providers import people as people_provider
    from app.documents.providers import protocol as protocol_provider
    from app.documents.providers import todos as todo_provider
    from app.models import Event, Template

    ctx = resolver.ctx
    assert ctx is not None and ctx.protocol is not None
    protocol = ctx.protocol
    ctx.ensure_can_read_protocol(protocol.id)
    strings = resolver.strings
    template = ctx.db.get(Template, protocol.template_id)
    event = ctx.db.get(Event, protocol.event_id) if protocol.event_id else None
    status_code = protocol_provider.protocol_status_code(protocol)

    elements = protocol_provider.element_blocks(ctx, protocol, include_session_todos=False)
    element_items = [{"title": block.title or "", "responsible": "", "index": index} for index, block in enumerate(elements, start=1)]
    invitation_elements = protocol_provider.element_blocks(ctx, protocol, include_session_todos=False, invitation_only=True)
    invitation_items = [{"title": block.title or "", "responsible": "", "index": index} for index, block in enumerate(invitation_elements, start=1)]

    participants: list[dict[str, Any]] = []
    for config in people_provider.protocol_attendance_configs(ctx, protocol):
        for entry in people_provider.attendance_entries(ctx, config):
            participants.append({"name": entry.name, "status": _status_label(strings, "attendanceStatus", entry.status), "status_code": entry.status or ""})
    counts = {status: sum(1 for item in participants if item["status_code"] == status) for status in ("present", "late", "excused", "absent")}

    next_session = None
    for element in repository.list_protocol_elements(ctx.db, protocol.id):
        for block in repository.list_element_blocks(ctx.db, element.id):
            if element_type_code(block.element_type_id) == "session_date":
                config = block.configuration_snapshot_json or {}
                next_session = config.get("selected_date") or config.get("session_date") or config.get("date") or next_session
                break
        if next_session:
            break

    protocol_rows = [row for row in todo_provider.list_tenant_todo_rows(ctx) if getattr(row, "protocol_id", None) == protocol.id]
    open_todos = [_todo_item(strings, row) for row in todo_provider.sort_rows([row for row in protocol_rows if todo_provider.is_open(row)])]

    return {
        "title": protocol.title or protocol.protocol_number,
        "number": protocol.protocol_number,
        "date": protocol.protocol_date,
        "status": _status_label(strings, "protocolStatus", status_code),
        "status_code": status_code or "",
        "version": resolver.env.document.get("version"),
        "template_name": template.name if template is not None else "",
        "event_title": event.title if event is not None else "",
        "next_session": next_session,
        "participant_count": len(participants),
        "present_count": counts["present"] + counts["late"],
        "excused_count": counts["excused"],
        "absent_count": counts["absent"],
        "elements": element_items,
        "invitation_elements": invitation_items,
        "participants": participants,
        "open_todos": open_todos,
        "new_todos_count": len(protocol_rows),
    }


def _todo_item(strings: dict[str, str], row: Any) -> dict[str, Any]:
    from app.documents.providers import todos as todo_provider

    return {
        "task": todo_provider.task_text(row),
        "assignee": getattr(row, "assigned_participant_name", None) or "",
        "due": getattr(row, "resolved_due_date", None),
        "status": _status_label(strings, "todoStatus", todo_provider.status_code(row)),
        "protocol": todo_provider.protocol_label(row),
    }


def _load_todos(resolver: BindingResolver) -> dict[str, Any]:
    from app.documents.providers import todos as todo_provider

    ctx = resolver.ctx
    assert ctx is not None
    rows = todo_provider.list_tenant_todo_rows(ctx)
    open_rows = todo_provider.sort_rows([row for row in rows if todo_provider.is_open(row)])
    return {
        "open": [_todo_item(resolver.strings, row) for row in open_rows],
        "open_count": len(open_rows),
        "done_count": sum(1 for row in rows if todo_provider.status_code(row) == "done"),
    }


def _load_events(resolver: BindingResolver) -> dict[str, Any]:
    from app.documents.catalog import EventSelectionParams
    from app.documents.providers import events as event_provider

    ctx = resolver.ctx
    assert ctx is not None
    events = [event for event in event_provider.select_events(ctx, EventSelectionParams(date_from=ctx.today, include_cancelled=False))]
    items = [
        {
            "date": event.event_date,
            "title": event.title,
            "location": getattr(event, "location", None) or "",
            "tag": getattr(event, "tag", None) or "",
            "description": getattr(event, "description", None) or "",
        }
        for event in events[:50]
    ]
    return {"upcoming": items, "upcoming_count": len(events)}


def _load_members(resolver: BindingResolver) -> dict[str, Any]:
    from sqlalchemy import select

    from app.models import Participant

    ctx = resolver.ctx
    assert ctx is not None
    rows = list(ctx.db.scalars(select(Participant).where(Participant.tenant_id == ctx.tenant_id, Participant.is_active.is_(True)).order_by(Participant.display_name)))
    values: dict[str, Any] = {"active_count": len(rows)}
    # Personendaten (Namen, E-Mail) nur mit Schreibrecht; die Anzahl ist für alle lesbar
    try:
        ctx.require("writer")
    except DocumentPermissionError:
        return values
    values["active"] = [
        {
            "name": row.display_name,
            "email": getattr(row, "email", None) or "",
            "joined_at": getattr(row, "joined_at", None),
            "role": "",
        }
        for row in rows
    ]
    return values


def _load_finance(resolver: BindingResolver) -> dict[str, Any]:
    from sqlalchemy import func, select

    from app.models import FinanceAccount, FinanceTransaction

    ctx = resolver.ctx
    assert ctx is not None
    accounts = list(ctx.db.scalars(select(FinanceAccount).where(FinanceAccount.tenant_id == ctx.tenant_id).order_by(FinanceAccount.name)))
    items = []
    total = 0.0
    for account in accounts:
        balance = float(ctx.db.scalar(select(func.coalesce(func.sum(FinanceTransaction.amount), 0)).where(FinanceTransaction.account_id == account.id)) or 0)
        total += balance
        items.append({"name": account.name, "balance": balance, "currency": account.currency_label or ""})
    return {"accounts": items, "total_balance": total}


def _load_statistics(resolver: BindingResolver) -> dict[str, Any]:
    from app.documents.providers import statistics as statistics_provider

    ctx = resolver.ctx
    assert ctx is not None
    bounds = statistics_provider.default_period(ctx.today)
    monthly, _ = statistics_provider._attendance(ctx, bounds)
    attended = sum(counts.present + counts.late for counts in monthly.values())
    total = sum(counts.total for counts in monthly.values())
    return {
        "sessions_count": statistics_provider._protocol_count(ctx, bounds),
        "attendance_rate": (attended / total) if total else None,
        "events_count": statistics_provider._event_count(ctx, bounds),
    }


_LOADERS: dict[str, Callable[[BindingResolver], dict[str, Any]]] = {
    "protocol": _load_protocol,
    "todos": _load_todos,
    "events": _load_events,
    "members": _load_members,
    "finance": _load_finance,
    "statistics": _load_statistics,
}
