"""Übernahme früherer Gestaltungsdaten in Brand-Profile des Document Studio.

Zwei Quellen:

1. Hausstile der ersten Typst-Dokument-Engine (``document_style``: ``style_key`` plus Tokens).
   Genutzt von Migration 0118 und vom Import von Mandanten-Archiven dieser Version.
2. TeX-basierte Dokumentvorlagen (``document_template.configuration_json`` vor 0115). Genutzt
   vom Import älterer Mandanten-Archive: zuerst wie bisher in Hausstil-Tokens, dann in ein
   Brand-Profil übersetzt.

Übernommen werden Farben, Schrift (inkl. hochgeladener Schriften), Grösse, Zeilenabstand,
Ränder, Format, Logo und Fussbild, Absender und Ort, Kopf-/Fussvarianten (als Brand-Schalter)
sowie Titelseite, Inhaltsverzeichnis, Nummerierung, Metadaten und Entwurfs-Wasserzeichen (als
Dokument-Standards des Brand-Profils, nach denen sich die Systemvorlagen richten). Eigener
Vorlagen-Code (``slots``) entfällt ersatzlos; ``has_custom_slots`` meldet, ob ein Mandant welche
hatte.
"""
from __future__ import annotations

import re
from typing import Any

from app.documents.brand import BrandTokens

# ── TeX-Vorlagen → Hausstil-Tokens (Format der ersten Typst-Engine) ─────────

# logo_date zeigte Logo und Datum - die Variante «logo» zeigt Logo, Titel und Datum.
_HEADER = {"none": "none", "minimal": "minimal", "standard": "standard", "bar": "bar", "logo": "logo", "logo_bar": "logo_bar", "logo_date": "logo"}
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


def tokens_from_legacy(config: dict | None, asset_ids: dict[str, str] | None = None) -> dict[str, Any]:
    """TeX-Konfiguration → Hausstil-Tokens (dict im Format von ``document_style.tokens_json``).
    ``asset_ids``: Rolle (logo, footer_image, font_regular …) → public_id des neuen Assets."""
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

    title_page = _TITLE.get(str(presets.get("title_page") or ""), "none" if presets else "modern")
    if presets:
        toc_preset = str(presets.get("toc") or "standard")
        toc = "off" if toc_preset == "none" else ("compact" if toc_preset == "compact" else "on")
    else:
        toc = "on" if options.get("show_toc", True) else "off"
    if title_page == "cover" and toc == "off":
        toc = "on"

    return {
        "primary_color": _color(theme.get("primary_color"), "#174b7a"),
        "secondary_color": _color(theme.get("secondary_color"), "#4f6d7a"),
        "font": font,
        "custom_fonts": custom_fonts if font == "custom" else {},
        "base_size": base_size,
        "orientation": "landscape" if options.get("orientation") == "landscape" else "portrait",
        "logo_asset_id": asset_ids.get("logo"),
        "footer_image_asset_id": asset_ids.get("footer_image"),
        "sender": str(title_text.get("footer_contact") or "")[:600],
        "place": str(title_text.get("location") or "")[:120],
        "header": _HEADER.get(str(presets.get("header") or "standard"), "standard"),
        "footer": _FOOTER.get(str(presets.get("footer") or "standard"), "standard"),
        "title_page": title_page,
        "toc": toc,
        "numbering": options.get("numbering_mode", "sections") == "sections",
        # Alter Export: Block «Protocol Metadata» erschien, solange hide_metadata nicht gesetzt war.
        "show_metadata": not options.get("hide_metadata", False),
    }


# ── Hausstil-Tokens → Brand-Profil ───────────────────────────────────────────

_STYLE_FONTS = {"modern": "inter", "classic": "liberation_serif", "compact": "liberation_sans"}
_LINE_HEIGHT = {"tight": 1.2, "normal": 1.35, "relaxed": 1.6}
_MARGINS = {"narrow": 15.0, "normal": 22.0, "wide": 30.0}
_BUILTIN = {"inter", "liberation_sans", "liberation_serif", "noto_sans"}


def _hex(value: Any, fallback: str) -> str:
    text = str(value or "").strip()
    return text.upper() if re.fullmatch(r"#[0-9A-Fa-f]{6}", text) else fallback


def brand_tokens_from_style(style_key: str | None, tokens: dict[str, Any] | None) -> BrandTokens:
    """Hausstil (``style_key`` + Tokens der ersten Typst-Engine) → BrandTokens. Ungültige oder
    fehlende Werte fallen auf die Brand-Standardwerte zurück; das Ergebnis ist immer gültig."""
    tokens = tokens or {}
    key = style_key if style_key in _STYLE_FONTS else "modern"
    primary = _hex(tokens.get("primary_color"), "#174B7A")
    secondary = _hex(tokens.get("secondary_color"), "#4F6D7A")

    font_choice = str(tokens.get("font") or "style")
    custom = tokens.get("custom_fonts") or {}
    custom_ids = [custom.get(cut) for cut in ("regular", "bold", "italic", "bold_italic") if custom.get(cut)]
    if font_choice == "custom" and custom_ids:
        font = {"builtin": None, "asset_ids": custom_ids}
    else:
        font = {"builtin": font_choice if font_choice in _BUILTIN else _STYLE_FONTS[key], "asset_ids": []}

    base_size = tokens.get("base_size") if tokens.get("base_size") in (10, 11, 12) else (10 if key == "compact" else 11)
    margin = _MARGINS.get(str(tokens.get("margins") or ("narrow" if key == "compact" else "normal")), 22.0)
    header = str(tokens.get("header") or "standard")
    footer = str(tokens.get("footer") or "standard")
    title_page = str(tokens.get("title_page") or "none")
    toc = str(tokens.get("toc") or "off")

    data: dict[str, Any] = {
        "colors": {
            "primary": primary,
            "secondary": secondary,
            "heading": "#111827" if key == "classic" else primary,
        },
        "typography": {
            "body": font,
            "heading": font,
            "base_size": float(base_size) - (0.5 if key != "compact" else 0),
            "line_height": _LINE_HEIGHT.get(str(tokens.get("line_spacing") or ("tight" if key == "compact" else "normal")), 1.35),
        },
        "assets": {
            "logo": tokens.get("logo_asset_id"),
            "footer_image": tokens.get("footer_image_asset_id"),
        },
        "layout": {
            "orientation": "landscape" if tokens.get("orientation") == "landscape" else "portrait",
            "margins": {"top": margin, "right": margin, "bottom": margin, "left": margin},
            "heading_style": {"modern": "underline", "classic": "plain", "compact": "bar"}[key],
            "table_style": {"modern": "lines", "classic": "grid", "compact": "zebra"}[key],
            "header_footer": {
                "header_show_logo": header in ("logo", "logo_bar"),
                "header_show_title": header not in ("none", "minimal"),
                "header_show_date": header not in ("none", "minimal"),
                "header_line": header not in ("none", "minimal"),
                "footer_show_number": footer in ("standard", "with_version"),
                "footer_show_pages": footer != "none",
                "footer_line": footer not in ("none", "minimal"),
            },
            "title_page": title_page != "none",
            "toc": toc != "off",
            "heading_numbering": bool(tokens.get("numbering", False)),
            "show_metadata": bool(tokens.get("show_metadata", False)),
            "watermark_draft": bool(tokens.get("watermark_draft", True)),
        },
        "organization": {
            "address": str(tokens.get("sender") or "")[:600],
            "place": str(tokens.get("place") or "")[:120],
        },
        "verify": {
            "show_url": bool(tokens.get("verify_show_url", True)),
            "show_id": bool(tokens.get("verify_show_id", True)),
            "show_qr": bool(tokens.get("verify_show_qr", True)),
        },
    }
    if key == "compact":
        data["typography"].update({"size_h1": 14, "size_h2": 12, "size_h3": 10.5})
    try:
        return BrandTokens.model_validate(data)
    except ValueError:
        # Defekte Asset-Referenzen o. ä.: ohne Assets übernehmen statt den Mandanten zu verlieren
        data["assets"] = {}
        data["typography"]["body"] = data["typography"]["heading"] = {"builtin": _STYLE_FONTS[key], "asset_ids": []}
        return BrandTokens.model_validate(data)


def brand_tokens_from_legacy(config: dict | None, asset_ids: dict[str, str] | None = None) -> BrandTokens:
    """TeX-Vorlage → BrandTokens (Import älterer Mandanten-Archive)."""
    return brand_tokens_from_style("modern", tokens_from_legacy(config, asset_ids))


# ── Dokument-Rezepte → Vorlageninhalt ────────────────────────────────────────

_SPACER_MM = {"s": 4.0, "m": 8.0, "l": 16.0}


def _plain(value: str) -> dict[str, Any]:
    return {"default": [{"t": "text", "v": value}]}


def content_from_recipe(blocks: list[dict[str, Any]] | None, options: dict[str, Any] | None = None) -> dict[str, Any]:
    """Rezept der ersten Typst-Engine (Blockliste + Export-Optionen) → TemplateContent-JSON.

    Strukturblöcke werden zu Layoutknoten, Fachblöcke zu ``data_block``-Knoten mit denselben
    Parametern (gleicher Katalog). Unbekannte Blöcke entfallen. Das Ergebnis nutzt Kopf und
    Fuss der Standard-Systemvorlage, damit das Rezept wie bisher aussieht."""
    from app.documents.catalog import CATALOG
    from app.documents.system_templates import cover_title_page, standard_master

    options = options or {}
    body: list[dict[str, Any]] = []
    for index, spec in enumerate(blocks or []):
        if not isinstance(spec, dict):
            continue
        block_type = spec.get("type")
        params = spec.get("params") or {}
        node_id = f"r{index + 1}"
        title = (spec.get("title") or "").strip()
        if block_type == "heading":
            body.append({"type": "text", "id": node_id, "role": "heading", "level": int(spec.get("level") or 1), "content": _plain(str(params.get("text") or title))})
        elif block_type in ("richtext", "static_text"):
            if title:
                body.append({"type": "text", "id": f"{node_id}-t", "role": "heading", "level": int(spec.get("level") or 1), "content": _plain(title)})
            body.append({"type": "rich_text", "id": node_id, "markdown": str(params.get("markdown") or "")})
        elif block_type == "page_break":
            body.append({"type": "page_break", "id": node_id})
        elif block_type == "toc":
            body.append({"type": "toc", "id": node_id, "depth": int(params.get("depth") or 2)})
        elif block_type == "spacer":
            body.append({"type": "spacer", "id": node_id, "size": _SPACER_MM.get(str(params.get("size") or "m"), 8.0)})
        elif block_type == "divider":
            body.append({"type": "divider", "id": node_id})
        elif block_type == "bullet_list":
            body.append({"type": "list", "id": node_id, "items": [str(item) for item in params.get("items") or [] if str(item).strip()]})
        elif block_type == "qr_link":
            qr: dict[str, Any] = {"type": "qr_code", "id": node_id, "target": "url" if params.get("target") == "url" else "protocol"}
            if params.get("url"):
                qr["url"] = params["url"]
            if params.get("label"):
                qr["caption"] = _plain(str(params["label"]))
            body.append(qr)
        elif block_type == "generic_table":
            headers = [str(value) for value in params.get("headers") or []]
            rows = [[str(cell) for cell in row] for row in params.get("rows") or []]
            width = max([len(headers), *(len(row) for row in rows)] or [0])
            if width:
                body.append({
                    "type": "table",
                    "id": node_id,
                    "columns": [{"id": f"{node_id}-c{column}", "header": _plain(headers[column] if column < len(headers) else "")} for column in range(width)],
                    "rows": rows,
                })
        elif block_type in CATALOG:
            node: dict[str, Any] = {
                "type": "data_block",
                "id": node_id,
                "component": block_type,
                "params": params,
                "hide_if_empty": bool(spec.get("hide_if_empty", True)),
                "level": int(spec.get("level") or 1),
            }
            if title:
                node.update(title=_plain(title), title_mode="custom")
            body.append(node)
    if options.get("toc") not in (None, "", "off"):
        body.insert(0, {"type": "toc", "id": "r-toc", "depth": 2})
    content: dict[str, Any] = {"masters": [standard_master()], "body": body}
    if options.get("title_page") not in (None, "", "none"):
        content["title_page"] = cover_title_page(condition=False)
    if options.get("orientation") == "landscape":
        content["page"] = {"orientation": "landscape"}
    if options.get("numbering") is not None:
        content["settings"] = {"heading_numbering": bool(options.get("numbering"))}
    return content
