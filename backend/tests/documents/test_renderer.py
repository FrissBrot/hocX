"""Typst-Renderer: Vollständigkeit, Unicode, Sicherheit, Fehlerzuordnung, Grenzen."""
from __future__ import annotations

import asyncio
import re

import pytest

from app.documents.model import Document, DocumentMeta, ImageBlock, ImageRef, RichTextBlock
from app.documents.renderer import DocumentRenderError, DocumentRenderer, RenderAssets
from app.documents.richtext import markdown_to_rich
from app.documents.strings import strings_for
from tests.documents.conftest import load_fixture, normalize, pdf_pages, pdf_text


def _render(renderer, document, assets=None):
    return asyncio.run(renderer.render_pdf(document, assets))


def test_long_table_keeps_all_500_rows_and_repeats_header(renderer):
    document = load_fixture("long")
    output = _render(renderer, document)
    assert output.pdf.startswith(b"%PDF")
    assert output.warnings == []
    text = pdf_text(output.pdf)
    for index in range(1, 501):
        assert f"Aufgabe {index:03d}" in text
    pages = [page for page in pdf_pages(output.pdf) if page.strip()]
    assert len(pages) > 3
    header = document.strings["col.assignee"]
    for page in pages:
        assert header in page, "Kopfzeile fehlt auf einer Folgeseite"


def test_unicode_and_emoji_do_not_break_export(renderer):
    output = _render(renderer, load_fixture("unicode"))
    text = pdf_text(output.pdf)
    assert "Ħ" in text
    assert "#set $x$" in text


def test_user_content_is_never_evaluated(renderer):
    payload = "#set page(fill: red) #eval(\"1+1\") $x^2$ @ref <lbl> `c` *b* _i_"
    document = Document(
        meta=DocumentMeta(document_type="custom", title=payload),
        strings=strings_for("de"),
        blocks=[RichTextBlock(title=payload, content=markdown_to_rich(payload))],
    )
    output = _render(renderer, document)
    flat = normalize(pdf_text(output.pdf))
    assert normalize('#eval("1+1")') in flat
    assert normalize("#set page(fill: red)") in flat


def test_all_blocks_fixture_completeness(renderer, assets):
    document = load_fixture("all_blocks")
    output = _render(renderer, document, assets)
    flat = normalize(pdf_text(output.pdf))
    expected: list[str] = []

    def collect(value):
        if isinstance(value, dict):
            if value.get("t") == "text" and value.get("v"):
                expected.append(value["v"])
            if value.get("k") in ("text", "amount") and value.get("v"):
                expected.append(value["v"])
            for item in value.values():
                collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)

    collect([block.model_dump(mode="json") for block in document.blocks])
    assert expected
    missing = [value for value in expected if normalize(value) not in flat]
    assert missing == []


def test_pdf_is_pdfa_2b(renderer):
    output = _render(renderer, load_fixture("short"))
    assert b"pdfaid:part" in output.pdf or b"<pdfaid:part>2</pdfaid:part>" in output.pdf
    assert re.search(rb"pdfaid:conformance[=>\"]+B", output.pdf)


def test_preview_returns_limited_png_pages(renderer, assets):
    output = asyncio.run(renderer.render_preview(load_fixture("all_blocks"), assets, max_pages=2))
    assert len(output.pages) == 2
    assert all(page.startswith(b"\x89PNG") for page in output.pages)


def test_failing_block_is_named(renderer):
    document = Document(
        meta=DocumentMeta(document_type="custom", title="Fehler"),
        strings=strings_for("de"),
        blocks=[
            RichTextBlock(title="Gut", content=markdown_to_rich("ok")),
            ImageBlock(title="Kaputtes Bild", image=ImageRef(path="assets/fehlt.png")),
        ],
    )
    with pytest.raises(DocumentRenderError) as excinfo:
        _render(renderer, document, RenderAssets())
    assert excinfo.value.key == "error.block"
    assert excinfo.value.block_label == "Kaputtes Bild"
    assert excinfo.value.detail


def test_timeout_is_curated():
    slow = DocumentRenderer(concurrency=1, timeout_seconds=0.001)
    try:
        with pytest.raises(DocumentRenderError) as excinfo:
            _render(slow, load_fixture("long"))
        assert excinfo.value.key == "error.timeout"
    finally:
        slow.shutdown()


def test_assets_cannot_escape_root(renderer):
    with pytest.raises(DocumentRenderError):
        _render(renderer, load_fixture("short"), RenderAssets(files={"assets/../../etc/passwd": b"x"}))


def test_uncovered_characters_are_replaced_not_fatal():
    from app.documents.renderer import REPLACEMENT_CHARACTER, font_coverage, sanitize_text

    coverage = font_coverage()
    assert sanitize_text("漢x😀\x07‍", coverage) == f"{REPLACEMENT_CHARACTER}x😀‍"
