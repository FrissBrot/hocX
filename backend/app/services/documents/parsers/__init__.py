"""Formatspezifische Parser der Textextraktion. Jeder Parser nimmt die Originalbytes und liefert
ParsedContent (app/services/documents/content.py); Normalisierung passiert danach zentral.

Die Parser laufen nur im isolierten Kindprozess (siehe sandbox_entry.py) - nie im Webprozess."""

from __future__ import annotations

from collections.abc import Callable

from app.services.documents.content import ParsedContent


def get_parser(name: str) -> Callable[[bytes], ParsedContent]:
    if name == "text":
        from app.services.documents.parsers.text import parse_plain_text

        return parse_plain_text
    if name == "markdown":
        from app.services.documents.parsers.text import parse_markdown

        return parse_markdown
    if name == "csv":
        from app.services.documents.parsers.text import parse_csv

        return parse_csv
    if name == "pdf":
        from app.services.documents.parsers.pdf import parse_pdf

        return parse_pdf
    if name == "docx":
        from app.services.documents.parsers.docx import parse_docx

        return parse_docx
    if name == "odt":
        from app.services.documents.parsers.odt import parse_odt

        return parse_odt
    if name == "rtf":
        from app.services.documents.parsers.rtf import parse_rtf

        return parse_rtf
    raise ValueError(f"Unbekannter Parser: {name}")
