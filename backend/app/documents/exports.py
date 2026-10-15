"""Zusatzformate aus den fachlichen Datenmodellen eines Exports: CSV/XLSX (Tabellen der
Fachkomponenten und gebundene Tabellen der Vorlage), ICS (Termine der Termin-Komponenten),
Markdown (Todo-Liste wie der frühere WhatsApp-Export). Grundlage ist dieselbe aufgelöste
Vorlage wie beim PDF, nie das Layout selbst.

Spaltenköpfe, Status und Gruppen werden mit den Texten der Dokumentsprache aufgelöst; es gibt
keine fest codierten Texte."""
from __future__ import annotations

import csv
import io
from typing import Any

from app.documents.catalog import BlockSpec
from app.documents.model import Cell, ProtocolElementBlock, TableColumn, TableData, TextSpan


def _walk_blocks(blocks: list[Any]):
    for block in blocks:
        if isinstance(block, ProtocolElementBlock):
            yield from _walk_blocks(block.children)
        else:
            yield block


def table_blocks(blocks: list[Any], strings: dict[str, str]) -> list[tuple[str, TableData]]:
    """Alle Tabellen der Fachkomponenten (Tabellen-Blöcke und Matrix-Gruppen) mit Titel."""
    result: list[tuple[str, TableData]] = []
    for block in _walk_blocks(blocks):
        title = block.title or (strings.get(block.title_key, "") if block.title_key else "") or strings.get(f"blockType.{block.type}", block.type)
        table = getattr(block, "table", None)
        if isinstance(table, TableData):
            result.append((title, table))
        for table in getattr(block, "tables", []) or []:
            if isinstance(table, TableData):
                result.append((title, table))
    return result


def _rich_text(nodes: list[Any]) -> str:
    parts: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, TextSpan):
            parts.append(value.v)
        elif isinstance(value, list):
            for item in value:
                walk(item)
        elif hasattr(value, "c"):
            walk(value.c)
            parts.append(" ")
        elif hasattr(value, "items"):
            for item in value.items:
                walk(item)
                parts.append("; ")
        elif hasattr(value, "rows"):
            parts.append("; ".join(" ".join(row) for row in value.rows))
        elif hasattr(value, "v"):
            parts.append(str(value.v))

    walk(nodes)
    return " ".join("".join(parts).split())


def cell_text(cell: Cell, strings: dict[str, str]) -> str:
    if cell.k == "status" and cell.status:
        text = strings.get(cell.status, cell.status)
        return f"{text} ({cell.v})" if cell.v else text
    if cell.k == "tags":
        return ", ".join(tag.label for tag in cell.tags)
    if cell.k == "rich":
        return _rich_text(cell.rich)
    if cell.k == "check":
        return "x" if cell.checked else ""
    value = cell.v
    if cell.note_key:
        note = strings.get(cell.note_key, "")
        value = f"{value} ({note})" if value else note
    return value


def header_text(column: TableColumn, strings: dict[str, str]) -> str:
    if column.label_key:
        return strings.get(column.label_key, column.label_key)
    return column.label or ""


def table_rows(table: TableData, strings: dict[str, str]) -> list[list[str]]:
    """Kopfzeile plus Zeilen; bei Gruppen eine zusätzliche Spalte mit dem Gruppenlabel."""
    grouped = any(group.label or group.label_key for group in table.groups)
    header = [header_text(column, strings) for column in table.columns]
    rows = [([strings.get("col.group", "")] if grouped else []) + header]
    for group in table.groups:
        label = group.label or (strings.get(group.label_key, "") if group.label_key else "")
        for row in group.rows:
            rows.append(([label] if grouped else []) + [cell_text(cell, strings) for cell in row.cells])
        if group.subtotal:
            rows.append(([label] if grouped else []) + [cell_text(cell, strings) for cell in group.subtotal])
    if table.totals:
        rows.append(([""] if grouped else []) + [cell_text(cell, strings) for cell in table.totals])
    return rows


def _span_text(spans: list[dict[str, Any]]) -> str:
    return "".join(span.get("v", " ") for span in spans).strip()


def layout_tables(compiled_data: dict[str, Any]) -> list[tuple[str, list[list[str]]]]:
    """Gebundene und feste Tabellen der Vorlage (kompilierte ``table``-Knoten) als Textzeilen."""
    result: list[tuple[str, list[list[str]]]] = []

    def walk(nodes: list[dict[str, Any]]) -> None:
        for node in nodes:
            if node.get("t") == "table" and node.get("rows"):
                header = [_span_text(column.get("header") or []) for column in node.get("columns", [])]
                rows = [[_span_text(cell) for cell in row] for row in node["rows"]]
                result.append((header[0] if header else "", ([header] if any(header) else []) + rows))
            walk(node.get("children") or [])

    for segment in compiled_data.get("segments", []):
        walk(segment.get("nodes", []))
    return result


def all_tables(blocks: list[Any], compiled_data: dict[str, Any], strings: dict[str, str]) -> list[tuple[str, list[list[str]]]]:
    tables = [(title, table_rows(table, strings)) for title, table in table_blocks(blocks, strings)]
    return tables + layout_tables(compiled_data)


def to_csv(tables: list[tuple[str, list[list[str]]]]) -> bytes:
    if not tables:
        raise ValueError("noTable")
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    for index, (title, rows) in enumerate(tables):
        if len(tables) > 1:
            if index:
                writer.writerow([])
            writer.writerow([title])
        writer.writerows(rows)
    # BOM, damit Excel UTF-8 erkennt
    return ("﻿" + buffer.getvalue()).encode("utf-8")


def to_xlsx(tables: list[tuple[str, list[list[str]]]]) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font

    if not tables:
        raise ValueError("noTable")
    workbook = Workbook()
    workbook.remove(workbook.active)
    used: set[str] = set()
    for title, rows in tables:
        name = "".join(char for char in title if char not in "[]:*?/\\")[:28] or "Tabelle"
        candidate, counter = name, 2
        while candidate in used:
            candidate = f"{name[:25]} {counter}"
            counter += 1
        used.add(candidate)
        sheet = workbook.create_sheet(candidate)
        for row_index, row in enumerate(rows, start=1):
            sheet.append(row)
            if row_index == 1:
                for cell in sheet[1]:
                    cell.font = Font(bold=True)
        for column in sheet.columns:
            width = max((len(str(cell.value or "")) for cell in column), default=8)
            sheet.column_dimensions[column[0].column_letter].width = min(max(width + 2, 8), 60)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


# ── ICS und Markdown aus den Fachkomponenten der Vorlage ─────────────────────

EVENT_COMPONENTS = ("event_table", "event_calendar_month", "event_agenda")


def component_specs(content: Any, params: dict[str, Any], components: tuple[str, ...]) -> list[BlockSpec]:
    """Aktive ``data_block``-Knoten der gewünschten Komponenten mit Seitenkontext-Parametern."""
    from app.documents.catalog import CATALOG
    from app.documents.layout import all_node_lists, iter_nodes

    specs: list[BlockSpec] = []
    for area, nodes in all_node_lists(content):
        if area.startswith("master:"):
            continue
        for node, _depth in iter_nodes(nodes):
            if node.type == "data_block" and node.enabled and node.component in components:
                allowed = set(CATALOG[node.component].params.model_fields)
                specs.append(BlockSpec(type=node.component, params={**node.params, **{key: value for key, value in params.items() if key in allowed}}))
    return specs


def ics_content(prepared: Any) -> bytes:
    from app.documents.catalog import EventSelectionParams, validate_spec
    from app.documents.providers import events
    from app.models import Tenant

    ctx = prepared.ctx
    specs = component_specs(prepared.content, prepared.params, EVENT_COMPONENTS)
    if not specs:
        if prepared.document_type not in ("events", "calendar"):
            raise ValueError("noTable")
        selected = events.select_events(ctx, EventSelectionParams(event_filter={"range": {"mode": "future"}}))
    else:
        selected = []
        for spec in specs:
            selected.extend(events.select_events(ctx, validate_spec(spec)))
    tenant = ctx.db.get(Tenant, ctx.tenant_id)
    unique = {event.id: event for event in selected}
    return events.ics(sorted(unique.values(), key=lambda event: (event.event_date, event.id)), tenant_name=tenant.name if tenant else "").encode("utf-8")


def markdown_content(prepared: Any) -> bytes:
    from app.documents.catalog import validate_spec
    from app.documents.providers import todos

    ctx = prepared.ctx
    specs = component_specs(prepared.content, prepared.params, ("todo_table",))
    if not specs:
        raise ValueError("noTable")
    rows: list[Any] = []
    group_by_person = show_status = False
    for spec in specs:
        params = validate_spec(spec)
        rows.extend(todos.filter_rows(ctx, todos.list_tenant_todo_rows(ctx), params))
        group_by_person = group_by_person or params.group_by == "person"
        show_status = show_status or params.status != "open"
    strings = prepared.compiled.data["strings"]
    return todos.markdown(rows, strings=strings, title=prepared.meta.title, group_by_person=group_by_person, show_status=show_status, today=ctx.today).encode("utf-8")
