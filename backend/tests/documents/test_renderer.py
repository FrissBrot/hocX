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


def _three_blocks() -> Document:
    return Document(
        meta=DocumentMeta(document_type="custom", title="Diagnose"),
        strings=strings_for("de"),
        blocks=[RichTextBlock(title=f"Block {index}", content=markdown_to_rich("x")) for index in range(3)],
    )


def test_diagnosis_stops_at_first_failed_probe(monkeypatch):
    """TYPST-009: scheitert ein Probe-Compile selbst (Timeout setzt den Pool zurück), bricht
    die Fehlersuche ab, statt bis zu 80 weitere Compiles anzustossen."""
    from app.documents.renderer import CompileResult

    renderer = DocumentRenderer(concurrency=1)
    calls = []

    async def fake_run(document_json, assets, fmt, ppi, max_pages=None):
        calls.append(fmt)
        if len(calls) == 1:
            return CompileResult(ok=False, error="kaputt")
        raise DocumentRenderError("error.timeout")

    monkeypatch.setattr(renderer, "_run", fake_run)
    with pytest.raises(DocumentRenderError) as excinfo:
        _render(renderer, _three_blocks())
    assert excinfo.value.key == "error.render" and excinfo.value.detail
    assert len(calls) == 2


def test_diagnosis_respects_time_budget(monkeypatch):
    """TYPST-009: die Fehlersuche endet nach dem Zeitbudget (2 × Timeout)."""
    from app.documents import renderer as renderer_module
    from app.documents.renderer import CompileResult

    renderer = DocumentRenderer(concurrency=1, timeout_seconds=0.05)
    monkeypatch.setattr(renderer_module, "_MAX_DIAGNOSE_COMPILES", 10_000)
    calls = []

    async def failing_run(document_json, assets, fmt, ppi, max_pages=None):
        calls.append(fmt)
        await asyncio.sleep(0.04)
        return CompileResult(ok=False, error="kaputt")

    monkeypatch.setattr(renderer, "_run", failing_run)
    document = _three_blocks().model_copy(update={"blocks": _three_blocks().blocks * 20})
    with pytest.raises(DocumentRenderError):
        _render(renderer, document)
    # 1 Haupt-Compile + höchstens ~3 Proben à 40 ms im Budget von 100 ms
    assert len(calls) <= 5


def test_queue_wait_is_bounded():
    """TYPST-005: ohne freien Compile-Platz gibt es nach der Wartezeit error.busy (HTTP 503)
    statt einer unbegrenzten Warteschlange."""
    renderer = DocumentRenderer(concurrency=1, queue_timeout_seconds=0.05)

    async def scenario():
        await renderer._semaphore().acquire()  # einziger Platz belegt
        with pytest.raises(DocumentRenderError) as excinfo:
            await renderer._acquire_slot()
        return excinfo.value.key

    assert asyncio.run(scenario()) == "error.busy"


def test_preview_rasterizes_only_the_requested_pages(renderer, assets, monkeypatch):
    """TYPST-005: Die Vorschau kompiliert ein PDF und rastert nur die angeforderten Seiten,
    nicht alle (typst-py kennt keine Seitenauswahl)."""
    from app.documents import renderer as renderer_module

    rasterized: list[int] = []
    original = renderer_module._rasterize

    def counting(pdf, *, ppi, max_pages):
        pages = original(pdf, ppi=ppi, max_pages=max_pages)
        rasterized.append(len(pages))
        return pages

    # Der Compile läuft im Worker-Prozess; zum Zählen direkt im Testprozess ausführen.
    monkeypatch.setattr(renderer_module, "_rasterize", counting)
    document = load_fixture("all_blocks")
    result = renderer_module._compile_job(renderer_module._dump(document), assets.files, assets.fonts, "png", 40, 2)

    assert result.ok and len(result.output) == 2 and rasterized == [2]
    assert all(page.startswith(b"\x89PNG") for page in result.output)


def test_cancelled_preview_keeps_the_slot_until_the_compile_finished(monkeypatch):
    """Ein abgebrochener Request gibt seinen Compile-Platz erst frei, wenn der Prozess fertig ist -
    sonst liefen mehr Compiles parallel als erlaubt."""
    import asyncio
    import concurrent.futures

    from app.documents import renderer as renderer_module

    gate = concurrent.futures.Future()

    class FakePool:
        def submit(self, *args, **kwargs):
            return gate

    renderer = renderer_module.DocumentRenderer(concurrency=1, timeout_seconds=30, memory_limit_mb=512)
    monkeypatch.setattr(renderer, "_pool", lambda: FakePool())

    async def scenario():
        semaphore = renderer._semaphore()
        task = asyncio.ensure_future(renderer._run("{}", renderer_module.RenderAssets(), "png", 40, 1))
        await asyncio.sleep(0.05)
        task.cancel()
        await asyncio.sleep(0.05)
        assert semaphore.locked(), "Platz wurde vor Ende des Compiles freigegeben"
        gate.set_result(renderer_module.CompileResult(ok=True, output=[]))
        await asyncio.sleep(0.05)
        assert not semaphore.locked()

    asyncio.run(scenario())
