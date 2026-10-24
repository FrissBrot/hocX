"""ODT (OpenDocument Text) über content.xml mit einem gehärteten lxml-Parser (keine Entitäten,
kein Netzwerk, keine DTD). Gelöschte Änderungen, Fussnoten und Kommentare werden übersprungen."""

from __future__ import annotations

import io
import zipfile

from lxml import etree

from app.services.documents.content import BlockBuilder, ParsedContent, heading, media, paragraph, table

PARSER_VERSION = "1"

# Obergrenzen gegen Zip-Bomben: entpackte Grösse von content.xml/styles.xml und Wiederholungen
# leerer Zellen (Tabellen tragen oft "1024 leere Spalten" als number-columns-repeated).
MAX_XML_BYTES = 64 * 1024 * 1024
MAX_REPEAT = 64

NS = {
    "office": "urn:oasis:names:tc:opendocument:xmlns:office:1.0",
    "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
    "table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
    "draw": "urn:oasis:names:tc:opendocument:xmlns:drawing:1.0",
    "xlink": "http://www.w3.org/1999/xlink",
    "svg": "urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0",
    "style": "urn:oasis:names:tc:opendocument:xmlns:style:1.0",
}


def _q(prefix: str, tag: str) -> str:
    return f"{{{NS[prefix]}}}{tag}"


_SKIP = {
    _q("text", "note"),
    _q("text", "tracked-changes"),
    _q("office", "annotation"),
    _q("office", "annotation-end"),
    _q("text", "bookmark-ref"),
    _q("text", "sequence-decls"),
    _q("text", "variable-decls"),
    _q("text", "user-field-decls"),
    _q("office", "forms"),
}


def _read_member(archive: zipfile.ZipFile, name: str) -> bytes | None:
    try:
        info = archive.getinfo(name)
    except KeyError:
        return None
    if info.file_size > MAX_XML_BYTES:
        raise ValueError(f"{name} ist zu gross")
    with archive.open(info) as handle:
        data = handle.read(MAX_XML_BYTES + 1)
    if len(data) > MAX_XML_BYTES:
        raise ValueError(f"{name} ist zu gross")
    return data


def _parse_xml(data: bytes):
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, huge_tree=False, remove_comments=True)
    return etree.fromstring(data, parser)


def _inline_text(element, out: list[str], images: list) -> None:
    if element.text:
        out.append(element.text)
    for child in element:
        tag = child.tag
        if tag in _SKIP:
            pass
        elif tag == _q("text", "s"):
            count = child.get(_q("text", "c"), "1")
            out.append(" " * min(int(count) if count.isdigit() else 1, 1000))
        elif tag == _q("text", "tab"):
            out.append("\t")
        elif tag == _q("text", "line-break"):
            out.append("\n")
        elif tag == _q("draw", "frame"):
            images.append(child)
        else:
            _inline_text(child, out, images)
        if child.tail:
            out.append(child.tail)


class _OdtWalker:
    def __init__(self, list_styles: dict[str, dict[int, bool]]) -> None:
        self.builder = BlockBuilder()
        self.list_styles = list_styles

    def _frames(self, frames: list) -> None:
        for frame in frames:
            image = frame.find(_q("draw", "image"))
            if image is None:
                continue
            href = image.get(_q("xlink", "href"))
            if not href:
                continue
            alt = None
            for tag in (_q("svg", "desc"), _q("svg", "title")):
                node = frame.find(tag)
                if node is not None and (node.text or "").strip():
                    alt = node.text
                    break
            self.builder.add(media(href, content_type=image.get(_q("draw", "mime-type")), alt=alt))

    def walk(self, container) -> None:
        for child in container:
            tag = child.tag
            if tag in _SKIP:
                continue
            if tag == _q("text", "h"):
                out: list[str] = []
                frames: list = []
                _inline_text(child, out, frames)
                level = child.get(_q("text", "outline-level"), "1")
                self.builder.add(heading("".join(out), int(level) if level.isdigit() else 1))
                self._frames(frames)
            elif tag == _q("text", "p"):
                out = []
                frames = []
                _inline_text(child, out, frames)
                self.builder.add(paragraph("".join(out)))
                self._frames(frames)
            elif tag == _q("text", "list"):
                self._list(child, level=0, style=child.get(_q("text", "style-name")))
            elif tag == _q("table", "table"):
                self._table(child)
            elif tag in (_q("text", "section"), _q("text", "index-body"), _q("text", "table-of-content"),
                         _q("text", "alphabetical-index"), _q("text", "bibliography")):
                self.walk(child)

    def _list(self, node, *, level: int, style: str | None) -> None:
        style = node.get(_q("text", "style-name")) or style
        ordered = self.list_styles.get(style or "", {}).get(level + 1, False)
        for item in node:
            if item.tag not in (_q("text", "list-item"), _q("text", "list-header")):
                continue
            for child in item:
                if child.tag == _q("text", "list"):
                    self._list(child, level=level + 1, style=style)
                elif child.tag in (_q("text", "p"), _q("text", "h")):
                    out: list[str] = []
                    frames: list = []
                    _inline_text(child, out, frames)
                    self.builder.list_item("".join(out), level=level, ordered=ordered)
                    self._frames(frames)
                elif child.tag == _q("table", "table"):
                    self._table(child)

    def _cell_text(self, cell) -> str:
        parts = []
        for child in cell:
            if child.tag in (_q("text", "p"), _q("text", "h")):
                out: list[str] = []
                _inline_text(child, out, [])
                parts.append("".join(out))
            elif child.tag == _q("text", "list"):
                for paragraph_node in child.iter(_q("text", "p")):
                    out = []
                    _inline_text(paragraph_node, out, [])
                    parts.append("".join(out))
        return "\n".join(parts)

    def _row(self, row) -> list[str]:
        cells: list[str] = []
        for cell in row:
            if cell.tag not in (_q("table", "table-cell"), _q("table", "covered-table-cell")):
                continue
            repeat_raw = cell.get(_q("table", "number-columns-repeated"), "1")
            repeat = int(repeat_raw) if repeat_raw.isdigit() else 1
            text = "" if cell.tag == _q("table", "covered-table-cell") else self._cell_text(cell)
            cells.extend([text] * min(repeat, MAX_REPEAT))
        while cells and not cells[-1]:
            cells.pop()
        return cells

    def _table(self, node) -> None:
        rows: list[list[str]] = []
        header_rows = 0

        def collect(container, header: bool) -> None:
            nonlocal header_rows
            for child in container:
                if child.tag == _q("table", "table-row"):
                    repeat_raw = child.get(_q("table", "number-rows-repeated"), "1")
                    repeat = min(int(repeat_raw) if repeat_raw.isdigit() else 1, MAX_REPEAT)
                    row = self._row(child)
                    for _ in range(repeat):
                        rows.append(list(row))
                        if header:
                            header_rows += 1
                elif child.tag == _q("table", "table-header-rows"):
                    collect(child, True)
                elif child.tag in (_q("table", "table-rows"), _q("table", "table-row-group")):
                    collect(child, header)

        collect(node, False)
        if any(cell for row in rows for cell in row):
            self.builder.add(table(rows, header_rows=header_rows))


def _list_styles(*roots) -> dict[str, dict[int, bool]]:
    styles: dict[str, dict[int, bool]] = {}
    for root in roots:
        if root is None:
            continue
        for list_style in root.iter(_q("text", "list-style")):
            name = list_style.get(_q("style", "name"))
            levels: dict[int, bool] = {}
            for child in list_style:
                level = child.get(_q("text", "level"), "1")
                if level.isdigit():
                    levels[int(level)] = child.tag == _q("text", "list-level-style-number")
            if name:
                styles[name] = levels
    return styles


def parse_odt(data: bytes) -> ParsedContent:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        content_xml = _read_member(archive, "content.xml")
        styles_xml = _read_member(archive, "styles.xml")
    if content_xml is None:
        raise ValueError("ODT ohne content.xml")
    content_root = _parse_xml(content_xml)
    styles_root = _parse_xml(styles_xml) if styles_xml else None
    walker = _OdtWalker(_list_styles(content_root, styles_root))
    body = content_root.find(f"{_q('office', 'body')}/{_q('office', 'text')}")
    if body is None:
        raise ValueError("ODT ohne Textkörper")
    walker.walk(body)
    return ParsedContent(parser="odt", parser_version=PARSER_VERSION, blocks=walker.builder.blocks)
