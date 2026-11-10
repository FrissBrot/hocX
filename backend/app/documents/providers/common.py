"""Gemeinsame Hilfen der Provider (keine Layout-Entscheidungen, nur Datenform)."""
from __future__ import annotations

import unicodedata
from typing import Any

from app.documents.catalog import BlockSpec
from app.documents.model import Cell, TableColumn, Tag

PROTOCOL_STATUS_CODES = {
    "geplant": "planned",
    "vorbereitet": "prepared",
    "durchgeführt": "held",
    "abgeschlossen": "closed",
}


def spec_fields(spec: BlockSpec, **overrides: Any) -> dict[str, Any]:
    fields = {"title": spec.title, "hide_if_empty": spec.hide_if_empty, "level": spec.level}
    fields.update(overrides)
    return fields


def col(key: str, label_key: str | None = None, *, label: str | None = None, align: str = "left", width: str = "auto") -> TableColumn:
    return TableColumn(key=key, label_key=label_key, label=label, align=align, width=width)


def text_cell(value: Any, **kwargs: Any) -> Cell:
    return Cell(k="text", v=str(value if value is not None else ""), **kwargs)


def amount_cell(value: str, **kwargs: Any) -> Cell:
    return Cell(k="amount", v=value, **kwargs)


def status_cell(key: str) -> Cell:
    return Cell(k="status", status=key)


def safe_color(value: Any) -> str | None:
    text = str(value or "")
    if len(text) == 7 and text.startswith("#") and all(char in "0123456789abcdefABCDEF" for char in text[1:]):
        return text
    return None


def tags_cell(tags: list[str], tag_config: dict | None = None) -> Cell:
    config = tag_config or {}
    return Cell(k="tags", tags=[Tag(label=tag, color=safe_color((config.get(tag) or {}).get("color"))) for tag in tags])


def split_tag_text(value: str | None) -> list[str]:
    return [tag.strip() for tag in str(value or "").split(",") if tag.strip()]


def sort_key(value: str | None) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or "").strip())
    return "".join(character for character in normalized if not unicodedata.combining(character)).casefold()


def inline_text(value: str | None) -> str:
    return " ".join(str(value or "").split()).strip()
