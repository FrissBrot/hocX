"""Excel-Exporte dürfen an Steuerzeichen in Mitgliedereingaben nicht scheitern.

openpyxl lehnt Zeichen wie \\x0b (manueller Zeilenumbruch aus Word) oder \\x07 mit
IllegalCharacterError ab. Ein einziges Anliegen, ein Listeneintrag oder ein Name mit einem
solchen Zeichen liess vorher den ganzen Excel-Export des Document Studio, die persönliche
Datenauskunft und den Mandantenexport scheitern."""
from __future__ import annotations

import io

from openpyxl import load_workbook

from app.documents import exports
from app.services.data_export import workbook

VALUES = ["Zeile 1\x0bZeile 2", "Glocke\x07", "Null\x00Byte", "Tab\tbleibt", "Umbruch\nbleibt"]
EXPECTED = ["Zeile 1\nZeile 2", "Glocke", "NullByte", "Tab\tbleibt", "Umbruch\nbleibt"]


def test_document_xlsx_export_survives_control_characters():
    content = exports.to_xlsx([("Liste\x0b", [["Titel"], *[[value] for value in VALUES]])])
    sheet = load_workbook(io.BytesIO(content)).active
    assert [sheet.cell(row=index, column=1).value for index in range(2, 2 + len(VALUES))] == EXPECTED


def test_data_export_workbook_survives_control_characters():
    content = workbook.build([workbook.Sheet(title="Anliegen", headers=["Titel\x0b"], rows=[[value] for value in VALUES])])
    sheet = load_workbook(io.BytesIO(content)).active
    assert sheet.cell(row=1, column=1).value == "Titel\n"
    assert [sheet.cell(row=index, column=1).value for index in range(2, 2 + len(VALUES))] == EXPECTED
