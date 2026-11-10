"""Einheitliches, versioniertes Inhaltsformat ("hocx.document-content") und deterministische
Normalisierung.

Das Format ist die spätere Eingabe für das Zusammenführen mehrerer Dokumente. Es beschreibt nur
Struktur und Text, keine Optik. Blocktypen (Schema-Version 1):

- heading    {"text", "level" (1-6)}
- paragraph  {"text"}
- list       {"items": [{"text", "level" (0-based), "ordered"}]}
- table      {"rows": [[zelle, ...], ...], "header_rows"}
- media      {"media_type": "image", "ref", "content_type", "alt"}

Jeder Block kann "page" (1-based) tragen, wenn die Quelle Seiten kennt (PDF).

Normalisierung verändert keinen Inhalt im fachlichen Sinn: Unicode NFC, Zeilenenden, unsichtbare
Steuerzeichen und Leerraum am Zeilenende. Es wird nichts ergänzt, umformuliert oder übersetzt.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

SCHEMA_NAME = "hocx.document-content"
SCHEMA_VERSION = 1

BLOCK_TYPES = ("heading", "paragraph", "list", "table", "media")

# Unsichtbare Zeichen ohne Inhalt: BOM/Zero-Width-No-Break-Space, weicher Trennstrich, Zero-Width-Space.
_INVISIBLE = dict.fromkeys(map(ord, "\ufeff\u00ad\u200b"), None)
# C0/C1-Steuerzeichen ausser Tab und Zeilenumbruch, DEL.
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
_TRAILING_WS = re.compile(r"[ \t]+\n")
_MANY_BLANK_LINES = re.compile(r"\n{3,}")


def normalize_text(value: str) -> str:
    """Deterministische Textnormalisierung (siehe Moduldoku). Idempotent."""
    if not value:
        return ""
    value = value.replace("\r\n", "\n").replace("\r", "\n").replace("\u2028", "\n").replace("\u2029", "\n")
    value = value.translate(_INVISIBLE)
    value = _CONTROL.sub("", value)
    value = unicodedata.normalize("NFC", value)
    value = _TRAILING_WS.sub("\n", value)
    value = _MANY_BLANK_LINES.sub("\n\n", value)
    return value.strip("\n").rstrip()


def normalize_inline(value: str) -> str:
    """Wie normalize_text, für einzeilige Inhalte (Überschrift, Tabellenzelle bleibt mehrzeilig
    erlaubt): zusätzlich führender/abschliessender Leerraum entfernt."""
    return normalize_text(value).strip()


@dataclass
class ParsedContent:
    """Ergebnis eines Parsers, vor der Normalisierung."""

    parser: str
    parser_version: str
    blocks: list[dict[str, Any]] = field(default_factory=list)
    page_count: int | None = None
    encoding: str | None = None
    warnings: list[str] = field(default_factory=list)
    # PDF ohne nennenswerte Textebene (gescannt) - OCR nötig.
    needs_ocr: bool = False
    ocr_applied: bool = False


def heading(text: str, level: int, *, page: int | None = None) -> dict[str, Any]:
    return _with_page({"type": "heading", "level": max(1, min(int(level), 6)), "text": text}, page)


def paragraph(text: str, *, page: int | None = None) -> dict[str, Any]:
    return _with_page({"type": "paragraph", "text": text}, page)


def table(rows: list[list[str]], *, header_rows: int = 0, page: int | None = None) -> dict[str, Any]:
    return _with_page({"type": "table", "rows": rows, "header_rows": header_rows}, page)


def media(ref: str, *, content_type: str | None = None, alt: str | None = None, page: int | None = None) -> dict[str, Any]:
    return _with_page({"type": "media", "media_type": "image", "ref": ref, "content_type": content_type, "alt": alt}, page)


def _with_page(block: dict[str, Any], page: int | None) -> dict[str, Any]:
    if page is not None:
        block["page"] = page
    return block


class BlockBuilder:
    """Sammelt Blöcke in Dokumentreihenfolge und fasst aufeinanderfolgende Listeneinträge zu einem
    Listenblock zusammen."""

    def __init__(self) -> None:
        self.blocks: list[dict[str, Any]] = []

    def add(self, block: dict[str, Any]) -> None:
        self.blocks.append(block)

    def list_item(self, text: str, *, level: int = 0, ordered: bool = False, page: int | None = None) -> None:
        item = {"text": text, "level": max(0, int(level)), "ordered": ordered}
        last = self.blocks[-1] if self.blocks else None
        if last is not None and last["type"] == "list" and last.get("page") == page:
            last["items"].append(item)
            return
        self.blocks.append(_with_page({"type": "list", "items": [item]}, page))


def _normalize_block(block: dict[str, Any]) -> dict[str, Any] | None:
    kind = block.get("type")
    if kind in ("heading", "paragraph"):
        text = normalize_inline(block.get("text") or "") if kind == "heading" else normalize_text(block.get("text") or "")
        if not text:
            return None
        return {**block, "text": text}
    if kind == "list":
        items = []
        for item in block.get("items") or []:
            text = normalize_text(item.get("text") or "")
            if text:
                items.append({**item, "text": text})
        return {**block, "items": items} if items else None
    if kind == "table":
        rows = [[normalize_text(str(cell or "")) for cell in row] for row in block.get("rows") or []]
        rows = [row for row in rows if any(cell for cell in row)]
        if not rows:
            return None
        width = max(len(row) for row in rows)
        rows = [row + [""] * (width - len(row)) for row in rows]
        return {**block, "rows": rows, "header_rows": min(int(block.get("header_rows") or 0), len(rows))}
    if kind == "media":
        return {**block, "alt": normalize_inline(block["alt"]) if block.get("alt") else None}
    return None


def build_content(parsed: ParsedContent, *, mime_type: str | None) -> dict[str, Any]:
    """Normalisiert die Parser-Ausgabe zum gespeicherten Inhaltsformat."""
    blocks = [normalized for block in parsed.blocks if (normalized := _normalize_block(block)) is not None]
    return {
        "schema": SCHEMA_NAME,
        "schema_version": SCHEMA_VERSION,
        "source": {
            "mime_type": mime_type,
            "parser": parsed.parser,
            "parser_version": parsed.parser_version,
            "encoding": parsed.encoding,
        },
        "page_count": parsed.page_count,
        "ocr_applied": parsed.ocr_applied,
        "blocks": blocks,
        "warnings": list(parsed.warnings),
    }


def to_plain_text(content: dict[str, Any]) -> str:
    """Klartext aus den Blöcken: Blöcke durch Leerzeile getrennt, Listeneinträge zeilenweise mit
    Einrückung nach Ebene, Tabellenzellen durch Tab getrennt. Keine Aufzählungszeichen, damit der
    Text nichts enthält, was nicht im Dokument steht."""
    parts: list[str] = []
    for block in content.get("blocks") or []:
        kind = block["type"]
        if kind in ("heading", "paragraph"):
            parts.append(block["text"])
        elif kind == "list":
            parts.append("\n".join(f"{'  ' * item['level']}{item['text']}" for item in block["items"]))
        elif kind == "table":
            parts.append("\n".join("\t".join(cell.replace("\n", " ") for cell in row) for row in block["rows"]))
    return "\n\n".join(part for part in parts if part)


def _md_escape_cell(value: str) -> str:
    return value.replace("\\", "\\\\").replace("|", "\\|").replace("\n", "<br>")


def to_markdown(content: dict[str, Any]) -> str:
    """Markdown-Darstellung der Blöcke (deterministisch, wird nicht gespeichert)."""
    parts: list[str] = []
    for block in content.get("blocks") or []:
        kind = block["type"]
        if kind == "heading":
            parts.append(f"{'#' * block['level']} {block['text']}")
        elif kind == "paragraph":
            parts.append(block["text"])
        elif kind == "list":
            lines = []
            counters: dict[int, int] = {}
            for item in block["items"]:
                level = item["level"]
                counters = {key: value for key, value in counters.items() if key <= level}
                if item["ordered"]:
                    counters[level] = counters.get(level, 0) + 1
                    marker = f"{counters[level]}."
                else:
                    marker = "-"
                text = item["text"].replace("\n", "\n" + "   " * (level + 1))
                lines.append(f"{'   ' * level}{marker} {text}")
            parts.append("\n".join(lines))
        elif kind == "table":
            rows = block["rows"]
            header_rows = block.get("header_rows") or 0
            header = rows[0] if header_rows else [""] * len(rows[0])
            body = rows[1:] if header_rows else rows
            lines = [
                "| " + " | ".join(_md_escape_cell(cell) for cell in header) + " |",
                "| " + " | ".join("---" for _ in header) + " |",
                *("| " + " | ".join(_md_escape_cell(cell) for cell in row) + " |" for row in body),
            ]
            parts.append("\n".join(lines))
        elif kind == "media":
            alt = (block.get("alt") or "").replace("]", "")
            parts.append(f"![{alt}]({block['ref']})")
    return "\n\n".join(parts) + ("\n" if parts else "")
