"""Dokumentmodell der Dokument-Engine (versioniert über ``SCHEMA_VERSION``).

Das Modell ist die einzige Schnittstelle zwischen Python und Typst: Provider füllen es, der
Hausstil rendert es. Es enthält nie Typst-Code. Fliesstext ist ein strukturierter
Rich-Text-Baum (``RichBlock``/``RichInline``), Tabellen sind ``TableData``. Status,
Spaltenköpfe und Leertexte stehen als Codes bzw. Schlüssel im Modell; übersetzt wird erst im
Hausstil über ``Document.strings``. Dadurch bleibt der Inhalt sprachneutral und der
Inhalts-Hash (siehe hashing.py) ändert sich bei einem reinen Sprachwechsel nicht.

Neuer Block-Typ: Modell hier, Parameter und Provider in catalog.py/providers, Basis-Komponente
in styles/base/blocks.typ, Texte in frontend/messages/<locale>/documentPdf.json. Der Check
``scripts/check-document-catalog.py`` prüft die Vollständigkeit.
"""
from __future__ import annotations

from typing import Annotated, Any, Literal, Union, get_args

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = 1

# Farbwerte im Modell sind immer #RRGGBB (Tag-Farben, Stil-Tokens). Andere Werte verwirft der
# Provider, bevor sie ins Modell gelangen.
HEX_COLOR_PATTERN = r"^#[0-9A-Fa-f]{6}$"
HexColor = Annotated[str, Field(pattern=HEX_COLOR_PATTERN)]

# Bedeutungsfarben (Statuspunkte, Diagrammreihen, Zeilen). Die Farbwerte kommen aus
# design/tokens.css über styles/_tokens.typ.
Tone = Literal["default", "muted", "success", "warning", "danger", "info", "neutral", "primary", "secondary"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ── Rich Text ────────────────────────────────────────────────────────────────


class TextSpan(_Strict):
    """Text mit Auszeichnungen. ``href`` nur http(s)/mailto (siehe richtext.safe_href)."""

    t: Literal["text"] = "text"
    v: str
    b: bool = False
    i: bool = False
    s: bool = False
    code: bool = False
    href: str | None = None
    # Fester Text (Schlüssel aus documentPdf), z. B. ein Status in einer Matrixzelle. Ersetzt
    # ``v`` in der Darstellung; so bleibt der Inhalt sprachneutral.
    key: str | None = None


class LineBreak(_Strict):
    t: Literal["br"] = "br"


RichInline = Annotated[Union[TextSpan, LineBreak], Field(discriminator="t")]


class Paragraph(_Strict):
    t: Literal["p"] = "p"
    c: list[RichInline] = Field(default_factory=list)


class Heading(_Strict):
    t: Literal["h"] = "h"
    level: int = Field(1, ge=1, le=3)
    c: list[RichInline] = Field(default_factory=list)


class BulletList(_Strict):
    t: Literal["ul"] = "ul"
    items: list[list["RichBlock"]] = Field(default_factory=list)


class OrderedList(_Strict):
    t: Literal["ol"] = "ol"
    start: int = 1
    items: list[list["RichBlock"]] = Field(default_factory=list)


class Quote(_Strict):
    t: Literal["quote"] = "quote"
    c: list["RichBlock"] = Field(default_factory=list)


class CodeBlock(_Strict):
    t: Literal["code"] = "code"
    v: str = ""


class InlineTable(_Strict):
    """Kleine Tabelle innerhalb von Rich Text (z. B. Formular in einer Matrixzelle).
    Wird nur von Providern erzeugt, nie aus Benutzer-Markdown."""

    t: Literal["table"] = "table"
    header: list[str] | None = None
    rows: list[list[str]] = Field(default_factory=list)


RichBlock = Annotated[
    Union[Paragraph, Heading, BulletList, OrderedList, Quote, CodeBlock, InlineTable],
    Field(discriminator="t"),
]

BulletList.model_rebuild()
OrderedList.model_rebuild()
Quote.model_rebuild()


def rich_is_empty(nodes: list[Any]) -> bool:
    """True, wenn ein Rich-Text-Baum keinen sichtbaren Text enthält."""
    for node in nodes or []:
        if isinstance(node, TextSpan):
            if node.v.strip() or node.key:
                return False
        elif isinstance(node, (Paragraph, Heading)):
            if not rich_is_empty(node.c):
                return False
        elif isinstance(node, (BulletList, OrderedList)):
            if any(not rich_is_empty(item) for item in node.items):
                return False
        elif isinstance(node, Quote):
            if not rich_is_empty(node.c):
                return False
        elif isinstance(node, CodeBlock):
            if node.v.strip():
                return False
        elif isinstance(node, InlineTable):
            if node.rows:
                return False
    return True


# ── Tabellen ─────────────────────────────────────────────────────────────────


class Tag(_Strict):
    label: str
    color: HexColor | None = None


class Cell(_Strict):
    """Tabellenzelle. ``k`` bestimmt die Darstellung:

    - ``text``: ``v`` als Text; ``amount``: ``v`` rechtsbündig (bereits formatiert)
    - ``status``: ``status`` als übersetztes Label mit farbigem Punkt
    - ``tags``: farbige Tags; ``rich``: Rich-Text-Baum; ``check``: leeres Kästchen/Häkchen
    - ``blank``: leere Fläche zum Ausfüllen (Unterschrift)
    """

    k: Literal["text", "amount", "status", "tags", "rich", "check", "blank"] = "text"
    v: str = ""
    status: str | None = None
    tags: list[Tag] = Field(default_factory=list)
    rich: list[RichBlock] = Field(default_factory=list)
    checked: bool = False
    tone: Tone = "default"
    strike: bool = False
    # Übersetzter Zusatz (Text-Schlüssel), z. B. «nächste Sitzung» hinter einem Fälligkeitsdatum
    note_key: str | None = None


class TableColumn(_Strict):
    """Spalte. Kopf ist entweder ein Text-Schlüssel (``label_key``, übersetzt) oder ein
    literaler Benutzertext (``label``, z. B. Listen-Spaltentitel)."""

    key: str
    label: str | None = None
    label_key: str | None = None
    align: Literal["left", "right", "center"] = "left"
    # auto = nach Inhalt, fill = Restbreite, narrow = so schmal wie möglich, wide = doppelter Anteil
    width: Literal["auto", "fill", "narrow", "wide"] = "auto"


class TableRow(_Strict):
    cells: list[Cell]
    muted: bool = False
    strong: bool = False


class TableGroup(_Strict):
    label: str | None = None
    label_key: str | None = None
    rows: list[TableRow] = Field(default_factory=list)
    subtotal: list[Cell] | None = None


class TableData(_Strict):
    columns: list[TableColumn]
    groups: list[TableGroup] = Field(default_factory=list)
    totals: list[Cell] | None = None
    show_header: bool = True

    def row_count(self) -> int:
        return sum(len(group.rows) for group in self.groups)


def table_from_rows(columns: list[TableColumn], rows: list[TableRow], **kwargs: Any) -> TableData:
    return TableData(columns=columns, groups=[TableGroup(rows=rows)] if rows else [], **kwargs)


# ── Blöcke ───────────────────────────────────────────────────────────────────


class BlockBase(_Strict):
    """Gemeinsame Felder aller Blöcke.

    ``hide_if_empty`` (Standard an): der Builder lässt leere Blöcke weg. Ist es aus, rendert
    der Hausstil den übersetzten Leertext (``empty.<type>``). ``empty`` setzt der Builder.
    ``level`` ist die Gliederungstiefe (1 = Abschnitt) für Titel und Inhaltsverzeichnis.
    """

    title: str | None = None
    # Fester Titel (Schlüssel aus documentPdf), wenn ``title`` leer ist, z. B. «Sitzungs-Todos».
    title_key: str | None = None
    hide_if_empty: bool = True
    level: int = Field(1, ge=1, le=4)
    empty: bool = False

    def is_empty(self) -> bool:  # pragma: no cover - jede Unterklasse überschreibt
        return False


# Struktur


class HeadingBlock(BlockBase):
    type: Literal["heading"] = "heading"
    text: str = ""

    def is_empty(self) -> bool:
        return not self.text.strip()


class RichTextBlock(BlockBase):
    type: Literal["richtext"] = "richtext"
    content: list[RichBlock] = Field(default_factory=list)

    def is_empty(self) -> bool:
        return rich_is_empty(self.content)


class StaticTextBlock(BlockBase):
    type: Literal["static_text"] = "static_text"
    content: list[RichBlock] = Field(default_factory=list)

    def is_empty(self) -> bool:
        return rich_is_empty(self.content)


class PageBreakBlock(BlockBase):
    type: Literal["page_break"] = "page_break"
    hide_if_empty: bool = False

    def is_empty(self) -> bool:
        return False


class TocBlock(BlockBase):
    type: Literal["toc"] = "toc"
    depth: int = Field(2, ge=1, le=4)
    hide_if_empty: bool = False

    def is_empty(self) -> bool:
        return False


class SpacerBlock(BlockBase):
    type: Literal["spacer"] = "spacer"
    size: Literal["s", "m", "l"] = "m"
    hide_if_empty: bool = False

    def is_empty(self) -> bool:
        return False


class DividerBlock(BlockBase):
    type: Literal["divider"] = "divider"
    hide_if_empty: bool = False

    def is_empty(self) -> bool:
        return False


# Protokoll


class ProtocolElementBlock(BlockBase):
    """Ein Protokollelement (Abschnitt) mit seinen Blöcken als ``children``."""

    type: Literal["protocol_element"] = "protocol_element"
    responsible: str | None = None
    children: list["Block"] = Field(default_factory=list)

    def is_empty(self) -> bool:
        return not self.children


class SessionDateBlock(BlockBase):
    type: Literal["session_date"] = "session_date"
    label: str | None = None
    date: str | None = None

    def is_empty(self) -> bool:
        return False


class SessionNotesBlock(BlockBase):
    type: Literal["session_notes"] = "session_notes"
    content: list[RichBlock] = Field(default_factory=list)

    def is_empty(self) -> bool:
        return rich_is_empty(self.content)


class FormRow(_Strict):
    label: str
    value: list[RichBlock] = Field(default_factory=list)


class FormBlock(BlockBase):
    type: Literal["form"] = "form"
    label_heading: str | None = None
    value_heading: str | None = None
    rows: list[FormRow] = Field(default_factory=list)

    def is_empty(self) -> bool:
        return not self.rows


class BulletListBlock(BlockBase):
    type: Literal["bullet_list"] = "bullet_list"
    items: list[str] = Field(default_factory=list)

    def is_empty(self) -> bool:
        return not any(item.strip() for item in self.items)


class MatrixBlock(BlockBase):
    """Matrix in Spaltengruppen (``tables``), Zellen als Rich Text."""

    type: Literal["matrix"] = "matrix"
    tables: list[TableData] = Field(default_factory=list)

    def is_empty(self) -> bool:
        return not any(table.row_count() for table in self.tables)


class EntryExitItem(_Strict):
    name: str
    date: str | None = None


class EntryExitBlock(BlockBase):
    type: Literal["entry_exit"] = "entry_exit"
    joins: list[EntryExitItem] = Field(default_factory=list)
    leaves: list[EntryExitItem] = Field(default_factory=list)

    def is_empty(self) -> bool:
        return not self.joins and not self.leaves


class ImageRef(_Strict):
    """Bild im Compile-Root. ``path`` erzeugt ausschliesslich der Renderer (assets/…)."""

    path: str = Field(pattern=r"^assets/[A-Za-z0-9_.-]+$")
    caption: str | None = None
    width_pt: float | None = None
    missing: bool = False


class ImageBlock(BlockBase):
    type: Literal["image"] = "image"
    image: ImageRef | None = None

    def is_empty(self) -> bool:
        return self.image is None


class ImageGalleryBlock(BlockBase):
    type: Literal["image_gallery"] = "image_gallery"
    images: list[ImageRef] = Field(default_factory=list)
    columns: int = Field(1, ge=1, le=3)

    def is_empty(self) -> bool:
        return not self.images


# Personen

AttendanceStatus = Literal["present", "late", "excused", "absent"]


class AttendanceEntry(_Strict):
    name: str
    status: AttendanceStatus | None = None


class AttendanceBlock(BlockBase):
    type: Literal["attendance"] = "attendance"
    entries: list[AttendanceEntry] = Field(default_factory=list)
    show_counts: bool = True

    def is_empty(self) -> bool:
        return not self.entries


class AttendanceMatrixBlock(BlockBase):
    """Mitglieder × Sitzungen. ``cells[i][j]`` ist der Status von ``people[i]`` in
    ``sessions[j]`` (None = nicht erfasst)."""

    type: Literal["attendance_matrix"] = "attendance_matrix"
    sessions: list[str] = Field(default_factory=list)
    people: list[str] = Field(default_factory=list)
    cells: list[list[AttendanceStatus | None]] = Field(default_factory=list)
    rates: list[str] = Field(default_factory=list)

    def is_empty(self) -> bool:
        return not self.people or not self.sessions


class MemberListBlock(BlockBase):
    type: Literal["member_list"] = "member_list"
    table: TableData

    def is_empty(self) -> bool:
        return self.table.row_count() == 0


class SignatureField(_Strict):
    label: str | None = None
    name: str | None = None


class SignatureFieldsBlock(BlockBase):
    type: Literal["signature_fields"] = "signature_fields"
    fields: list[SignatureField] = Field(default_factory=list)
    with_place_date: bool = True
    hide_if_empty: bool = False

    def is_empty(self) -> bool:
        return not self.fields


class AttendanceSheetBlock(BlockBase):
    """Präsenzliste zum Ausdrucken: Namen plus leere Unterschriftsspalten."""

    type: Literal["attendance_sheet"] = "attendance_sheet"
    names: list[str] = Field(default_factory=list)
    columns: list[str] = Field(default_factory=list)
    blank_rows: int = Field(0, ge=0, le=50)

    def is_empty(self) -> bool:
        return not self.names and self.blank_rows == 0


# Aufgaben, Termine, Listen


class TodoTableBlock(BlockBase):
    type: Literal["todo_table"] = "todo_table"
    table: TableData

    def is_empty(self) -> bool:
        return self.table.row_count() == 0


class EventTableBlock(BlockBase):
    type: Literal["event_table"] = "event_table"
    table: TableData

    def is_empty(self) -> bool:
        return self.table.row_count() == 0


class CalendarEvent(_Strict):
    title: str
    muted: bool = False
    color: HexColor | None = None
    cancelled: bool = False


class CalendarMonth(_Strict):
    year: int
    month: int = Field(ge=1, le=12)
    # Wochentag des Monatsersten, 0 = Montag
    first_weekday: int = Field(ge=0, le=6)
    days: int = Field(ge=28, le=31)
    # Tag (als String, JSON-Objektschlüssel) → Termine
    events: dict[str, list[CalendarEvent]] = Field(default_factory=dict)


class EventCalendarMonthBlock(BlockBase):
    type: Literal["event_calendar_month"] = "event_calendar_month"
    months: list[CalendarMonth] = Field(default_factory=list)

    def is_empty(self) -> bool:
        return not self.months


class AgendaItem(_Strict):
    date: str
    title: str
    detail: str | None = None
    tags: list[Tag] = Field(default_factory=list)
    muted: bool = False
    cancelled: bool = False


class AgendaMonth(_Strict):
    year: int
    month: int = Field(ge=1, le=12)
    items: list[AgendaItem] = Field(default_factory=list)


class EventAgendaBlock(BlockBase):
    type: Literal["event_agenda"] = "event_agenda"
    months: list[AgendaMonth] = Field(default_factory=list)

    def is_empty(self) -> bool:
        return not any(month.items for month in self.months)


class ListTableBlock(BlockBase):
    type: Literal["list_table"] = "list_table"
    table: TableData

    def is_empty(self) -> bool:
        return self.table.row_count() == 0


# Finanzen


class BalanceLine(_Strict):
    name: str
    amount: str
    currency: str = ""
    negative: bool = False
    as_of: str | None = None


class FinanceBalanceBlock(BlockBase):
    type: Literal["finance_balance"] = "finance_balance"
    balances: list[BalanceLine] = Field(default_factory=list)

    def is_empty(self) -> bool:
        return not self.balances


class FinanceTransactionsBlock(BlockBase):
    type: Literal["finance_transactions"] = "finance_transactions"
    table: TableData

    def is_empty(self) -> bool:
        return self.table.row_count() == 0


class FinesBlock(BlockBase):
    type: Literal["fines"] = "fines"
    table: TableData

    def is_empty(self) -> bool:
        return self.table.row_count() == 0


# Statistik


class KpiTile(_Strict):
    label: str | None = None
    label_key: str | None = None
    value: str
    hint: str | None = None
    tone: Tone = "default"


class KpiTilesBlock(BlockBase):
    type: Literal["kpi_tiles"] = "kpi_tiles"
    tiles: list[KpiTile] = Field(default_factory=list)

    def is_empty(self) -> bool:
        return not self.tiles


class ChartSeries(_Strict):
    label: str | None = None
    label_key: str | None = None
    values: list[float] = Field(default_factory=list)
    tone: Tone = "primary"


class ChartBlock(BlockBase):
    """Diagramm als Datenreihen; gezeichnet wird in Typst (Vektor, Hausfarben).

    ``categories`` sind die x-Werte (bzw. Segmente beim Donut). Bei ``donut`` hat genau eine
    Reihe einen Wert pro Kategorie; die Segmentfarben folgen ``category_tones``."""

    type: Literal["chart"] = "chart"
    kind: Literal["bar", "stacked_bar", "line", "donut"] = "bar"
    horizontal: bool = False
    categories: list[str] = Field(default_factory=list)
    # Optional pro Kategorie ein Text-Schlüssel (übersetzt) statt des literalen Labels
    category_keys: list[str | None] = Field(default_factory=list)
    category_tones: list[Tone] = Field(default_factory=list)
    series: list[ChartSeries] = Field(default_factory=list)
    value_format: Literal["number", "decimal", "amount"] = "number"

    def is_empty(self) -> bool:
        return not self.categories or not any(any(value for value in series.values) for series in self.series)


class StatTableBlock(BlockBase):
    type: Literal["stat_table"] = "stat_table"
    table: TableData

    def is_empty(self) -> bool:
        return self.table.row_count() == 0


# Sonstiges


class QrLinkBlock(BlockBase):
    """QR-Code als Modulmatrix (in Python erzeugt, in Typst als Vektor gezeichnet)."""

    type: Literal["qr_link"] = "qr_link"
    url: str
    label: str | None = None
    modules: list[str] = Field(default_factory=list)

    def is_empty(self) -> bool:
        return not self.modules


class GenericTableBlock(BlockBase):
    type: Literal["generic_table"] = "generic_table"
    table: TableData

    def is_empty(self) -> bool:
        return self.table.row_count() == 0


Block = Annotated[
    Union[
        HeadingBlock,
        RichTextBlock,
        StaticTextBlock,
        PageBreakBlock,
        TocBlock,
        SpacerBlock,
        DividerBlock,
        ProtocolElementBlock,
        SessionDateBlock,
        SessionNotesBlock,
        FormBlock,
        BulletListBlock,
        MatrixBlock,
        EntryExitBlock,
        ImageBlock,
        ImageGalleryBlock,
        AttendanceBlock,
        AttendanceMatrixBlock,
        MemberListBlock,
        SignatureFieldsBlock,
        AttendanceSheetBlock,
        TodoTableBlock,
        EventTableBlock,
        EventCalendarMonthBlock,
        EventAgendaBlock,
        ListTableBlock,
        FinanceBalanceBlock,
        FinanceTransactionsBlock,
        FinesBlock,
        KpiTilesBlock,
        ChartBlock,
        StatTableBlock,
        QrLinkBlock,
        GenericTableBlock,
    ],
    Field(discriminator="type"),
]

ProtocolElementBlock.model_rebuild()

# Alle Block-Typen (für Katalog, Prüfskript und Tests)
BLOCK_MODELS: dict[str, type[BlockBase]] = {
    model.model_fields["type"].default: model for model in get_args(get_args(Block)[0])
}


# ── Dokument ─────────────────────────────────────────────────────────────────


class DocumentMeta(_Strict):
    document_type: str
    title: str
    subtitle: str | None = None
    number: str | None = None
    date: str | None = None
    status: str | None = None
    version: str | None = None
    tenant_name: str = ""
    language: str = "de"


class DocumentOptions(_Strict):
    title_page: Literal["none", "minimal", "modern", "bold", "cover"] = "none"
    toc: Literal["off", "on", "compact", "very_compact"] = "off"
    toc_block_titles: bool = True
    show_metadata: bool = False
    numbering: bool = False
    orientation: Literal["portrait", "landscape"] = "portrait"
    watermark: bool = False


class ResolvedStyle(_Strict):
    """Aufgelöster Hausstil für den Compile: Tokens plus Pfade im Compile-Root."""

    key: Literal["modern", "classic", "compact"] = "modern"
    version: int = 1
    primary_color: HexColor = "#174B7A"
    secondary_color: HexColor = "#4F6D7A"
    # Vorangestellte Schriftfamilien (z. B. hochgeladene Mandantenschrift); leer = Hausschrift
    # des Stils. Fallbacks (Noto Sans, Noto Color Emoji) hängt der Stil selbst an.
    fonts: list[Annotated[str, Field(max_length=120)]] = Field(default_factory=list, max_length=4)
    base_size: Literal[10, 11, 12] = 11
    line_spacing: Literal["tight", "normal", "relaxed"] = "normal"
    margins: Literal["narrow", "normal", "wide"] = "normal"
    header: Literal["none", "minimal", "standard", "bar", "logo", "logo_bar"] = "standard"
    footer: Literal["none", "minimal", "standard", "with_version", "date_page"] = "standard"
    logo: str | None = Field(None, pattern=r"^assets/[A-Za-z0-9_.-]+$")
    footer_image: str | None = Field(None, pattern=r"^assets/[A-Za-z0-9_.-]+$")
    sender: str = ""
    sender_color: HexColor | None = None
    place: str = ""


class RenderInfo(_Strict):
    """Angaben zu genau diesem Rendering - nie Teil des Inhalts-Hashes."""

    document_id: str | None = None
    signed: bool = False
    preview: bool = False


class Document(_Strict):
    schema_version: int = SCHEMA_VERSION
    meta: DocumentMeta
    options: DocumentOptions = Field(default_factory=DocumentOptions)
    style: ResolvedStyle = Field(default_factory=ResolvedStyle)
    strings: dict[str, str] = Field(default_factory=dict)
    render: RenderInfo = Field(default_factory=RenderInfo)
    blocks: list[Block] = Field(default_factory=list)
