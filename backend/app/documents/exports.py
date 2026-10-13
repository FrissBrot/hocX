"""Zusatzformate aus demselben Dokumentmodell: CSV/XLSX (Tabellen-Blöcke), ICS (Termine),
Markdown (Todo-Liste wie der frühere WhatsApp-Export).

Spaltenköpfe, Status und Gruppen werden mit den Texten der Dokumentsprache aufgelöst; es gibt
keine fest codierten Texte."""
from __future__ import annotations

import csv
import io
from typing import Any

from app.documents.model import Cell, Document, ProtocolElementBlock, TableColumn, TableData, TextSpan


def _walk_blocks(blocks: list[Any]):
    for block in blocks:
        if isinstance(block, ProtocolElementBlock):
            yield from _walk_blocks(block.children)
        else:
            yield block


def table_blocks(document: Document) -> list[tuple[str, TableData]]:
    """Alle Tabellen eines Dokuments (Tabellen-Blöcke und Matrix-Gruppen) mit Titel."""
    strings = document.strings
    result: list[tuple[str, TableData]] = []
    for block in _walk_blocks(document.blocks):
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


def to_csv(document: Document) -> bytes:
    tables = table_blocks(document)
    if not tables:
        raise ValueError("noTable")
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    for index, (title, table) in enumerate(tables):
        if len(tables) > 1:
            if index:
                writer.writerow([])
            writer.writerow([title])
        writer.writerows(table_rows(table, document.strings))
    # BOM, damit Excel UTF-8 erkennt
    return ("﻿" + buffer.getvalue()).encode("utf-8")


def to_xlsx(document: Document) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font

    tables = table_blocks(document)
    if not tables:
        raise ValueError("noTable")
    workbook = Workbook()
    workbook.remove(workbook.active)
    used: set[str] = set()
    for title, table in tables:
        name = "".join(char for char in title if char not in "[]:*?/\\")[:28] or "Tabelle"
        candidate, counter = name, 2
        while candidate in used:
            candidate = f"{name[:25]} {counter}"
            counter += 1
        used.add(candidate)
        sheet = workbook.create_sheet(candidate)
        for row_index, row in enumerate(table_rows(table, document.strings), start=1):
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
