"""Gestaltungsbeispiele für alle Dokumenttypen ausser dem Protokoll.

Vorlage: Claude-Design-Projekt «Dokumenttypen» (je eine Datei pro Firma: Jungwacht Sachseln,
Bergmann Bau AG, lumio GmbH, Keller & Partner, Aarwerk AG), abgeleitet von den Protokoll-
Designs Kreide, Signal, Fokus, Siegel und Atlas. Jede Firma hat einen eigenen Kopf, eigene
Kennzahl-Kacheln, Traktandenzeilen und eine eigene Fusszeile; der Inhalt je Dokumenttyp ist in
allen Designs gleich gegliedert und kommt aus den vorhandenen Fachkomponenten.

Ein Beispiel heisst «<design>-<typ>» (z. B. ``signal-todos``), bringt das CD seines Protokoll-
Designs mit (gleiche Farben, Schriften, Bilder, Organisationsangaben) und wird wie die
Protokoll-Beispiele übernommen und danach frei bearbeitet. Texte sind Schlüssel aus
documentPdf; Freitexte (Einleitung, Hinweis, Brieftext) sind leere Textfelder zum Ausfüllen.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Callable

from app.documents.examples import WHITE, _agenda_rows, _area, _fill, _kpi, _pad, _page_layer, _small, label_text
from app.documents.system_templates import _upcoming_events_table, bind, content, data, exists, key, lit, node, text, txt

if TYPE_CHECKING:
    from app.documents.examples import DesignExample

# Reihenfolge wie im Katalog (doc_types.DOCUMENT_TYPES ohne Protokoll)
DOCUMENT_TYPES: tuple[str, ...] = (
    "invitation", "agenda", "attendance", "attendance_sheet", "members", "todos", "events", "calendar",
    "finance", "transactions", "fines", "statistics", "list", "form", "custom",
)
# Designs mit Dokumenttypen-Datei; Alpin hat keine (die Jungwacht-Datei gehört zu Kreide)
DESIGNS: tuple[str, ...] = ("kreide", "signal", "fokus", "siegel", "atlas")

_FUTURE = {"range": {"mode": "future"}}
_YEAR = {"relative": "current_year"}

Node = dict[str, Any]


@dataclass(frozen=True)
class Style:
    """Was ein Design an den Dokumenttypen ausmacht."""

    key: str
    # Kopf: (Art, Titel, Untertitel) -> Knoten am Anfang des Dokuments
    head: Callable[[list[Node], list[Node], list[Node]], list[Node]]
    # Kennzahl-Kacheln: [(id, Beschriftung, Wert-Inlines)] -> Zeile
    kpis: Callable[[list[tuple[str, Node, list[Node]]]], Node]
    # Fusszeile «Organisation · Adresse · Dokumentart  Seite x von y»
    master: Callable[[str], Node]
    agenda: Callable[[], Node]
    page: dict[str, Any] | None = None


def _inl(*inlines: Node) -> list[Node]:
    return list(inlines)


def _footer_master(doc_type: str, *, line: float | None, line_color: str = "$brand.border", color: str = "$brand.muted", size: float = 8, page_color: str = "$brand.muted", page_bold: bool = False, address: bool = True, website: bool = False, lower: bool = False) -> Node:
    """Seitenvorlage ohne Kopf (der Kopf steht im Dokument): Fusszeile mit Organisation,
    Adresse und Dokumentart links, Seitenzahl rechts. Folgt den Fusszeilen-Schaltern."""
    parts: list[Node] = [] if website else [bind("organization.name")]
    if address:
        parts += [lit(" · ") if parts else lit(""), bind("organization.address")]
    if website:
        parts += [lit(" · "), bind("organization.website")]
    parts += [lit(" · "), key(f"docType.{doc_type}")]
    text_style: dict[str, Any] = {"size": size, "color": color}
    if lower:
        text_style["transform"] = "lower"
    children: list[Node] = []
    if line:
        children.append(node("divider", "ftr-line", thickness=line, color=line_color))
    children.append(
        node("row", "ftr-row", gap=4, valign="middle", style={"margin_top": 1.5} if line else {}, children=[
            label_text("ftr-text", *parts, role="small", style={"width": "fill", "text": text_style}),
            node("page_number", "ftr-page", style={"text": {"size": size, "color": page_color, **({"weight": "bold"} if page_bold else {})}}, visible_if={"op": "eq", "path": "brand.footer_show_pages", "value": True}),
        ])
    )
    return {
        "id": "default",
        "name": "",
        "footer": node("footer", "ftr", children=children),
        "background": [node("watermark", "watermark", when="draft", visible_if={"op": "eq", "path": "brand.watermark_draft", "value": True})],
    }


def _title_block(prefix: str, kind: list[Node], title: list[Node], subtitle: list[Node], *, kind_color: str, kind_size: float = 7.5, kind_spacing: float = 1, title_size: float = 22, title_style: dict[str, Any] | None = None, subtitle_style: dict[str, Any] | None = None, align: str | None = None, number: bool = True, margin_top: float = 8) -> list[Node]:
    kicker: list[Node] = [_small(f"{prefix}-kind", *kind, color=kind_color, size=kind_size, bold=True, spacing=kind_spacing, **({"align": align} if align else {}))]
    if number and not align:
        kicker.append(_small(f"{prefix}-number", bind("document.number"), upper=False, spacing=0.5))
    title_text = {"size": title_size, "line_height": 1.08, "letter_spacing": -0.3, "color": "$brand.text", **(title_style or {})}
    if align:
        title_text["align"] = align
    sub_text = {"size": 10, "color": "$brand.muted", **(subtitle_style or {})}
    if align:
        sub_text["align"] = align
    return [
        node("row", f"{prefix}-kicker", gap=2, style={"margin_top": margin_top}, children=kicker) if not align else kicker[0] | {"style": {**kicker[0]["style"], "margin_top": margin_top}},
        label_text(f"{prefix}-title", *title, role="title", style={"text": title_text, "margin_top": 1.5}),
        label_text(f"{prefix}-subtitle", *subtitle, style={"text": sub_text, "margin_top": 1.5, "margin_bottom": 5}),
    ]


# ── Kreide (Jungwacht Sachseln) ─────────────────────────────────────────────


def _kreide_head(kind: list[Node], title: list[Node], subtitle: list[Node]) -> list[Node]:
    return [
        node("container", "hd", style={"padding": _pad(0, 0, 3, 0), "border": {"width": 0.5, "color": "$brand.border", "sides": ["bottom"]}}, children=[
            node("row", "hd-row", valign="middle", gap=4, children=[
                node("image", "hd-logo", source={"kind": "binding", "path": "brand.logo"}, style={"width": "auto", "height": "11mm"}, visible_if=exists("brand.logo")),
                label_text("hd-org", bind("organization.name"), role="small", style={"width": "fill", "text": {"size": 8.5, "weight": "bold", "color": "$brand.primary", "align": "right", "transform": "lower", "letter_spacing": 0.3}}),
            ]),
        ]),
        *_title_block("hd", kind, title, subtitle, kind_color="$brand.accent", title_style={"weight": "bold"}),
    ]


def _kreide_kpis(items: list[tuple[str, Node, list[Node]]]) -> Node:
    return node("row", "kpis", gap=4, style={"padding": _pad(4, 0, 0, 0), "margin_bottom": 5, "border": {"width": 0.5, "color": "$brand.border", "sides": ["top"]}}, children=[
        _kpi(f"kpi-{item_id}", label, *value, box={}, label_color="$brand.secondary", value_color="$brand.text", value_weight="regular") for item_id, label, value in items
    ])


# ── Signal (Bergmann Bau AG) ────────────────────────────────────────────────

_SIGNAL_BAND = 54


def _signal_head(kind: list[Node], title: list[Node], subtitle: list[Node]) -> list[Node]:
    band = _page_layer(
        "hd-band",
        _area("hd-band-fill", "$brand.primary", height=_SIGNAL_BAND),
        _area("hd-band-stripe", "$brand.accent", y=_SIGNAL_BAND, height=3),
        label_text("hd-org", bind("organization.name"), role="small", style={"text": {"size": 13, "weight": "bold", "color": WHITE, "transform": "upper", "letter_spacing": 0.5}}, frame={"x": 18, "y": 10, "width": 100}),
        label_text("hd-number", bind("document.number"), role="small", style={"text": {"size": 9, "weight": "bold", "color": "$brand.accent", "align": "right", "transform": "upper", "letter_spacing": 0.7}}, frame={"x": 112, "y": 11, "width": 80}),
        _small("hd-kind", *kind, color="$brand.accent", size=10, bold=True, spacing=1.2, frame={"x": 18, "y": 25, "width": 174}),
        text("hd-title", *title, role="title", style={"text": {"size": 28, "color": WHITE, "transform": "upper", "line_height": 0.98}}, frame={"x": 18, "y": 30.5, "width": 174}),
        text("hd-subtitle", *subtitle, style={"text": {"size": 9.5, "color": "$brand.border"}}, frame={"x": 18, "y": 44, "width": 174}),
    )
    return [band, node("spacer", "hd-space", size=_SIGNAL_BAND - 12 + 3 + 6)]


def _signal_kpis(items: list[tuple[str, Node, list[Node]]]) -> Node:
    return node("row", "kpis", gap=4, style={"margin_bottom": 5}, children=[
        _kpi(f"kpi-{item_id}", label, *value, box={"padding": _pad(3.5, 4), **_fill("$brand.accent" if index == 0 else "$brand.surface")}, label_color="$brand.text" if index == 0 else "$brand.muted", value_color="$brand.text", value_size=22)
        for index, (item_id, label, value) in enumerate(items)
    ])


# ── Fokus (lumio GmbH) ──────────────────────────────────────────────────────


def _fokus_head(kind: list[Node], title: list[Node], subtitle: list[Node]) -> list[Node]:
    return [
        node("row", "hd-row", valign="middle", gap=2, children=[
            node("container", "hd-dot", style={"width": "4.5mm", "height": "4.5mm", **_fill("$brand.primary", radius=2.25)}),
            label_text("hd-org", bind("organization.name"), style={"width": "fill", "text": {"size": 11.5, "weight": "bold", "transform": "lower", "letter_spacing": -0.1}}),
            _small("hd-number", bind("document.number"), upper=False, spacing=0),
        ]),
        *_title_block(
            "hd", kind, title, subtitle, kind_color="$brand.primary", kind_size=8, kind_spacing=0, title_size=26, number=False, margin_top=14,
            title_style={"weight": "bold", "letter_spacing": -0.7, "line_height": 1.04}, subtitle_style={"size": 8.5},
        ),
    ]


def _fokus_kpis(items: list[tuple[str, Node, list[Node]]]) -> Node:
    cells = []
    for index, (item_id, label, value) in enumerate(items):
        box: dict[str, Any] = {"padding": _pad(3)}
        if index:
            box["border"] = {"width": 0.5, "color": "$brand.border", "sides": ["left"]}
        cells.append(_kpi(f"kpi-{item_id}", label, *value, box=box, value_color="$brand.text", value_weight="regular"))
    return node("row", "kpis", gap=0, style={"margin_bottom": 5, "border": {"width": 0.5, "color": "$brand.border", "radius": 1.5}}, children=cells)


# ── Siegel (Keller & Partner) ───────────────────────────────────────────────


def _siegel_head(kind: list[Node], title: list[Node], subtitle: list[Node]) -> list[Node]:
    return [
        text("hd-org", bind("organization.name"), style={"text": {"size": 13, "align": "center", "letter_spacing": 0.8}}),
        _small("hd-place", bind("organization.place"), size=6.5, spacing=2, align="center"),
        node("divider", "hd-rule-1", thickness=0.5, color="$brand.text", style={"margin_top": 3}),
        node("divider", "hd-rule-2", thickness=0.5, color="$brand.text", style={"margin_top": 0.6}),
        *_title_block(
            "hd", kind, title, subtitle, kind_color="$brand.primary", kind_spacing=1.8, align="center", margin_top=10,
            title_style={"weight": "regular", "line_height": 1.15}, subtitle_style={"italic": True, "size": 10.5},
        ),
    ]


def _siegel_kpis(items: list[tuple[str, Node, list[Node]]]) -> Node:
    cells = []
    for index, (item_id, label, value) in enumerate(items):
        box: dict[str, Any] = {"padding": _pad(3, 0, 3, 4 if index else 0)}
        if index:
            box["border"] = {"width": 0.5, "color": "$brand.border", "sides": ["left"]}
        cells.append(_kpi(f"kpi-{item_id}", label, *value, box=box, value_color="$brand.text", value_size=17, value_weight="regular"))
    rule = {"width": 0.5, "color": "$brand.primary", "sides": ["top", "bottom"]}
    return node("row", "kpis", gap=0, style={"margin_bottom": 5, "border": rule}, children=cells)


# ── Atlas (Aarwerk AG) ──────────────────────────────────────────────────────

_ATLAS_BAND = 58


def _atlas_head(kind: list[Node], title: list[Node], subtitle: list[Node]) -> list[Node]:
    band = _page_layer(
        "hd-band",
        _area("hd-band-fill", "$brand.primary", height=_ATLAS_BAND),
        node("container", "hd-logo-box", visible_if=exists("brand.logo"), style={"padding": _pad(1), **_fill(WHITE)}, frame={"x": 20, "y": 10, "width": 10, "height": 10}, children=[
            node("image", "hd-logo", source={"kind": "binding", "path": "brand.logo"}, style={"height": "8mm"}),
        ]),
        label_text("hd-org", bind("organization.name"), style={"text": {"size": 11, "weight": "bold", "color": WHITE, "letter_spacing": 0.2}}, frame={"x": 33, "y": 12.5, "width": 100}),
        _small("hd-number", bind("document.number"), color="$brand.border", bold=True, spacing=1.2, align="right", frame={"x": 120, "y": 13, "width": 70}),
        _small("hd-kind", *kind, color="$brand.border", size=8, bold=True, spacing=1.4, frame={"x": 20, "y": 31, "width": 170}),
        text("hd-title", *title, role="title", style={"text": {"size": 24, "color": WHITE, "line_height": 1.08}}, frame={"x": 20, "y": 36, "width": 170}),
        text("hd-subtitle", *subtitle, style={"text": {"size": 10, "color": "$brand.border"}}, frame={"x": 20, "y": 48, "width": 170}),
    )
    return [band, node("spacer", "hd-space", size=_ATLAS_BAND - 12 + 6)]


def _atlas_kpis(items: list[tuple[str, Node, list[Node]]]) -> Node:
    return node("row", "kpis", gap=4, style={"margin_bottom": 5}, children=[
        _kpi(f"kpi-{item_id}", label, *value, box={"padding": _pad(4), **_fill("$brand.surface")}, value_size=18) for item_id, label, value in items
    ])


STYLES: dict[str, Style] = {
    "kreide": Style(
        "kreide", _kreide_head, _kreide_kpis,
        lambda doc_type: _footer_master(doc_type, line=0.5, color="$brand.secondary", address=False),
        lambda: _agenda_rows("ag", number_color="$brand.primary", size=10, source="protocol.invitation_elements"),
        page={"size": "A4", "margins": _pad(14, 18, 12, 18)},
    ),
    "signal": Style(
        "signal", _signal_head, _signal_kpis,
        lambda doc_type: _footer_master(doc_type, line=1, line_color="$brand.primary", page_color="$brand.text", page_bold=True),
        lambda: _agenda_rows("ag", number_color="$brand.text", size=10, line_color="$brand.border", source="protocol.invitation_elements"),
        page={"size": "A4", "margins": _pad(12, 18, 12, 18)},
    ),
    "fokus": Style(
        "fokus", _fokus_head, _fokus_kpis,
        lambda doc_type: _footer_master(doc_type, line=None, size=7, address=False, lower=True),
        lambda: _agenda_rows("ag", number_color="$brand.primary", size=10.5, source="protocol.invitation_elements"),
        page={"size": "A4", "margins": _pad(16, 18, 14, 18)},
    ),
    "siegel": Style(
        "siegel", _siegel_head, _siegel_kpis,
        lambda doc_type: _footer_master(doc_type, line=None, size=7.5, website=True),
        lambda: _agenda_rows("ag", number_color="$brand.primary", size=11, number_prefix="§ ", responsible_italic=True, source="protocol.invitation_elements"),
        page={"size": "A4", "margins": _pad(16, 24, 14, 24)},
    ),
    "atlas": Style(
        "atlas", _atlas_head, _atlas_kpis,
        lambda doc_type: _footer_master(doc_type, line=0.5),
        lambda: _agenda_rows("ag", number_color="$brand.primary", number_box="$brand.primary", source="protocol.invitation_elements"),
        page={"size": "A4", "margins": _pad(12, 20, 12, 20)},
    ),
}


# ── Inhalt je Dokumenttyp ───────────────────────────────────────────────────


def _kind(doc_type: str) -> list[Node]:
    return [key(f"docType.{doc_type}")]


_DOC_TITLE = [bind("document.title")]
_AS_OF = [key("label.asOfPrefix"), lit(" "), bind("document.date")]
_PLACE_DATE = [bind("organization.place"), lit(", "), bind("document.date", date="long")]
_SESSION = [bind("protocol.date", date="weekday")]


def _section(node_id: str, title_key: str, *children: Node, **fields: Any) -> Node:
    return node("section", node_id, title=txt(key(title_key)), level=2, children=list(children), **fields)


def _signatures() -> Node:
    return node("container", "signatures", keep_together=True, style={"margin_top": 10}, children=[data("signature-fields", "signature_fields")])


def _body(style: Style, doc_type: str) -> tuple[list[Node], dict[str, Any]]:
    """(Knoten, Seiteneinstellungen) des Dokuments; der Kopf ist schon enthalten."""
    head = style.head
    kpis = style.kpis
    page: dict[str, Any] = {}
    if doc_type == "invitation":
        nodes = [
            *head(_kind(doc_type), [bind("protocol.title")], _SESSION),
            text("place-date", *_PLACE_DATE, style={"text": {"color": "$brand.muted"}, "margin_bottom": 4}),
            node("rich_text", "intro", markdown=""),
            data("session-date", "session_date"),
            _section("agenda", "label.agenda", style.agenda()),
            node("rich_text", "note", markdown="", style={"margin_top": 4}),
            _signatures(),
        ]
    elif doc_type == "agenda":
        nodes = [
            *head(_kind(doc_type), [bind("protocol.title")], [*_SESSION, lit(" · "), bind("organization.place")]),
            data("session-date", "session_date"),
            _section("agenda", "label.agenda", style.agenda()),
            node("rich_text", "attachments", markdown="", style={"margin_top": 4}),
        ]
    elif doc_type == "attendance":
        nodes = [
            *head(_kind(doc_type), [bind("protocol.title")], _SESSION),
            kpis([
                ("present", key("attendanceStatus.present"), [bind("protocol.present_count"), lit(" / "), bind("protocol.participant_count")]),
                ("excused", key("attendanceStatus.excused"), [bind("protocol.excused_count")]),
                ("absent", key("attendanceStatus.absent"), [bind("protocol.absent_count")]),
            ]),
            data("attendance", "attendance"),
        ]
    elif doc_type == "attendance_sheet":
        nodes = [
            *head(_kind(doc_type), _DOC_TITLE, [bind("organization.name")]),
            data("sheet", "attendance_sheet", params={"source": "active_members", "blank_rows": 4}),
        ]
    elif doc_type == "members":
        nodes = [
            *head(_kind(doc_type), _DOC_TITLE, _AS_OF),
            kpis([("members", key("kpi.members"), [bind("members.active_count")])]),
            data("members", "member_list", params={"columns": ["email", "role", "joined_at"]}),
        ]
    elif doc_type == "todos":
        nodes = [
            *head(_kind(doc_type), _DOC_TITLE, _AS_OF),
            kpis([
                ("open", key("kpi.open"), [bind("todos.open_count")]),
                ("overdue", key("kpi.overdue"), [bind("todos.overdue_count")]),
                ("done", key("kpi.done"), [bind("todos.done_count")]),
            ]),
            data("todos", "todo_table", params={"status": "open", "group_by": "tag", "columns": ["assignee", "due", "protocol"]}),
        ]
    elif doc_type == "events":
        nodes = [
            *head(_kind(doc_type), _DOC_TITLE, _AS_OF),
            data("events", "event_table", params={"event_filter": _FUTURE, "columns": ["date", "title", "location", "organizers"], "show_tag_colors": True}),
        ]
    elif doc_type == "calendar":
        nodes = [
            *head(_kind(doc_type), _DOC_TITLE, [bind("organization.name")]),
            data("calendar", "event_calendar_month", params={"event_filter": {"range": {"mode": "window", "start_days": 0, "end_days": 31}}}),
            _upcoming_events_table("upcoming"),
        ]
    elif doc_type == "finance":
        nodes = [
            *head(_kind(doc_type), _DOC_TITLE, _AS_OF),
            kpis([("balance", key("kpi.balance"), [bind("finance.total_balance", number="amount")])]),
            data("balances", "finance_balance", title=txt(key("blockType.finance_balance"))),
            data("monthly", "stat_table", title=txt(key("label.byMonth")), params={"table": "finance_by_month", **_YEAR}),
            node("rich_text", "remark", markdown="", style={"margin_top": 4}),
        ]
    elif doc_type == "transactions":
        nodes = [
            *head(_kind(doc_type), _DOC_TITLE, _AS_OF),
            data("transactions", "finance_transactions", params={**_YEAR, "subtotals": "month"}),
        ]
    elif doc_type == "fines":
        nodes = [
            *head(_kind(doc_type), _DOC_TITLE, _AS_OF),
            data("kpis", "kpi_tiles", params={**_YEAR, "tiles": ["finesTotal"]}),
            data("fines", "fines", title=txt(key("label.openFines")), params={"status": "open", "group_by_person": True}),
            data("fines-chart", "chart", params={"chart_type": "fines_by_participant", **_YEAR}, keep_together=True),
            node("rich_text", "note", markdown="", style={"margin_top": 4}),
        ]
    elif doc_type == "statistics":
        nodes = [
            *head(_kind(doc_type), _DOC_TITLE, _AS_OF),
            data("kpis", "kpi_tiles", params={**_YEAR, "tiles": ["sessions", "attendanceRate", "openTodos", "events"]}),
            data("attendance-chart", "chart", title=txt(key("chartTitle.attendance_over_time")), params={"chart_type": "attendance_over_time", **_YEAR}, keep_together=True),
            data("attendance-table", "stat_table", title=txt(key("chartTitle.attendance_by_participant")), params={"table": "attendance_by_participant", **_YEAR}),
        ]
    elif doc_type == "list":
        nodes = [*head(_kind(doc_type), _DOC_TITLE, _AS_OF), data("list", "list_table")]
    elif doc_type == "form":
        nodes = [
            *head(_kind(doc_type), _DOC_TITLE, [bind("organization.name")]),
            node("rich_text", "intro", markdown=""),
            data("form", "form", params={"rows": [{"label": "", "value": ""} for _ in range(6)]}),
            _signatures(),
        ]
    elif doc_type == "custom":
        nodes = [
            *head(_kind(doc_type), _DOC_TITLE, _PLACE_DATE),
            node("rich_text", "body", markdown=""),
            _signatures(),
        ]
    else:  # pragma: no cover - DOCUMENT_TYPES ist abschliessend
        raise ValueError(doc_type)
    return nodes, page


def build(design: str, doc_type: str) -> dict[str, Any]:
    style = STYLES[design]
    nodes, page = _body(style, doc_type)
    return content(nodes, masters=[style.master(doc_type)], page=page or style.page)


def document_type_examples(protocol_examples: tuple[DesignExample, ...]) -> tuple[DesignExample, ...]:
    """Je Design und Dokumenttyp ein Beispiel mit dem CD des Protokoll-Beispiels."""
    by_key = {item.key: item for item in protocol_examples}
    result = []
    for design in DESIGNS:
        base = by_key[design]
        for index, doc_type in enumerate(DOCUMENT_TYPES):
            result.append(
                replace(
                    base,
                    key=f"{design}-{doc_type}",
                    document_type=doc_type,
                    build=lambda design=design, doc_type=doc_type: build(design, doc_type),
                    design=design,
                    sort_index=100 * base.sort_index + index,
                )
            )
    return tuple(result)
