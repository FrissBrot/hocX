"""RTF über einen eigenen, kleinen Tokenizer (keine zusätzliche Abhängigkeit).

Erkannt werden Absätze, Zeilenumbrüche, Tabulatoren, Tabellen (\\intbl/\\cell/\\row),
Überschriften (\\outlinelevelN oder Absatzformat "heading N"/"Überschrift N"/"Title" aus dem
Stylesheet), Listen (\\ls/\\ilvl, geordnet, wenn der Listentext eine Ziffer
enthält), Unicode (\\uN mit \\uc) und Codepages (\\ansicpg, \\'hh). Steuer- und Metadaten-
Destinationen (Schrift-/Farbtabellen, Kopf-/Fusszeilen, Fussnoten, Feldbefehle, Objekte) werden
übersprungen; eingebettete Bilder (\\pict) werden nur als Referenz notiert."""

from __future__ import annotations

import re

from app.services.documents.content import BlockBuilder, ParsedContent, heading, media, paragraph, table

PARSER_VERSION = "1"

_TOKEN = re.compile(
    r"\\([a-zA-Z]{1,32})(-?\d{1,10})? ?|\\'([0-9a-fA-F]{2})|\\([^a-zA-Z])|([{}])|[\r\n]+|([^\\{}\r\n]+)",
    re.S,
)

_IGNORED_DESTINATIONS = frozenset({
    "fonttbl", "colortbl", "info", "object", "header", "headerl", "headerr", "headerf",
    "footer", "footerl", "footerr", "footerf", "footnote", "annotation", "fldinst", "themedata",
    "colorschememapping", "latentstyles", "datastore", "xmlnstbl", "listtable", "listoverridetable",
    "rsidtbl", "generator", "pgdsctbl", "filetbl", "revtbl", "bkmkstart", "bkmkend", "atnid", "atnauthor",
    "nonshppict", "mmathPr", "wgrffmtfilter", "pnseclvl", "xe", "tc", "private", "passwordhash", "docvar",
    "comment", "listpicture", "template", "userprops", "objdata", "objclass", "fldtype", "sp", "sn", "sv",
})
_IMAGE_TYPES = {"pngblip": "image/png", "jpegblip": "image/jpeg", "emfblip": "image/emf", "wmetafile": "image/wmf"}


_HEADING_STYLE = re.compile(r"^(?:heading|überschrift|titre|titolo)\s*([1-9])$", re.IGNORECASE)


class _Group:
    __slots__ = ("skip", "uc", "capture", "pict", "style_no", "buffer")

    def __init__(self, skip: bool = False, uc: int = 1, capture: str | None = None, pict: bool = False) -> None:
        self.skip = skip
        self.uc = uc
        self.capture = capture
        self.pict = pict
        self.style_no: int | None = None
        self.buffer: list[str] = []


class _RtfState:
    def __init__(self) -> None:
        self.builder = BlockBuilder()
        self.encoding = "cp1252"
        self.text: list[str] = []
        self.listtext: list[str] = []
        self.in_table = False
        self.outline: int | None = None
        self.list_level: int | None = None
        self.cell: list[str] = []
        self.row: list[str] = []
        self.rows: list[list[str]] = []
        self.pending_images: list[str | None] = []
        self.image_count = 0
        # Absatzformate aus dem Stylesheet: Nummer -> Name, und das Format des aktuellen Absatzes.
        self.styles: dict[int, str] = {}
        self.style: int = 0

    def reset_paragraph_props(self) -> None:
        self.in_table = False
        self.outline = None
        self.list_level = None
        self.style = 0

    def heading_level(self) -> int | None:
        if self.outline is not None:
            return self.outline + 1
        name = self.styles.get(self.style, "")
        if name.lower() == "title":
            return 1
        match = _HEADING_STYLE.match(name)
        return int(match.group(1)) if match else None

    def flush_table(self) -> None:
        if self.row or self.cell:
            self.row.append("".join(self.cell))
            self.rows.append(self.row)
            self.row, self.cell = [], []
        if self.rows:
            self.builder.add(table(self.rows))
            self.rows = []

    def end_paragraph(self) -> None:
        text = "".join(self.text)
        self.text = []
        listtext = "".join(self.listtext)
        self.listtext = []
        if self.in_table:
            self.cell.append(text + "\n")
        else:
            self.flush_table()
            if text.strip():
                level = self.heading_level()
                if level is not None:
                    self.builder.add(heading(text, level))
                elif self.list_level is not None:
                    self.builder.list_item(text, level=self.list_level, ordered=any(ch.isdigit() for ch in listtext))
                else:
                    self.builder.add(paragraph(text))
        self._emit_images()

    def _emit_images(self) -> None:
        for content_type in self.pending_images:
            self.image_count += 1
            self.builder.add(media(f"rtf-pict-{self.image_count}", content_type=content_type))
        self.pending_images = []

    def end_cell(self) -> None:
        self.cell.extend(self.text)
        self.text = []
        self.row.append("".join(self.cell).strip("\n"))
        self.cell = []

    def end_row(self) -> None:
        if self.text:
            self.cell.extend(self.text)
            self.text = []
        if self.cell:
            self.row.append("".join(self.cell).strip("\n"))
            self.cell = []
        self.rows.append(self.row)
        self.row = []
        self._emit_images()


def parse_rtf(data: bytes) -> ParsedContent:
    source = data.decode("latin-1")
    if not source.lstrip().startswith("{\\rtf"):
        raise ValueError("Keine RTF-Datei")
    state = _RtfState()
    stack: list[_Group] = [_Group()]
    skip_chars = 0
    destination_pending = False
    group_started = False

    def out(chars: str) -> None:
        group = stack[-1]
        if group.skip or group.capture == "stylesheet":
            return
        if group.capture == "style":
            group.buffer.append(chars)
        elif group.capture == "listtext":
            state.listtext.append(chars)
        else:
            state.text.append(chars)

    for match in _TOKEN.finditer(source):
        word, arg, hexcode, symbol, brace, literal = match.groups()
        current = stack[-1]
        starts_group = group_started
        group_started = False
        if brace == "{":
            stack.append(_Group(skip=current.skip, uc=current.uc, capture=current.capture))
            group_started = True
            skip_chars = 0
            continue
        if brace == "}":
            if len(stack) > 1:
                closed = stack.pop()
                if closed.capture == "style" and closed.style_no is not None and not closed.skip:
                    state.styles[closed.style_no] = "".join(closed.buffer).split(";")[0].strip()
            skip_chars = 0
            continue
        if skip_chars and (literal is not None or hexcode is not None):
            if literal is not None and len(literal) > skip_chars:
                literal = literal[skip_chars:]
                skip_chars = 0
            else:
                skip_chars -= 1 if hexcode is not None else len(literal)
                skip_chars = max(skip_chars, 0)
                continue
        if symbol is not None:
            if symbol == "*":
                # Optionale Destination: das folgende Steuerwort entscheidet (siehe unten).
                destination_pending = True
                group_started = starts_group
                continue
            if symbol == "~":
                out("\u00a0")
            elif symbol == "_":
                out("\u2011")
            elif symbol in "\\{}":
                out(symbol)
            elif symbol in "\r\n":
                if not current.skip and current.capture is None:
                    state.end_paragraph()
            # \- (optionaler Trennstrich) und unbekannte Symbole: kein Inhalt
            continue
        if hexcode is not None:
            try:
                out(bytes([int(hexcode, 16)]).decode(state.encoding))
            except (UnicodeDecodeError, LookupError):
                out(bytes([int(hexcode, 16)]).decode("latin-1"))
            continue
        if word is not None:
            value = int(arg) if arg is not None else None
            if destination_pending:
                destination_pending = False
                # \shppict enthält das eigentliche Bild, alle anderen \* -Destinationen sind
                # unbekannt bzw. Metadaten und werden übersprungen.
                if word != "shppict":
                    current.skip = True
                continue
            if starts_group and word in _IGNORED_DESTINATIONS:
                current.skip = True
                continue
            if starts_group and word == "stylesheet":
                current.capture = "stylesheet"
                continue
            if current.capture == "stylesheet" and starts_group and word == "s" and value is not None:
                current.capture = "style"
                current.style_no = value
                continue
            if current.capture in ("stylesheet", "style"):
                continue
            if starts_group and word in ("listtext", "pntext"):
                current.capture = "listtext"
                continue
            if word == "pict" and starts_group:
                current.skip = True
                if not stack[-2].skip if len(stack) > 1 else True:
                    state.pending_images.append(None)
                    current.pict = True
                continue
            if current.pict and word in _IMAGE_TYPES and state.pending_images:
                state.pending_images[-1] = _IMAGE_TYPES[word]
                continue
            if word == "ansicpg" and value:
                state.encoding = f"cp{value}"
            elif word == "uc" and value is not None:
                current.uc = max(value, 0)
            elif word == "u" and value is not None:
                out(chr(value + 65536 if value < 0 else value))
                skip_chars = current.uc
            elif current.skip:
                continue
            elif word in ("par", "sect", "page"):
                if current.capture is None:
                    state.end_paragraph()
            elif word == "line":
                out("\n")
            elif word == "tab":
                out("\t")
            elif word in ("emdash", "endash", "bullet", "lquote", "rquote", "ldblquote", "rdblquote"):
                out({"emdash": "\u2014", "endash": "\u2013", "bullet": "\u2022", "lquote": "\u2018",
                     "rquote": "\u2019", "ldblquote": "\u201c", "rdblquote": "\u201d"}[word])
            elif word == "pard":
                state.reset_paragraph_props()
            elif word == "intbl":
                state.in_table = True
            elif word == "cell":
                state.end_cell()
            elif word == "row":
                state.end_row()
            elif word == "outlinelevel" and value is not None and 0 <= value < 9:
                state.outline = value
            elif word == "ls":
                state.list_level = state.list_level or 0
            elif word == "s" and value is not None:
                state.style = value
            elif word == "ilvl" and value is not None:
                state.list_level = max(0, min(value, 8))
            continue
        if literal is not None:
            out(literal)
    if state.text:
        state.end_paragraph()
    state.flush_table()
    state._emit_images()
    return ParsedContent(parser="rtf", parser_version=PARSER_VERSION, encoding=state.encoding, blocks=state.builder.blocks)
