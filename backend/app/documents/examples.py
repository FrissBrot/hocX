"""Gestaltungsbeispiele des Document Studio: fertig gestaltete Vorlagen samt passendem CD.

Die Beispiele sind keine Systemvorlagen. Ein Verein holt sie bei Bedarf in sein Studio
(``import_example``): Dabei entstehen eine eigene Vorlage und ein Brand-Profil mit den Farben,
Schriften, Beispielbildern und Organisationsangaben des Mockups, und die Vorlage ist mit
diesem Profil verknüpft. So sieht der Verein die Vorlage zuerst wie im Entwurf. Stellt er die
Vorlage auf sein eigenes Brand-Profil um, erscheint sie in seinen Farben, mit seinem Logo und
seinen Angaben.

Vorlage: Claude-Design-Projekt «Protokoll-Templates» (Template, Template v2, Bau, Tech,
Kanzlei, Corporate). Gebaut nur aus den vorhandenen Bausteinen; Texte sind Schlüssel aus
documentPdf, Namen und Beschreibungen übersetzt das Frontend (``documentStudio.examples.<key>``).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.documents.appearance import APPEARANCE_BASES
from app.documents.brand import BrandTokens
from app.documents.layout import TemplateContent
from app.documents.system_templates import bind, content, data, exists, key, lit, node, text, txt, when

ASSET_DIR = Path(__file__).with_name("example_assets")


WHITE = "#FFFFFF"


def label_text(node_id: str, *inlines: dict[str, Any], **fields: Any) -> dict[str, Any]:
    """Wie text(); Name ohne «text(f"…")», das der SQL-Prüfung wie ein f-String-Query aussieht."""
    return text(node_id, *inlines, **fields)


def _or_dash(path: str) -> dict[str, Any]:
    return {**bind(path), "fallback": "–"}


def _pad(top: float, right: float | None = None, bottom: float | None = None, left: float | None = None) -> dict[str, float]:
    right = top if right is None else right
    return {"top": top, "right": right, "bottom": top if bottom is None else bottom, "left": right if left is None else left}


def _fill(color: str, *, radius: float = 0) -> dict[str, Any]:
    """Hintergrund ohne sichtbaren Rahmen (der Radius braucht im Renderer einen Rahmen)."""
    return {"background": color, "border": {"width": 0, "color": color, "radius": radius}}


def _small(node_id: str, *inlines: dict[str, Any], color: str = "$brand.muted", size: float = 7.5, upper: bool = True, bold: bool = False, spacing: float = 0.6, align: str | None = None, frame: dict[str, Any] | None = None, **style: Any) -> dict[str, Any]:
    text_style: dict[str, Any] = {"size": size, "color": color, "letter_spacing": spacing}
    if align:
        text_style["align"] = align
    if upper:
        text_style["transform"] = "upper"
    if bold:
        text_style["weight"] = "bold"
    extra = {"frame": frame} if frame else {}
    return text(node_id, *inlines, role="small", style={"text": text_style, **style}, **extra)


def _kpi(node_id: str, label: dict[str, Any], *value: dict[str, Any], box: dict[str, Any], label_color: str = "$brand.muted", value_color: str = "$brand.primary", value_size: float = 15, value_weight: str = "bold") -> dict[str, Any]:
    return node(
        "container",
        node_id,
        gap=1,
        style={"width": "fill", **box},
        children=[
            _small(f"{node_id}-label", label, color=label_color),
            label_text(f"{node_id}-value", *value, style={"text": {"size": value_size, "weight": value_weight, "color": value_color, "line_height": 1.1}}),
        ],
    )


def _kpi_row(prefix: str, *, box: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    """Anwesend / Offene Todos / Nächste Sitzung - die Kennzahlen der Titelseiten."""
    return node(
        "row",
        f"{prefix}-kpis",
        gap=4,
        style={"margin_bottom": 2},
        children=[
            _kpi(f"{prefix}-kpi-present", key("attendanceStatus.present"), bind("protocol.present_count"), lit(" / "), bind("protocol.participant_count"), box=box, **kwargs),
            _kpi(f"{prefix}-kpi-todos", key("kpi.openTodos"), bind("todos.open_count"), box=box, **kwargs),
            _kpi(f"{prefix}-kpi-next", key("label.nextSession"), _or_dash("protocol.next_session"), box=box, **kwargs),
        ],
    )


def _running_master(prefix: str, *, brand_color: str, line_color: str = "$brand.border", line: float = 0.5, dot: bool = False, page_color: str = "$brand.primary", page_bold: bool = True, background: list[dict[str, Any]] | None = None, upper_name: bool = False, lower_name: bool = False, meta_color: str = "$brand.muted", meta_separator: bool = False) -> dict[str, Any]:
    """Kopf «Organisation · Titel · Datum» und Fuss «Nummer · Seite x von y» der Inhaltsseiten.
    Die Teile folgen den Kopf-/Fusszeilen-Schaltern des Brand-Profils bzw. der Vorlage
    (Organisation = Schalter «Logo», wie das Logo der Standard-Seitenvorlage). ``meta_separator``:
    «Titel · Datum» statt zwei Einträgen mit Abstand."""
    name_style: dict[str, Any] = {"size": 8, "weight": "bold", "color": brand_color}
    if upper_name:
        name_style.update(transform="upper", letter_spacing=0.4)
    elif lower_name:
        name_style.update(transform="lower", letter_spacing=0.2)
    left: list[dict[str, Any]] = []
    if dot:
        left.append(node("container", f"{prefix}-dot", style={"width": "2.2mm", "height": "2.2mm", **_fill(brand_color, radius=1.1)}, visible_if=when("brand.header_show_logo")))
    left.append(label_text(f"{prefix}-org", bind("organization.name"), role="small", style={"text": name_style}, visible_if=when("brand.header_show_logo")))
    meta_style = {"size": 8, "align": "right", "color": meta_color}
    separator = [label_text(f"{prefix}-hdr-sep", lit("·"), role="small", style={"text": meta_style}, visible_if={"op": "all", "items": [when("brand.header_show_title"), when("brand.header_show_date")]})] if meta_separator else []
    header = node(
        "header",
        f"{prefix}-hdr",
        children=[
            node(
                "row",
                f"{prefix}-hdr-row",
                valign="middle",
                gap=1.5 if meta_separator else 2,
                children=[
                    *left,
                    label_text(f"{prefix}-hdr-title", bind("document.title"), role="small", style={"width": "fill", "text": meta_style}, visible_if=when("brand.header_show_title")),
                    *separator,
                    label_text(f"{prefix}-hdr-date", bind("document.date"), role="small", style={"text": meta_style}, visible_if=when("brand.header_show_date")),
                ],
            ),
            node("divider", f"{prefix}-hdr-line", thickness=line, color=line_color),
        ],
    )
    footer = node(
        "footer",
        f"{prefix}-ftr",
        children=[
            node("divider", f"{prefix}-ftr-line", thickness=0.5, color="$brand.border"),
            node(
                "row",
                f"{prefix}-ftr-row",
                gap=4,
                children=[
                    label_text(f"{prefix}-ftr-number", bind("document.number"), role="small", style={"width": "fill", "text": {"size": 8, "color": meta_color}}, visible_if=when("brand.footer_show_number")),
                    label_text(f"{prefix}-ftr-text", bind("brand.footer_text"), role="small", style={"width": "fill", "text": {"size": 8, "align": "center", "color": "$brand.muted"}}),
                    node("page_number", f"{prefix}-ftr-page", style={"text": {"size": 8, "color": page_color, **({"weight": "bold"} if page_bold else {})}}, visible_if=when("brand.footer_show_pages")),
                ],
            ),
        ],
    )
    return {
        "id": "default",
        "name": "",
        "header": header,
        "footer": footer,
        "background": [*(background or []), node("watermark", f"{prefix}-watermark", when="draft", visible_if=when("brand.watermark_draft"))],
    }


def _page_layer(node_id: str, *children: dict[str, Any]) -> dict[str, Any]:
    return node("absolute_layer", node_id, anchor="page", children=list(children))


def _area(node_id: str, color: str, *, x: float = 0, y: float = 0, width: float = 210, height: float) -> dict[str, Any]:
    """Farbfläche auf einer Seitenebene (Titelband, Signalstreifen, Papierfarbe)."""
    return node("container", node_id, style={"width": f"{width:g}mm", "height": f"{height:g}mm", **_fill(color)}, frame={"x": x, "y": y, "width": width, "height": height})


def _footer_image(prefix: str, *, color: str = "$brand.muted", size: float | None = None) -> dict[str, Any]:
    """Adresszeile und Fussbild (Brand-Profil: Bild «Fusszeile») über die ganze Seitenbreite am
    Seitenende; ohne Fussbild steht die Adresse am unteren Rand."""
    address_style: dict[str, Any] = {"align": "center", "color": color, **({"size": size} if size else {})}
    return _page_layer(
        f"{prefix}-footer-art",
        label_text(f"{prefix}-address", bind("organization.address"), role="small", style={"text": address_style}, frame={"x": 0, "y": 256, "width": 210}, visible_if=exists("brand.footer_image")),
        label_text(f"{prefix}-address-plain", bind("organization.address"), role="small", style={"text": address_style}, frame={"x": 0, "y": 280, "width": 210}, visible_if={"op": "not", "item": exists("brand.footer_image")}),
        node("image", f"{prefix}-footer-img", source={"kind": "binding", "path": "brand.footer_image"}, fit="contain", style={"width": "210mm"}, frame={"x": 0, "y": 262, "width": 210, "height": 35, "valign": "bottom"}, visible_if=exists("brand.footer_image")),
    )


def _agenda_rows(prefix: str, *, number_color: str, size: float = 10, number_prefix: str = "", responsible_italic: bool = False, line_color: str = "$brand.border", number_box: str | None = None) -> dict[str, Any]:
    """Traktandenliste der Titelseite: eine Zeile je Protokollelement (Nummer, Titel, Verantwortlich)."""
    number_style: dict[str, Any] = {"size": size * 0.85, "weight": "bold", "color": number_color}
    number_node: dict[str, Any]
    if number_box:
        number_node = node(
            "container",
            f"{prefix}-agenda-badge",
            style={"width": "6mm", "padding": _pad(0.8, 0), **_fill(number_box)},
            children=[label_text(f"{prefix}-agenda-no", bind("item.index"), style={"text": {**number_style, "color": WHITE, "align": "center"}})],
        )
    else:
        inlines = [lit(number_prefix), bind("item.index")] if number_prefix else [bind("item.index")]
        number_node = label_text(f"{prefix}-agenda-no", *inlines, style={"width": "10mm", "text": number_style})
    return node(
        "container",
        f"{prefix}-agenda-row",
        repeat={"source": "protocol.elements", "limit": 40},
        style={"padding": _pad(1.8, 0), "border": {"width": 0.5, "color": line_color, "sides": ["bottom"]}},
        children=[
            node(
                "row",
                f"{prefix}-agenda-cols",
                gap=3,
                valign="middle",
                children=[
                    number_node,
                    label_text(f"{prefix}-agenda-title", bind("item.title"), style={"width": "fill", "text": {"size": size}}),
                    label_text(f"{prefix}-agenda-resp", bind("item.responsible"), role="small", style={"text": {"size": size * 0.82, "color": "$brand.muted", **({"italic": True} if responsible_italic else {})}}),
                ],
            )
        ],
    )


def _protocol_band() -> dict[str, Any]:
    """Farbband: Titelseite mit vollflächigem Band in der Hauptfarbe, Kennzahlen-Kacheln und
    Inhaltsverzeichnis, Fussbild am Seitenende (Vorlage «Protokoll Template»)."""
    band = _page_layer(
        "tp-band",
        _area("tp-band-fill", "$brand.primary", y=0, height=88),
        node("container", "tp-logo-box", visible_if=exists("brand.logo"), style={"padding": _pad(2.5, 3.5), **_fill(WHITE, radius=2)}, frame={"x": 22, "y": 14, "width": 60, "height": 29}, children=[
            node("image", "tp-logo", source={"kind": "binding", "path": "brand.logo"}, style={"height": "24mm"}),
        ]),
        text("tp-org", bind("organization.name"), role="small", style={"text": {"size": 9, "weight": "bold", "color": WHITE, "align": "right", "letter_spacing": 0.4, "transform": "lower"}}, frame={"x": 100, "y": 26, "width": 88}),
        node("row", "tp-chips", gap=2, frame={"x": 22, "y": 50, "width": 166}, children=[
            node("container", "tp-chip-kind", style={"padding": _pad(0.8, 2.5), **_fill("$brand.accent", radius=4)}, children=[_small("tp-chip-kind-text", key("docType.protocol"), color=WHITE, bold=True, spacing=1)]),
            node("container", "tp-chip-number", visible_if=exists("document.number"), style={"padding": _pad(0.8, 2.5), "border": {"width": 0.75, "color": WHITE, "radius": 4}}, children=[_small("tp-chip-number-text", bind("document.number"), color=WHITE, bold=True, upper=False)]),
        ]),
        text("tp-title", bind("document.title"), role="title", style={"text": {"size": 30, "color": WHITE, "line_height": 1.05, "letter_spacing": -0.4}}, frame={"x": 22, "y": 58, "width": 166}),
        text("tp-place-date", bind("organization.place"), lit(", "), bind("document.date"), style={"text": {"size": 10.5, "color": WHITE}}, frame={"x": 22, "y": 76, "width": 166}),
    )
    title_page = {
        "enabled": True,
        "children": [
            band,
            node("spacer", "tp-band-space", size=72),
            _kpi_row("tp", box={"padding": _pad(3, 3.5), **_fill("$brand.surface", radius=2)}),
            node("spacer", "tp-toc-space", size=4),
            node("toc", "tp-toc", depth=1, density="compact"),
            _footer_image("tp"),
        ],
    }
    return content(
        [data("protocol", "protocol_element")],
        masters=[_running_master("run", brand_color="$brand.primary", dot=True)],
        title_page=title_page,
        heading_numbering=True
    )


def _protocol_light() -> dict[str, Any]:
    """Hell: dieselbe Gliederung wie «Farbband», aber weiss mit feinen Linien, Akzent nur in
    Schrift (Vorlage «Protokoll Template v2»): Name klein geschrieben, Metadaten in der
    Zweitfarbe, Inhaltsverzeichnis mit Führungspunkten."""
    title_page = {
        "enabled": True,
        "children": [
            node("row", "tp-head", valign="middle", gap=6, style={"margin_bottom": 12}, children=[
                node("image", "tp-logo", source={"kind": "binding", "path": "brand.logo"}, style={"width": "auto", "height": "18mm"}, visible_if=exists("brand.logo")),
                text("tp-org", bind("organization.name"), role="small", style={"width": "fill", "text": {"size": 9, "weight": "bold", "color": "$brand.primary", "align": "right", "letter_spacing": 0.4, "transform": "lower"}}),
            ]),
            node("row", "tp-kicker", gap=2, children=[
                _small("tp-kind", key("docType.protocol"), color="$brand.accent", bold=True, spacing=1),
                _small("tp-number", bind("document.number"), upper=False, spacing=0.5),
            ]),
            text("tp-title", bind("document.title"), role="title", style={"text": {"size": 30, "line_height": 1.05, "letter_spacing": -0.6, "color": "$brand.text"}, "margin_top": 2}),
            text("tp-place-date", bind("organization.place"), lit(", "), bind("document.date"), style={"text": {"size": 10.5, "color": "$brand.muted"}, "margin_top": 4}),
            node("divider", "tp-line", thickness=0.5, color="$brand.border", style={"margin_top": 9, "margin_bottom": 7}),
            _kpi_row("tp", box={}, label_color="$brand.secondary", value_color="$brand.text", value_weight="regular"),
            node("spacer", "tp-toc-space", size=4),
            node("toc", "tp-toc", depth=1, density="normal"),
            _footer_image("tp", color="$brand.secondary", size=8.5),
        ],
    }
    return content(
        [data("protocol", "protocol_element")],
        masters=[_running_master("run", brand_color="$brand.primary", page_color="$brand.muted", page_bold=False, lower_name=True, meta_color="$brand.secondary", meta_separator=True)],
        title_page=title_page,
        heading_numbering=True
    )


def _meta_cell(node_id: str, label: dict[str, Any], *value: dict[str, Any], border: dict[str, Any] | None = None) -> dict[str, Any]:
    style: dict[str, Any] = {"width": "fill", "padding": _pad(2.5, 3)}
    if border:
        style["border"] = border
    return node("container", node_id, gap=1.5, style=style, children=[
        _small(f"{node_id}-label", label, bold=True),
        label_text(f"{node_id}-value", *value, style={"text": {"size": 10, "weight": "bold"}}),
    ])


def _protocol_construction() -> dict[str, Any]:
    """Baustelle: dunkles Titelband mit Signalstreifen, Eckdaten im Rahmen, Kennzahlen und
    Verteiler (Vorlage «Protokoll Bau»)."""
    band = _page_layer(
        "tp-band",
        _area("tp-band-fill", "$brand.primary", y=0, height=76),
        _area("tp-band-stripe", "$brand.accent", y=76, height=4),
        text("tp-org", bind("organization.name"), role="small", style={"text": {"size": 16, "weight": "bold", "color": WHITE, "transform": "upper", "letter_spacing": 0.6}}, frame={"x": 18, "y": 14, "width": 120}),
        text("tp-number", bind("document.number"), role="small", style={"text": {"size": 10, "weight": "bold", "color": "$brand.accent", "align": "right", "letter_spacing": 0.8}}, frame={"x": 140, "y": 15, "width": 52}),
        _small("tp-kind", key("docType.protocol"), color="$brand.accent", size=11, bold=True, spacing=1.3, frame={"x": 18, "y": 42, "width": 174}),
        text("tp-title", bind("document.title"), role="title", style={"text": {"size": 34, "color": WHITE, "transform": "upper", "line_height": 0.95}}, frame={"x": 18, "y": 49, "width": 174}),
    )
    rule = {"width": 1, "color": "$brand.primary"}
    title_page = {
        "enabled": True,
        "children": [
            band,
            node("spacer", "tp-band-space", size=66),
            node("row", "tp-facts", gap=0, style={"border": rule}, children=[
                _meta_cell("tp-fact-date", key("titlePage.date"), bind("protocol.date"), border={**rule, "sides": ["right"]}),
                _meta_cell("tp-fact-place", key("titlePage.place"), _or_dash("organization.place"), border={**rule, "sides": ["right"]}),
                _meta_cell("tp-fact-number", key("titlePage.number"), _or_dash("document.number"), border={**rule, "sides": ["right"]}),
                _meta_cell("tp-fact-next", key("label.nextSession"), _or_dash("protocol.next_session")),
            ]),
            node("spacer", "tp-kpi-space", size=6),
            node("row", "tp-kpis", gap=4, children=[
                _kpi("tp-kpi-present", key("attendanceStatus.present"), bind("protocol.present_count"), lit(" / "), bind("protocol.participant_count"), box={"padding": _pad(4), **_fill("$brand.accent")}, label_color="$brand.primary", value_color="$brand.primary", value_size=22),
                _kpi("tp-kpi-todos", key("kpi.openTodos"), bind("todos.open_count"), box={"padding": _pad(4), **_fill("$brand.surface")}, value_color="$brand.primary", value_size=22),
                _kpi("tp-kpi-excused", key("attendanceStatus.excused"), bind("protocol.excused_count"), box={"padding": _pad(4), **_fill("$brand.surface")}, value_color="$brand.primary", value_size=22),
            ]),
            text("tp-people-title", key("col.participants"), style={"margin_top": 8, "margin_bottom": 2, "text": {"transform": "upper", "size": 15, "weight": "bold", "color": "$brand.primary"}}),
            node("table", "tp-people", source="protocol.participants", columns=[
                {"id": "tp-people-name", "header": txt(key("col.name")), "width": "fill", "cell": txt(bind("item.name"))},
                {"id": "tp-people-status", "header": txt(key("col.status")), "cell": txt(bind("item.status"))},
            ]),
            node("spacer", "tp-flex", flexible=True),
            node("divider", "tp-foot-line", thickness=1, color="$brand.primary"),
            text("tp-address", bind("organization.name"), lit(" · "), bind("organization.address"), role="small", style={"text": {"color": "$brand.muted"}}),
        ],
    }
    return content(
        [data("protocol", "protocol_element")],
        masters=[_running_master("run", brand_color="$brand.primary", line_color="$brand.primary", line=2, page_color="$brand.primary", upper_name=True)],
        title_page=title_page,
        page={"size": "A4", "margins": _pad(18, 18, 18, 18)},
        heading_numbering=True
    )


def _protocol_tech() -> dict[str, Any]:
    """Tech: viel Weissraum, Kennungen klein in der Akzentfarbe, Agenda als Tabelle auf der
    Titelseite und Teilnehmende als Chips (Vorlage «Protokoll Tech»)."""
    title_page = {
        "enabled": True,
        "children": [
            node("row", "tp-head", valign="middle", gap=2, children=[
                node("container", "tp-dot", style={"width": "5mm", "height": "5mm", **_fill("$brand.primary", radius=2.5)}),
                text("tp-org", bind("organization.name"), style={"width": "fill", "text": {"size": 12, "weight": "bold", "transform": "lower", "letter_spacing": -0.1}}),
                _small("tp-number", bind("document.number"), upper=False),
            ]),
            node("spacer", "tp-space", size=30),
            _small("tp-kind", key("docType.protocol"), color="$brand.primary", size=8, upper=False, spacing=0),
            text("tp-title", bind("document.title"), role="title", style={"text": {"size": 34, "line_height": 1.02, "letter_spacing": -0.8, "color": "$brand.text"}, "width": "150mm", "margin_top": 3}),
            node("grid", "tp-facts", columns=2, column_widths=["24mm", "fill"], gap_x=0, gap_y=1.5, style={"margin_top": 10, "text": {"size": 8.5}}, children=[
                _small("tp-fact-date-k", key("titlePage.date"), upper=False, spacing=0, size=8.5), text("tp-fact-date", bind("protocol.date"), style={"text": {"size": 8.5}}),
                _small("tp-fact-place-k", key("titlePage.place"), upper=False, spacing=0, size=8.5), text("tp-fact-place", _or_dash("organization.place"), style={"text": {"size": 8.5}}),
                _small("tp-fact-people-k", key("label.participantCount"), upper=False, spacing=0, size=8.5), text("tp-fact-people", bind("protocol.present_count"), lit(" / "), bind("protocol.participant_count"), style={"text": {"size": 8.5}}),
                _small("tp-fact-next-k", key("label.nextSession"), upper=False, spacing=0, size=8.5), text("tp-fact-next", _or_dash("protocol.next_session"), style={"text": {"size": 8.5}}),
            ]),
            node("container", "tp-agenda-head", style={"margin_top": 14, "padding": _pad(0, 0, 2, 0), "border": {"width": 0.5, "color": "$brand.text", "sides": ["bottom"]}}, children=[
                _small("tp-agenda-label", key("label.agenda"), spacing=0.4),
            ]),
            _agenda_rows("tp", number_color="$brand.primary", size=10.5),
            node("spacer", "tp-flex", flexible=True),
            _small("tp-foot", bind("organization.name"), lit(" · "), bind("organization.website"), upper=False, spacing=0, size=7),
        ],
    }
    chips = node("grid", "chips", columns=4, gap_x=1.5, gap_y=1.5, style={"margin_bottom": 6}, children=[
        node("container", "chip", repeat={"source": "protocol.participants", "limit": 60}, style={"padding": _pad(1, 2.5), "border": {"width": 0.5, "color": "$brand.border", "radius": 4}}, children=[
            text("chip-name", bind("item.name"), style={"text": {"size": 8.5}}),
        ]),
    ])
    return content(
        [chips, data("protocol", "protocol_element")],
        masters=[_running_master("run", brand_color="$brand.primary", dot=True, page_color="$brand.muted", page_bold=False)],
        title_page=title_page,
        page={"size": "A4", "margins": _pad(16, 18, 16, 18)},
        heading_numbering=True
    )


def _protocol_law() -> dict[str, Any]:
    """Kanzlei: Serifenschrift, zentrierter Briefkopf mit Doppellinie, Traktanden mit §-Nummern,
    Unterschriften am Schluss (Vorlage «Protokoll Kanzlei»)."""
    paper = "#FDFBF8"
    title_page = {
        "enabled": True,
        "background": paper,
        "children": [
            text("tp-org", bind("organization.name"), style={"text": {"size": 17, "align": "center", "letter_spacing": 1}}),
            _small("tp-place", bind("organization.place"), size=7, spacing=2.1, align="center"),
            node("divider", "tp-rule-1", thickness=0.5, color="$brand.text", style={"margin_top": 4}),
            node("divider", "tp-rule-2", thickness=0.5, color="$brand.text"),
            node("spacer", "tp-space", size=24),
            _small("tp-kind", key("docType.protocol"), color="$brand.primary", bold=True, spacing=1.8, align="center"),
            text("tp-title", bind("document.title"), role="title", style={"text": {"size": 30, "weight": "regular", "align": "center", "line_height": 1.12, "color": "$brand.text"}, "margin_top": 3}),
            text("tp-date", bind("protocol.date", date="weekday"), style={"text": {"size": 11, "italic": True, "align": "center", "color": "$brand.muted"}}),
            node("spacer", "tp-space-2", size=18),
            _small("tp-agenda-label", key("label.agenda"), spacing=1.5, margin_bottom=2),
            _agenda_rows("tp", number_color="$brand.primary", size=11, number_prefix="§ ", responsible_italic=True),
            node("spacer", "tp-flex", flexible=True),
            _small("tp-foot", bind("organization.address"), lit(" · "), bind("organization.website"), upper=False, spacing=0.3),
        ],
    }
    page_bg = node("absolute_layer", "run-paper", anchor="page", children=[
        _area("run-paper-fill", paper, height=297),
    ])
    attendance = node("row", "attendance", gap=6, style={"margin_bottom": 4}, children=[
        _small("attendance-label", key("col.participants"), spacing=1.3, width="28mm"),
        node("grid", "attendance-list", columns=2, gap_x=6, gap_y=1.2, style={"width": "fill"}, children=[
            node("row", "attendance-person", repeat={"source": "protocol.participants", "limit": 80}, gap=2, children=[
                text("attendance-name", bind("item.name"), style={"width": "fill", "text": {"size": 10}}),
                text("attendance-status", bind("item.status"), role="small", style={"text": {"italic": True, "color": "$brand.muted"}}),
            ]),
        ]),
    ])
    signatures = node("section", "signatures", title=txt(key("label.signature")), keep_together=True, style={"margin_top": 10}, children=[data("signature-fields", "signature_fields")])
    return content(
        [attendance, node("divider", "attendance-line", thickness=0.5, color="$brand.border", style={"margin_bottom": 4}), data("protocol", "protocol_element"), signatures],
        masters=[_running_master("run", brand_color="$brand.text", line_color="$brand.text", page_color="$brand.muted", page_bold=False, background=[page_bg])],
        title_page=title_page,
        page={"size": "A4", "margins": _pad(18, 26, 16, 26)},
        heading_numbering=True
    )


def _protocol_corporate() -> dict[str, Any]:
    """Corporate: Titelband in der Hauptfarbe, Eckdaten, Kennzahlen, nummerierte Traktanden
    (Vorlage «Protokoll Corporate»)."""
    band = _page_layer(
        "tp-band",
        _area("tp-band-fill", "$brand.primary", y=0, height=80),
        node("container", "tp-logo-box", visible_if=exists("brand.logo"), style={"padding": _pad(1.5), **_fill(WHITE)}, frame={"x": 20, "y": 14, "width": 30, "height": 12}, children=[
            node("image", "tp-logo", source={"kind": "binding", "path": "brand.logo"}, style={"height": "9mm"}),
        ]),
        text("tp-org", bind("organization.name"), style={"text": {"size": 12, "weight": "bold", "color": WHITE, "letter_spacing": 0.2}}, frame={"x": 54, "y": 17.5, "width": 100}),
        _small("tp-kind", key("docType.protocol"), lit(" · "), bind("document.number"), color="$brand.border", size=8, bold=True, spacing=1.1, frame={"x": 20, "y": 50, "width": 170}),
        text("tp-title", bind("document.title"), role="title", style={"text": {"size": 28, "color": WHITE, "line_height": 1.08}}, frame={"x": 20, "y": 56, "width": 170}),
    )
    line = {"width": 0.5, "color": "$brand.border", "sides": ["bottom"]}
    title_page = {
        "enabled": True,
        "children": [
            band,
            node("spacer", "tp-band-space", size=68),
            node("row", "tp-facts", gap=4, style={"padding": _pad(6, 0), "border": line}, children=[
                _meta_cell("tp-fact-date", key("titlePage.date"), bind("protocol.date")),
                _meta_cell("tp-fact-place", key("titlePage.place"), _or_dash("organization.place")),
                _meta_cell("tp-fact-number", key("titlePage.number"), _or_dash("document.number")),
                _meta_cell("tp-fact-next", key("label.nextSession"), _or_dash("protocol.next_session")),
            ]),
            node("spacer", "tp-kpi-space", size=6),
            _kpi_row("tp", box={"padding": _pad(4), **_fill("$brand.surface")}, value_size=18),
            text("tp-agenda-heading", key("label.agenda"), style={"margin_top": 8, "margin_bottom": 2, "text": {"size": 12, "weight": "bold", "color": "$brand.primary"}}),
            _agenda_rows("tp", number_color="$brand.primary", number_box="$brand.primary"),
            node("spacer", "tp-flex", flexible=True),
            node("divider", "tp-foot-line", thickness=0.5, color="$brand.border"),
            text("tp-address", bind("organization.name"), lit(" · "), bind("organization.address"), role="small", style={"text": {"color": "$brand.muted"}}),
        ],
    }
    return content(
        [data("protocol", "protocol_element")],
        masters=[_running_master("run", brand_color="$brand.primary", line_color="$brand.primary", line=1.5, page_color="$brand.muted", page_bold=False)],
        title_page=title_page,
        page={"size": "A4", "margins": _pad(16, 20, 14, 20)},
        heading_numbering=True
    )


# ── Beispiel-CDs ─────────────────────────────────────────────────────────────


def _colors(primary: str, secondary: str, accent: str, heading: str, *, text: str, muted: str, surface: str, border: str, table_header_background: str, table_header_text: str) -> dict[str, str]:
    return {
        "primary": primary, "secondary": secondary, "accent": accent, "heading": heading, "text": text, "muted": muted,
        "surface": surface, "border": border, "table_header_background": table_header_background, "table_header_text": table_header_text,
    }


def _typography(font: str, *, heading_font: str | None = None, base_size: float = 10, heading_transform: str = "none") -> dict[str, Any]:
    return {"body": {"builtin": font}, "heading": {"builtin": heading_font or font}, "base_size": base_size, "heading_transform": heading_transform}


_CLUB_ORGANIZATION = {"name": "Jugendverein Musterdorf", "address": "Dorfstrasse 1 · 6000 Musterdorf", "website": "jv-musterdorf.ch", "place": "Musterdorf"}


@dataclass(frozen=True)
class DesignExample:
    key: str
    document_type: str
    build: Callable[[], dict[str, Any]]
    tokens: dict[str, Any]
    # Beispielbilder (example_assets/) für Brand-Asset-Felder, z. B. {"logo": "club-logo.png"}
    images: dict[str, str] = field(default_factory=dict)
    sort_index: int = 0


EXAMPLES: tuple[DesignExample, ...] = (
    DesignExample(
        "alpin", "protocol", _protocol_band,
        {
            "colors": _colors("#0A600B", "#4A5D4C", "#E2001A", "#0A600B", text="#1A1D21", muted="#4A5D4C", surface="#EDF4EA", border="#CFDCCB", table_header_background="#EDF4EA", table_header_text="#0A600B"),
            "typography": _typography("liberation_sans"),
            "layout": {"empty_blocks": "hide"},
            "appearance": {"base": "alpin"},
            "organization": _CLUB_ORGANIZATION,
        },
        images={"logo": "club-logo.png", "footer_image": "club-footer.png"},
        sort_index=1,
    ),
    DesignExample(
        "kreide", "protocol", _protocol_light,
        {
            # Wie im Mockup: Traktandentitel in Textfarbe (nur die Nummer grün), 14/10.5 pt
            "colors": _colors("#0A600B", "#4A5D4C", "#E2001A", "#1A1D21", text="#1A1D21", muted="#6B7A6D", surface="#F4F6F3", border="#E6EAE4", table_header_background="#FFFFFF", table_header_text="#6B7A6D"),
            "typography": {**_typography("liberation_sans", base_size=9.5), "size_h1": 14, "size_h2": 10.5, "size_h3": 9.5, "letter_spacing_heading": -0.1},
            "layout": {"empty_blocks": "hide", "section_gap": 6.5},
            "appearance": {"base": "kreide"},
            "organization": _CLUB_ORGANIZATION,
        },
        images={"logo": "club-logo.png", "footer_image": "club-footer.png"},
        sort_index=2,
    ),
    DesignExample(
        "signal", "protocol", _protocol_construction,
        {
            "colors": _colors("#161616", "#6B6B6B", "#F2B705", "#161616", text="#161616", muted="#6B6B6B", surface="#F3F2EF", border="#D8D6D1", table_header_background="#F3F2EF", table_header_text="#161616"),
            "typography": _typography("liberation_sans", heading_transform="upper"),
            "appearance": {"base": "signal"},
            "organization": {"name": "Bergmann Bau AG", "address": "Seestrasse 5 · 6300 Zug", "website": "bergmann-bau.ch", "place": "Zug"},
        },
        sort_index=3,
    ),
    DesignExample(
        "fokus", "protocol", _protocol_tech,
        {
            "colors": _colors("#4B4FD8", "#6A6F7C", "#2E9E6A", "#14161B", text="#14161B", muted="#6A6F7C", surface="#F3F3FD", border="#E0E1E6", table_header_background="#F3F3FD", table_header_text="#14161B"),
            "typography": _typography("inter"),
            "appearance": {"base": "fokus"},
            "organization": {"name": "lumio GmbH", "address": "Hardturmstrasse 101 · 8005 Zürich", "website": "lumio.ch", "place": "Zürich"},
        },
        sort_index=4,
    ),
    DesignExample(
        "siegel", "protocol", _protocol_law,
        {
            "colors": _colors("#7A1F2B", "#6E655D", "#7A1F2B", "#221E1B", text="#221E1B", muted="#6E655D", surface="#F4EFE8", border="#E3DDD4", table_header_background="#F4EFE8", table_header_text="#7A1F2B"),
            "typography": _typography("liberation_serif", base_size=10.5),
            "appearance": {"base": "siegel"},
            "organization": {"name": "Keller & Partner", "address": "Bahnhofstrasse 40 · 8001 Zürich", "website": "kellerpartner.ch", "place": "Zürich"},
        },
        sort_index=5,
    ),
    DesignExample(
        "atlas", "protocol", _protocol_corporate,
        {
            "colors": _colors("#17325C", "#5A6B82", "#17325C", "#17325C", text="#18202B", muted="#5A6B82", surface="#EEF2F8", border="#D9DFE7", table_header_background="#EEF2F8", table_header_text="#17325C"),
            "typography": _typography("noto_sans"),
            "appearance": {"base": "atlas"},
            "organization": {"name": "Aarwerk AG", "address": "Industriestrasse 12 · 5000 Aarau", "website": "aarwerk.ch", "place": "Aarau"},
        },
        images={"logo": "corporate-mark.png"},
        sort_index=6,
    ),
)

EXAMPLE_KEYS: tuple[str, ...] = tuple(item.key for item in EXAMPLES)


def get_example(example_key: str) -> DesignExample | None:
    return next((item for item in EXAMPLES if item.key == example_key), None)


def build_example_content(example: DesignExample) -> TemplateContent:
    return TemplateContent.model_validate(example.build())


def example_tokens(example: DesignExample, images: dict[str, str] | None = None) -> BrandTokens:
    """CD des Beispiels; ``images`` setzt die Asset-IDs der importierten Beispielbilder. Der
    Seitenaufbau (Überschriften, Tabellen, Ecken …) kommt aus dem Design (APPEARANCE_BASES),
    ``tokens["layout"]`` enthält nur Abweichungen davon."""
    layout = {**APPEARANCE_BASES[example.key]["layout"], **example.tokens.get("layout", {})}
    raw = {**example.tokens, "layout": layout, "assets": dict(images or {})}
    return BrandTokens.model_validate(raw)


def thumbnail_path(example: DesignExample) -> Path:
    return ASSET_DIR / "thumbnails" / f"{example.key}.png"


async def import_example(  # loop-ok: nur im Worker-Thread (core/offload.run_coroutine_in_thread)
    db: Session, tenant_id: int, example: DesignExample, *, name: str, user_id: int | None
):
    """Beispiel in den Mandanten holen: Beispielbilder als Assets, eigenes Brand-Profil (nie
    Standardprofil) und eine damit verknüpfte Vorlage mit Entwurf. Kein Commit."""
    from app.documents import assets as asset_service
    from app.documents import brand_service, template_service

    images: dict[str, str] = {}
    for slot, filename in example.images.items():
        asset = await asset_service.create_asset(
            db, tenant_id, kind="image", filename=filename, content=(ASSET_DIR / filename).read_bytes(), user_id=user_id,
            category="logo" if slot == "logo" else "graphic", name=name,
        )
        images[slot] = str(asset.public_id)
    # Ohne Standardprofil würde das Beispiel-CD zum Standard aller Dokumente des Vereins.
    brand_service.ensure_default_brand(db, tenant_id)
    brand = brand_service.create_brand(db, tenant_id, name=name, tokens=example_tokens(example, images), user_id=user_id)
    template, revision = template_service.create_template(
        db, tenant_id, name=name, document_type=example.document_type, content=build_example_content(example), brand_id=brand.public_id, user_id=user_id,
    )
    return template, brand
