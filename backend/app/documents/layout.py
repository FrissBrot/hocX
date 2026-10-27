"""Deklaratives Layoutschema des Document Studio (versioniert über ``LAYOUT_SCHEMA_VERSION``).

Eine Dokumentvorlage ist ein JSON-Baum aus Knoten (``Node``). Der Baum enthält nie Code: Texte
sind Text, Datenbindungen sind Pfade aus der Bindungs-Registry (bindings.py), Bedingungen sind
deklarative Ausdrücke (conditions.py), Farben und Schriften sind Brand-Referenzen
(``$brand.primary``) oder geprüfte Literale. Der Layout-Compiler (compiler.py) löst den Baum
mit Brand und Daten auf und übergibt das Ergebnis an Typst; Benutzereingaben werden dort
ausschliesslich als Inhalt eingesetzt.

Masseinheiten: Längen in mm, Linienstärken und Schriftgrössen in pt. Breiten als
``auto`` / ``fill`` / ``<n>mm`` / ``<n>%`` / ``<n>fr``.

Neuer Knotentyp: Modell hier (``Node``-Union + ``NODE_MODELS``), Editor-Metadaten in
components.py, Kompilierung in compiler.py, Darstellung in typst/layout.typ, Texte in
frontend/messages/<locale>/documentStudio.json. ``scripts/check-document-catalog.py`` prüft
die Vollständigkeit.
"""
from __future__ import annotations

import json
import uuid
from typing import Annotated, Any, Iterator, Literal, Union, get_args

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator, model_validator

from app.documents.appearance import AppearanceBase, ElementAppearance, validate_appearance_elements, validate_block_overrides
from app.documents.conditions import Condition

LAYOUT_SCHEMA_VERSION = 1

MAX_NODES = 2000
MAX_DEPTH = 14
# Obergrenze für einen gesendeten Layoutbaum (serialisiertes JSON). Knotenzahl und Tiefe allein
# begrenzen die Grösse nicht (lange Texte, Übersetzungen, Tabellenzellen, Komponentenparameter);
# jeder Autosave schreibt den ganzen Baum, Vorschau und Thumbnail rendern ihn. Bewusst nur für
# eingehende Anfragen (LayoutJson) und nicht als Feldgrenze im Schema: gespeicherte Revisionen
# und die Rezept-Übernahme der Migration 0118 laufen durch dasselbe Schema und dürfen durch
# eine nachträglich engere Grenze nicht unlesbar werden.
MAX_CONTENT_BYTES = 2_000_000

NODE_ID_PATTERN = r"^[A-Za-z0-9_-]{1,40}$"
# Farbe: Hex-Literal oder Brand-Referenz ($brand.primary, $brand.custom.<name>, $brand.status.success)
COLOR_PATTERN = r"^(#[0-9A-Fa-f]{6}|\$brand\.[a-z_]{2,30}(\.[a-z0-9_]{1,40})?)$"
# Schrift: Brand-Rolle oder Familienname einer verfügbaren Schrift (geprüft beim Kompilieren)
FONT_PATTERN = r"^(\$brand\.font\.(body|heading|mono)|[A-Za-z0-9 ._-]{1,80})$"
LENGTH_PATTERN = r"^(auto|fill|\d{1,4}(\.\d{1,2})?(mm|%|fr))$"
# Bindungspfad (bindings.py), z. B. protocol.date oder item.name
BINDING_PATTERN = r"^[a-z][a-z0-9_]{0,40}(\.[a-z0-9_]{1,40}){0,4}$"

ColorRef = Annotated[str, Field(pattern=COLOR_PATTERN, max_length=80)]
FontRef = Annotated[str, Field(pattern=FONT_PATTERN, max_length=80)]
Length = Annotated[str, Field(pattern=LENGTH_PATTERN)]
BindingPath = Annotated[str, Field(pattern=BINDING_PATTERN, max_length=200)]
NodeId = Annotated[str, Field(pattern=NODE_ID_PATTERN)]
Mm = Annotated[float, Field(ge=0, le=1000)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ── Stil ─────────────────────────────────────────────────────────────────────


class Spacing(_Strict):
    top: Mm = 0
    right: Mm = 0
    bottom: Mm = 0
    left: Mm = 0


class Border(_Strict):
    width: float = Field(0.5, ge=0, le=10)
    color: ColorRef = "$brand.border"
    style: Literal["solid", "dashed", "dotted"] = "solid"
    sides: list[Literal["top", "right", "bottom", "left"]] = Field(default_factory=lambda: ["top", "right", "bottom", "left"], max_length=4)
    radius: float = Field(0, ge=0, le=30)


class TextStyle(_Strict):
    """Textauszeichnung. ``None`` = vom Elternknoten bzw. aus dem Brand-Profil geerbt."""

    font: FontRef | None = None
    size: float | None = Field(None, ge=4, le=96)
    weight: Literal["regular", "medium", "bold"] | None = None
    italic: bool | None = None
    color: ColorRef | None = None
    align: Literal["left", "center", "right", "justify"] | None = None
    line_height: float | None = Field(None, ge=0.8, le=3)
    letter_spacing: float | None = Field(None, ge=-2, le=10)
    transform: Literal["none", "upper", "lower"] | None = None


class BoxStyle(_Strict):
    width: Length = "auto"
    height: Length | None = None
    padding: Spacing = Field(default_factory=Spacing)
    margin_top: Mm = 0
    margin_bottom: Mm = 0
    background: ColorRef | None = None
    border: Border | None = None
    # Ausrichtung des Knotens im verfügbaren Platz
    align: Literal["left", "center", "right"] = "left"
    text: TextStyle = Field(default_factory=TextStyle)


class Frame(_Strict):
    """Position auf einer absoluten Ebene (mm ab der linken oberen Ecke der Ebene)."""

    x: Mm = 0
    y: Mm = 0
    width: Mm | None = None
    height: Mm | None = None
    rotate: float = Field(0, ge=-180, le=180)
    opacity: float = Field(1, ge=0, le=1)
    # Ausrichtung des Inhalts in der Rahmenhöhe, z. B. Fussbild bündig am Seitenende
    valign: Literal["top", "middle", "bottom"] = "top"


class RepeatSpec(_Strict):
    """Wiederholt den Knoten für jedes Element einer Listenbindung. Innerhalb sind die
    Felder des Elements als ``item.<feld>`` bindbar."""

    source: BindingPath
    limit: int = Field(200, ge=1, le=1000)
    # Text bei leerer Liste (literal); None = Knoten entfällt
    empty_text: str | None = Field(None, max_length=300)


# ── Inhalt ───────────────────────────────────────────────────────────────────


class FormatSpec(_Strict):
    """Formatierung eines gebundenen Werts. ``date``: short = TT.MM.JJJJ (fest wie in der App),
    long = ausgeschriebener Monat in der Dokumentsprache, weekday = mit Wochentag."""

    date: Literal["short", "long", "weekday", "month_year", "year"] = "short"
    number: Literal["integer", "decimal", "percent", "amount"] = "integer"
    transform: Literal["none", "upper", "lower"] = "none"
    prefix: str = Field("", max_length=60)
    suffix: str = Field("", max_length=60)


class InlineText(_Strict):
    t: Literal["text"] = "text"
    v: str = Field("", max_length=20_000)
    b: bool = False
    i: bool = False


class InlineBinding(_Strict):
    t: Literal["bind"] = "bind"
    path: BindingPath
    format: FormatSpec = Field(default_factory=FormatSpec)
    # Ersatztext, wenn der Wert leer ist
    fallback: str = Field("", max_length=300)
    b: bool = False
    i: bool = False


class InlineKey(_Strict):
    """Fester Text in der Dokumentsprache (Schlüssel aus documentPdf, z. B. ``docType.protocol``).
    So sind Systemvorlagen in jeder Sprache ohne Übersetzung im Layout nutzbar."""

    t: Literal["key"] = "key"
    key: str = Field(..., pattern=r"^[A-Za-z0-9_]{1,40}(\.[A-Za-z0-9_]{1,40}){1,3}$")
    b: bool = False
    i: bool = False


class InlineBreak(_Strict):
    t: Literal["br"] = "br"


Inline = Annotated[Union[InlineText, InlineBinding, InlineKey, InlineBreak], Field(discriminator="t")]


class TextContent(_Strict):
    """Mehrsprachiger Text: ``default`` gilt immer, ``translations`` je Sprache (optional)."""

    default: list[Inline] = Field(default_factory=list, max_length=200)
    translations: dict[str, list[Inline]] = Field(default_factory=dict)

    @field_validator("translations")
    @classmethod
    def _known_languages(cls, value: dict[str, list[Any]]) -> dict[str, list[Any]]:
        from app.core.locale_config_generated import SUPPORTED_LOCALES

        unknown = [key for key in value if key not in SUPPORTED_LOCALES]
        if unknown:
            raise ValueError(f"unbekannte Sprache: {unknown[0]}")
        return value


def plain_text(value: str) -> TextContent:
    return TextContent(default=[InlineText(v=value)])


def bound_text(path: str, **format_kwargs: Any) -> TextContent:
    return TextContent(default=[InlineBinding(path=path, format=FormatSpec(**format_kwargs))])


def key_text(key: str) -> TextContent:
    return TextContent(default=[InlineKey(key=key)])


# ── Knoten ───────────────────────────────────────────────────────────────────


def new_node_id() -> str:
    return uuid.uuid4().hex[:12]


class NodeBase(_Strict):
    id: NodeId = Field(default_factory=new_node_id)
    # Anzeigename in der Ebenenansicht
    name: str | None = Field(None, max_length=120)
    style: BoxStyle = Field(default_factory=BoxStyle)
    # Abschalten ohne Löschen (Modus «Einfach»: Abschnitte aktivieren/deaktivieren)
    enabled: bool = True
    visible_if: Condition | None = None
    keep_together: bool = False
    break_before: bool = False
    repeat: RepeatSpec | None = None
    # Position auf einer absoluten Ebene (nur Kinder von absolute_layer)
    frame: Frame | None = None
    # Gesperrt: im Designer nicht verschieb- oder löschbar (z. B. Pflichtteile einer Systemvorlage)
    locked: bool = False


class ChildrenMixin(_Strict):
    children: list["Node"] = Field(default_factory=list, max_length=500)


class StackNode(NodeBase, ChildrenMixin):
    """Kinder untereinander (Standardfluss, bricht über Seiten um)."""

    type: Literal["stack"] = "stack"
    gap: Mm = 3


class ColumnNode(NodeBase, ChildrenMixin):
    """Spalte innerhalb einer Zeile; Breite über ``style.width``."""

    type: Literal["column"] = "column"
    gap: Mm = 3


class RowNode(NodeBase, ChildrenMixin):
    """Kinder nebeneinander. Breiten aus ``style.width`` der Kinder (auto/fill/mm/%/fr)."""

    type: Literal["row"] = "row"
    gap: Mm = 5
    valign: Literal["top", "middle", "bottom"] = "top"


class GridNode(NodeBase, ChildrenMixin):
    type: Literal["grid"] = "grid"
    columns: int = Field(2, ge=1, le=6)
    column_widths: list[Length] = Field(default_factory=list, max_length=6)
    gap_x: Mm = 5
    gap_y: Mm = 4


class ContainerNode(NodeBase, ChildrenMixin):
    """Box mit Hintergrund, Rahmen und Innenabstand."""

    type: Literal["container"] = "container"
    gap: Mm = 3
    # Container nicht über Seiten umbrechen
    breakable: bool = True


class SectionNode(NodeBase, ChildrenMixin):
    """Gliederungsabschnitt mit optionalem Titel (Inhaltsverzeichnis, Nummerierung)."""

    type: Literal["section"] = "section"
    title: TextContent | None = None
    level: int = Field(1, ge=1, le=4)
    outlined: bool = True
    gap: Mm = 3


class TextNode(NodeBase):
    type: Literal["text"] = "text"
    role: Literal["paragraph", "title", "subtitle", "heading", "caption", "label", "small"] = "paragraph"
    # Nur role=heading: Gliederungsebene (Inhaltsverzeichnis)
    level: int = Field(1, ge=1, le=4)
    content: TextContent = Field(default_factory=TextContent)


class RichTextNode(NodeBase):
    """Formatierter Fliesstext (Markdown-Untermenge, siehe richtext.py)."""

    type: Literal["rich_text"] = "rich_text"
    markdown: str = Field("", max_length=50_000)
    translations: dict[str, str] = Field(default_factory=dict)


class AssetImageSource(_Strict):
    kind: Literal["asset"] = "asset"
    asset_id: uuid.UUID | None = None


class BindingImageSource(_Strict):
    kind: Literal["binding"] = "binding"
    # z. B. brand.logo, brand.logo_alt, brand.letterhead
    path: BindingPath = "brand.logo"


ImageSource = Annotated[Union[AssetImageSource, BindingImageSource], Field(discriminator="kind")]


class ImageNode(NodeBase):
    type: Literal["image"] = "image"
    source: ImageSource = Field(default_factory=BindingImageSource)
    fit: Literal["contain", "cover", "stretch"] = "contain"
    caption: TextContent | None = None


class DividerNode(NodeBase):
    type: Literal["divider"] = "divider"
    thickness: float = Field(0.6, ge=0.1, le=10)
    color: ColorRef = "$brand.border"
    line_style: Literal["solid", "dashed", "dotted"] = "solid"
    length: Length = "fill"


class SpacerNode(NodeBase):
    type: Literal["spacer"] = "spacer"
    size: Mm = 6
    # Flexibler Abstand: füllt den Rest der Seite (z. B. Fussbereich einer Titelseite)
    flexible: bool = False


class TableColumnSpec(_Strict):
    id: NodeId = Field(default_factory=new_node_id)
    header: TextContent = Field(default_factory=TextContent)
    width: Length = "auto"
    align: Literal["left", "center", "right"] = "left"
    # Gebundene Tabelle: Feld des Listenelements (item.<feld>) bzw. Inhalt der Zelle
    cell: TextContent = Field(default_factory=TextContent)


class TableNode(NodeBase):
    """Tabelle mit festen Zeilen oder einer Zeile pro Element einer Listenbindung."""

    type: Literal["table"] = "table"
    columns: list[TableColumnSpec] = Field(default_factory=list, max_length=12)
    # Feste Zeilen (nur ohne ``source``): Zellen als Text
    rows: list[list[str]] = Field(default_factory=list, max_length=500)
    source: BindingPath | None = None
    limit: int = Field(500, ge=1, le=2000)
    show_header: bool = True
    repeat_header: bool = True
    zebra: bool | None = None
    empty_text: str | None = Field(None, max_length=300)


class ListNode(NodeBase):
    type: Literal["list"] = "list"
    marker: Literal["bullet", "number", "none"] = "bullet"
    items: list[str] = Field(default_factory=list, max_length=300)
    source: BindingPath | None = None
    item: TextContent = Field(default_factory=TextContent)
    limit: int = Field(300, ge=1, le=2000)


class DataBlockNode(NodeBase):
    """Fachkomponente aus dem Block-Katalog (catalog.py), z. B. Traktanden, Aufgaben, Finanzen.
    ``params`` werden gegen das Parameterschema der Komponente geprüft."""

    type: Literal["data_block"] = "data_block"
    component: str = Field(..., max_length=60)
    params: dict[str, Any] = Field(default_factory=dict)
    title: TextContent | None = None
    # none = ohne eigenen Titel, auto = Name der Komponente in der Dokumentsprache, custom = ``title``
    title_mode: Literal["none", "auto", "custom"] = "none"
    level: int = Field(1, ge=1, le=4)
    hide_if_empty: bool = True
    # Darstellung dieses Blocks abweichend vom Brand-Profil (Elementart → Variante/Ecken)
    appearance: dict[str, ElementAppearance] = Field(default_factory=dict)
    # Darstellung einzelner Bausteine (nur «Protokollinhalt» einer Gestaltung, die einer
    # Sitzungsvorlage gehört): Baustein-Schlüssel (appearance.block_source) → Elementart →
    # Variante/Ecken, über ``appearance`` gelegt
    block_appearance: dict[str, dict[str, ElementAppearance]] = Field(default_factory=dict)

    @field_validator("appearance")
    @classmethod
    def _known_appearance(cls, value: dict[str, ElementAppearance]) -> dict[str, ElementAppearance]:
        return validate_appearance_elements(value, allow_brand_only=False)

    @field_validator("block_appearance")
    @classmethod
    def _known_block_appearance(cls, value: dict[str, dict[str, ElementAppearance]]) -> dict[str, dict[str, ElementAppearance]]:
        return validate_block_overrides(value)


class PageBreakNode(NodeBase):
    type: Literal["page_break"] = "page_break"
    # Seitenvorlage ab dem Umbruch (z. B. Querformat-Anhang); None = Standard
    master: NodeId | None = None


class HeaderNode(NodeBase, ChildrenMixin):
    type: Literal["header"] = "header"
    gap: Mm = 1.5


class FooterNode(NodeBase, ChildrenMixin):
    type: Literal["footer"] = "footer"
    gap: Mm = 1.5


class AbsoluteLayerNode(NodeBase, ChildrenMixin):
    """Ebene mit frei positionierten Kindern (``frame``). ``anchor=page``: relativ zur Seite
    (Deckblatt, Hintergrund), ``flow``: Fläche mit fester Höhe im Textfluss."""

    type: Literal["absolute_layer"] = "absolute_layer"
    anchor: Literal["page", "flow"] = "flow"
    height: Mm = 60


class PageNumberNode(NodeBase):
    type: Literal["page_number"] = "page_number"
    format: Literal["page", "page_of"] = "page_of"


class TocNode(NodeBase):
    type: Literal["toc"] = "toc"
    depth: int = Field(2, ge=1, le=4)
    show_title: bool = True
    density: Literal["normal", "compact", "very_compact"] = "normal"


class QrCodeNode(NodeBase):
    type: Literal["qr_code"] = "qr_code"
    target: Literal["verify", "url", "protocol"] = "verify"
    url: str | None = Field(None, max_length=1000)
    size: Mm = 22
    caption: TextContent | None = None

    @field_validator("url")
    @classmethod
    def _http_only(cls, value: str | None) -> str | None:
        if value and not value.lower().startswith(("https://", "http://")):
            raise ValueError("URL muss mit http:// oder https:// beginnen")
        return value


class VerifyNoteNode(NodeBase):
    """Prüfvermerk der Echtheitsprüfung (URL, Kurz-ID, optional QR-Code)."""

    type: Literal["verify_note"] = "verify_note"
    show_url: bool = True
    show_id: bool = True
    show_qr: bool = False


class MetadataNode(NodeBase):
    """Angaben zum Dokument als Liste (Nummer, Datum, Status, Version, Ort)."""

    type: Literal["metadata"] = "metadata"
    fields: list[Literal["number", "date", "status", "version", "place", "type", "organization"]] = Field(
        default_factory=lambda: ["number", "date", "status", "version"], max_length=7
    )
    layout: Literal["list", "inline"] = "list"


class WatermarkNode(NodeBase):
    """Wasserzeichen (in Seitenvorlagen). Text leer = «Entwurf» in der Dokumentsprache."""

    type: Literal["watermark"] = "watermark"
    text: TextContent | None = None
    asset_id: uuid.UUID | None = None
    angle: float = Field(-35, ge=-90, le=90)
    size: float = Field(96, ge=8, le=300)
    color: ColorRef = "$brand.watermark"
    # draft = nur bei Entwürfen (nicht abgeschlossene Protokolle), always = immer
    when: Literal["draft", "always"] = "draft"


class ComponentRefNode(NodeBase):
    """Verweis auf eine wiederverwendbare Komponente des Mandanten (document_component).
    Der Compiler setzt deren gespeicherten Knoten ein (mandantengebunden)."""

    type: Literal["component_ref"] = "component_ref"
    component_id: uuid.UUID


Node = Annotated[
    Union[
        StackNode,
        RowNode,
        ColumnNode,
        GridNode,
        ContainerNode,
        SectionNode,
        TextNode,
        RichTextNode,
        ImageNode,
        DividerNode,
        SpacerNode,
        TableNode,
        ListNode,
        DataBlockNode,
        PageBreakNode,
        HeaderNode,
        FooterNode,
        AbsoluteLayerNode,
        PageNumberNode,
        TocNode,
        QrCodeNode,
        VerifyNoteNode,
        MetadataNode,
        WatermarkNode,
        ComponentRefNode,
    ],
    Field(discriminator="type"),
]

for _model in (StackNode, RowNode, ColumnNode, GridNode, ContainerNode, SectionNode, HeaderNode, FooterNode, AbsoluteLayerNode):
    _model.model_rebuild()

NODE_MODELS: dict[str, type[NodeBase]] = {model.model_fields["type"].default: model for model in get_args(get_args(Node)[0])}
CONTAINER_TYPES = frozenset(name for name, model in NODE_MODELS.items() if "children" in model.model_fields)
# Knoten, die nur in Seitenvorlagen (Kopf, Fuss, Hintergrund) vorkommen dürfen
MASTER_ONLY_TYPES = frozenset({"header", "footer", "watermark"})


# ── Seite und Vorlage ────────────────────────────────────────────────────────

PAPER_SIZES_MM: dict[str, tuple[float, float]] = {
    "A3": (297, 420),
    "A4": (210, 297),
    "A5": (148, 210),
    "Letter": (215.9, 279.4),
    "Legal": (215.9, 355.6),
}


class PageSetup(_Strict):
    size: Literal["A3", "A4", "A5", "Letter", "Legal", "custom"] = "A4"
    width: float = Field(210, ge=50, le=1200)
    height: float = Field(297, ge=50, le=1200)
    orientation: Literal["portrait", "landscape"] = "portrait"
    margins: Spacing = Field(default_factory=lambda: Spacing(top=22, right=20, bottom=22, left=20))
    columns: int = Field(1, ge=1, le=3)
    column_gap: Mm = 8

    def dimensions_mm(self) -> tuple[float, float]:
        width, height = PAPER_SIZES_MM.get(self.size, (self.width, self.height))
        if self.orientation == "landscape":
            width, height = max(width, height), min(width, height)
        else:
            width, height = min(width, height), max(width, height)
        return width, height


class PageMaster(_Strict):
    """Seitenvorlage: Kopf, Fuss und Hintergrund (z. B. Briefpapier, Wasserzeichen)."""

    id: NodeId = "default"
    name: str = Field("", max_length=120)
    header: HeaderNode | None = None
    footer: FooterNode | None = None
    background: list[Node] = Field(default_factory=list, max_length=20)
    # Abweichende Seiteneinstellungen (z. B. Querformat für einen Anhang)
    orientation: Literal["portrait", "landscape"] | None = None
    margins: Spacing | None = None


class TitlePage(_Strict):
    enabled: bool = False
    # Zusätzliche Bedingung (z. B. Brand-Standard «Titelseite»)
    visible_if: Condition | None = None
    # Seitenvorlage der Titelseite; None = ohne Kopf und Fuss
    master: NodeId | None = None
    background: ColorRef | None = None
    children: list[Node] = Field(default_factory=list, max_length=100)


class WatermarkSettings(_Strict):
    mode: Literal["off", "draft", "always"] = "draft"


class BrandOverrides(_Strict):
    """Abweichungen dieser Vorlage vom Brand-Profil (Modus «Einfach»: Logo, Farben, Schriften).
    Leer = Wert aus dem Brand-Profil. Gilt nur für diese Vorlage."""

    primary: Annotated[str, Field(pattern=r"^#[0-9A-Fa-f]{6}$")] | None = None
    secondary: Annotated[str, Field(pattern=r"^#[0-9A-Fa-f]{6}$")] | None = None
    accent: Annotated[str, Field(pattern=r"^#[0-9A-Fa-f]{6}$")] | None = None
    heading: Annotated[str, Field(pattern=r"^#[0-9A-Fa-f]{6}$")] | None = None
    logo_asset_id: uuid.UUID | None = None
    body_font: Literal["inter", "liberation_sans", "liberation_serif", "noto_sans"] | None = None
    heading_font: Literal["inter", "liberation_sans", "liberation_serif", "noto_sans"] | None = None
    base_size: float | None = Field(None, ge=7, le=16)
    # Stil (Design als Grundstil, appearance.APPEARANCE_BASES) nur für diese Vorlage
    appearance_base: AppearanceBase | None = None
    # Kopf- und Fusszeile nur für diese Vorlage (sonst BrandHeaderFooter des Profils)
    header_show_logo: bool | None = None
    header_show_title: bool | None = None
    header_show_date: bool | None = None
    footer_show_number: bool | None = None
    footer_show_pages: bool | None = None
    footer_text: str | None = Field(None, max_length=300)

    def is_empty(self) -> bool:
        return not any(value is not None for value in self.model_dump().values())


class TemplateSettings(_Strict):
    # Seitenvorlage der ersten Inhaltsseite (abweichende erste Seite); None = default_master
    first_page_master: NodeId | None = None
    default_master: NodeId = "default"
    # None = Brand-Standard (brand.layout.heading_numbering)
    heading_numbering: bool | None = None
    justify: bool = False
    hyphenate: bool = True
    # Feste Dokumentsprache der Vorlage; None = Sprache des Exports
    language: str | None = Field(None, max_length=10)
    # Prüfvermerk automatisch am Dokumentende, falls die Vorlage keinen eigenen enthält
    auto_verify_note: bool = True
    brand_overrides: BrandOverrides = Field(default_factory=BrandOverrides)


class TemplateContent(_Strict):
    """Gesamte Layoutstruktur einer Vorlagenrevision (gespeichert als JSONB)."""

    schema_version: Literal[1] = LAYOUT_SCHEMA_VERSION
    page: PageSetup = Field(default_factory=PageSetup)
    masters: list[PageMaster] = Field(default_factory=lambda: [PageMaster()], min_length=1, max_length=8)
    title_page: TitlePage = Field(default_factory=TitlePage)
    body: list[Node] = Field(default_factory=list, max_length=500)
    settings: TemplateSettings = Field(default_factory=TemplateSettings)

    @model_validator(mode="after")
    def _check_structure(self) -> "TemplateContent":
        validate_structure(self)
        return self

    def master(self, master_id: str | None) -> PageMaster | None:
        return next((item for item in self.masters if item.id == master_id), None)


# ── Strukturprüfung ──────────────────────────────────────────────────────────


class LayoutValidationError(ValueError):
    """Strukturfehler mit Knoten-ID (für Fehlerhinweise am Element im Designer)."""

    def __init__(self, code: str, node_id: str | None = None, detail: str = "") -> None:
        super().__init__(f"{code}{f' ({node_id})' if node_id else ''}{f': {detail}' if detail else ''}")
        self.code = code
        self.node_id = node_id
        self.detail = detail


def layout_error_of(exc: Exception) -> "LayoutValidationError | None":
    """Strukturfehler aus einer Pydantic-ValidationError (der Validator läuft im Modell)."""
    if isinstance(exc, LayoutValidationError):
        return exc
    errors = getattr(exc, "errors", None)
    if callable(errors):
        for item in errors():
            error = (item.get("ctx") or {}).get("error")
            if isinstance(error, LayoutValidationError):
                return error
    return None


def iter_nodes(nodes: list[Any], depth: int = 0) -> Iterator[tuple[Any, int]]:
    for node in nodes:
        yield node, depth
        children = getattr(node, "children", None)
        if children:
            yield from iter_nodes(children, depth + 1)


def all_node_lists(content: TemplateContent) -> list[tuple[str, list[Any]]]:
    lists: list[tuple[str, list[Any]]] = [("body", content.body), ("title_page", content.title_page.children)]
    for master in content.masters:
        lists.append((f"master:{master.id}", [node for node in (master.header, master.footer) if node is not None] + list(master.background)))
    return lists


def validate_structure(content: TemplateContent) -> None:
    """Eindeutige IDs, Tiefe, Anzahl, Knotentypen je Bereich und Seitenvorlagen-Referenzen."""
    master_ids = [master.id for master in content.masters]
    if len(set(master_ids)) != len(master_ids):
        raise LayoutValidationError("duplicateMaster")
    for reference in (content.settings.default_master, content.settings.first_page_master, content.title_page.master):
        if reference is not None and reference not in master_ids:
            raise LayoutValidationError("unknownMaster", detail=reference)
    seen: set[str] = set()
    total = 0
    for area, nodes in all_node_lists(content):
        for node, depth in iter_nodes(nodes):
            total += 1
            if total > MAX_NODES:
                raise LayoutValidationError("tooManyNodes", detail=str(MAX_NODES))
            if depth > MAX_DEPTH:
                raise LayoutValidationError("tooDeep", node.id)
            if node.id in seen:
                raise LayoutValidationError("duplicateId", node.id)
            seen.add(node.id)
            if area in ("body", "title_page") and node.type in MASTER_ONLY_TYPES:
                raise LayoutValidationError("masterOnly", node.id, node.type)
            if node.type == "page_break" and node.master is not None and node.master not in master_ids:
                raise LayoutValidationError("unknownMaster", node.id, node.master)
            if node.type == "absolute_layer":
                for child in node.children:
                    if child.frame is None:
                        child.frame = Frame()
            if node.type == "table" and node.source is None and node.rows:
                width = len(node.columns)
                if any(len(row) > width for row in node.rows):
                    raise LayoutValidationError("tableRowTooWide", node.id)


def check_content_size(raw: Any) -> Any:
    """Gesendeten Layoutbaum (bzw. Komponentenknoten) vor der Schemaprüfung auf
    ``MAX_CONTENT_BYTES`` begrenzen."""
    if raw is not None and len(json.dumps(raw, ensure_ascii=False, separators=(",", ":")).encode()) > MAX_CONTENT_BYTES:
        raise LayoutValidationError("contentTooLarge", detail=str(MAX_CONTENT_BYTES))
    return raw


# Für Request-Modelle: rohes Layout-JSON mit Grössengrenze
LayoutJson = Annotated[dict[str, Any], AfterValidator(check_content_size)]


def parse_content(raw: dict[str, Any] | None) -> TemplateContent:
    """JSON → TemplateContent inkl. Migration älterer Schemaversionen (layout_migrations.py)."""
    from app.documents.layout_migrations import migrate_content

    return TemplateContent.model_validate(migrate_content(raw or {}))


def content_json(content: TemplateContent) -> dict[str, Any]:
    return content.model_dump(mode="json", exclude_none=False)
