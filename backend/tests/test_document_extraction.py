"""Textextraktion: Parser je Format gegen echte, von LibreOffice erzeugte Dateien
(tests/fixtures/documents/generate.py), Normalisierung, Inhaltsformat und Sandbox-Einstieg."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from app.services.documents import formats
from app.services.documents.content import (
    SCHEMA_NAME,
    SCHEMA_VERSION,
    ParsedContent,
    build_content,
    normalize_text,
    paragraph,
    to_markdown,
    to_plain_text,
)
from app.services.documents.parsers import get_parser
from app.services.documents.parsers.text import decode_text
from app.services.documents.sandbox import python_entry_args

FIXTURES = Path(__file__).parent / "fixtures" / "documents"


def _content(name: str, parser: str, mime_type: str | None = None) -> dict:
    parsed = get_parser(parser)((FIXTURES / name).read_bytes())
    return build_content(parsed, mime_type=mime_type)


def _types(content: dict) -> list[str]:
    return [block["type"] for block in content["blocks"]]


@pytest.mark.parametrize(
    ("name", "parser"),
    [("sample.docx", "docx"), ("sample.odt", "odt"), ("sample.rtf", "rtf"), ("sample.pdf", "pdf")],
)
def test_office_formats_keep_structure_and_order(name, parser):
    content = _content(name, parser)
    blocks = content["blocks"]
    headings = [(block["level"], block["text"]) for block in blocks if block["type"] == "heading"]
    assert headings == [(1, "Jahresbericht Pfadi Musterhausen"), (2, "Aktivitäten"), (2, "Schluss")]
    assert any(block["type"] == "paragraph" and "Grüße aus dem Sommerlager – Ärger, Öl und Übermut" in block["text"] for block in blocks)
    lists = [block for block in blocks if block["type"] == "list"]
    bullet_texts = [item["text"] for block in lists for item in block["items"] if not item["ordered"]]
    assert bullet_texts == ["Wanderung auf den Säntis", "Lagerfeuer am See"]
    # Reihenfolge: Überschrift vor Liste vor Bild vor Schlussüberschrift.
    types = _types(content)
    assert types.index("heading") < types.index("list") < types.index("media")
    assert blocks[-1] == {"type": "paragraph", "text": "Allzeit bereit!", **({"page": 1} if parser == "pdf" else {})}


@pytest.mark.parametrize(("name", "parser"), [("sample.docx", "docx"), ("sample.odt", "odt"), ("sample.rtf", "rtf")])
def test_office_formats_extract_numbered_lists_and_tables(name, parser):
    content = _content(name, parser)
    ordered = [item["text"] for block in content["blocks"] if block["type"] == "list" for item in block["items"] if item["ordered"]]
    assert ordered == ["Rückblick und Ausblick", "Planung Herbstlager"]
    tables = [block for block in content["blocks"] if block["type"] == "table"]
    assert len(tables) == 1
    assert tables[0]["rows"] == [["Posten", "Betrag"], ["Material", "120.50"], ["Verpflegung", "340.00"]]


def test_docx_media_reference_points_into_the_package():
    media = [block for block in _content("sample.docx", "docx")["blocks"] if block["type"] == "media"]
    assert media == [{"type": "media", "media_type": "image", "ref": "media/image1.png", "content_type": "image/png", "alt": None}]


def test_pdf_blocks_carry_page_numbers_and_page_count():
    content = _content("sample.pdf", "pdf")
    assert content["page_count"] == 1
    assert all(block.get("page") == 1 for block in content["blocks"])


def test_scanned_pdf_is_flagged_for_ocr_without_inventing_text():
    parsed = get_parser("pdf")((FIXTURES / "scanned.pdf").read_bytes())
    assert parsed.needs_ocr is True
    content = build_content(parsed, mime_type=formats.PDF)
    assert [block for block in content["blocks"] if block["type"] in ("paragraph", "heading")] == []


def test_markdown_structure():
    content = _content("sample.md", "markdown")
    assert content["blocks"][0] == {"type": "heading", "level": 1, "text": "Lagerplanung"}
    # Inline-Markup bleibt unverändert, es wird nichts umgeschrieben.
    assert {"type": "paragraph", "text": "Einleitung mit **Markdown**."} in content["blocks"]
    items = [item for block in content["blocks"] if block["type"] == "list" for item in block["items"]]
    assert [(item["text"], item["level"], item["ordered"]) for item in items] == [
        ("Zelte", 0, False), ("Kocher", 0, False), ("Gas", 1, False), ("Packen", 0, True), ("Losfahren", 0, True),
    ]
    table = next(block for block in content["blocks"] if block["type"] == "table")
    assert table == {"type": "table", "rows": [["Tag", "Ort"], ["Mo", "Bern"], ["Di", "Thun"]], "header_rows": 1}
    assert content["blocks"][-1]["type"] == "media"


def test_plain_text_detects_windows_1252_and_normalizes_line_endings():
    content = _content("sample-cp1252.txt", "text")
    assert content["source"]["encoding"] == "cp1252"
    assert [block["text"] for block in content["blocks"]] == ["Grüße aus Zürich", "Zweiter Absatz – mit Gedankenstrich."]


def test_csv_becomes_one_table_without_guessing_a_header():
    content = _content("sample.csv", "csv")
    assert content["blocks"] == [
        {"type": "table", "rows": [["Name", "Funktion"], ["Anna", "Leitung"], ["Beat", "Kasse"]], "header_rows": 0}
    ]


@pytest.mark.parametrize(
    ("raw", "encoding"),
    [
        ("Grüße".encode("utf-8"), "utf-8"),
        (b"\xef\xbb\xbf" + "Grüße".encode("utf-8"), "utf-8-sig"),
        ("Grüße".encode("utf-16"), "utf-16"),
        ("Grüße".encode("cp1252"), "cp1252"),
        (b"\x81\x8d\x8f", "latin-1"),
    ],
)
def test_decode_text_is_deterministic(raw, encoding):
    text, detected = decode_text(raw)
    assert detected == encoding
    assert decode_text(raw) == (text, detected)


def test_normalize_text_is_idempotent_and_only_touches_invisible_characters():
    raw = "Café\r\nZeile­ zwei ​\t \r\rEnde\x07﻿"
    normalized = normalize_text(raw)
    assert normalized == "Café\nZeile zwei\n\nEnde"
    assert normalize_text(normalized) == normalized


def test_build_content_schema_plain_text_and_markdown():
    parsed = ParsedContent(
        parser="test", parser_version="1",
        blocks=[
            {"type": "heading", "level": 2, "text": " Titel "},
            paragraph("Absatz"),
            {"type": "list", "items": [{"text": "eins", "level": 0, "ordered": True}, {"text": "zwei", "level": 1, "ordered": False}]},
            {"type": "table", "rows": [["a|b", "c"], ["", ""], ["1"]], "header_rows": 1},
            paragraph("   "),
        ],
    )
    content = build_content(parsed, mime_type="text/plain")
    assert content["schema"] == SCHEMA_NAME and content["schema_version"] == SCHEMA_VERSION
    # Leere Absätze und leere Tabellenzeilen entfallen, kurze Zeilen werden aufgefüllt.
    assert content["blocks"][3]["rows"] == [["a|b", "c"], ["1", ""]]
    assert len(content["blocks"]) == 4
    assert to_plain_text(content) == "Titel\n\nAbsatz\n\neins\n  zwei\n\na|b\tc\n1\t"
    assert to_markdown(content) == "## Titel\n\nAbsatz\n\n1. eins\n   - zwei\n\n| a\\|b | c |\n| --- | --- |\n| 1 |  |\n"


@pytest.mark.parametrize("parser", ["docx", "odt", "pdf", "rtf"])
def test_corrupt_files_raise_instead_of_returning_garbage(parser):
    with pytest.raises(Exception):
        get_parser(parser)(b"PK\x03\x04 kaputt, kein gueltiges Dokument")


def test_odt_parser_rejects_external_entities(tmp_path):
    import io
    import zipfile

    xml = (
        '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY ext SYSTEM "file:///etc/passwd">]>'
        '<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
        'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"><office:body><office:text>'
        "<text:p>&ext;</text:p></office:text></office:body></office:document-content>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("content.xml", xml)
    try:
        content = build_content(get_parser("odt")(buffer.getvalue()), mime_type=formats.ODT)
    except Exception:
        return  # Ablehnen ist ebenso in Ordnung
    assert "root:" not in json.dumps(content)


def test_formats_classify_documents_and_exclude_images_and_archives():
    assert formats.is_document_mime(formats.DOCX)
    assert formats.is_document_mime(formats.PDF)
    assert formats.is_document_mime(formats.XLSX)
    for mime in ("image/jpeg", "application/zip", "video/mp4", "application/vnd.apple.pages", None):
        assert not formats.is_document_mime(mime)
    assert not formats.needs_conversion(formats.PDF)
    assert formats.needs_conversion(formats.DOCX)
    assert formats.extraction_parser(formats.XLSX) is None


def test_sandbox_entry_runs_isolated_without_app_configuration(tmp_path):
    source = tmp_path / "input.bin"
    source.write_bytes((FIXTURES / "sample.docx").read_bytes())
    output = tmp_path / "out.json"
    # Leere Umgebung: der Kindprozess darf weder Secrets noch die App-Konfiguration brauchen.
    subprocess.run(
        python_entry_args("extract", "docx", formats.DOCX, str(source), str(output)),
        check=True, env={"PATH": "/usr/bin:/bin"}, cwd=tmp_path, timeout=120,
    )
    content = json.loads(output.read_text(encoding="utf-8"))
    assert content["source"]["parser"] == "docx"
    assert content["needs_ocr"] is False
    assert content["blocks"][0]["text"] == "Jahresbericht Pfadi Musterhausen"


def test_sandbox_entry_reports_errors_on_stderr_without_traceback(tmp_path):
    source = tmp_path / "input.bin"
    source.write_bytes(b"kein docx")
    result = subprocess.run(
        python_entry_args("extract", "docx", formats.DOCX, str(source), str(tmp_path / "out.json")),
        env={"PATH": "/usr/bin:/bin"}, cwd=tmp_path, capture_output=True, timeout=120,
    )
    assert result.returncode == 1
    assert b"Traceback" not in result.stderr
    assert sys.executable  # Interpreter des Tests = Interpreter des Kindprozesses
