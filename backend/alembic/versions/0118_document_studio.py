"""Document Studio: Brand-Profile, Vorlagen mit Revisionen, Komponenten, Zuweisungen.

Ersetzt Hausstile (document_style), Stil-Assets (document_style_asset) und Dokument-Rezepte
(document_recipe) der ersten Typst-Dokument-Engine. Ablauf:

1. document_style_asset wird zu document_asset (Dateien bleiben, wo sie sind) + Kategorie,
   Bildmasse.
2. Neue Tabellen document_brand, document_brand_revision, document_template,
   document_template_revision (unveränderlich ab Veröffentlichung, Trigger),
   document_component, document_template_assignment.
3. Datenübernahme - nichts geht stillschweigend verloren:
   - jeder Hausstil → Brand-Profil (Revision 1),
     Standard bleibt Standard (eingefrorene Übersetzung, STUDIO-017); als Logo verwendete Assets bekommen die Kategorie «logo»;
   - Hausstil einer Protokollvorlage (abweichend vom Standard) → Brand-Zuweisung für
     Protokolle dieser Vorlage; ein abweichender Hausstil eines einzelnen Protokolls lässt sich
     nicht mehr abbilden (Anzahl im Migrationsprotokoll), es gilt die Vorlage/der Standard;
   - jedes Rezept → veröffentlichte Mandantenvorlage (eingefrorene Übersetzung, siehe unten);
     Tabellen mit mehr als 12 Spalten werden auf 12 gekürzt, ungültige Ebenen auf 1 gesetzt;
     scheitert ein Rezept trotzdem, wird es mit Mandant, Name und Fehler protokolliert;
   - document_export: Rezept → Vorlage, Hausstil → Brand-Revision; Inhalts-Hashes und
     Versionen bleiben unverändert (Protokollversionierung).
4. document_registry bekommt design_hash (nullable); bestehende Einträge bleiben unberührt.
5. Alte Spalten entfallen erst nach der Übernahme; ihre Verweise sichert
   document_studio_legacy_ref. document_style und document_recipe werden nicht gelöscht, sondern
   als document_style_legacy/document_recipe_legacy archiviert (STUDIO-008). Der Downgrade
   stellt Hausstile, Rezepte und Verweise daraus wieder her; im Studio neu Angelegtes geht dabei
   verloren.

Revision ID: 0118_document_studio
Revises: 0117_document_verify_public
Create Date: 2026-10-15
"""
from __future__ import annotations

import hashlib
import json
import logging
import re

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0118_document_studio"
down_revision = "0117_document_verify_public"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.runtime.migration")

# ── Eingefrorene Übersetzung (Audit STUDIO-017) ─────────────────────────────────────────────
# Stand von app.documents.legacy (brand_tokens_from_style, content_from_recipe),
# system_templates (standard_master, cover_title_page), catalog (Blocktypen), doc_types
# (Kategorien) und hashing am 2026-10-16 - bewusst kopiert statt importiert: spätere Änderungen
# am App-Code dürfen das Ergebnis dieser Migration nicht verändern. Nicht anpassen. Gespeichert
# werden die übersetzten Daten; die App liest sie über ihre Modelle (fehlende Felder =
# Standardwerte).
_STANDARD_MASTER = json.loads('{"id": "default", "name": "", "header": {"type": "header", "id": "hdr", "children": [{"type": "row", "id": "hdr-row", "valign": "middle", "gap": 4, "children": [{"type": "image", "id": "hdr-logo", "source": {"kind": "binding", "path": "brand.logo"}, "style": {"width": "28mm", "height": "9mm"}, "visible_if": {"op": "eq", "path": "brand.header_show_logo", "value": true}}, {"type": "text", "id": "hdr-title", "role": "small", "content": {"default": [{"t": "bind", "path": "document.title"}]}, "style": {"width": "fill", "text": {"italic": true, "color": "$brand.muted"}}, "visible_if": {"op": "eq", "path": "brand.header_show_title", "value": true}}, {"type": "text", "id": "hdr-date", "role": "small", "content": {"default": [{"t": "bind", "path": "document.date"}]}, "style": {"text": {"color": "$brand.muted"}}, "visible_if": {"op": "eq", "path": "brand.header_show_date", "value": true}}]}, {"type": "divider", "id": "hdr-line", "thickness": 0.4, "color": "$brand.border", "visible_if": {"op": "eq", "path": "brand.header_line", "value": true}}]}, "footer": {"type": "footer", "id": "ftr", "children": [{"type": "divider", "id": "ftr-line", "thickness": 0.4, "color": "$brand.border", "visible_if": {"op": "eq", "path": "brand.footer_line", "value": true}}, {"type": "row", "id": "ftr-row", "gap": 4, "children": [{"type": "text", "id": "ftr-number", "role": "small", "content": {"default": [{"t": "bind", "path": "document.number"}]}, "style": {"width": "fill", "text": {"color": "$brand.muted"}}, "visible_if": {"op": "eq", "path": "brand.footer_show_number", "value": true}}, {"type": "text", "id": "ftr-text", "role": "small", "content": {"default": [{"t": "bind", "path": "brand.footer_text"}]}, "style": {"width": "fill", "text": {"align": "center", "color": "$brand.muted"}}}, {"type": "page_number", "id": "ftr-page", "style": {"text": {"size": 8, "color": "$brand.muted"}}, "visible_if": {"op": "eq", "path": "brand.footer_show_pages", "value": true}}]}]}, "background": [{"type": "watermark", "id": "bg-watermark", "when": "draft", "visible_if": {"op": "eq", "path": "brand.watermark_draft", "value": true}}]}')
_COVER_TITLE_PAGE = json.loads('{"enabled": true, "children": [{"type": "image", "id": "tp-logo", "source": {"kind": "binding", "path": "brand.logo"}, "style": {"height": "30mm", "align": "center", "margin_bottom": 10}, "visible_if": {"op": "exists", "path": "brand.logo"}}, {"type": "spacer", "id": "tp-space-1", "size": 45}, {"type": "text", "id": "tp-title", "role": "title", "content": {"default": [{"t": "bind", "path": "document.title"}]}, "style": {"text": {"align": "center"}}}, {"type": "spacer", "id": "tp-space-2", "size": 18}, {"type": "container", "id": "tp-facts", "style": {"width": "110mm", "align": "center", "padding": {"top": 5, "right": 6, "bottom": 5, "left": 6}, "border": {"width": 0.6, "color": "$brand.border", "radius": 2}}, "children": [{"type": "metadata", "id": "tp-meta", "fields": ["number", "date", "status", "version", "place"]}]}, {"type": "spacer", "id": "tp-flex", "flexible": true}, {"type": "text", "id": "tp-org", "role": "label", "content": {"default": [{"t": "bind", "path": "organization.name"}]}, "style": {"text": {"align": "center"}}}, {"type": "text", "id": "tp-address", "role": "small", "content": {"default": [{"t": "bind", "path": "organization.address"}]}, "style": {"text": {"align": "center", "color": "$brand.muted"}}}]}')
_CATALOG = frozenset(['attendance', 'attendance_matrix', 'attendance_sheet', 'chart', 'entry_exit', 'event_agenda', 'event_calendar_month', 'event_table', 'finance_balance', 'finance_transactions', 'fines', 'form', 'image', 'image_gallery', 'kpi_tiles', 'list_table', 'matrix', 'member_list', 'protocol_element', 'session_date', 'session_notes', 'signature_fields', 'stat_table', 'todo_table'])
_CATEGORIES = {'protocol': 'protocols', 'invitation': 'protocols', 'agenda': 'protocols', 'attendance': 'people', 'attendance_sheet': 'people', 'members': 'people', 'todos': 'tasks', 'events': 'events', 'calendar': 'events', 'finance': 'finance', 'transactions': 'finance', 'fines': 'finance', 'statistics': 'statistics', 'list': 'lists', 'form': 'forms', 'custom': 'general'}
_LAYOUT_SCHEMA_VERSION = 1
_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_STYLE_FONTS = {"modern": "inter", "classic": "liberation_serif", "compact": "liberation_sans"}
_LINE_HEIGHT = {"tight": 1.2, "normal": 1.35, "relaxed": 1.6}
_MARGINS = {"narrow": 15.0, "normal": 22.0, "wide": 30.0}
_BUILTIN = {"inter", "liberation_sans", "liberation_serif", "noto_sans"}
_SPACER_MM = {"s": 4.0, "m": 8.0, "l": 16.0}
# Tabellen des neuen Schemas haben höchstens 12 Spalten (STUDIO-008); weitere Zellen entfallen,
# das Original bleibt in document_recipe_legacy erhalten.
_MAX_TABLE_COLUMNS = 12


def _json_hash(payload) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _hex(value, fallback: str) -> str:
    text = str(value or "").strip()
    return text.upper() if re.fullmatch(r"#[0-9A-Fa-f]{6}", text) else fallback


def _asset_ref(value):
    return value if isinstance(value, str) and _UUID.fullmatch(value) else None


def brand_tokens_from_style(style_key, tokens) -> dict:
    tokens = tokens or {}
    key = style_key if style_key in _STYLE_FONTS else "modern"
    primary = _hex(tokens.get("primary_color"), "#174B7A")
    secondary = _hex(tokens.get("secondary_color"), "#4F6D7A")
    font_choice = str(tokens.get("font") or "style")
    custom = tokens.get("custom_fonts") or {}
    custom_ids = [custom.get(cut) for cut in ("regular", "bold", "italic", "bold_italic") if custom.get(cut)]
    # Ungültige Asset-Verweise: wie in legacy.py ohne Assets und mit Hausschrift übernehmen
    broken = any(_asset_ref(ref) is None for ref in custom_ids) or any(
        tokens.get(name) and _asset_ref(tokens.get(name)) is None for name in ("logo_asset_id", "footer_image_asset_id")
    )
    if font_choice == "custom" and custom_ids and not broken:
        font = {"builtin": None, "asset_ids": custom_ids}
    else:
        font = {"builtin": font_choice if font_choice in _BUILTIN and not broken else _STYLE_FONTS[key], "asset_ids": []}
    base_size = tokens.get("base_size") if tokens.get("base_size") in (10, 11, 12) else (10 if key == "compact" else 11)
    margin = _MARGINS.get(str(tokens.get("margins") or ("narrow" if key == "compact" else "normal")), 22.0)
    header = str(tokens.get("header") or "standard")
    footer = str(tokens.get("footer") or "standard")
    title_page = str(tokens.get("title_page") or "none")
    toc = str(tokens.get("toc") or "off")
    data = {
        "colors": {"primary": primary, "secondary": secondary, "heading": "#111827" if key == "classic" else primary},
        "typography": {
            "body": font,
            "heading": font,
            "base_size": float(base_size) - (0.5 if key != "compact" else 0),
            "line_height": _LINE_HEIGHT.get(str(tokens.get("line_spacing") or ("tight" if key == "compact" else "normal")), 1.35),
        },
        "assets": {} if broken else {"logo": tokens.get("logo_asset_id"), "footer_image": tokens.get("footer_image_asset_id")},
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
        "organization": {"address": str(tokens.get("sender") or "")[:600], "place": str(tokens.get("place") or "")[:120]},
        "verify": {
            "show_url": bool(tokens.get("verify_show_url", True)),
            "show_id": bool(tokens.get("verify_show_id", True)),
            "show_qr": bool(tokens.get("verify_show_qr", True)),
        },
    }
    if key == "compact":
        data["typography"].update({"size_h1": 14, "size_h2": 12, "size_h3": 10.5})
    return data


def _plain(value: str) -> dict:
    return {"default": [{"t": "text", "v": value}]}


def _level(value) -> int:
    try:
        return min(max(int(value or 1), 1), 6)
    except (TypeError, ValueError):
        return 1


def content_from_recipe(blocks, options=None) -> dict:
    options = options or {}
    body: list = []
    for index, spec in enumerate(blocks or []):
        if not isinstance(spec, dict):
            continue
        block_type = spec.get("type")
        params = spec.get("params") or {}
        node_id = f"r{index + 1}"
        title = str(spec.get("title") or "").strip()
        if block_type == "heading":
            body.append({"type": "text", "id": node_id, "role": "heading", "level": _level(spec.get("level")), "content": _plain(str(params.get("text") or title))})
        elif block_type in ("richtext", "static_text"):
            if title:
                body.append({"type": "text", "id": f"{node_id}-t", "role": "heading", "level": _level(spec.get("level")), "content": _plain(title)})
            body.append({"type": "rich_text", "id": node_id, "markdown": str(params.get("markdown") or "")})
        elif block_type == "page_break":
            body.append({"type": "page_break", "id": node_id})
        elif block_type == "toc":
            body.append({"type": "toc", "id": node_id, "depth": _level(params.get("depth") or 2)})
        elif block_type == "spacer":
            body.append({"type": "spacer", "id": node_id, "size": _SPACER_MM.get(str(params.get("size") or "m"), 8.0)})
        elif block_type == "divider":
            body.append({"type": "divider", "id": node_id})
        elif block_type == "bullet_list":
            body.append({"type": "list", "id": node_id, "items": [str(item) for item in params.get("items") or [] if str(item).strip()]})
        elif block_type == "qr_link":
            qr = {"type": "qr_code", "id": node_id, "target": "url" if params.get("target") == "url" else "protocol"}
            if params.get("url"):
                qr["url"] = params["url"]
            if params.get("label"):
                qr["caption"] = _plain(str(params["label"]))
            body.append(qr)
        elif block_type == "generic_table":
            headers = [str(value) for value in params.get("headers") or []][:_MAX_TABLE_COLUMNS]
            rows = [[str(cell) for cell in row][:_MAX_TABLE_COLUMNS] for row in params.get("rows") or [] if isinstance(row, list)]
            width = max([len(headers), *(len(row) for row in rows)] or [0])
            if width:
                body.append({
                    "type": "table",
                    "id": node_id,
                    "columns": [{"id": f"{node_id}-c{column}", "header": _plain(headers[column] if column < len(headers) else "")} for column in range(width)],
                    "rows": rows,
                })
        elif block_type in _CATALOG:
            node = {
                "type": "data_block",
                "id": node_id,
                "component": block_type,
                "params": params,
                "hide_if_empty": bool(spec.get("hide_if_empty", True)),
                "level": _level(spec.get("level")),
            }
            if title:
                node.update(title=_plain(title), title_mode="custom")
            body.append(node)
    if options.get("toc") not in (None, "", "off"):
        body.insert(0, {"type": "toc", "id": "r-toc", "depth": 2})
    content = {"masters": [json.loads(json.dumps(_STANDARD_MASTER))], "body": body}
    if options.get("title_page") not in (None, "", "none"):
        content["title_page"] = json.loads(json.dumps(_COVER_TITLE_PAGE))
    if options.get("orientation") == "landscape":
        content["page"] = {"orientation": "landscape"}
    if options.get("numbering") is not None:
        content["settings"] = {"heading_numbering": bool(options.get("numbering"))}
    return content


# Archiv der alten Daten (STUDIO-008): Rezepte und Hausstile werden nicht gelöscht, sondern
# umbenannt; Verweise aus gelöschten Spalten bleiben hier erhalten. Der Downgrade stellt beides
# wieder her.
LEGACY_REF_TABLE = "document_studio_legacy_ref"

NEW_TABLES = (
    "document_brand",
    "document_brand_revision",
    "document_template",
    "document_template_revision",
    "document_component",
    "document_template_assignment",
)


def _public_id() -> sa.Column:
    return sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True, server_default=sa.text("uuidv7()"))


def _ts(name: str) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()"))


def _user(name: str) -> sa.Column:
    return sa.Column(name, sa.BigInteger(), sa.ForeignKey("app_user.id", ondelete="SET NULL"))


def _create_tables() -> None:
    op.create_table(
        "document_brand",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        _public_id(),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("FALSE")),
        sa.Column("current_revision", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("lock_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        _user("created_by"),
        _user("updated_by"),
        _ts("created_at"),
        _ts("updated_at"),
        sa.CheckConstraint("current_revision >= 1", name="ck_document_brand_revision_positive"),
    )
    op.create_index("idx_document_brand_tenant", "document_brand", ["tenant_id"])
    op.create_index("uq_document_brand_default", "document_brand", ["tenant_id"], unique=True, postgresql_where=sa.text("is_default"))

    op.create_table(
        "document_brand_revision",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        _public_id(),
        sa.Column("brand_id", sa.BigInteger(), sa.ForeignKey("document_brand.id", ondelete="CASCADE"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("tokens_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("tokens_hash", sa.Text(), nullable=False),
        sa.Column("note", sa.Text()),
        _ts("created_at"),
        _user("created_by"),
        sa.UniqueConstraint("brand_id", "revision", name="uq_document_brand_revision"),
    )

    op.create_table(
        "document_template",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        _public_id(),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenant.id", ondelete="CASCADE")),
        sa.Column("system_key", sa.Text()),
        sa.Column("origin", sa.Text(), nullable=False, server_default=sa.text("'tenant'")),
        sa.Column("source_template_id", sa.BigInteger(), sa.ForeignKey("document_template.id", ondelete="SET NULL")),
        sa.Column("source_revision_id", sa.BigInteger()),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("document_type", sa.Text(), nullable=False),
        sa.Column("variant", sa.Text()),
        sa.Column("category", sa.Text(), nullable=False, server_default=sa.text("'general'")),
        sa.Column("brand_id", sa.BigInteger(), sa.ForeignKey("document_brand.id", ondelete="SET NULL")),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'active'")),
        sa.Column("published_revision_id", sa.BigInteger()),
        sa.Column("is_platform_default", sa.Boolean(), nullable=False, server_default=sa.text("FALSE")),
        sa.Column("sort_index", sa.Integer(), nullable=False, server_default=sa.text("0")),
        _user("created_by"),
        _user("updated_by"),
        _ts("created_at"),
        _ts("updated_at"),
        sa.CheckConstraint("origin IN ('system', 'tenant', 'copy')", name="ck_document_template_origin"),
        sa.CheckConstraint("status IN ('active', 'archived')", name="ck_document_template_status"),
        sa.CheckConstraint("(tenant_id IS NULL) = (origin = 'system')", name="ck_document_template_system_tenant"),
    )
    op.create_index("idx_document_template_tenant", "document_template", ["tenant_id", "document_type"])
    op.create_index("uq_document_template_system_key", "document_template", ["system_key"], unique=True, postgresql_where=sa.text("system_key IS NOT NULL"))
    # Höchstens ein Plattform-Standard je Dokumenttyp
    op.create_index(
        "uq_document_template_platform_default", "document_template", ["document_type"], unique=True, postgresql_where=sa.text("tenant_id IS NULL AND is_platform_default")
    )

    op.create_table(
        "document_template_revision",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        _public_id(),
        sa.Column("template_id", sa.BigInteger(), sa.ForeignKey("document_template.id", ondelete="CASCADE"), nullable=False),
        sa.Column("revision_no", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'draft'")),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("content_json", postgresql.JSONB(), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("brand_mode", sa.Text(), nullable=False, server_default=sa.text("'follow'")),
        sa.Column("brand_revision_id", sa.BigInteger(), sa.ForeignKey("document_brand_revision.id", ondelete="SET NULL")),
        sa.Column("lock_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("note", sa.Text()),
        _ts("created_at"),
        _ts("updated_at"),
        _user("created_by"),
        _user("updated_by"),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        _user("published_by"),
        sa.UniqueConstraint("template_id", "revision_no", name="uq_document_template_revision_no"),
        sa.CheckConstraint("status IN ('draft', 'published', 'superseded')", name="ck_document_template_revision_status"),
        sa.CheckConstraint("brand_mode IN ('follow', 'pinned')", name="ck_document_template_revision_brand_mode"),
    )
    op.create_index("uq_document_template_revision_draft", "document_template_revision", ["template_id"], unique=True, postgresql_where=sa.text("status = 'draft'"))
    op.create_foreign_key("fk_document_template_published_revision", "document_template", "document_template_revision", ["published_revision_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_document_template_source_revision", "document_template", "document_template_revision", ["source_revision_id"], ["id"], ondelete="SET NULL")

    op.create_table(
        "document_component",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        _public_id(),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("category", sa.Text(), nullable=False, server_default=sa.text("'general'")),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("node_json", postgresql.JSONB(), nullable=False),
        sa.Column("lock_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        _user("created_by"),
        _user("updated_by"),
        _ts("created_at"),
        _ts("updated_at"),
    )
    op.create_index("idx_document_component_tenant", "document_component", ["tenant_id"])

    op.create_table(
        "document_template_assignment",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_type", sa.Text(), nullable=False),
        sa.Column("protocol_template_id", sa.BigInteger(), sa.ForeignKey("template.id", ondelete="CASCADE")),
        sa.Column("document_template_id", sa.BigInteger(), sa.ForeignKey("document_template.id", ondelete="CASCADE")),
        sa.Column("brand_id", sa.BigInteger(), sa.ForeignKey("document_brand.id", ondelete="CASCADE")),
        _ts("created_at"),
        _user("created_by"),
        sa.CheckConstraint("document_template_id IS NOT NULL OR brand_id IS NOT NULL", name="ck_document_template_assignment_target"),
    )
    op.create_index("uq_document_template_assignment_tenant", "document_template_assignment", ["tenant_id", "document_type"], unique=True, postgresql_where=sa.text("protocol_template_id IS NULL"))
    op.create_index(
        "uq_document_template_assignment_protocol_template",
        "document_template_assignment",
        ["tenant_id", "document_type", "protocol_template_id"],
        unique=True,
        postgresql_where=sa.text("protocol_template_id IS NOT NULL"),
    )

    for table in ("document_brand", "document_template", "document_component"):
        op.execute(f"CREATE TRIGGER trg_{table}_updated_at BEFORE UPDATE ON {table} FOR EACH ROW EXECUTE FUNCTION public.set_updated_at()")

    # Veröffentlichte und abgelöste Revisionen sind unveränderlich: nur der Übergang
    # published → superseded ist erlaubt, Inhalt und Brand-Bezug nie.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.document_template_revision_immutable() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF OLD.status IN ('published', 'superseded') THEN
                IF NEW.content_json IS DISTINCT FROM OLD.content_json
                   OR NEW.content_hash IS DISTINCT FROM OLD.content_hash
                   OR NEW.schema_version IS DISTINCT FROM OLD.schema_version
                   OR NEW.brand_mode IS DISTINCT FROM OLD.brand_mode
                   OR NEW.template_id IS DISTINCT FROM OLD.template_id
                   OR NEW.revision_no IS DISTINCT FROM OLD.revision_no
                   OR (NEW.brand_revision_id IS DISTINCT FROM OLD.brand_revision_id AND NEW.brand_revision_id IS NOT NULL)
                   OR NOT (NEW.status = OLD.status OR (OLD.status = 'published' AND NEW.status = 'superseded')) THEN
                    RAISE EXCEPTION 'document_template_revision % ist veröffentlicht und unveränderlich', OLD.id
                        USING ERRCODE = 'check_violation';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_document_template_revision_immutable BEFORE UPDATE ON document_template_revision "
        "FOR EACH ROW EXECUTE FUNCTION public.document_template_revision_immutable()"
    )


def _rename_assets() -> None:
    op.execute("ALTER TABLE document_style_asset RENAME TO document_asset")
    op.execute("ALTER SEQUENCE document_style_asset_id_seq RENAME TO document_asset_id_seq")
    op.execute("ALTER INDEX idx_document_style_asset_tenant RENAME TO idx_document_asset_tenant")
    op.execute("ALTER TABLE document_asset RENAME CONSTRAINT ck_document_style_asset_kind TO ck_document_asset_kind")
    conn = op.get_bind()
    for old, new in (("document_style_asset_pkey", "document_asset_pkey"), ("document_style_asset_public_id_key", "document_asset_public_id_key")):
        exists = conn.execute(sa.text("SELECT 1 FROM pg_constraint WHERE conname = :name"), {"name": old}).scalar()
        if exists:
            op.execute(f"ALTER TABLE document_asset RENAME CONSTRAINT {old} TO {new}")
    op.add_column("document_asset", sa.Column("category", sa.Text(), nullable=False, server_default=sa.text("'image'")))
    op.add_column("document_asset", sa.Column("width_px", sa.Integer()))
    op.add_column("document_asset", sa.Column("height_px", sa.Integer()))
    op.execute("UPDATE document_asset SET category = 'font' WHERE kind = 'font'")
    op.create_check_constraint(
        "ck_document_asset_category", "document_asset", "category IN ('logo', 'letterhead', 'background', 'watermark', 'graphic', 'image', 'font')"
    )


def _migrate_data() -> None:
    conn = op.get_bind()

    # 1. Hausstile → Brand-Profile
    style_map: dict[int, tuple[int, int]] = {}
    logos: set[str] = set()
    styles = conn.execute(sa.text("SELECT id, tenant_id, name, style_key, tokens_json, is_default, created_at FROM document_style ORDER BY tenant_id, is_default DESC, id")).all()
    for style in styles:
        data = brand_tokens_from_style(style.style_key, style.tokens_json or {})
        if data["assets"].get("logo"):
            logos.add(data["assets"]["logo"])
        brand_id = conn.execute(
            sa.text(
                "INSERT INTO document_brand (tenant_id, name, is_default, current_revision, created_at, updated_at) "
                "VALUES (:tenant_id, :name, :is_default, 1, :created_at, now()) RETURNING id"
            ),
            {"tenant_id": style.tenant_id, "name": style.name or "Brand", "is_default": bool(style.is_default), "created_at": style.created_at},
        ).scalar_one()
        revision_id = conn.execute(
            sa.text(
                "INSERT INTO document_brand_revision (brand_id, revision, tokens_json, tokens_hash, note, created_at) "
                "VALUES (:brand_id, 1, CAST(:tokens AS jsonb), :hash, 'migration:document_style', now()) RETURNING id"
            ),
            {"brand_id": brand_id, "tokens": json.dumps(data), "hash": _json_hash(data)},
        ).scalar_one()
        style_map[style.id] = (brand_id, revision_id)
    for public_id in logos:
        conn.execute(sa.text("UPDATE document_asset SET category = 'logo' WHERE public_id = CAST(:id AS uuid) AND kind = 'image'"), {"id": public_id})
    default_style = {row.tenant_id: row.id for row in styles if row.is_default}

    # 2. Hausstil der Protokollvorlagen → Brand-Zuweisung (nur wenn abweichend vom Standard)
    assignments = 0
    for row in conn.execute(sa.text("SELECT id, tenant_id, document_style_id FROM template WHERE document_style_id IS NOT NULL")).all():
        mapped = style_map.get(row.document_style_id)
        if mapped is None or default_style.get(row.tenant_id) == row.document_style_id:
            continue
        conn.execute(
            sa.text("INSERT INTO document_template_assignment (tenant_id, document_type, protocol_template_id, brand_id) VALUES (:tenant_id, 'protocol', :template_id, :brand_id)"),
            {"tenant_id": row.tenant_id, "template_id": row.id, "brand_id": mapped[0]},
        )
        assignments += 1
    divergent = conn.execute(
        sa.text(
            "SELECT count(*) FROM protocol p JOIN template t ON t.id = p.template_id "
            "WHERE p.document_style_id IS NOT NULL AND p.document_style_id IS DISTINCT FROM t.document_style_id"
        )
    ).scalar() or 0

    # 3. Rezepte → veröffentlichte Mandantenvorlagen
    recipe_map: dict[int, tuple[int, int]] = {}
    skipped_recipes = 0
    for recipe in conn.execute(sa.text("SELECT id, tenant_id, name, document_type, blocks_json, options_json, style_id, created_at FROM document_recipe ORDER BY id")).all():
        try:
            data = content_from_recipe(recipe.blocks_json or [], recipe.options_json or {})
        except Exception as exc:  # noqa: BLE001 - jedes Rezept einzeln; das Original bleibt im Archiv
            # Nur protokolliert, Ergebnis der Migration unverändert (STUDIO-008)
            skipped_recipes += 1
            logger.warning("Rezept %s (Mandant %s, «%s») nicht übernommen (ungültige Blöcke): %s", recipe.id, recipe.tenant_id, recipe.name, exc)
            continue
        document_type = recipe.document_type if recipe.document_type in _CATEGORIES else "custom"
        template_id = conn.execute(
            sa.text(
                "INSERT INTO document_template (tenant_id, origin, name, document_type, category, brand_id, status, created_at, updated_at) "
                "VALUES (:tenant_id, 'tenant', :name, :document_type, :category, :brand_id, 'active', :created_at, now()) RETURNING id"
            ),
            {
                "tenant_id": recipe.tenant_id,
                "name": recipe.name or document_type,
                "document_type": document_type,
                "category": _CATEGORIES[document_type],
                "brand_id": style_map[recipe.style_id][0] if recipe.style_id in style_map else None,
                "created_at": recipe.created_at,
            },
        ).scalar_one()
        revision_id = conn.execute(
            sa.text(
                "INSERT INTO document_template_revision (template_id, revision_no, status, schema_version, content_json, content_hash, note, published_at) "
                "VALUES (:template_id, 1, 'published', :schema_version, CAST(:content AS jsonb), :hash, 'migration:document_recipe', now()) RETURNING id"
            ),
            {"template_id": template_id, "schema_version": _LAYOUT_SCHEMA_VERSION, "content": json.dumps(data), "hash": _json_hash(data)},
        ).scalar_one()
        conn.execute(sa.text("UPDATE document_template SET published_revision_id = :revision WHERE id = :id"), {"revision": revision_id, "id": template_id})
        recipe_map[recipe.id] = (template_id, revision_id)

    # 4. Export-Datensätze: Herkunft übernehmen (Hashes und Versionen bleiben unverändert)
    op.add_column("document_export", sa.Column("design_hash", sa.Text()))
    op.add_column("document_export", sa.Column("template_id", sa.BigInteger(), sa.ForeignKey("document_template.id", ondelete="SET NULL")))
    op.add_column("document_export", sa.Column("template_revision_id", sa.BigInteger(), sa.ForeignKey("document_template_revision.id", ondelete="SET NULL")))
    op.add_column("document_export", sa.Column("brand_revision_id", sa.BigInteger(), sa.ForeignKey("document_brand_revision.id", ondelete="SET NULL")))
    op.add_column("document_export", sa.Column("options_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")))
    for export in conn.execute(sa.text("SELECT id, recipe_id, style_id, style_key, style_version FROM document_export WHERE recipe_id IS NOT NULL OR style_id IS NOT NULL OR style_key IS NOT NULL")).all():
        template = recipe_map.get(export.recipe_id) if export.recipe_id else None
        brand = style_map.get(export.style_id) if export.style_id else None
        conn.execute(
            sa.text(
                "UPDATE document_export SET template_id = :template_id, template_revision_id = :revision_id, brand_revision_id = :brand_revision_id, "
                "options_json = CAST(:options AS jsonb) WHERE id = :id"
            ),
            {
                "id": export.id,
                "template_id": template[0] if template else None,
                "revision_id": template[1] if template else None,
                "brand_revision_id": brand[1] if brand else None,
                # Herkunft vor dem Document Studio bleibt nachvollziehbar
                "options": json.dumps({"legacy": {"style_key": export.style_key, "style_version": export.style_version}}),
            },
        )
    logger.info(
        "Document Studio: %s Hausstile → Brand-Profile, %s Rezepte → Vorlagen (%s übersprungen, siehe Warnungen), %s Brand-Zuweisungen; %s Protokolle mit eigenem Hausstil folgen nun ihrer Vorlage",
        len(style_map),
        len(recipe_map),
        skipped_recipes,
        assignments,
        divergent,
    )


def _archive_references() -> None:
    """Verweise aus Spalten sichern, die gleich entfallen (für den Downgrade, STUDIO-008)."""
    op.execute(f"CREATE TABLE {LEGACY_REF_TABLE} (table_name text NOT NULL, row_id bigint NOT NULL, column_name text NOT NULL, value_text text)")
    for table, columns in (("template", ("document_style_id",)), ("protocol", ("document_style_id",)), ("document_export", ("recipe_id", "style_id", "style_key", "style_version"))):
        for column in columns:
            op.execute(
                f"INSERT INTO {LEGACY_REF_TABLE} (table_name, row_id, column_name, value_text) "
                f"SELECT '{table}', id, '{column}', {column}::text FROM {table} WHERE {column} IS NOT NULL"
            )


def _restore_references() -> None:
    conn = op.get_bind()
    if not conn.execute(sa.text("SELECT to_regclass(:name)"), {"name": LEGACY_REF_TABLE}).scalar():
        return
    casts = {"document_style_id": "bigint", "recipe_id": "bigint", "style_id": "bigint", "style_key": "text", "style_version": "integer"}
    for table, column in conn.execute(sa.text(f"SELECT DISTINCT table_name, column_name FROM {LEGACY_REF_TABLE}")).all():
        op.execute(
            f"UPDATE {table} t SET {column} = r.value_text::{casts[column]} FROM {LEGACY_REF_TABLE} r "
            f"WHERE r.table_name = '{table}' AND r.column_name = '{column}' AND r.row_id = t.id"
        )
    op.execute(f"DROP TABLE {LEGACY_REF_TABLE}")


def upgrade() -> None:
    _rename_assets()
    _create_tables()
    _migrate_data()

    op.add_column("document_registry", sa.Column("design_hash", sa.Text()))

    _archive_references()
    op.drop_column("document_export", "recipe_id")
    op.drop_column("document_export", "style_id")
    op.drop_column("document_export", "style_key")
    op.drop_column("document_export", "style_version")
    op.drop_index("idx_protocol_document_style", table_name="protocol")
    op.drop_index("idx_template_document_style", table_name="template")
    op.drop_column("protocol", "document_style_id")
    op.drop_column("template", "document_style_id")
    op.execute("ALTER TABLE document_recipe RENAME TO document_recipe_legacy")
    op.execute("ALTER TABLE document_style RENAME TO document_style_legacy")

    for table in NEW_TABLES:
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO hocx_app")
        op.execute(f"GRANT USAGE, SELECT ON SEQUENCE {table}_id_seq TO hocx_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON document_asset TO hocx_app")
    op.execute("GRANT USAGE, SELECT ON SEQUENCE document_asset_id_seq TO hocx_app")


def downgrade() -> None:
    """Rückkehr zu 0117 (STUDIO-008): Hausstile, Rezepte und die Verweise darauf kommen aus dem
    Archiv unverändert zurück. Was erst im Document Studio entstanden ist (Brand-Profile,
    Vorlagen, Komponenten), wird nicht zurückübersetzt und geht verloren - vorher Backup ziehen."""
    op.drop_column("document_registry", "design_hash")
    conn = op.get_bind()
    if conn.execute(sa.text("SELECT to_regclass('document_style_legacy')")).scalar():
        op.execute("ALTER TABLE document_style_legacy RENAME TO document_style")
        op.execute("ALTER TABLE document_recipe_legacy RENAME TO document_recipe")
    else:
        _create_legacy_tables()
    _downgrade_columns()


def _create_legacy_tables() -> None:
    op.create_table(
        "document_style",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        _public_id(),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("style_key", sa.Text(), nullable=False, server_default=sa.text("'modern'")),
        sa.Column("tokens_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("FALSE")),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        _ts("created_at"),
        _ts("updated_at"),
        sa.CheckConstraint("style_key IN ('modern', 'classic', 'compact')", name="ck_document_style_key"),
        sa.CheckConstraint("version >= 1", name="ck_document_style_version_positive"),
    )
    op.create_index("idx_document_style_tenant", "document_style", ["tenant_id"])
    op.create_index("uq_document_style_default", "document_style", ["tenant_id"], unique=True, postgresql_where=sa.text("is_default"))
    op.create_table(
        "document_recipe",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        _public_id(),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("document_type", sa.Text(), nullable=False, server_default=sa.text("'custom'")),
        sa.Column("blocks_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("options_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("style_id", sa.BigInteger(), sa.ForeignKey("document_style.id", ondelete="SET NULL")),
        sa.Column("language", sa.Text()),
        _user("created_by"),
        _ts("created_at"),
        _ts("updated_at"),
    )
    op.create_index("idx_document_recipe_tenant", "document_recipe", ["tenant_id"])
    for table in ("document_style", "document_recipe"):
        op.execute(f"CREATE TRIGGER trg_{table}_updated_at BEFORE UPDATE ON {table} FOR EACH ROW EXECUTE FUNCTION public.set_updated_at()")
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO hocx_app")
        op.execute(f"GRANT USAGE, SELECT ON SEQUENCE {table}_id_seq TO hocx_app")


def _downgrade_columns() -> None:
    op.add_column("template", sa.Column("document_style_id", sa.BigInteger(), sa.ForeignKey("document_style.id", ondelete="SET NULL")))
    op.add_column("protocol", sa.Column("document_style_id", sa.BigInteger(), sa.ForeignKey("document_style.id", ondelete="SET NULL")))
    op.create_index("idx_template_document_style", "template", ["document_style_id"])
    op.create_index("idx_protocol_document_style", "protocol", ["document_style_id"])
    op.add_column("document_export", sa.Column("recipe_id", sa.BigInteger(), sa.ForeignKey("document_recipe.id", ondelete="SET NULL")))
    op.add_column("document_export", sa.Column("style_id", sa.BigInteger(), sa.ForeignKey("document_style.id", ondelete="SET NULL")))
    op.add_column("document_export", sa.Column("style_key", sa.Text()))
    op.add_column("document_export", sa.Column("style_version", sa.Integer()))
    for column in ("options_json", "brand_revision_id", "template_revision_id", "template_id", "design_hash"):
        op.drop_column("document_export", column)
    _restore_references()

    op.execute("DROP TRIGGER IF EXISTS trg_document_template_revision_immutable ON document_template_revision")
    # Funktion nur entfernen, wenn kein anderer Trigger sie noch verwendet
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_trigger t JOIN pg_proc p ON p.oid = t.tgfoid WHERE p.proname = 'document_template_revision_immutable'
            ) THEN
                DROP FUNCTION IF EXISTS public.document_template_revision_immutable();
            END IF;
        END
        $$
        """
    )
    op.drop_table("document_template_assignment")
    op.drop_table("document_component")
    op.drop_constraint("fk_document_template_published_revision", "document_template", type_="foreignkey")
    op.drop_constraint("fk_document_template_source_revision", "document_template", type_="foreignkey")
    op.drop_table("document_template_revision")
    op.drop_table("document_template")
    op.drop_table("document_brand_revision")
    op.drop_table("document_brand")

    op.drop_constraint("ck_document_asset_category", "document_asset", type_="check")
    op.drop_column("document_asset", "height_px")
    op.drop_column("document_asset", "width_px")
    op.drop_column("document_asset", "category")
    conn = op.get_bind()
    for old, new in (("document_asset_pkey", "document_style_asset_pkey"), ("document_asset_public_id_key", "document_style_asset_public_id_key")):
        if conn.execute(sa.text("SELECT 1 FROM pg_constraint WHERE conname = :name"), {"name": old}).scalar():
            op.execute(f"ALTER TABLE document_asset RENAME CONSTRAINT {old} TO {new}")
    op.execute("ALTER TABLE document_asset RENAME CONSTRAINT ck_document_asset_kind TO ck_document_style_asset_kind")
    op.execute("ALTER INDEX idx_document_asset_tenant RENAME TO idx_document_style_asset_tenant")
    op.execute("ALTER SEQUENCE document_asset_id_seq RENAME TO document_style_asset_id_seq")
    op.execute("ALTER TABLE document_asset RENAME TO document_style_asset")
