"""Übersetzung der früheren (TeX-basierten) Dokumentvorlagen (document_template.configuration_json) in
Hausstil-Tokens. Genutzt von der Migration 0115 und vom Import älterer Mandanten-Archive.

Übernommen werden Farben, Schriftgrösse, Schriftfamilie (inkl. hochgeladener Schriften),
Format, Kopf-, Fuss-, Titelseiten- und TOC-Variante, Nummerierung, Ort und Absender sowie Logo
und Fussbild. Eigener Vorlagen-Code (``slots``) entfällt ersatzlos; ``has_custom_slots`` meldet,
ob ein Mandant welche hatte (Hinweis in den Release-Notes und im Migrationsprotokoll).
"""
from __future__ import annotations

import re
from typing import Any

from app.documents.style_tokens import DocumentStyleTokens

_HEADER = {"none": "none", "minimal": "minimal", "standard": "standard", "bar": "bar", "logo": "logo", "logo_bar": "logo", "logo_date": "logo"}
_FOOTER = {"none": "none", "minimal": "minimal", "standard": "standard", "with_version": "with_version", "date_page": "date_page"}
_TITLE = {"none": "none", "minimal": "minimal", "modern": "modern", "bold": "bold", "combined_toc": "cover"}
_FONT = {"arial": "liberation_sans", "helvet": "liberation_sans", "palatino": "liberation_serif"}
FONT_SLOTS = {"font_regular": "regular", "font_bold": "bold", "font_italic": "italic", "font_bold_italic": "bold_italic"}


def _color(value: Any, fallback: str) -> str:
    text = str(value or "").strip().lstrip("#")
    return f"#{text.lower()}" if re.fullmatch(r"[0-9a-fA-F]{6}", text) else fallback


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def legacy_part_refs(config: dict | None) -> dict[str, int]:
    """Part-IDs, die als Logo/Fussbild oder Schrift verwendet werden: Rolle → interne Part-ID."""
    config = config or {}
    refs: dict[str, int] = {}
    assets = config.get("title_assets") or {}
    for role, key in (("logo", "header_image_part_id"), ("footer_image", "footer_image_part_id")):
        part_id = _int(assets.get(key))
        if part_id:
            refs[role] = part_id
    for slot in FONT_SLOTS:
        part_id = _int(((config.get("theme") or {}).get("font_parts") or {}).get(slot))
        if part_id:
            refs[slot] = part_id
    return refs


def has_custom_slots(config: dict | None) -> bool:
    return any(value for value in ((config or {}).get("slots") or {}).values())


def tokens_from_legacy(config: dict | None, asset_ids: dict[str, str] | None = None) -> DocumentStyleTokens:
    """``asset_ids``: Rolle (logo, footer_image, font_regular …) → public_id des neuen Assets."""
    config = config or {}
    asset_ids = asset_ids or {}
    theme = config.get("theme") or {}
    options = config.get("options") or {}
    presets = config.get("presets") or {}
    title_text = config.get("title_text") or {}

    size = _int(str(theme.get("font_size", "11")).replace("pt", "")) or 11
    base_size = min(max(size, 10), 12)

    font = _FONT.get(str(theme.get("font_family") or ""), "style")
    custom_fonts = {cut: asset_ids.get(slot) for slot, cut in FONT_SLOTS.items()}
    if theme.get("font_family") in ("century_gothic", "uploaded") and custom_fonts.get("regular"):
        font = "custom"
    elif font == "custom":
        font = "style"

    title_page = _TITLE.get(str(presets.get("title_page") or ""), "none" if presets else "modern")
    if presets:
        toc_preset = str(presets.get("toc") or "standard")
        toc = "off" if toc_preset == "none" else ("compact" if toc_preset == "compact" else "on")
    else:
        toc = "on" if options.get("show_toc", True) else "off"
    if title_page == "cover" and toc == "off":
        toc = "on"
    if options.get("toc_spacing") in ("compact", "very_compact") and toc == "on":
        toc = "compact"

    return DocumentStyleTokens(
        primary_color=_color(theme.get("primary_color"), "#174b7a"),
        secondary_color=_color(theme.get("secondary_color"), "#4f6d7a"),
        font=font,
        custom_fonts={key: value for key, value in custom_fonts.items()} if font == "custom" else {},
        base_size=base_size,
        orientation="landscape" if options.get("orientation") == "landscape" else "portrait",
        logo_asset_id=asset_ids.get("logo"),
        footer_image_asset_id=asset_ids.get("footer_image"),
        sender=str(title_text.get("footer_contact") or "")[:600],
        place=str(title_text.get("location") or "")[:120],
        header=_HEADER.get(str(presets.get("header") or "standard"), "standard"),
        footer=_FOOTER.get(str(presets.get("footer") or "standard"), "standard"),
        title_page=title_page,
        toc=toc,
        numbering=options.get("numbering_mode", "sections") == "sections",
    )
