"""Systemvorlagen von hocX (Template Library, Herkunft «System»).

Die Vorlagen sind hier als Daten definiert (dieselbe Layoutstruktur, die der Designer
bearbeitet) und werden beim Start in die Datenbank synchronisiert (``sync_system_templates``):
eine geänderte Definition ergibt eine neue veröffentlichte Revision, ältere bleiben für
historische Exporte erhalten. Mandanten können Systemvorlagen nicht ändern, nur duplizieren.

Texte sind Schlüssel aus documentPdf (``{"t": "key"}``), Namen und Beschreibungen übersetzt das
Frontend über ``documentStudio.system.<system_key>``. Gestaltung kommt aus dem Brand-Profil
(Farben, Schriften, Logo, Kopf/Fuss-Schalter, Dokument-Standards wie Titelseite und
Inhaltsverzeichnis über Bedingungen auf ``brand.*``).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.documents.hashing import json_hash
from app.documents.layout import LAYOUT_SCHEMA_VERSION, TemplateContent, content_json

logger = logging.getLogger(__name__)

# ── Bausteine ────────────────────────────────────────────────────────────────


def key(text_key: str, **flags: Any) -> dict[str, Any]:
    return {"t": "key", "key": text_key, **flags}


def bind(path: str, **fmt: Any) -> dict[str, Any]:
    item: dict[str, Any] = {"t": "bind", "path": path}
    if fmt:
        item["format"] = fmt
    return item


def lit(value: str) -> dict[str, Any]:
    return {"t": "text", "v": value}


def txt(*inlines: dict[str, Any]) -> dict[str, Any]:
    return {"default": list(inlines)}


def when(path: str, value: Any = True) -> dict[str, Any]:
    return {"op": "eq", "path": path, "value": value}


def exists(path: str) -> dict[str, Any]:
    return {"op": "exists", "path": path}


def node(node_type: str, node_id: str, **fields: Any) -> dict[str, Any]:
    return {"type": node_type, "id": node_id, **fields}


def text(node_id: str, *inlines: dict[str, Any], role: str = "paragraph", **fields: Any) -> dict[str, Any]:
    return node("text", node_id, role=role, content=txt(*inlines), **fields)


def data(node_id: str, component: str, *, title: dict[str, Any] | None = None, **fields: Any) -> dict[str, Any]:
    extra: dict[str, Any] = {"component": component, **fields}
    if title is not None:
        extra.update(title=title, title_mode="custom")
    return node("data_block", node_id, **extra)


def standard_master(*, letterhead: bool = False) -> dict[str, Any]:
    """Kopf mit Logo/Titel/Datum und Fuss mit Nummer/Text/Seitenzahl - jeweils über die
    Brand-Schalter ein- und ausblendbar; Entwurfs-Wasserzeichen nach Brand-Standard."""
    header_children = [
        node(
            "row",
            "hdr-row",
            valign="middle",
            gap=4,
            children=[
                node("image", "hdr-logo", source={"kind": "binding", "path": "brand.logo"}, style={"width": "28mm", "height": "9mm"}, visible_if=when("brand.header_show_logo")),
                text("hdr-title", bind("document.title"), role="small", style={"width": "fill", "text": {"italic": True, "color": "$brand.muted"}}, visible_if=when("brand.header_show_title")),
                text("hdr-date", bind("document.date"), role="small", style={"text": {"color": "$brand.muted"}}, visible_if=when("brand.header_show_date")),
            ],
        ),
        node("divider", "hdr-line", thickness=0.4, color="$brand.border", visible_if=when("brand.header_line")),
    ]
    footer_children = [
        node("divider", "ftr-line", thickness=0.4, color="$brand.border", visible_if=when("brand.footer_line")),
        node(
            "row",
            "ftr-row",
            gap=4,
            children=[
                text("ftr-number", bind("document.number"), role="small", style={"width": "fill", "text": {"color": "$brand.muted"}}, visible_if=when("brand.footer_show_number")),
                text("ftr-text", bind("brand.footer_text"), role="small", style={"width": "fill", "text": {"align": "center", "color": "$brand.muted"}}),
                node("page_number", "ftr-page", style={"text": {"size": 8, "color": "$brand.muted"}}, visible_if=when("brand.footer_show_pages")),
            ],
        ),
    ]
    background = [node("watermark", "bg-watermark", when="draft", visible_if=when("brand.watermark_draft"))]
    if letterhead:
        background.insert(0, node("absolute_layer", "bg-letterhead", anchor="page", visible_if=exists("brand.letterhead"), children=[
            node("image", "bg-letterhead-img", source={"kind": "binding", "path": "brand.letterhead"}, fit="cover", style={"width": "210mm"}, frame={"x": 0, "y": 0, "width": 210}),
        ]))
    return {
        "id": "default",
        "name": "",
        "header": node("header", "hdr", children=header_children),
        "footer": node("footer", "ftr", children=footer_children),
        "background": background,
    }


def plain_master(master_id: str = "plain") -> dict[str, Any]:
    """Nur Seitenzahl und Wasserzeichen (erste Seite eines Briefs)."""
    return {
        "id": master_id,
        "name": "",
        "footer": node("footer", f"{master_id}-ftr", children=[node("page_number", f"{master_id}-page", style={"align": "right", "text": {"size": 8, "color": "$brand.muted"}}, visible_if=when("brand.footer_show_pages"))]),
        "background": [node("watermark", f"{master_id}-watermark", when="draft", visible_if=when("brand.watermark_draft"))],
    }


def cover_title_page(*, condition: bool = True, subtitle_key: str | None = None) -> dict[str, Any]:
    children = [
        node("image", "tp-logo", source={"kind": "binding", "path": "brand.logo"}, style={"height": "30mm", "align": "center", "margin_bottom": 10}, visible_if=exists("brand.logo")),
        node("spacer", "tp-space-1", size=45),
        text("tp-title", bind("document.title"), role="title", style={"text": {"align": "center"}}),
    ]
    if subtitle_key:
        children.append(text("tp-subtitle", key(subtitle_key), role="subtitle", style={"text": {"align": "center"}}))
    children += [
        node("spacer", "tp-space-2", size=18),
        node("container", "tp-facts", style={"width": "110mm", "align": "center", "padding": {"top": 5, "right": 6, "bottom": 5, "left": 6}, "border": {"width": 0.6, "color": "$brand.border", "radius": 2}}, children=[node("metadata", "tp-meta", fields=["number", "date", "status", "version", "place"])]),
        node("spacer", "tp-flex", flexible=True),
        text("tp-org", bind("organization.name"), role="label", style={"text": {"align": "center"}}),
        text("tp-address", bind("organization.address"), role="small", style={"text": {"align": "center", "color": "$brand.muted"}}),
    ]
    page: dict[str, Any] = {"enabled": True, "children": children}
    if condition:
        page["visible_if"] = when("brand.title_page")
    return page


def toc(*, always: bool = False) -> dict[str, Any]:
    extra = {} if always else {"visible_if": when("brand.toc")}
    return node("toc", "toc", depth=2, style={"margin_bottom": 6}, **extra)


def metadata_box(*, always: bool = False) -> dict[str, Any]:
    extra = {} if always else {"visible_if": when("brand.show_metadata")}
    return node(
        "container",
        "meta-box",
        style={"padding": {"top": 3, "right": 4, "bottom": 3, "left": 4}, "border": {"width": 0.5, "color": "$brand.border", "radius": 1.5}, "margin_bottom": 4},
        children=[text("meta-title", key("metadata.title"), role="label"), node("metadata", "meta-list", fields=["number", "date", "status", "version", "place"])],
        **extra,
    )


def doc_heading(*, subtitle: dict[str, Any] | None = None, meta_inline: bool = True) -> list[dict[str, Any]]:
    """Dokumenttitel am Seitenanfang (ohne Titelseite)."""
    items = [text("doc-title", bind("document.title"), role="title", visible_if={"op": "not", "item": when("brand.title_page")})]
    if subtitle is not None:
        items.append(node("text", "doc-subtitle", role="subtitle", content=subtitle))
    if meta_inline:
        items.append(node("metadata", "doc-meta", fields=["number", "date", "version"], layout="inline", style={"margin_bottom": 4, "text": {"color": "$brand.muted", "size": 9}}))
    return items


def content(
    body: list[dict[str, Any]],
    *,
    masters: list[dict[str, Any]] | None = None,
    title_page: dict[str, Any] | None = None,
    page: dict[str, Any] | None = None,
    **settings: Any,
) -> dict[str, Any]:
    result: dict[str, Any] = {"schema_version": LAYOUT_SCHEMA_VERSION, "masters": masters or [standard_master()], "body": body}
    if page is not None:
        result["page"] = page
    if title_page is not None:
        result["title_page"] = title_page
    if settings:
        result["settings"] = settings
    return result


def landscape_page() -> dict[str, Any]:
    return {"size": "A4", "orientation": "landscape", "margins": {"top": 18, "right": 18, "bottom": 18, "left": 18}}


# ── Definitionen ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SystemTemplate:
    key: str
    document_type: str
    variant: str
    build: Callable[[], dict[str, Any]]
    platform_default: bool = False
    sort_index: int = 0


def _protocol_standard() -> dict[str, Any]:
    return content([toc(), metadata_box(), *doc_heading(meta_inline=False), data("protocol", "protocol_element")], title_page=cover_title_page())


def _protocol_formal() -> dict[str, Any]:
    return content(
        [
            toc(always=True),
            node("page_break", "toc-break"),
            data("protocol", "protocol_element"),
            node("section", "signatures", title=txt(key("label.signature")), keep_together=True, style={"margin_top": 10}, children=[data("signature-fields", "signature_fields")]),
        ],
        title_page=cover_title_page(condition=False, subtitle_key="docType.protocol"),
        heading_numbering=True,
    )


def _protocol_compact() -> dict[str, Any]:
    return content(
        [
            *doc_heading(),
            node("divider", "head-line", thickness=1.2, color="$brand.primary", style={"margin_bottom": 3}),
            data("protocol", "protocol_element"),
        ],
        masters=[standard_master()],
    )


def _protocol_short() -> dict[str, Any]:
    return content(
        [
            *doc_heading(subtitle=txt(key("docType.protocol_short"))),
            data("attendance", "attendance", title=txt(key("blockType.attendance")), level=2),
            data("protocol", "protocol_element", params={"content": "text_and_todos", "include_images": False}),
        ]
    )


def _protocol_decisions() -> dict[str, Any]:
    todo_table = node(
        "table",
        "open-todos",
        source="protocol.open_todos",
        columns=[
            {"id": "c-task", "header": txt(key("col.task")), "width": "fill", "cell": txt(bind("item.task"))},
            {"id": "c-assignee", "header": txt(key("col.assignee")), "cell": txt(bind("item.assignee"))},
            {"id": "c-due", "header": txt(key("col.due")), "cell": txt(bind("item.due"))},
        ],
    )
    return content(
        [
            *doc_heading(subtitle=txt(key("docType.protocol_decisions"))),
            data("protocol", "protocol_element", params={"content": "text", "include_session_todos": False, "include_images": False}),
            node("section", "pending", title=txt(key("label.sessionTodos")), visible_if={"op": "count", "path": "protocol.open_todos", "cmp": "gt", "value": 0}, children=[todo_table]),
            node("section", "signatures", title=txt(key("label.signature")), keep_together=True, style={"margin_top": 8}, children=[data("signature-fields", "signature_fields")]),
        ]
    )


def _letterhead() -> dict[str, Any]:
    return node(
        "row",
        "letterhead",
        valign="top",
        style={"margin_bottom": 12},
        children=[
            node(
                "stack",
                "sender",
                gap=0.5,
                style={"width": "fill"},
                children=[
                    text("sender-name", bind("organization.name"), role="label", style={"text": {"color": "$brand.primary", "size": 11}}),
                    text("sender-address", bind("organization.address"), role="small", style={"text": {"color": "$brand.muted"}}),
                    text("sender-contact", bind("organization.contact"), role="small", style={"text": {"color": "$brand.muted"}}),
                ],
            ),
            node("image", "letter-logo", source={"kind": "binding", "path": "brand.logo"}, style={"width": "38mm", "height": "18mm"}, visible_if=exists("brand.logo")),
        ],
    )


def _upcoming_events_table(node_id: str) -> dict[str, Any]:
    return node(
        "section",
        f"{node_id}-section",
        title=txt(key("label.upcomingEvents")),
        level=2,
        visible_if={"op": "count", "path": "events.upcoming", "cmp": "gt", "value": 0},
        children=[
            node(
                "table",
                node_id,
                source="events.upcoming",
                limit=8,
                columns=[
                    {"id": f"{node_id}-date", "header": txt(key("col.date")), "cell": txt(bind("item.date", date="weekday"))},
                    {"id": f"{node_id}-title", "header": txt(key("col.title")), "width": "fill", "cell": txt(bind("item.title"))},
                    {"id": f"{node_id}-location", "header": txt(key("col.location")), "cell": txt(bind("item.location"))},
                ],
            )
        ],
    )


def _invitation_standard() -> dict[str, Any]:
    return content(
        [
            text("inv-kicker", key("docType.invitation"), role="label", style={"text": {"color": "$brand.primary", "transform": "upper"}}),
            text("inv-title", bind("protocol.title"), role="title"),
            data("session-date", "session_date"),
            node("section", "agenda", title=txt(key("docType.agenda")), children=[data("agenda-items", "protocol_element", params={"titles_only": True, "invitation_only": True})]),
            _upcoming_events_table("events"),
        ]
    )


def _invitation_letter() -> dict[str, Any]:
    return content(
        [
            _letterhead(),
            text("letter-place-date", bind("organization.place"), lit(", "), bind("document.date", date="long"), style={"text": {"align": "right"}, "margin_bottom": 10}),
            text("letter-subject", key("docType.invitation"), lit(": "), bind("protocol.title"), role="heading", level=1),
            data("session-date", "session_date"),
            node("section", "agenda", title=txt(key("docType.agenda")), level=2, children=[node("list", "agenda-list", marker="number", source="protocol.invitation_elements", item=txt(bind("item.title")))]),
            _upcoming_events_table("events"),
            node("spacer", "letter-space", size=10),
            text("letter-closing", bind("organization.name"), role="label"),
        ],
        masters=[plain_master("default")],
    )


def _agenda_standard() -> dict[str, Any]:
    return content(
        [
            text("agenda-kicker", key("docType.agenda"), role="label", style={"text": {"color": "$brand.primary", "transform": "upper"}}),
            text("agenda-title", bind("protocol.title"), role="title"),
            node("metadata", "agenda-meta", fields=["number", "date", "place"], layout="inline", style={"margin_bottom": 6, "text": {"color": "$brand.muted"}}),
            node("list", "agenda-list", marker="number", source="protocol.invitation_elements", item=txt(bind("item.title")), style={"text": {"size": 12}}),
        ]
    )


def _attendance_list() -> dict[str, Any]:
    return content(
        [
            *doc_heading(subtitle=txt(key("docType.attendance"))),
            data("attendance", "attendance"),
            text("attendance-total", key("label.participantCount"), lit(": "), bind("protocol.participant_count"), role="small", style={"text": {"color": "$brand.muted"}}),
        ]
    )


def _attendance_sheet_standard() -> dict[str, Any]:
    return content(
        [
            text("sheet-title", key("docType.attendance_sheet"), role="title"),
            text("sheet-date", key("titlePage.date"), lit(": "), bind("protocol.date", date="weekday"), style={"margin_bottom": 4}),
            data("sheet", "attendance_sheet", params={"source": "active_members", "blank_rows": 4}),
        ]
    )


def _signature_sheet() -> dict[str, Any]:
    return content(
        [
            text("sheet-title", key("docType.signature_sheet"), role="title"),
            text("sheet-org", bind("organization.name"), role="subtitle"),
            data("sheet", "attendance_sheet", params={"source": "active_members", "columns": [""], "blank_rows": 8}),
        ]
    )


def _members_standard() -> dict[str, Any]:
    return content([*doc_heading(), data("members", "member_list", params={"columns": ["email", "role", "joined_at"]})])


def _todos_standard() -> dict[str, Any]:
    return content([*doc_heading(), data("todos", "todo_table", params={"status": "open", "columns": ["status", "assignee", "due", "protocol"]})])


def _todos_by_person() -> dict[str, Any]:
    return content([*doc_heading(), data("todos", "todo_table", params={"status": "open", "group_by": "person", "columns": ["status", "due", "protocol"]})])


_FUTURE = {"range": {"mode": "future"}}


def _events_agenda() -> dict[str, Any]:
    return content([*doc_heading(), data("events", "event_agenda", params={"event_filter": _FUTURE})])


def _events_table() -> dict[str, Any]:
    columns = ["date", "tag", "title", "location", "organizers"]
    return content(
        [*doc_heading(), data("events", "event_table", params={"event_filter": _FUTURE, "columns": columns, "show_tag_colors": True})],
        page=landscape_page(),
    )


def _calendar_month() -> dict[str, Any]:
    window = {"range": {"mode": "window", "start_days": 0, "end_days": 92}}
    return content(
        [*doc_heading(meta_inline=False), data("calendar", "event_calendar_month", params={"event_filter": window})],
        page=landscape_page(),
    )


def _finance_report() -> dict[str, Any]:
    period = {"relative": "current_year"}
    return content(
        [
            *doc_heading(),
            data("balances", "finance_balance", title=txt(key("blockType.finance_balance"))),
            data("monthly", "stat_table", title=txt(key("label.byMonth")), params={"table": "finance_by_month", **period}),
            data("chart", "chart", params={"chart_type": "finance_by_month", **period}, keep_together=True),
        ]
    )


def _transactions_list() -> dict[str, Any]:
    return content([*doc_heading(), data("transactions", "finance_transactions", params={"relative": "current_year", "subtotals": "month"})])


def _fines_overview() -> dict[str, Any]:
    return content(
        [
            *doc_heading(),
            data("fines-open", "fines", title=txt(key("label.openFines")), params={"status": "open", "group_by_person": True}),
            data("fines-chart", "chart", params={"chart_type": "fines_by_participant", "relative": "current_year"}, keep_together=True),
        ]
    )


def _statistics_report() -> dict[str, Any]:
    period = {"relative": "current_year"}
    return content(
        [
            *doc_heading(),
            data("kpis", "kpi_tiles", params={**period, "tiles": ["sessions", "attendanceRate", "openTodos", "events"]}),
            data("attendance-chart", "chart", title=txt(key("chartTitle.attendance_over_time")), params={"chart_type": "attendance_over_time", **period}, keep_together=True),
            data("attendance-table", "stat_table", title=txt(key("chartTitle.attendance_by_participant")), params={"table": "attendance_by_participant", **period}),
            data("groups", "stat_table", title=txt(key("chartTitle.groups_sessions")), params={"table": "groups", **period}),
        ]
    )


def _statistics_charts() -> dict[str, Any]:
    period = {"relative": "current_year"}
    charts = ["attendance_over_time", "attendance_by_participant", "todos", "groups_sessions"]
    return content(
        [
            *doc_heading(subtitle=txt(key("docType.charts"))),
            node(
                "grid",
                "charts",
                columns=2,
                gap_x=8,
                gap_y=8,
                children=[data(f"chart-{name}", "chart", title=txt(key(f"chartTitle.{name}")), level=2, params={"chart_type": name, **period}, keep_together=True) for name in charts],
            ),
        ]
    )


def _list_standard() -> dict[str, Any]:
    return content([*doc_heading(meta_inline=False), data("list", "list_table")])


def _form_blank() -> dict[str, Any]:
    return content(
        [
            _letterhead(),
            text("form-title", key("docType.form"), role="title"),
            data("form", "form", params={"rows": [{"label": "", "value": ""}, {"label": "", "value": ""}, {"label": "", "value": ""}]}),
            node("section", "form-signature", keep_together=True, style={"margin_top": 12}, children=[data("form-signature-fields", "signature_fields")]),
        ]
    )


def _custom_blank() -> dict[str, Any]:
    return content([*doc_heading(meta_inline=False), node("rich_text", "custom-text", markdown="")])


def _custom_letter() -> dict[str, Any]:
    return content(
        [
            _letterhead(),
            text("letter-place-date", bind("organization.place"), lit(", "), bind("document.date", date="long"), style={"text": {"align": "right"}, "margin_bottom": 10}),
            text("letter-subject", bind("document.title"), role="heading", level=1),
            node("rich_text", "letter-body", markdown=""),
            node("spacer", "letter-space", size=10),
            text("letter-closing", bind("organization.name"), role="label"),
        ],
        masters=[plain_master("default")],
    )


SYSTEM_TEMPLATES: tuple[SystemTemplate, ...] = (
    SystemTemplate("protocol_standard", "protocol", "standard", _protocol_standard, platform_default=True, sort_index=1),
    SystemTemplate("protocol_formal", "protocol", "formal", _protocol_formal, sort_index=2),
    SystemTemplate("protocol_compact", "protocol", "compact", _protocol_compact, sort_index=3),
    SystemTemplate("protocol_short", "protocol", "short", _protocol_short, sort_index=4),
    SystemTemplate("protocol_decisions", "protocol", "decisions", _protocol_decisions, sort_index=5),
    SystemTemplate("invitation_standard", "invitation", "standard", _invitation_standard, platform_default=True, sort_index=1),
    SystemTemplate("invitation_letter", "invitation", "letter", _invitation_letter, sort_index=2),
    SystemTemplate("agenda_standard", "agenda", "standard", _agenda_standard, platform_default=True),
    SystemTemplate("attendance_list", "attendance", "standard", _attendance_list, platform_default=True),
    SystemTemplate("attendance_sheet_standard", "attendance_sheet", "standard", _attendance_sheet_standard, platform_default=True, sort_index=1),
    SystemTemplate("signature_sheet", "attendance_sheet", "signature", _signature_sheet, sort_index=2),
    SystemTemplate("members_standard", "members", "standard", _members_standard, platform_default=True),
    SystemTemplate("todos_standard", "todos", "standard", _todos_standard, platform_default=True, sort_index=1),
    SystemTemplate("todos_by_person", "todos", "by_person", _todos_by_person, sort_index=2),
    SystemTemplate("events_agenda", "events", "agenda", _events_agenda, platform_default=True, sort_index=1),
    SystemTemplate("events_table", "events", "table", _events_table, sort_index=2),
    SystemTemplate("calendar_month", "calendar", "month", _calendar_month, platform_default=True),
    SystemTemplate("finance_report", "finance", "report", _finance_report, platform_default=True),
    SystemTemplate("transactions_list", "transactions", "standard", _transactions_list, platform_default=True),
    SystemTemplate("fines_overview", "fines", "standard", _fines_overview, platform_default=True),
    SystemTemplate("statistics_report", "statistics", "report", _statistics_report, platform_default=True, sort_index=1),
    SystemTemplate("statistics_charts", "statistics", "charts", _statistics_charts, sort_index=2),
    SystemTemplate("list_standard", "list", "standard", _list_standard, platform_default=True),
    SystemTemplate("form_blank", "form", "standard", _form_blank, platform_default=True),
    SystemTemplate("custom_blank", "custom", "blank", _custom_blank, platform_default=True, sort_index=1),
    SystemTemplate("custom_letter", "custom", "letter", _custom_letter, sort_index=2),
)

SYSTEM_TEMPLATE_KEYS: tuple[str, ...] = tuple(item.key for item in SYSTEM_TEMPLATES)


def build_content(definition: SystemTemplate) -> TemplateContent:
    return TemplateContent.model_validate(definition.build())


def sync_system_templates(db: Session) -> dict[str, int]:
    """Systemvorlagen anlegen bzw. bei geänderter Definition neu veröffentlichen. Vom
    Plattform-Admin archivierte Vorlagen bleiben archiviert, gesetzte Plattform-Standards
    bleiben erhalten (der Code-Standard gilt nur, solange für den Typ keiner gesetzt ist)."""
    from datetime import UTC, datetime

    from app.models import DocumentTemplate, DocumentTemplateRevision

    created = updated = 0
    for definition in SYSTEM_TEMPLATES:
        data = content_json(build_content(definition))
        digest = json_hash(data)
        template = db.scalar(select(DocumentTemplate).where(DocumentTemplate.system_key == definition.key))
        if template is None:
            template = DocumentTemplate(
                tenant_id=None,
                system_key=definition.key,
                origin="system",
                name=definition.key,
                document_type=definition.document_type,
                variant=definition.variant,
                category=_category(definition.document_type),
                status="active",
                sort_index=definition.sort_index,
            )
            db.add(template)
            db.flush()
            created += 1
        else:
            template.document_type = definition.document_type
            template.variant = definition.variant
            template.sort_index = definition.sort_index
        current = db.get(DocumentTemplateRevision, template.published_revision_id) if template.published_revision_id else None
        if current is not None and current.content_hash == digest:
            continue
        if current is not None:
            current.status = "superseded"
            db.flush()
            updated += 1
        revision_no = (max((row.revision_no for row in db.scalars(select(DocumentTemplateRevision).where(DocumentTemplateRevision.template_id == template.id))), default=0)) + 1
        revision = DocumentTemplateRevision(
            template_id=template.id,
            revision_no=revision_no,
            status="published",
            schema_version=LAYOUT_SCHEMA_VERSION,
            content_json=data,
            content_hash=digest,
            brand_mode="follow",
            published_at=datetime.now(UTC),
        )
        db.add(revision)
        db.flush()
        template.published_revision_id = revision.id
    for definition in SYSTEM_TEMPLATES:
        if not definition.platform_default:
            continue
        has_default = db.scalar(
            select(DocumentTemplate.id).where(
                DocumentTemplate.tenant_id.is_(None), DocumentTemplate.document_type == definition.document_type, DocumentTemplate.is_platform_default.is_(True)
            )
        )
        if has_default is None:
            template = db.scalar(select(DocumentTemplate).where(DocumentTemplate.system_key == definition.key))
            if template is not None and template.status == "active":
                template.is_platform_default = True
    db.flush()
    return {"created": created, "updated": updated}


def _category(document_type: str) -> str:
    from app.documents.doc_types import DOCUMENT_TYPES

    return DOCUMENT_TYPES[document_type].category
