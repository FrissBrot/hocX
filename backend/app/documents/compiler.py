"""Layout-Compiler: Vorlage + Brand + Datenkontext → validierte Layoutrepräsentation für Typst.

Ablauf (``LayoutCompiler.compile``):

1. Vorlage (``TemplateContent``, bereits schemavalidiert) und aufgelöstes Brand-Profil
2. Wiederverwendbare Komponenten (``component_ref``) mandantengebunden einsetzen
3. Bedingungen (``visible_if``, conditions.py) und Wiederholungen (``repeat``) auswerten
4. Datenbindungen auflösen (bindings.py, Rechte des Exportierenden) und formatieren
5. Fachkomponenten (``data_block``) über den Katalog prüfen und von den Providern füllen
6. Farben/Schriften/Längen in feste Werte übersetzen
7. JSON für ``typst/main.typ`` erzeugen: nur Daten, nie Code - Typst setzt jeden Text als Inhalt

Modi: ``strict`` (Export) bricht bei Fehlern mit kuratierten Ausnahmen ab; sonst (Vorschau)
werden Fehler als ``Diagnostic`` mit Knoten-ID gesammelt und als Hinweis am Element gezeigt.
``mode="sample"`` füllt Bindungen und Fachkomponenten mit Beispielinhalten (samples.py) und
ist nur in der Vorschau erlaubt. ``validate_template`` prüft eine Vorlage ohne Daten (beim
Speichern und Veröffentlichen).
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import TypeAdapter, ValidationError
from sqlalchemy.orm import Session

from app.documents import assets as asset_service
from app.documents import bindings as binding_registry
from app.documents.bindings import BindingDef, BindingEnvironment, BindingResolver, UnknownBindingError, format_value
from app.documents.brand import BrandTokens, resolve_appearance, resolve_color
from app.documents.brand_service import ResolvedBrand
from app.documents.catalog import CATALOG, NEEDS_PROTOCOL, BlockSpec, validate_spec
from app.documents.conditions import ConditionError, condition_paths, evaluate
from app.documents.context import AssetCollector, BuildContext, DocumentNotFoundError, DocumentPermissionError
from app.documents.layout import (
    LENGTH_PATTERN,
    MASTER_ONLY_TYPES,
    BoxStyle,
    FormatSpec,
    Node,
    NodeBase,
    PageMaster,
    Spacing,
    TemplateContent,
    TextContent,
    TextStyle,
    all_node_lists,
    iter_nodes,
    WatermarkNode,
)
from app.documents.model import DocumentMeta, ProtocolElementBlock, RenderInfo, rich_is_empty
from app.documents.providers import PROVIDERS
from app.documents.richtext import markdown_to_rich

_NODE_ADAPTER = TypeAdapter(Node)
MAX_COMPONENT_DEPTH = 4
MAX_REPEAT_TOTAL = 5000

Severity = Literal["error", "warning"]


@dataclass
class Diagnostic:
    node_id: str | None
    severity: Severity
    code: str
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"node_id": self.node_id, "severity": self.severity, "code": self.code, "detail": self.detail}


class CompileError(ValueError):
    """Kuratierter Fehler im strikten Modus (Export). ``code`` ist ein documentPdf-Schlüssel."""

    def __init__(self, code: str, node_id: str | None = None, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.node_id = node_id
        self.detail = detail


@dataclass
class CompileInput:
    content: TemplateContent
    brand: ResolvedBrand
    ctx: BuildContext
    meta: DocumentMeta
    strings: dict[str, str]
    render: RenderInfo = field(default_factory=RenderInfo)
    mode: Literal["data", "sample"] = "data"
    strict: bool = True
    # Seitenkontext (z. B. aktive Filter der Todo-Seite) für passende Komponentenparameter
    params: dict[str, Any] = field(default_factory=dict)
    is_draft: bool = False
    document_env: dict[str, Any] = field(default_factory=dict)


@dataclass
class CompiledDocument:
    data: dict[str, Any]
    files: dict[str, bytes]
    fonts: dict[str, bytes]
    blocks: list[Any]
    diagnostics: list[Diagnostic]
    template_asset_checksums: dict[str, str]
    used_bindings: set[str]


# ── Hilfen ───────────────────────────────────────────────────────────────────

_LENGTH_RE = re.compile(LENGTH_PATTERN)


def compile_length(value: str | None) -> dict[str, Any] | None:
    if value is None:
        return None
    if value in ("auto", "fill"):
        return {"k": value}
    match = re.fullmatch(r"(\d{1,4}(?:\.\d{1,2})?)(mm|%|fr)", value)
    if not match:
        return {"k": "auto"}
    number, unit = float(match.group(1)), match.group(2)
    return {"k": {"mm": "mm", "%": "pct", "fr": "fr"}[unit], "v": number}


def _spacing(value: Spacing | None) -> list[float] | None:
    if value is None:
        return None
    return [value.top, value.right, value.bottom, value.left]


_WEIGHTS = {"regular": 400, "medium": 500, "bold": 700}


class LayoutCompiler:
    def __init__(self, data: CompileInput, db: Session) -> None:
        self.input = data
        self.db = db
        self.ctx = data.ctx
        self.strings = data.strings
        self.tokens: BrandTokens = data.brand.tokens
        self.diagnostics: list[Diagnostic] = []
        self.blocks: list[Any] = []
        self.template_assets = AssetCollector(prefix="tpl")
        self.template_asset_checksums: dict[str, str] = {}
        self._component_stack: list[str] = []
        self._repeat_total = 0
        self._has_verify_note = False
        env = BindingEnvironment(document=data.document_env, brand=data.brand.env, organization=data.brand.organization)
        self.resolver = BindingResolver(self.ctx, env, strings=data.strings, mode=data.mode)

    # Fehler -------------------------------------------------------------

    def _problem(self, node_id: str | None, code: str, detail: str = "", *, severity: Severity = "error", exc: Exception | None = None) -> None:
        if self.input.strict and severity == "error":
            if isinstance(exc, (DocumentPermissionError, DocumentNotFoundError)):
                raise exc
            raise CompileError(code, node_id, detail) from exc
        self.diagnostics.append(Diagnostic(node_id, severity, code, detail))

    # Werte --------------------------------------------------------------

    def color(self, reference: str | None, node_id: str | None = None, *, default: str | None = None) -> str | None:
        if reference is None:
            return default
        value = resolve_color(reference, self.tokens)
        if value is None:
            self._problem(node_id, "unknownColor", reference, severity="warning")
            return default
        return value

    def fonts(self, reference: str | None, node_id: str | None = None) -> list[str] | None:
        if reference is None:
            return None
        families = self.input.brand.typst["fonts"]
        if reference == "$brand.font.heading":
            return families["heading"]
        if reference in ("$brand.font.body", "$brand.font.mono"):
            return families["body"]
        if reference in self.input.brand.families:
            return [reference] + [name for name in families["body"] if name != reference]
        self._problem(node_id, "unknownFont", reference, severity="warning")
        return families["body"]

    def value(self, path: str, scope: dict[str, Any] | None, node_id: str | None) -> Any:
        try:
            return self.resolver.resolve(path, scope)
        except UnknownBindingError as exc:
            self._problem(node_id, "unknownBinding", path, exc=exc)
        except DocumentPermissionError as exc:
            self._problem(node_id, "bindingPermission", path, exc=exc)
        return None

    def binding_type(self, path: str) -> str | None:
        try:
            return binding_registry.lookup(path).type
        except UnknownBindingError:
            return None

    def spans(self, content: TextContent | None, scope: dict[str, Any] | None, node_id: str | None, scope_def: BindingDef | None = None) -> list[dict[str, Any]]:
        if content is None:
            return []
        inlines = content.translations.get(self.input.meta.language) or content.default
        result: list[dict[str, Any]] = []
        for inline in inlines:
            if inline.t == "br":
                result.append({"br": True})
                continue
            if inline.t == "text":
                text = inline.v
            elif inline.t == "key":
                text = self.strings.get(inline.key)
                if text is None:
                    self._problem(node_id, "unknownTextKey", inline.key, severity="warning")
                    text = ""
            else:
                value_type = self._inline_type(inline.path, scope_def)
                raw = self.value(inline.path, scope, node_id)
                if value_type == "image":
                    self._problem(node_id, "bindingTypeMismatch", inline.path, severity="warning")
                    raw = None
                text = format_value(raw, value_type or "text", inline.format, self.strings) or inline.fallback
            if text:
                result.append({"v": text, "b": inline.b, "i": inline.i} if (inline.b or inline.i) else {"v": text})
        return result

    def _inline_type(self, path: str, scope_def: BindingDef | None) -> str | None:
        if path.startswith("item."):
            if scope_def is None:
                return "text"
            item = scope_def.item_field(path.split(".", 1)[1])
            return item.type if item is not None else "text"
        return self.binding_type(path)

    def text(self, content: TextContent | None, scope: dict[str, Any] | None, node_id: str | None) -> str:
        return "".join(span.get("v", "\n") for span in self.spans(content, scope, node_id))

    # Stil ---------------------------------------------------------------

    def text_style(self, style: TextStyle, node_id: str) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if style.font is not None:
            out["font"] = self.fonts(style.font, node_id)
        if style.size is not None:
            out["size"] = style.size
        if style.weight is not None:
            out["weight"] = _WEIGHTS[style.weight]
        if style.italic is not None:
            out["italic"] = style.italic
        if style.color is not None:
            out["color"] = self.color(style.color, node_id)
        if style.align is not None:
            out["align"] = style.align
        if style.line_height is not None:
            out["leading"] = round(max(style.line_height - 0.7, 0.1), 3)
        if style.letter_spacing is not None:
            out["tracking"] = style.letter_spacing
        if style.transform is not None and style.transform != "none":
            out["transform"] = style.transform
        return out

    def box_style(self, style: BoxStyle, node_id: str) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if style.width != "auto":
            out["w"] = compile_length(style.width)
        if style.height is not None:
            out["h"] = compile_length(style.height)
        padding = _spacing(style.padding)
        if padding and any(padding):
            out["pad"] = padding
        if style.margin_top:
            out["mt"] = style.margin_top
        if style.margin_bottom:
            out["mb"] = style.margin_bottom
        if style.background is not None:
            out["bg"] = self.color(style.background, node_id)
        if style.border is not None and style.border.width > 0:
            out["border"] = {
                "w": style.border.width,
                "c": self.color(style.border.color, node_id, default=self.tokens.colors.border.upper()),
                "style": style.border.style,
                "sides": list(style.border.sides),
                "r": style.border.radius,
            }
        if style.align != "left":
            out["align"] = style.align
        text = self.text_style(style.text, node_id)
        if text:
            out["text"] = text
        return out

    # Knoten -------------------------------------------------------------

    def nodes(self, nodes: list[Any], scope: dict[str, Any] | None, area: str, scope_def: BindingDef | None = None) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for node in nodes:
            result.extend(self.node(node, scope, area, scope_def))
        return result

    def node(self, node: NodeBase, scope: dict[str, Any] | None, area: str, scope_def: BindingDef | None = None) -> list[dict[str, Any]]:
        if not node.enabled:
            return []
        if area in ("body", "title_page") and node.type in MASTER_ONLY_TYPES:
            self._problem(node.id, "masterOnly", node.type)
            return []
        if node.repeat is not None:
            definition = self._list_def(node.repeat.source, node.id)
            items = self.value(node.repeat.source, scope, node.id) if definition is not None else None
            items = items if isinstance(items, list) else []
            if not items:
                if node.repeat.empty_text:
                    return [{"t": "text", "id": node.id, "role": "paragraph", "spans": [{"v": node.repeat.empty_text, "i": True}], "s": {}}]
                return []
            result = []
            for item in items[: node.repeat.limit]:
                self._repeat_total += 1
                if self._repeat_total > MAX_REPEAT_TOTAL:
                    self._problem(node.id, "repeatLimit", str(MAX_REPEAT_TOTAL))
                    break
                result.extend(self._single(node, item if isinstance(item, dict) else {"value": item}, area, definition))
            return result
        return self._single(node, scope, area, scope_def)

    def _list_def(self, path: str, node_id: str) -> BindingDef | None:
        try:
            definition = binding_registry.lookup(path)
        except UnknownBindingError as exc:
            self._problem(node_id, "unknownBinding", path, exc=exc)
            return None
        if definition.type != "list":
            self._problem(node_id, "bindingTypeMismatch", path)
            return None
        return definition

    def _visible(self, node: NodeBase, scope: dict[str, Any] | None) -> bool:
        if node.visible_if is None:
            return True
        try:
            return evaluate(node.visible_if, lambda path: self.value(path, scope, node.id))
        except ConditionError as exc:
            self._problem(node.id, "invalidCondition", str(exc), exc=exc)
            return False

    def _base(self, node: NodeBase, kind: str) -> dict[str, Any]:
        out: dict[str, Any] = {"t": kind, "id": node.id, "s": self.box_style(node.style, node.id)}
        if node.keep_together:
            out["keep"] = True
        if node.break_before:
            out["break"] = True
        if node.frame is not None:
            frame = node.frame
            out["frame"] = {"x": frame.x, "y": frame.y, "w": frame.width, "h": frame.height, "rotate": frame.rotate, "opacity": frame.opacity, "valign": frame.valign}
        return out

    def _single(self, node: NodeBase, scope: dict[str, Any] | None, area: str, scope_def: BindingDef | None) -> list[dict[str, Any]]:
        if not self._visible(node, scope):
            return []
        handler = getattr(self, f"_node_{node.type}", None)
        if handler is None:  # pragma: no cover - jeder Knotentyp hat einen Handler (Test)
            self._problem(node.id, "unknownNodeType", node.type)
            return []
        try:
            compiled = handler(node, scope, area, scope_def)
        except (CompileError, DocumentPermissionError, DocumentNotFoundError):
            raise
        except ValueError as exc:
            self._problem(node.id, "invalidNode", str(exc), exc=exc)
            return [self._error_node(node, "invalidNode")]
        if compiled is None:
            return []
        return compiled if isinstance(compiled, list) else [compiled]

    def _error_node(self, node: NodeBase, code: str) -> dict[str, Any]:
        return {"t": "error", "id": node.id, "code": code, "label": node.name or node.type, "s": {}}

    def _children(self, node: Any, kind: str, scope, area, scope_def, **extra: Any) -> dict[str, Any]:
        out = self._base(node, kind)
        out["children"] = self.nodes(node.children, scope, area, scope_def)
        out.update(extra)
        return out

    def _node_stack(self, node, scope, area, scope_def):
        return self._children(node, "stack", scope, area, scope_def, gap=node.gap)

    def _node_column(self, node, scope, area, scope_def):
        return self._children(node, "stack", scope, area, scope_def, gap=node.gap)

    def _node_container(self, node, scope, area, scope_def):
        return self._children(node, "container", scope, area, scope_def, gap=node.gap, breakable=node.breakable)

    def _node_header(self, node, scope, area, scope_def):
        return self._children(node, "stack", scope, area, scope_def, gap=node.gap)

    def _node_footer(self, node, scope, area, scope_def):
        return self._children(node, "stack", scope, area, scope_def, gap=node.gap)

    def _node_row(self, node, scope, area, scope_def):
        out = self._base(node, "row")
        children = []
        for child in node.children:
            for compiled in self.node(child, scope, area, scope_def):
                children.append(compiled)
        out.update(children=children, gap=node.gap, valign=node.valign)
        return out

    def _node_grid(self, node, scope, area, scope_def):
        widths = [compile_length(width) for width in node.column_widths][: node.columns]
        return self._children(node, "grid", scope, area, scope_def, columns=node.columns, widths=widths, gap_x=node.gap_x, gap_y=node.gap_y)

    def _node_section(self, node, scope, area, scope_def):
        out = self._children(node, "section", scope, area, scope_def, gap=node.gap, level=node.level, outlined=node.outlined)
        out["title"] = self.spans(node.title, scope, node.id, scope_def)
        if not out["children"] and not out["title"]:
            return None
        return out

    def _node_text(self, node, scope, area, scope_def):
        spans = self.spans(node.content, scope, node.id, scope_def)
        if not spans:
            return None
        out = self._base(node, "text")
        out.update(role=node.role, level=node.level, spans=spans)
        return out

    def _node_rich_text(self, node, scope, area, scope_def):
        markdown = node.translations.get(self.input.meta.language) or node.markdown
        content = markdown_to_rich(markdown)
        if rich_is_empty(content):
            return None
        out = self._base(node, "rich")
        out["content"] = [item.model_dump(mode="json") for item in content]
        return out

    def _image_path(self, node: Any, scope) -> str | None:
        source = node.source
        if source.kind == "binding":
            definition_type = self.binding_type(source.path) if not source.path.startswith("item.") else "image"
            if definition_type != "image":
                self._problem(node.id, "bindingTypeMismatch", source.path)
                return None
            value = self.value(source.path, scope, node.id)
            if isinstance(value, dict):
                return None
            return value if isinstance(value, str) and value.startswith("assets/") else None
        return self.asset_image(source.asset_id, node.id)

    def asset_image(self, asset_id: uuid.UUID | None, node_id: str) -> str | None:
        if asset_id is None:
            return None
        asset = asset_service.get_asset(self.db, self.ctx.tenant_id, asset_id)
        content = asset_service.read_asset(asset) if asset is not None and asset.kind == "image" else None
        if content is None:
            self._problem(node_id, "assetNotFound", str(asset_id), severity="warning")
            return None
        self.template_asset_checksums[str(asset.public_id)] = asset.checksum_sha256 or ""
        ref = self.template_assets.add_image(content, key=f"tpl:{asset.public_id}")
        return None if ref.missing else ref.path

    def _node_image(self, node, scope, area, scope_def):
        path = self._image_path(node, scope)
        if path is None:
            if self.input.mode == "sample" or not self.input.strict:
                out = self._base(node, "image")
                out.update(path=None, fit=node.fit, caption=self.spans(node.caption, scope, node.id, scope_def))
                return out
            return None
        out = self._base(node, "image")
        out.update(path=path, fit=node.fit, caption=self.spans(node.caption, scope, node.id, scope_def))
        return out

    def _node_divider(self, node, scope, area, scope_def):
        out = self._base(node, "divider")
        out.update(thickness=node.thickness, color=self.color(node.color, node.id, default=self.tokens.colors.border.upper()), line_style=node.line_style, length=compile_length(node.length))
        return out

    def _node_spacer(self, node, scope, area, scope_def):
        out = self._base(node, "spacer")
        out.update(size=node.size, flexible=node.flexible)
        return out

    def _node_page_break(self, node, scope, area, scope_def):
        out = self._base(node, "pagebreak")
        out["master"] = node.master
        return out

    def _node_page_number(self, node, scope, area, scope_def):
        out = self._base(node, "page_number")
        out["format"] = node.format
        return out

    def _node_toc(self, node, scope, area, scope_def):
        out = self._base(node, "toc")
        out.update(depth=node.depth, show_title=node.show_title, density=node.density)
        return out

    def _node_metadata(self, node, scope, area, scope_def):
        env = self.input.document_env
        labels = {
            "number": "titlePage.number",
            "date": "titlePage.date",
            "status": "titlePage.status",
            "version": "titlePage.version",
            "place": "titlePage.place",
            "type": "metadata.type",
            "organization": "metadata.organization",
        }
        values = {
            "number": env.get("number"),
            "date": format_value(env.get("date"), "date", FormatSpec(), self.strings),
            "status": env.get("status"),
            "version": env.get("version"),
            "place": self.input.brand.organization.get("place"),
            "type": env.get("type"),
            "organization": self.input.brand.organization.get("name"),
        }
        if self.input.mode == "sample":
            for key in ("number", "date", "status", "version"):
                if not values[key]:
                    definition = binding_registry.REGISTRY[f"document.{key}"]
                    values[key] = format_value(self.resolver._sample(definition), definition.type, FormatSpec(), self.strings)
        rows = [[self.strings.get(labels[key], key), str(values[key])] for key in node.fields if values.get(key)]
        if not rows:
            return None
        out = self._base(node, "metadata")
        out.update(rows=rows, layout=node.layout)
        return out

    def _node_verify_note(self, node, scope, area, scope_def):
        self._has_verify_note = True
        out = self._base(node, "verify")
        out.update(show_url=node.show_url, show_id=node.show_id, show_qr=node.show_qr)
        return out

    def _node_qr_code(self, node, scope, area, scope_def):
        render = self.input.render
        link = None
        if node.target == "verify":
            link = None if render.preview else render.verify_link
        elif node.target == "url":
            link = node.url
        elif node.target == "protocol":
            protocol = self.ctx.protocol
            base = self.ctx.public_base_url
            if protocol is not None and base:
                link = f"{base.rstrip('/')}/protocols/{protocol.public_id}"
        if not link and not (render.preview or self.input.mode == "sample"):
            return None
        out = self._base(node, "qr")
        out.update(link=link, size=node.size, caption=self.spans(node.caption, scope, node.id, scope_def))
        return out

    def _node_watermark(self, node, scope, area, scope_def):
        if node.when == "draft" and not self.input.is_draft:
            return None
        out = self._base(node, "watermark")
        text = self.text(node.text, scope, node.id) if node.text is not None else ""
        out.update(
            text=text or self.strings.get("watermark.draft", ""),
            path=self.asset_image(node.asset_id, node.id) if node.asset_id else None,
            angle=node.angle,
            size=node.size,
            color=self.color(node.color, node.id, default=self.tokens.colors.watermark.upper()),
        )
        return out

    def _node_absolute_layer(self, node, scope, area, scope_def):
        out = self._children(node, "layer", scope, area, scope_def, anchor=node.anchor, height=node.height)
        if node.anchor == "page" and area != "master":
            margins = self._area_margins(area)
            out["offset"] = [-margins[3], -margins[0]]
        else:
            out["offset"] = [0, 0]
        return out

    def _area_margins(self, area: str) -> list[float]:
        content = self.input.content
        if area == "title_page" and content.title_page.master:
            master = content.master(content.title_page.master)
            if master is not None and master.margins is not None:
                return _spacing(master.margins) or [0, 0, 0, 0]
        return _spacing(content.page.margins) or [0, 0, 0, 0]

    def _node_list(self, node, scope, area, scope_def):
        if node.source is not None:
            definition = self._list_def(node.source, node.id)
            items = self.value(node.source, scope, node.id) if definition is not None else None
            entries = [self.spans(node.item, item if isinstance(item, dict) else {"value": item}, node.id, definition) for item in (items or [])[: node.limit]]
        else:
            entries = [[{"v": item}] for item in node.items if item.strip()]
        entries = [entry for entry in entries if entry]
        if not entries:
            return None
        out = self._base(node, "list")
        out.update(marker=node.marker, items=entries)
        return out

    def _node_table(self, node, scope, area, scope_def):
        columns = [
            {"w": compile_length(column.width), "align": column.align, "header": self.spans(column.header, scope, node.id, scope_def)}
            for column in node.columns
        ]
        if not columns:
            return None
        rows: list[list[list[dict[str, Any]]]] = []
        if node.source is not None:
            definition = self._list_def(node.source, node.id)
            items = self.value(node.source, scope, node.id) if definition is not None else None
            for item in (items or [])[: node.limit]:
                item_scope = item if isinstance(item, dict) else {"value": item}
                rows.append([self.spans(column.cell, item_scope, node.id, definition) for column in node.columns])
        else:
            for row in node.rows:
                rows.append([[{"v": cell}] if cell else [] for cell in row] + [[] for _ in range(len(columns) - len(row))])
        zebra = node.zebra if node.zebra is not None else self.tokens.layout.table_style == "zebra"
        out = self._base(node, "table")
        out.update(
            columns=columns,
            rows=rows,
            show_header=node.show_header and any(column["header"] for column in columns),
            repeat_header=node.repeat_header,
            zebra=zebra,
            empty=node.empty_text if not rows else None,
        )
        if not rows and not node.empty_text:
            return None
        return out

    def _node_data_block(self, node, scope, area, scope_def):
        entry = CATALOG.get(node.component)
        if entry is None:
            self._problem(node.id, "unknownComponent", node.component)
            return self._error_node(node, "unknownComponent")
        if node.title_mode == "custom":
            title = self.text(node.title, scope, node.id) or None
        elif node.title_mode == "auto":
            title = self.strings.get(f"blockType.{node.component}") or None
        else:
            title = None
        allowed = set(entry.params.model_fields)
        params = {**node.params, **{key: value for key, value in self.input.params.items() if key in allowed}}
        spec = BlockSpec(type=node.component, title=title, hide_if_empty=node.hide_if_empty, level=node.level, params=params)
        if (
            self.input.mode != "sample"
            and node.component in NEEDS_PROTOCOL
            and self.ctx.protocol is None
            and not params.get("protocol_id")
            and not params.get("protocol_block_id")
        ):
            self._problem(node.id, "needsProtocol", node.component, severity="warning")
            return None
        try:
            blocks = run_component(self.ctx, spec, sample=self.input.mode == "sample", strings=self.strings)
        except BlockSpecError as exc:
            self._problem(node.id, "invalidParams", exc.detail, exc=exc)
            return self._error_node(node, "invalidParams")
        except DocumentPermissionError as exc:
            self._problem(node.id, "componentPermission", node.component, exc=exc)
            return self._error_node(node, "componentPermission")
        except DocumentNotFoundError as exc:
            self._problem(node.id, "referenceNotFound", str(exc), exc=exc)
            return self._error_node(node, "referenceNotFound")
        if not blocks:
            return None
        return self._data_output(node, blocks)

    def _data_output(self, node, blocks) -> dict[str, Any]:
        self.blocks.extend(blocks)
        out = self._base(node, "data")
        out["blocks"] = [block.model_dump(mode="json") for block in blocks]
        if node.appearance:
            # Vollständig aufgelöst, damit Typst nichts zusammenführen muss
            out["appearance"] = resolve_appearance(self.input.brand.tokens, node.appearance)
        return out

    def _node_component_ref(self, node, scope, area, scope_def):
        from app.models import DocumentComponent

        key = str(node.component_id)
        if key in self._component_stack or len(self._component_stack) >= MAX_COMPONENT_DEPTH:
            self._problem(node.id, "componentCycle", key)
            return None
        component = self.db.query(DocumentComponent).filter(DocumentComponent.public_id == node.component_id, DocumentComponent.tenant_id == self.ctx.tenant_id).one_or_none()
        if component is None:
            self._problem(node.id, "componentNotFound", key)
            return self._error_node(node, "componentNotFound")
        try:
            inner = _NODE_ADAPTER.validate_python(component.node_json)
        except ValidationError as exc:
            self._problem(node.id, "invalidComponent", key, exc=exc)
            return self._error_node(node, "invalidComponent")
        self._component_stack.append(key)
        try:
            compiled = self.node(inner, scope, area, scope_def)
        finally:
            self._component_stack.pop()
        # Stil des Verweises (z. B. Abstand) umschliesst die Komponente
        out = self._base(node, "stack")
        out.update(children=compiled, gap=0)
        return out

    # Seitenvorlagen und Dokument -------------------------------------------

    def master(self, master: PageMaster) -> dict[str, Any]:
        header = self.node(master.header, None, "master")[0] if master.header is not None and master.header.enabled else None
        footer = self.node(master.footer, None, "master")[0] if master.footer is not None and master.footer.enabled else None
        result = {
            "header": header if header and header.get("children") else None,
            "footer": footer if footer and footer.get("children") else None,
            "background": self.nodes(master.background, None, "master"),
        }
        # Entwürfe immer kennzeichnen (STUDIO-007): auch wenn die Vorlage keinen
        # Wasserzeichen-Knoten hat, sonst exportierte sie Entwürfe ohne Markierung.
        if self.input.is_draft and not any(node.get("t") == "watermark" for node in result["background"]):
            result["background"].append(self._node_watermark(WatermarkNode(id="hocx-draft-watermark"), None, "master", None))
        if master.orientation is not None:
            result["orientation"] = master.orientation
        if master.margins is not None:
            result["margins"] = _spacing(master.margins)
        return result

    def compile(self) -> CompiledDocument:
        content = self.input.content
        width, height = content.page.dimensions_mm()
        masters = {master.id: self.master(master) for master in content.masters}

        title_page = None
        if content.title_page.enabled and self._title_page_visible():
            title_page = {
                "master": content.title_page.master,
                "background": self.color(content.title_page.background, None) if content.title_page.background else None,
                "children": self.nodes(content.title_page.children, None, "title_page"),
            }

        segments: list[dict[str, Any]] = [{"master": None, "nodes": []}]
        for compiled in self.nodes(content.body, None, "body"):
            if compiled["t"] == "pagebreak" and compiled.get("master"):
                segments.append({"master": compiled["master"], "nodes": []})
                continue
            segments[-1]["nodes"].append(compiled)
        if not segments[0]["nodes"] and len(segments) > 1:
            segments.pop(0)

        settings = content.settings
        numbering = settings.heading_numbering if settings.heading_numbering is not None else self.tokens.layout.heading_numbering
        verify = self.tokens.verify
        data = {
            "meta": self.input.meta.model_dump(mode="json"),
            "strings": self.strings,
            "render": self.input.render.model_dump(mode="json"),
            "flags": {"draft": self.input.is_draft, "preview": self.input.render.preview, "sample": self.input.mode == "sample", "diagnostics": not self.input.strict},
            "brand": self.input.brand.typst,
            "page": {
                "width": width,
                "height": height,
                "margins": _spacing(content.page.margins),
                "columns": content.page.columns,
                "column_gap": content.page.column_gap,
            },
            "settings": {
                "numbering": bool(numbering),
                "justify": settings.justify,
                "hyphenate": settings.hyphenate,
                "default_master": settings.default_master,
                "first_page_master": settings.first_page_master,
            },
            "masters": masters,
            "title_page": title_page,
            "segments": segments,
            "verify": {
                "auto": settings.auto_verify_note and not self._has_verify_note,
                "show_url": verify.show_url,
                "show_id": verify.show_id,
                "show_qr": verify.show_qr,
            },
        }
        files = {**self.input.brand.files, **self.template_assets.files, **self.ctx.assets.files}
        return CompiledDocument(
            data=data,
            files=files,
            fonts=dict(self.input.brand.fonts),
            blocks=self.blocks,
            diagnostics=self.diagnostics,
            template_asset_checksums=self.template_asset_checksums,
            used_bindings=set(self.resolver.used),
        )

    def _title_page_visible(self) -> bool:
        condition = self.input.content.title_page.visible_if
        if condition is None:
            return True
        try:
            return evaluate(condition, lambda path: self.value(path, None, "title_page"))
        except ConditionError as exc:
            self._problem("title_page", "invalidCondition", str(exc), exc=exc)
            return False


class BlockSpecError(ValueError):
    """Ungültige Komponente oder Parameter (kuratiert, wird als 422 gemeldet)."""

    def __init__(self, block_type: str, detail: str) -> None:
        super().__init__(f"{block_type}: {detail}")
        self.block_type = block_type
        self.detail = detail


def run_component(ctx: BuildContext, spec: BlockSpec, *, sample: bool = False, strings: dict[str, str] | None = None) -> list[Any]:
    """Eine Fachkomponente ausführen: Katalog und Parameter prüfen, Recht prüfen, Provider
    (bzw. Beispielinhalt) aufrufen, leere Blöcke markieren/entfernen."""
    entry = CATALOG.get(spec.type)
    if entry is None:
        raise BlockSpecError(spec.type, "unbekannte Komponente")
    try:
        validated = validate_spec(spec)
    except ValidationError as exc:
        errors = exc.errors()
        raise BlockSpecError(spec.type, errors[0].get("msg", "ungültig") if errors else "ungültig") from exc
    if sample:
        from app.documents.samples import sample_blocks

        return _mark_empty(sample_blocks(spec, validated, strings or {}))
    ctx.require(entry.access)
    return _mark_empty(PROVIDERS[spec.type](ctx, spec, validated))


def build_blocks(ctx: BuildContext, specs: list[BlockSpec]) -> list[Any]:
    """Mehrere Fachkomponenten nacheinander (Inhalts-Hash, Tests)."""
    blocks: list[Any] = []
    for spec in specs:
        blocks.extend(run_component(ctx, spec))
    return blocks


def _mark_empty(blocks: list[Any]) -> list[Any]:
    result = []
    for block in blocks:
        if isinstance(block, ProtocolElementBlock):
            block.children = _mark_empty(block.children)
        block.empty = block.is_empty()
        if block.empty and block.hide_if_empty:
            continue
        result.append(block)
    return result


def compile_document(db: Session, data: CompileInput) -> CompiledDocument:
    return LayoutCompiler(data, db).compile()


# ── Statische Prüfung (ohne Daten) ───────────────────────────────────────────


def validate_template(db: Session, tenant_id: int | None, content: TemplateContent, *, document_type: str | None = None) -> list[Diagnostic]:
    """Prüft Bindungen (Pfad, Typ, Wiederholungs-Kontext), Bedingungen, Fachkomponenten
    (Parameter), Assets und Komponentenverweise einer Vorlage. Fehler verhindern das
    Veröffentlichen, Warnungen nicht."""
    from app.documents.doc_types import DOCUMENT_TYPES
    from app.models import DocumentComponent

    diagnostics: list[Diagnostic] = []
    needs_protocol_type = DOCUMENT_TYPES[document_type].needs_protocol if document_type in DOCUMENT_TYPES else True

    def problem(node_id, code, detail="", severity: Severity = "error"):
        diagnostics.append(Diagnostic(node_id, severity, code, detail))

    def check_path(node_id: str, path: str, scope_def: BindingDef | None, *, expect: tuple[str, ...] | None = None) -> BindingDef | None:
        try:
            value_type, definition = binding_registry.validate_path(path, scope=scope_def)
        except UnknownBindingError:
            problem(node_id, "unknownBinding", path)
            return None
        if expect is not None and value_type not in expect:
            problem(node_id, "bindingTypeMismatch", path)
        if definition is not None and definition.needs_protocol and not needs_protocol_type:
            problem(node_id, "bindingNeedsProtocol", path, "warning")
        return definition

    def check_text(node_id: str, content_value: TextContent | None, scope_def: BindingDef | None) -> None:
        if content_value is None:
            return
        for inlines in [content_value.default, *content_value.translations.values()]:
            for inline in inlines:
                if inline.t == "bind":
                    check_path(node_id, inline.path, scope_def, expect=("text", "date", "number", "amount", "percent", "bool", "list"))

    asset_ids: dict[str, list[str]] = {}
    component_ids: dict[str, list[str]] = {}

    def walk(nodes: list[Any], scope_def: BindingDef | None, area: str) -> None:
        for node in nodes:
            current = scope_def
            if area in ("body", "title_page") and node.type in MASTER_ONLY_TYPES:
                problem(node.id, "masterOnly", node.type)
            if node.repeat is not None:
                current = check_path(node.id, node.repeat.source, scope_def, expect=("list",)) or scope_def
            if node.visible_if is not None:
                for path in condition_paths(node.visible_if):
                    check_path(node.id, path, current)
            for attribute in ("content", "title", "caption"):
                value = getattr(node, attribute, None)
                if isinstance(value, TextContent):
                    check_text(node.id, value, current)
            if node.type in ("table", "list") and node.source is not None:
                list_def = check_path(node.id, node.source, current, expect=("list",))
                if node.type == "table":
                    for column in node.columns:
                        check_text(node.id, column.header, current)
                        check_text(node.id, column.cell, list_def)
                else:
                    check_text(node.id, node.item, list_def)
            elif node.type == "table":
                for column in node.columns:
                    check_text(node.id, column.header, current)
            if node.type == "image":
                if node.source.kind == "binding":
                    check_path(node.id, node.source.path, current, expect=("image",))
                elif node.source.asset_id is not None:
                    asset_ids.setdefault(str(node.source.asset_id), []).append(node.id)
            if node.type == "watermark" and node.asset_id is not None:
                asset_ids.setdefault(str(node.asset_id), []).append(node.id)
            if node.type == "data_block":
                entry = CATALOG.get(node.component)
                if entry is None:
                    problem(node.id, "unknownComponent", node.component)
                else:
                    try:
                        validate_spec(BlockSpec(type=node.component, params=node.params))
                    except ValidationError as exc:
                        problem(node.id, "invalidParams", exc.errors()[0].get("msg", "") if exc.errors() else "")
                    if node.component in NEEDS_PROTOCOL and not needs_protocol_type and not node.params.get("protocol_id") and not node.params.get("protocol_block_id"):
                        problem(node.id, "needsProtocol", node.component, "warning")
                check_text(node.id, node.title, current)
            if node.type == "component_ref":
                component_ids.setdefault(str(node.component_id), []).append(node.id)
            children = getattr(node, "children", None)
            if children:
                walk(children, current, area)

    for area, nodes in all_node_lists(content):
        walk(nodes, None, "master" if area.startswith("master:") else area)
    if content.title_page.visible_if is not None:
        for path in condition_paths(content.title_page.visible_if):
            check_path("title_page", path, None)
    if content.settings.brand_overrides.logo_asset_id is not None:
        asset_ids.setdefault(str(content.settings.brand_overrides.logo_asset_id), []).append("settings")

    if asset_ids:
        found = asset_service.assets_by_ids(db, tenant_id, [uuid.UUID(value) for value in asset_ids]) if tenant_id is not None else {}
        for value, node_ids in asset_ids.items():
            asset = found.get(uuid.UUID(value))
            if asset is None or asset.kind != "image":
                for node_id in node_ids:
                    problem(node_id, "assetNotFound", value)
    if component_ids:
        found_components = set()
        if tenant_id is not None:
            found_components = {
                str(row.public_id)
                for row in db.query(DocumentComponent.public_id).filter(
                    DocumentComponent.tenant_id == tenant_id, DocumentComponent.public_id.in_([uuid.UUID(value) for value in component_ids])
                )
            }
        for value, node_ids in component_ids.items():
            if value not in found_components:
                for node_id in node_ids:
                    problem(node_id, "componentNotFound", value)
    return diagnostics


def has_errors(diagnostics: list[Diagnostic]) -> bool:
    return any(item.severity == "error" for item in diagnostics)


__all__ = [
    "BlockSpecError",
    "build_blocks",
    "run_component",
    "CompileError",
    "CompileInput",
    "CompiledDocument",
    "Diagnostic",
    "LayoutCompiler",
    "compile_document",
    "has_errors",
    "validate_template",
    "iter_nodes",
]
