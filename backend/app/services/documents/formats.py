"""Welche Dateien sind Dokumente, was lässt sich konvertieren, womit wird extrahiert.

Grundlage ist ausschliesslich stored_file.mime_type: alle Uploadwege leiten ihn serverseitig aus
den Magic Bytes und einer festen Endungsliste ab (upload_pipeline._sniff_document_mime,
abgabebox-backend routes/public.py::_EXTENSION_MIME_MAP) und vertrauen nie dem Client.

Bewusst keine Dokumente: Bilder, Videos, ZIP-Archive und Apple-iWork-Dateien (Pages/Keynote/
Numbers - LibreOffice liest nur ältere Varianten zuverlässig). Sie bleiben normale Dateien ohne
Dokumentebene, damit sie nie wie Textdokumente verarbeitet werden.
"""

from __future__ import annotations

PDF = "application/pdf"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
DOC = "application/msword"
ODT = "application/vnd.oasis.opendocument.text"
RTF = "application/rtf"
TXT = "text/plain"
MD = "text/markdown"
CSV = "text/csv"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
XLS = "application/vnd.ms-excel"
ODS = "application/vnd.oasis.opendocument.spreadsheet"
PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
PPT = "application/vnd.ms-powerpoint"
ODP = "application/vnd.oasis.opendocument.presentation"

TEXT_MIMES = frozenset({TXT, MD, CSV})

# MIME -> Dateiendung für die Konvertierung (LibreOffice wählt den Importfilter nach Endung).
CONVERTIBLE_TO_PDF: dict[str, str] = {
    DOCX: ".docx",
    DOC: ".doc",
    ODT: ".odt",
    RTF: ".rtf",
    TXT: ".txt",
    MD: ".txt",
    CSV: ".csv",
    XLSX: ".xlsx",
    XLS: ".xls",
    ODS: ".ods",
    PPTX: ".pptx",
    PPT: ".ppt",
    ODP: ".odp",
}

# MIME -> Parser der Textextraktion (Name = Modul in app.services.documents.parsers).
EXTRACTION_PARSERS: dict[str, str] = {
    PDF: "pdf",
    DOCX: "docx",
    DOC: "doc",
    ODT: "odt",
    RTF: "rtf",
    TXT: "text",
    MD: "markdown",
    CSV: "csv",
}

DOCUMENT_MIMES = frozenset({PDF, *CONVERTIBLE_TO_PDF, *EXTRACTION_PARSERS})


def is_document_mime(mime_type: str | None) -> bool:
    return mime_type in DOCUMENT_MIMES


def needs_conversion(mime_type: str | None) -> bool:
    return mime_type in CONVERTIBLE_TO_PDF


def extraction_parser(mime_type: str | None) -> str | None:
    return EXTRACTION_PARSERS.get(mime_type or "")
