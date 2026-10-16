"""Dokument-Engine: bisherige Dokumentvorlagen übernehmen und die TeX-Strukturen entfernen.

1. Jede document_template wird ein document_style (Tokens über die hier eingefrorene Übersetzung, Stand app.documents.legacy 2026-10-16). Bild- und
   Schrift-Bestandteile (document_template_part) werden document_style_asset; die Datei bleibt am
   selben Speicherort (keine Kopie, kein Verlust). Eigener Vorlagen-Code (Slots) entfällt; betroffene
   Mandanten werden im Migrationsprotokoll genannt (siehe auch Release-Notes).
2. template/protocol.document_style_id aus den bisherigen Verweisen setzen.
3. protocol_export_cache (PDF) wird document_export (ohne Inhalts-Hash), damit Historie und
   Speicherstatistik erhalten bleiben.
4. Alte Tabellen und Spalten entfernen: document_template, document_template_part,
   protocol_export_cache, protocol.document_template_*, template.document_template_id,
   stored_file.latex_path, *_block.latex_template(_snapshot).

Dateien (document_templates/, document_template_snapshots/, .tex-Parts, latex_templates/)
entfernt nach dem Update scripts/cleanup-legacy-document-templates.sh; hochgeladene Schriften und
Bilder bleiben, weil document_style_asset auf sie zeigt.

Nicht umkehrbar: downgrade() bricht ab.
"""
from __future__ import annotations

import json
import re
import logging
import os
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = "0115_document_engine_migrate"
down_revision = "0114_document_engine"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.runtime.migration")

_IMAGE_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
_FONT_MIME = {".ttf": "font/ttf", ".otf": "font/otf"}


def _font_family(storage_path: str) -> str | None:
    root = os.environ.get("STORAGE_ROOT", "/app/storage")
    path = Path(root) / storage_path
    try:
        from fontTools.ttLib import TTFont

        font = TTFont(str(path), lazy=True, fontNumber=0)
        try:
            name = font["name"]
            return str(name.getDebugName(16) or name.getDebugName(1) or "").strip() or None
        finally:
            font.close()
    except Exception:  # noqa: BLE001 - Datei fehlt/unlesbar: Schrift ohne Familie, Stil nutzt Hausschrift
        return None


def _table_exists(conn, name: str) -> bool:
    return bool(conn.execute(sa.text("SELECT to_regclass(:name)"), {"name": f"public.{name}"}).scalar())


# ── Eingefrorene Übersetzung (Audit TYPST-014) ─────────────────────────────────────────────
# Stand von app/documents/legacy.py und DocumentStyleTokens am 2026-10-16, bewusst kopiert statt
# importiert: spätere Änderungen am App-Code dürfen das Ergebnis dieser historischen Migration
# nicht verändern. Nicht anpassen; neue Token-Felder kommen über ihre Standardwerte dazu.
_FROZEN_TOKEN_DEFAULTS: dict = {
    "primary_color": "#174b7a",
    "secondary_color": "#4f6d7a",
    "font": "style",
    "custom_fonts": {"regular": None, "bold": None, "italic": None, "bold_italic": None},
    "base_size": 11,
    "line_spacing": "normal",
    "margins": "normal",
    "orientation": "portrait",
    "logo_asset_id": None,
    "footer_image_asset_id": None,
    "sender": "",
    "sender_color": None,
    "place": "",
    "header": "standard",
    "footer": "standard",
    "title_page": "modern",
    "toc": "on",
    "numbering": True,
    "toc_block_titles": True,
    "show_metadata": True,
    "watermark_draft": True,
    "verify_show_url": True,
    "verify_show_id": True,
    "verify_show_qr": True,
}
_HEADER = {"none": "none", "minimal": "minimal", "standard": "standard", "bar": "bar", "logo": "logo", "logo_bar": "logo_bar", "logo_date": "logo"}
_FOOTER = {"none": "none", "minimal": "minimal", "standard": "standard", "with_version": "with_version", "date_page": "date_page"}
_TITLE = {"none": "none", "minimal": "minimal", "modern": "modern", "bold": "bold", "combined_toc": "cover"}
_FONT = {"arial": "liberation_sans", "helvet": "liberation_sans", "palatino": "liberation_serif"}
_FONT_SLOTS = {"font_regular": "regular", "font_bold": "bold", "font_italic": "italic", "font_bold_italic": "bold_italic"}


def _color(value, fallback: str) -> str:
    text = str(value or "").strip().lstrip("#")
    return f"#{text.lower()}" if re.fullmatch(r"[0-9a-fA-F]{6}", text) else fallback


def _int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def legacy_part_refs(config: dict | None) -> dict[str, int]:
    config = config or {}
    refs: dict[str, int] = {}
    assets = config.get("title_assets") or {}
    for role, key in (("logo", "header_image_part_id"), ("footer_image", "footer_image_part_id")):
        part_id = _int(assets.get(key))
        if part_id:
            refs[role] = part_id
    for slot in _FONT_SLOTS:
        part_id = _int(((config.get("theme") or {}).get("font_parts") or {}).get(slot))
        if part_id:
            refs[slot] = part_id
    return refs


def has_custom_slots(config: dict | None) -> bool:
    return any(value for value in ((config or {}).get("slots") or {}).values())


def tokens_from_legacy(config: dict | None, asset_ids: dict[str, str] | None = None) -> dict:
    config = config or {}
    asset_ids = asset_ids or {}
    theme = config.get("theme") or {}
    options = config.get("options") or {}
    presets = config.get("presets") or {}
    title_text = config.get("title_text") or {}

    size = _int(str(theme.get("font_size", "11")).replace("pt", "")) or 11
    font = _FONT.get(str(theme.get("font_family") or ""), "style")
    custom_fonts = {cut: asset_ids.get(slot) for slot, cut in _FONT_SLOTS.items()}
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
    if toc in ("on", "compact") and options.get("toc_spacing") in ("compact", "very_compact"):
        toc = options["toc_spacing"]

    tokens = json.loads(json.dumps(_FROZEN_TOKEN_DEFAULTS))
    tokens.update(
        primary_color=_color(theme.get("primary_color"), "#174b7a"),
        secondary_color=_color(theme.get("secondary_color"), "#4f6d7a"),
        font=font,
        base_size=min(max(size, 10), 12),
        orientation="landscape" if options.get("orientation") == "landscape" else "portrait",
        logo_asset_id=asset_ids.get("logo"),
        footer_image_asset_id=asset_ids.get("footer_image"),
        sender=str(title_text.get("footer_contact") or "")[:600],
        sender_color=_color(title_text.get("footer_color"), "") or None,
        place=str(title_text.get("location") or "")[:120],
        header=_HEADER.get(str(presets.get("header") or "standard"), "standard"),
        footer=_FOOTER.get(str(presets.get("footer") or "standard"), "standard"),
        title_page=title_page,
        toc=toc,
        numbering=options.get("numbering_mode", "sections") == "sections",
        show_metadata=not options.get("hide_metadata", False),
    )
    if font == "custom":
        tokens["custom_fonts"] = custom_fonts
    return tokens


def upgrade() -> None:
    conn = op.get_bind()
    if _table_exists(conn, "document_template"):
        parts = {
            row.id: row
            for row in conn.execute(sa.text("SELECT id, tenant_id, name, part_type, storage_path, created_at FROM document_template_part")).all()
        }
        asset_ids: dict[tuple[int, str], str] = {}  # (part_id, kind) → asset public_id
        style_map: dict[int, int] = {}
        tenants_with_slots: set[int] = set()
        # Mandanten mit bereits vorhandenem Standard-Hausstil (z. B. vom App-Start) behalten ihn.
        default_seen: set[int] = set(conn.execute(sa.text("SELECT tenant_id FROM document_style WHERE is_default")).scalars())

        templates = conn.execute(
            sa.text("SELECT id, tenant_id, name, is_default, is_active, configuration_json FROM document_template WHERE tenant_id IS NOT NULL ORDER BY tenant_id, is_default DESC, id")
        ).all()
        for template in templates:
            config = template.configuration_json or {}
            if has_custom_slots(config):
                tenants_with_slots.add(template.tenant_id)
            role_ids: dict[str, str] = {}
            for role, part_id in legacy_part_refs(config).items():
                part = parts.get(part_id)
                if part is None or part.tenant_id != template.tenant_id:
                    continue
                kind = "font" if role.startswith("font_") else "image"
                suffix = Path(part.storage_path).suffix.lower()
                if (kind == "image" and suffix not in _IMAGE_MIME) or (kind == "font" and suffix not in _FONT_MIME):
                    continue
                key = (part_id, kind)
                if key not in asset_ids:
                    asset_ids[key] = str(conn.execute(
                        sa.text(
                            "INSERT INTO document_style_asset (tenant_id, kind, name, original_name, mime_type, storage_path, font_family, created_at) "
                            "VALUES (:tenant_id, :kind, :name, :original_name, :mime, :path, :family, :created_at) RETURNING public_id"
                        ),
                        {
                            "tenant_id": part.tenant_id,
                            "kind": kind,
                            "name": part.name,
                            "original_name": Path(part.storage_path).name,
                            "mime": (_FONT_MIME if kind == "font" else _IMAGE_MIME)[suffix],
                            "path": part.storage_path,
                            "family": _font_family(part.storage_path) if kind == "font" else None,
                            "created_at": part.created_at,
                        },
                    ).scalar())
                role_ids[role] = asset_ids[key]
            tokens = tokens_from_legacy(config, role_ids)
            if tokens["font"] == "custom" and not role_ids.get("font_regular"):
                tokens["font"] = "style"
            is_default = bool(template.is_default and template.is_active) and template.tenant_id not in default_seen
            if is_default:
                default_seen.add(template.tenant_id)
            style_map[template.id] = conn.execute(
                sa.text(
                    "INSERT INTO document_style (tenant_id, name, style_key, tokens_json, is_default, version) "
                    "VALUES (:tenant_id, :name, 'modern', CAST(:tokens AS jsonb), :is_default, 1) RETURNING id"
                ),
                {"tenant_id": template.tenant_id, "name": template.name, "tokens": json.dumps(tokens), "is_default": is_default},
            ).scalar()

        # Mandanten ohne Standard: erster übernommener Stil wird Standard
        conn.execute(sa.text(
            "UPDATE document_style s SET is_default = TRUE WHERE s.id IN ("
            " SELECT MIN(id) FROM document_style GROUP BY tenant_id"
            " HAVING NOT bool_or(is_default))"
        ))

        for table in ("template", "protocol"):
            for old_id, new_id in style_map.items():
                conn.execute(sa.text(f"UPDATE {table} SET document_style_id = :new WHERE document_template_id = :old"), {"new": new_id, "old": old_id})

        if tenants_with_slots:
            names = [row.name for row in conn.execute(sa.text("SELECT name FROM tenant WHERE id = ANY(:ids) ORDER BY name"), {"ids": sorted(tenants_with_slots)})]
            logger.warning("Dokument-Engine: eigener Vorlagen-Code (TeX) entfällt für %d Mandant(en): %s", len(names), ", ".join(names))

    if _table_exists(conn, "protocol_export_cache"):
        conn.execute(sa.text(
            "INSERT INTO document_export (tenant_id, protocol_id, document_type, title, stored_file_id, created_at) "
            "SELECT p.tenant_id, c.protocol_id, 'protocol', COALESCE(p.title, p.protocol_number), c.generated_file_id, c.created_at "
            "FROM protocol_export_cache c JOIN protocol p ON p.id = c.protocol_id "
            "WHERE c.export_format = 'pdf' AND c.generated_file_id IS NOT NULL"
        ))

    # Element-Definitionen tragen in ihren Blockkonfigurationen noch den LaTeX-Teilpfad.
    for row in conn.execute(sa.text("SELECT id, configuration_json FROM element_definition WHERE configuration_json::text LIKE '%latex_template%'")).all():
        config = dict(row.configuration_json or {})
        blocks = config.get("blocks")
        if isinstance(blocks, list):
            config["blocks"] = [{k: v for k, v in block.items() if k != "latex_template"} if isinstance(block, dict) else block for block in blocks]
            conn.execute(sa.text("UPDATE element_definition SET configuration_json = CAST(:config AS jsonb) WHERE id = :id"), {"config": json.dumps(config), "id": row.id})
    # Ungenutzter Render-Typ für TeX-Fragmente (nur entfernen, wenn nichts darauf zeigt)
    conn.execute(sa.text(
        "DELETE FROM render_type WHERE code = 'raw_latex' "
        "AND NOT EXISTS (SELECT 1 FROM protocol_element_block b WHERE b.render_type_id = render_type.id) "
        "AND NOT EXISTS (SELECT 1 FROM element_definition d WHERE d.render_type_id = render_type.id)"
    ))
    # Alte SQL-Funktion aus der Baseline, die Dokumentvorlagen-Snapshots schrieb (von der App nicht genutzt)
    op.execute("DROP FUNCTION IF EXISTS public.create_protocol_from_template(bigint, bigint, text, date, bigint, text, bigint)")

    op.execute("DROP INDEX IF EXISTS idx_protocol_document_template")
    op.execute("DROP INDEX IF EXISTS idx_template_document_template")
    for table, column in (
        ("protocol", "document_template_path_snapshot"),
        ("protocol", "document_template_version"),
        ("protocol", "document_template_id"),
        ("template", "document_template_id"),
        ("stored_file", "latex_path"),
        ("protocol_element_block", "latex_template_snapshot"),
        ("template_element_block", "latex_template"),
        ("element_definition", "latex_template"),
    ):
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS {column}")
    op.execute("DROP TABLE IF EXISTS protocol_export_cache")
    op.execute("DROP TABLE IF EXISTS document_template")
    op.execute("DROP TABLE IF EXISTS document_template_part")


def downgrade() -> None:
    raise RuntimeError("0115_document_engine_migrate ist nicht umkehrbar (TeX-Vorlagen wurden entfernt).")
