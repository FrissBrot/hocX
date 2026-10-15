"""TXT, Markdown und CSV."""

from __future__ import annotations

import codecs
import csv
import io
import re

from app.services.documents.content import BlockBuilder, ParsedContent, heading, media, paragraph, table

PARSER_VERSION = "1"


def decode_text(data: bytes) -> tuple[str, str]:
    """Deterministische Erkennung der Zeichenkodierung: BOM, sonst UTF-8 (strikt), sonst
    Windows-1252, sonst ISO-8859-1 (dekodiert jedes Byte)."""
    for bom, encoding in (
        (codecs.BOM_UTF8, "utf-8-sig"),
        (codecs.BOM_UTF32_LE, "utf-32"),
        (codecs.BOM_UTF32_BE, "utf-32"),
        (codecs.BOM_UTF16_LE, "utf-16"),
        (codecs.BOM_UTF16_BE, "utf-16"),
    ):
        if data.startswith(bom):
            try:
                return data.decode(encoding), encoding
            except UnicodeDecodeError:
                break
    for encoding in ("utf-8", "cp1252"):
        try:
            return data.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1"), "latin-1"


def _paragraphs(text: str) -> list[str]:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return [part for part in re.split(r"\n[ \t]*\n", text) if part.strip()]


def parse_plain_text(data: bytes) -> ParsedContent:
    """Absätze = durch Leerzeilen getrennte Abschnitte. Bewusst keine Strukturerkennung: ein
    Klartext hat keine Überschriften, und erraten wird nichts."""
    text, encoding = decode_text(data)
    return ParsedContent(
        parser="text", parser_version=PARSER_VERSION, encoding=encoding,
        blocks=[paragraph(part) for part in _paragraphs(text)],
    )


_ATX_HEADING = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?(?:[ \t]+#+)?[ \t]*$")
_SETEXT = re.compile(r"^ {0,3}(=+|-+)[ \t]*$")
_LIST_ITEM = re.compile(r"^([ \t]*)([-*+]|\d{1,9}[.)])[ \t]+(.*)$")
_FENCE = re.compile(r"^ {0,3}(```|~~~)")
_TABLE_SEPARATOR = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")
_IMAGE_LINE = re.compile(r"^\s*!\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)\s*$")


def _split_table_row(line: str) -> list[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|") and not stripped.endswith("\\|"):
        stripped = stripped[:-1]
    cells = re.split(r"(?<!\\)\|", stripped)
    return [cell.strip().replace("\\|", "|") for cell in cells]


def parse_markdown(data: bytes) -> ParsedContent:
    """CommonMark-Teilmenge: ATX-/Setext-Überschriften, Listen (Ebene über Einrückung),
    Pipe-Tabellen, Bildzeilen, Codeblöcke (als Absatz mit Originaltext). Inline-Markup bleibt
    unverändert im Text - es wird nichts umgeschrieben."""
    text, encoding = decode_text(data)
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    builder = BlockBuilder()
    buffer: list[str] = []

    def flush() -> None:
        if buffer:
            builder.add(paragraph("\n".join(buffer)))
            buffer.clear()

    index = 0
    while index < len(lines):
        line = lines[index]
        if _FENCE.match(line):
            flush()
            fence = _FENCE.match(line).group(1)
            code: list[str] = []
            index += 1
            while index < len(lines) and not lines[index].strip().startswith(fence):
                code.append(lines[index])
                index += 1
            builder.add(paragraph("\n".join(code)))
            index += 1
            continue
        if not line.strip():
            flush()
            index += 1
            continue
        match = _ATX_HEADING.match(line)
        if match:
            flush()
            builder.add(heading(match.group(2) or "", len(match.group(1))))
            index += 1
            continue
        if buffer and len(buffer) == 1 and _SETEXT.match(line):
            builder.add(heading(buffer.pop(), 1 if line.strip().startswith("=") else 2))
            index += 1
            continue
        if "|" in line and index + 1 < len(lines) and _TABLE_SEPARATOR.match(lines[index + 1]):
            flush()
            rows = [_split_table_row(line)]
            index += 2
            while index < len(lines) and "|" in lines[index] and lines[index].strip():
                rows.append(_split_table_row(lines[index]))
                index += 1
            builder.add(table(rows, header_rows=1))
            continue
        image = _IMAGE_LINE.match(line)
        if image:
            flush()
            builder.add(media(image.group(2), alt=image.group(1) or None))
            index += 1
            continue
        item = _LIST_ITEM.match(line)
        if item:
            flush()
            indent = len(item.group(1).replace("\t", "    "))
            builder.list_item(item.group(3), level=indent // 2, ordered=item.group(2)[0].isdigit())
            index += 1
            continue
        buffer.append(line)
        index += 1
    flush()
    return ParsedContent(parser="markdown", parser_version=PARSER_VERSION, encoding=encoding, blocks=builder.blocks)


def parse_csv(data: bytes) -> ParsedContent:
    """Eine Tabelle. Trennzeichen per csv.Sniffer aus , ; Tab | (Fallback Komma). Ob die erste
    Zeile eine Kopfzeile ist, wird nicht geraten (header_rows=0)."""
    text, encoding = decode_text(data)
    sample = text[:65536]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    rows = [row for row in csv.reader(io.StringIO(text), dialect)]
    blocks = [table(rows)] if rows else []
    return ParsedContent(parser="csv", parser_version=PARSER_VERSION, encoding=encoding, blocks=blocks)
