"""PDF über pdfplumber (pdfminer): Text zeilenweise mit Position und Schriftgrösse, Tabellen über
pdfplumbers Tabellenerkennung, Reihenfolge nach Position auf der Seite.

Struktur wird nur aus eindeutigen Signalen abgeleitet: Überschrift = Zeile mit deutlich grösserer
Schrift als der Fliesstext, Aufzählung = Zeile beginnt mit einem Aufzählungszeichen. Zeilenumbrüche
innerhalb eines Absatzes bleiben erhalten (keine Silbentrennungs-"Reparatur").

Gescannte PDFs (praktisch keine Textebene, aber Bilder) werden als needs_ocr markiert; die OCR
selbst übernimmt der Worker (app/services/documents/ocr.py)."""

from __future__ import annotations

import io
from collections import Counter
from statistics import median

from app.services.documents.content import BlockBuilder, ParsedContent, heading, media, paragraph, table

PARSER_VERSION = "1"

HEADING_SIZE_RATIO = 1.15
MAX_HEADING_CHARS = 200
# Unterhalb davon (Zeichen je Seite im Schnitt) gilt ein PDF mit Bildern als gescannt.
OCR_CHARS_PER_PAGE = 25
MIN_IMAGE_SIZE_PT = 48
BULLETS = ("\u2022", "\u25e6", "\u25aa", "\u2023", "\u25cf", "\u25cb", "\u25a0", "\u25a1", "\u00b7", "\u2013", "-", "*",
           # Symbol-/Wingdings-Aufzählungszeichen aus Word-Dokumenten (Private Use Area).
           "\uf0b7", "\uf0a7", "\uf0d8", "\uf076")


def _inside(obj: dict, bbox: tuple[float, float, float, float]) -> bool:
    x0, top, x1, bottom = bbox
    cx = (obj["x0"] + obj["x1"]) / 2
    cy = (obj["top"] + obj["bottom"]) / 2
    return x0 <= cx <= x1 and top <= cy <= bottom


def _line_size(line: dict) -> float:
    sizes = [char.get("size") or 0 for char in line.get("chars") or [] if (char.get("text") or "").strip()]
    return round(median(sizes) * 2) / 2 if sizes else 0.0


def parse_pdf(data: bytes) -> ParsedContent:
    import pdfplumber

    warnings: list[str] = []
    pages: list[tuple[int, list[tuple[float, str, object]]]] = []
    size_weights: Counter[float] = Counter()
    total_chars = 0
    image_pages = 0

    with pdfplumber.open(io.BytesIO(data)) as pdf:
        page_count = len(pdf.pages)
        for page_number, page in enumerate(pdf.pages, start=1):
            items: list[tuple[float, str, object]] = []
            try:
                tables = page.find_tables()
            except Exception:  # noqa: BLE001 - defekte Tabellengeometrie: Text trotzdem lesen
                tables = []
                warnings.append(f"table_detection_failed:page_{page_number}")
            bboxes = [found.bbox for found in tables]
            for found in tables:
                rows = [[cell or "" for cell in row] for row in found.extract()]
                items.append((found.bbox[1], "table", rows))
            text_page = page.filter(lambda obj: obj.get("object_type") != "char" or not any(_inside(obj, bbox) for bbox in bboxes)) if bboxes else page
            for line in text_page.extract_text_lines(layout=False, strip=True, return_chars=True):
                text = line.get("text") or ""
                if not text.strip():
                    continue
                size = _line_size(line)
                size_weights[size] += len(text)
                total_chars += len(text.strip())
                items.append((line["top"], "line", {"text": text, "size": size, "top": line["top"], "bottom": line["bottom"]}))
            large_images = [
                image for image in page.images
                if (image.get("width") or 0) >= MIN_IMAGE_SIZE_PT and (image.get("height") or 0) >= MIN_IMAGE_SIZE_PT
            ]
            if large_images:
                image_pages += 1
            for index, image in enumerate(large_images, start=1):
                items.append((image["top"], "image", f"page-{page_number}-image-{index}"))
            items.sort(key=lambda item: (item[0], {"table": 0, "line": 1, "image": 2}[item[1]]))
            pages.append((page_number, items))

    body_size = size_weights.most_common(1)[0][0] if size_weights else 0.0
    heading_sizes = sorted(
        {size for size in size_weights if body_size and size >= body_size * HEADING_SIZE_RATIO}, reverse=True
    )
    level_by_size = {size: min(index + 1, 6) for index, size in enumerate(heading_sizes)}

    builder = BlockBuilder()
    for page_number, items in pages:
        buffer: list[dict] = []

        def flush() -> None:
            if buffer:
                builder.add(paragraph("\n".join(line["text"] for line in buffer), page=page_number))
                buffer.clear()

        for _top, kind, payload in items:
            if kind == "table":
                flush()
                builder.add(table(payload, page=page_number))
                continue
            if kind == "image":
                flush()
                builder.add(media(payload, page=page_number))
                continue
            line = payload
            level = level_by_size.get(line["size"])
            if level is not None and len(line["text"]) <= MAX_HEADING_CHARS:
                flush()
                builder.add(heading(line["text"], level, page=page_number))
                continue
            stripped = line["text"].lstrip()
            bullet = next((mark for mark in BULLETS if stripped.startswith(mark + " ") or stripped.startswith(mark + "\t")), None)
            if bullet is not None:
                flush()
                builder.list_item(stripped[len(bullet):].lstrip(), page=page_number)
                continue
            if buffer:
                previous = buffer[-1]
                height = max(previous["bottom"] - previous["top"], 1.0)
                if line["top"] - previous["bottom"] > 0.6 * height or line["size"] != previous["size"]:
                    flush()
            buffer.append(line)
        flush()

    parsed = ParsedContent(parser="pdf", parser_version=PARSER_VERSION, blocks=builder.blocks, page_count=page_count, warnings=warnings)
    if page_count and total_chars < OCR_CHARS_PER_PAGE * page_count and image_pages > 0:
        parsed.needs_ocr = True
    return parsed
