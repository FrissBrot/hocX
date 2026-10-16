"""DOCX über python-docx bzw. dessen lxml-Baum.

Bewusst eigener Durchlauf über w:body statt Document.paragraphs/tables: nur so bleibt die
Reihenfolge von Absätzen und Tabellen erhalten. Verbundene Zellen werden nicht vervielfacht
(gridSpan/vMerge -> leere Zellen), mc:Fallback-Inhalte (Doppelungen von Textfeldern) und
gelöschte Änderungen (w:delText) werden übersprungen.

Unabhängig vom domänenspezifischen Protokollimport (word_import_service.parse_document)."""

from __future__ import annotations

import io
import re

from app.services.documents.content import BlockBuilder, ParsedContent, heading, media, paragraph, table

PARSER_VERSION = "1"

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
V = "urn:schemas-microsoft-com:vml"


def _q(ns: str, tag: str) -> str:
    return f"{{{ns}}}{tag}"


_HEADING_STYLE = re.compile(r"^(?:heading|berschrift|titre|titolo)\s*([1-9])$", re.IGNORECASE)


class _DocxContext:
    def __init__(self, document) -> None:
        self.document = document
        self.part = document.part
        self.styles = {}
        try:
            for style in document.styles:
                self.styles[style.style_id] = style
        except Exception:  # noqa: BLE001 - defekte Stylesheets: dann eben ohne Stilinformation
            self.styles = {}
        self._numbering_formats = self._load_numbering()

    def _load_numbering(self) -> dict[tuple[str, int], bool]:
        """(numId, ilvl) -> geordnet? aus numbering.xml."""
        result: dict[tuple[str, int], bool] = {}
        try:
            numbering = self.part.numbering_part.element
        except Exception:  # noqa: BLE001 - Dokument ohne Nummerierungsdefinition
            return result
        abstract: dict[str, dict[int, bool]] = {}
        for node in numbering.findall(_q(W, "abstractNum")):
            levels: dict[int, bool] = {}
            for lvl in node.findall(_q(W, "lvl")):
                fmt = lvl.find(_q(W, "numFmt"))
                value = fmt.get(_q(W, "val")) if fmt is not None else "decimal"
                levels[int(lvl.get(_q(W, "ilvl"), "0"))] = value not in ("bullet", "none")
            abstract[node.get(_q(W, "abstractNumId"))] = levels
        for num in numbering.findall(_q(W, "num")):
            ref = num.find(_q(W, "abstractNumId"))
            if ref is None:
                continue
            for ilvl, ordered in abstract.get(ref.get(_q(W, "val")), {}).items():
                result[(num.get(_q(W, "numId")), ilvl)] = ordered
        return result

    def style_chain(self, style_id: str | None):
        seen = set()
        style = self.styles.get(style_id) if style_id else None
        while style is not None and style.style_id not in seen:
            seen.add(style.style_id)
            yield style
            style = style.base_style

    def heading_level(self, p) -> int | None:
        ppr = p.find(_q(W, "pPr"))
        style_id = None
        if ppr is not None:
            outline = ppr.find(_q(W, "outlineLvl"))
            if outline is not None and outline.get(_q(W, "val"), "9").isdigit() and int(outline.get(_q(W, "val"))) < 9:
                return int(outline.get(_q(W, "val"))) + 1
            pstyle = ppr.find(_q(W, "pStyle"))
            style_id = pstyle.get(_q(W, "val")) if pstyle is not None else None
        for style in self.style_chain(style_id):
            if style.style_id == "Title":
                return 1
            match = _HEADING_STYLE.match(style.style_id or "") or _HEADING_STYLE.match((style.name or "").replace("Ü", "").replace("ü", ""))
            if match:
                return int(match.group(1))
            outline = style.element.find(f"{_q(W, 'pPr')}/{_q(W, 'outlineLvl')}")
            if outline is not None and outline.get(_q(W, "val"), "9").isdigit() and int(outline.get(_q(W, "val"))) < 9:
                return int(outline.get(_q(W, "val"))) + 1
        return None

    def list_info(self, p) -> tuple[int, bool] | None:
        ppr = p.find(_q(W, "pPr"))
        num_pr = ppr.find(_q(W, "numPr")) if ppr is not None else None
        style_id = None
        if ppr is not None and ppr.find(_q(W, "pStyle")) is not None:
            style_id = ppr.find(_q(W, "pStyle")).get(_q(W, "val"))
        if num_pr is None:
            for style in self.style_chain(style_id):
                num_pr = style.element.find(f"{_q(W, 'pPr')}/{_q(W, 'numPr')}")
                if num_pr is not None:
                    break
        if num_pr is None:
            return None
        num_id_node = num_pr.find(_q(W, "numId"))
        ilvl_node = num_pr.find(_q(W, "ilvl"))
        num_id = num_id_node.get(_q(W, "val")) if num_id_node is not None else None
        if num_id in (None, "0"):  # numId 0 = Nummerierung ausdrücklich entfernt
            return None
        level = int(ilvl_node.get(_q(W, "val"), "0")) if ilvl_node is not None else 0
        return level, self._numbering_formats.get((num_id, level), False)

    def image(self, blip) -> tuple[str, str | None] | None:
        rel_id = blip.get(_q(R, "embed")) or blip.get(_q(R, "id"))
        if not rel_id:
            return None
        try:
            rel = self.part.rels[rel_id]
        except KeyError:
            return None
        if rel.is_external:
            # Externe Bildverweise werden nie aufgelöst, nur als Referenz notiert.
            return rel.target_ref, None
        return rel.target_ref, rel.target_part.content_type


def _iter_content(element):
    """Kinder in Dokumentreihenfolge, mc:AlternateContent über mc:Choice (Fallback ignoriert),
    w:sdt (Inhaltssteuerelemente) und w:customXml transparent."""
    for child in element:
        tag = child.tag
        if tag == _q(MC, "AlternateContent"):
            choice = child.find(_q(MC, "Choice"))
            if choice is not None:
                yield from _iter_content(choice)
            continue
        if tag == _q(W, "sdt"):
            content = child.find(_q(W, "sdtContent"))
            if content is not None:
                yield from _iter_content(content)
            continue
        if tag in (_q(W, "customXml"), _q(W, "smartTag")):
            yield from _iter_content(child)
            continue
        yield child


def _run_text(element, out: list[str], images: list) -> None:
    for node in _iter_content(element):
        tag = node.tag
        if tag == _q(W, "t"):
            out.append(node.text or "")
        elif tag == _q(W, "tab"):
            out.append("\t")
        elif tag in (_q(W, "br"), _q(W, "cr")):
            out.append("\n")
        elif tag == _q(W, "noBreakHyphen"):
            out.append("-")
        elif tag in (_q(W, "del"), _q(W, "delText"), _q(W, "instrText"), _q(W, "rPr"), _q(W, "pPr"),
                     _q(W, "footnoteReference"), _q(W, "endnoteReference"), _q(W, "commentReference")):
            continue
        elif tag == _q(A, "blip"):
            images.append(node)
        elif tag == _q(V, "imagedata"):
            images.append(node)
        elif tag == _q(WP, "docPr"):
            images.append(node)
        else:
            _run_text(node, out, images)


def _paragraph_text(p) -> tuple[str, list]:
    out: list[str] = []
    images: list = []
    _run_text(p, out, images)
    return "".join(out), images


def _table_rows(tbl) -> tuple[list[list[str]], int]:
    rows: list[list[str]] = []
    header_rows = 0
    counting_header = True
    for tr in _iter_content(tbl):
        if tr.tag != _q(W, "tr"):
            continue
        trpr = tr.find(_q(W, "trPr"))
        is_header = trpr is not None and trpr.find(_q(W, "tblHeader")) is not None
        if counting_header and is_header:
            header_rows += 1
        else:
            counting_header = False
        row: list[str] = []
        for tc in _iter_content(tr):
            if tc.tag != _q(W, "tc"):
                continue
            tcpr = tc.find(_q(W, "tcPr"))
            span = 1
            continued = False
            if tcpr is not None:
                grid_span = tcpr.find(_q(W, "gridSpan"))
                if grid_span is not None and grid_span.get(_q(W, "val"), "1").isdigit():
                    span = max(1, min(int(grid_span.get(_q(W, "val"))), 64))
                v_merge = tcpr.find(_q(W, "vMerge"))
                continued = v_merge is not None and v_merge.get(_q(W, "val"), "continue") == "continue"
            texts = []
            for node in tc.iter(_q(W, "p")):
                text, _ = _paragraph_text(node)
                texts.append(text)
            row.append("" if continued else "\n".join(texts).strip("\n"))
            row.extend([""] * (span - 1))
        rows.append(row)
    return rows, header_rows


def parse_docx(data: bytes) -> ParsedContent:
    from docx import Document as load_docx

    document = load_docx(io.BytesIO(data))
    context = _DocxContext(document)
    builder = BlockBuilder()
    warnings: list[str] = []
    body = document.element.body
    for node in _iter_content(body):
        if node.tag == _q(W, "p"):
            text, images = _paragraph_text(node)
            level = context.heading_level(node)
            if text.strip():
                if level is not None:
                    builder.add(heading(text, level))
                else:
                    info = context.list_info(node)
                    if info is not None:
                        builder.list_item(text, level=info[0], ordered=info[1])
                    else:
                        builder.add(paragraph(text))
            alt = None
            for image in images:
                if image.tag == _q(WP, "docPr"):
                    alt = image.get("descr") or image.get("title") or None
                    continue
                resolved = context.image(image)
                if resolved is not None:
                    builder.add(media(resolved[0], content_type=resolved[1], alt=alt))
                    alt = None
        elif node.tag == _q(W, "tbl"):
            rows, header_rows = _table_rows(node)
            if any(cell.strip() for row in rows for cell in row):
                builder.add(table(rows, header_rows=header_rows))
    if document.sections and any(
        section.header is not None and any(p.text.strip() for p in section.header.paragraphs) for section in document.sections
    ):
        warnings.append("header_footer_not_extracted")
    return ParsedContent(parser="docx", parser_version=PARSER_VERSION, blocks=builder.blocks, warnings=warnings)
