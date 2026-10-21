"""Typst-Renderer und Layout-Darstellung: Vollständigkeit, wiederholte Tabellenköpfe, Unicode,
Sicherheit (kein Benutzercode), Fehlerzuordnung am Knoten, PDF/A, Grenzen."""
from __future__ import annotations

import asyncio
import copy
import re

import pytest

from app.documents.renderer import DocumentRenderError, DocumentRenderer, RenderAssets
from tests.documents.conftest import compiled_assets, normalize, pdf_pages, pdf_text
from tests.documents.fixtures.scenarios import Scenario, all_data_blocks, compile_scenario, scenarios, system


def _render(renderer, compiled, assets=None):
    return asyncio.run(renderer.render_pdf(compiled.data, assets if assets is not None else compiled_assets(compiled)))


def test_long_table_keeps_all_500_rows_and_repeats_header(renderer):
    compiled = compile_scenario(scenarios()["long_table"])
    output = _render(renderer, compiled)
    assert output.pdf.startswith(b"%PDF")
    assert output.warnings == []
    text = pdf_text(output.pdf)
    for index in range(1, 501):
        assert f"Aufgabe {index:03d}" in text
    pages = [page for page in pdf_pages(output.pdf) if page.strip()]
    assert len(pages) > 3
    header = compiled.data["strings"]["col.assignee"]
    for page in pages:
        assert header in page, "Tabellenkopf fehlt auf einer Folgeseite"


def test_repeated_header_and_footer_on_every_page(renderer):
    compiled = compile_scenario(scenarios()["protocol_multipage"])
    pages = [page for page in pdf_pages(_render(renderer, compiled).pdf) if page.strip()]
    content_pages = pages[1:]  # Titelseite ohne Kopf/Fuss
    assert len(content_pages) >= 3
    total = len(content_pages)
    for number, page in enumerate(content_pages, start=1):
        assert "P-2026-07" in page
        assert compiled.data["strings"]["page.of"].replace("{page}", str(number)).replace("{total}", str(total)) in page


def test_first_page_master_differs(renderer):
    pages = [page for page in pdf_pages(_render(renderer, compile_scenario(scenarios()["custom_header"])).pdf) if page.strip()]
    assert len(pages) >= 2
    organization = "MustervereinSeeland"
    assert organization not in normalize(pages[0].split("Fixture-Dokument")[0])  # kein Kopf auf Seite 1
    assert organization in normalize(pages[1])


def test_conditions_repeat_and_disabled_nodes(renderer):
    text = pdf_text(_render(renderer, compile_scenario(scenarios()["conditions"])).pdf)
    assert "SICHTBAR-OFFENE-AUFGABEN" in text
    for hidden in ("VERSTECKT-KEINE-AUFGABEN", "VERSTECKT-BRAND", "VERSTECKT-DEAKTIVIERT"):
        assert hidden not in text
    assert text.count("PERSON:") == 5
    assert "Einladungen zum Sommerfest versenden" in text


def test_unicode_and_emoji_do_not_break_export(renderer):
    text = pdf_text(_render(renderer, compile_scenario(scenarios()["unicode"])).pdf)
    assert "Ħ" in text
    assert "#set $x$" in text


def test_user_content_is_never_evaluated(renderer):
    payload = "#set page(fill: red) #eval(\"1+1\") $x^2$ @ref <lbl> `c` *b* _i_ ] ) }"
    content = {
        "masters": [{"id": "default"}],
        "body": [
            {"type": "text", "id": "a", "role": "title", "content": {"default": [{"t": "text", "v": payload}]}},
            {"type": "rich_text", "id": "b", "markdown": payload},
            {"type": "table", "id": "c", "columns": [{"id": "c1", "header": {"default": [{"t": "text", "v": payload}]}}], "rows": [[payload]]},
            {"type": "list", "id": "d", "items": [payload]},
        ],
    }
    output = _render(renderer, compile_scenario(Scenario(content, document_type="custom")))
    flat = normalize(pdf_text(output.pdf))
    assert flat.count(normalize('#eval("1+1")')) >= 3
    assert normalize("#set page(fill: red)") in flat


def test_all_data_blocks_are_complete(renderer):
    compiled = compile_scenario(scenarios()["all_blocks"])
    flat = normalize(pdf_text(_render(renderer, compiled).pdf))
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

    collect(all_data_blocks())
    assert expected
    missing = [value for value in expected if normalize(value) not in flat]
    assert missing == []


def test_pdf_is_pdfa_2b(renderer):
    output = _render(renderer, compile_scenario(scenarios()["protocol_simple"]))
    assert b"pdfaid:part" in output.pdf
    assert re.search(rb"pdfaid:conformance[=>\"]+B", output.pdf)


def test_preview_returns_limited_png_pages(renderer):
    compiled = compile_scenario(scenarios()["all_blocks"])
    output = asyncio.run(renderer.render_preview(compiled.data, compiled_assets(compiled), max_pages=2))
    assert len(output.pages) == 2
    assert all(page.startswith(b"\x89PNG") for page in output.pages)


def test_failing_node_is_named_with_id(renderer):
    content = {
        "masters": [{"id": "default"}],
        "body": [
            {"type": "text", "id": "good", "content": {"default": [{"t": "text", "v": "ok"}]}},
            {"type": "data_block", "id": "broken", "component": "image"},
        ],
    }
    blocks = {"broken": [{"type": "image", "title": "Kaputtes Bild", "image": {"path": "assets/fehlt.png"}}]}
    compiled = compile_scenario(Scenario(content, blocks, document_type="custom"))
    with pytest.raises(DocumentRenderError) as excinfo:
        _render(renderer, compiled, RenderAssets())
    assert excinfo.value.key == "error.block"
    assert excinfo.value.block_label == "Kaputtes Bild"
    assert excinfo.value.node_id == "broken"
    assert excinfo.value.detail


def test_timeout_is_curated():
    slow = DocumentRenderer(concurrency=1, timeout_seconds=0.001)
    try:
        with pytest.raises(DocumentRenderError) as excinfo:
            compiled = compile_scenario(scenarios()["long_table"])
            _render(slow, compiled)
        assert excinfo.value.key == "error.timeout"
    finally:
        slow.shutdown()


def test_assets_cannot_escape_root(renderer):
    compiled = compile_scenario(scenarios()["protocol_simple"])
    with pytest.raises(DocumentRenderError):
        _render(renderer, compiled, RenderAssets(files={"assets/../../etc/passwd": b"x"}))


def test_uncovered_characters_are_replaced_not_fatal():
    from app.documents.renderer import REPLACEMENT_CHARACTER, font_coverage, sanitize_text

    coverage = font_coverage()
    assert sanitize_text("漢x😀\x07‍", coverage) == f"{REPLACEMENT_CHARACTER}x😀‍"


@pytest.mark.parametrize("preset", ["classic_blue", "graphite", "forest", "bordeaux", "compact"])
@pytest.mark.parametrize("orientation", ["portrait", "landscape"])
def test_every_brand_preset_renders_without_warnings(renderer, preset, orientation):
    from app.documents.brand import BRAND_PRESETS

    content = copy.deepcopy(system("protocol_formal"))
    content["page"] = {"orientation": orientation}
    compiled = compile_scenario(Scenario(content, {"protocol": [all_data_blocks()[0]]}, brand=BRAND_PRESETS[preset]))
    output = _render(renderer, compiled)
    assert output.pdf.startswith(b"%PDF") and output.warnings == []


@pytest.mark.parametrize("heading_style", ["plain", "underline", "bar", "boxed"])
@pytest.mark.parametrize("table_style", ["lines", "grid", "zebra", "minimal"])
def test_heading_and_table_styles_render(renderer, heading_style, table_style):
    compiled = compile_scenario(Scenario(system("protocol_compact"), {"protocol": [all_data_blocks()[0], {"type": "protocol_element", "title": "T", "children": [{**all_data_blocks()[10], "level": 2}]}]}, brand={"layout": {"heading_style": heading_style, "table_style": table_style}}))
    assert _render(renderer, compiled).warnings == []


def test_png_with_page_limit_rasterizes_only_those_pages_but_reports_all(monkeypatch):
    """STUDIO-015: Thumbnails/Vorschau rastern nur die angeforderten Seiten über das PDF und
    melden trotzdem die Gesamtzahl der Seiten."""
    from app.documents import renderer as renderer_module

    calls: list[int] = []
    original = renderer_module._rasterize

    def counting(pdf, *, ppi, max_pages):
        pages, total = original(pdf, ppi=ppi, max_pages=max_pages)
        calls.append(len(pages))
        return pages, total

    monkeypatch.setattr(renderer_module, "_rasterize", counting)
    pdf = _three_page_pdf()
    pages, total = renderer_module._rasterize(pdf, ppi=30, max_pages=1)
    assert len(pages) == 1 and total == 3 and pages[0].startswith(b"\x89PNG")
    assert calls == [1]


def _three_page_pdf() -> bytes:
    import io

    from pypdf import PdfWriter

    writer = PdfWriter()
    for _ in range(3):
        writer.add_blank_page(width=200, height=200)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


# ── Aus feat/document-engine-typst übernommen (TYPST-005/-009), auf das Studio-Dokumentformat portiert ──


def _three_nodes(count: int = 3) -> dict:
    return {
        "strings": {},
        "masters": {},
        "title_page": None,
        "segments": [{"master": None, "nodes": [{"t": "text", "id": f"n{index}"} for index in range(count)]}],
    }


def test_diagnosis_stops_at_first_failed_probe(monkeypatch):
    """TYPST-009: scheitert ein Probe-Compile selbst (Timeout, Worker weg), bricht
    die Fehlersuche ab, statt bis zu 80 weitere Compiles anzustossen."""
    from app.documents.renderer import CompileResult

    renderer = DocumentRenderer(concurrency=1)
    calls = []

    async def fake_run(document_json, assets, fmt, ppi, max_pages=None, **slot):
        calls.append(fmt)
        if len(calls) == 1:
            return CompileResult(ok=False, error="kaputt")
        raise DocumentRenderError("error.timeout")

    monkeypatch.setattr(renderer, "_run", fake_run)
    with pytest.raises(DocumentRenderError) as excinfo:
        asyncio.run(renderer.render_pdf(_three_nodes(), RenderAssets()))
    assert excinfo.value.key == "error.render" and excinfo.value.detail
    assert len(calls) == 2


def test_diagnosis_respects_time_budget(monkeypatch):
    """TYPST-009: die Fehlersuche endet nach dem Zeitbudget (2 × Timeout)."""
    from app.documents import renderer as renderer_module
    from app.documents.renderer import CompileResult

    renderer = DocumentRenderer(concurrency=1, timeout_seconds=0.05)
    monkeypatch.setattr(renderer_module, "_MAX_DIAGNOSE_COMPILES", 10_000)
    calls = []

    async def failing_run(document_json, assets, fmt, ppi, max_pages=None, **slot):
        calls.append(fmt)
        await asyncio.sleep(0.04)
        return CompileResult(ok=False, error="kaputt")

    monkeypatch.setattr(renderer, "_run", failing_run)
    with pytest.raises(DocumentRenderError):
        asyncio.run(renderer.render_pdf(_three_nodes(60), RenderAssets()))
    # 1 Haupt-Compile + höchstens ~3 Proben à 40 ms im Budget von 100 ms
    assert len(calls) <= 5


def test_queue_wait_is_bounded():
    """TYPST-005: ohne freien Compile-Platz gibt es nach der Wartezeit error.busy (HTTP 503)
    statt einer unbegrenzten Warteschlange."""
    renderer = DocumentRenderer(concurrency=1, queue_timeout_seconds=0.05)

    async def scenario():
        await renderer._acquire_slot()  # einziger Platz belegt
        with pytest.raises(DocumentRenderError) as excinfo:
            await renderer._acquire_slot()
        assert renderer._compile_slots().running == 1  # Abbruch gibt keinen fremden Platz frei
        return excinfo.value.key

    assert asyncio.run(scenario()) == "error.busy"


class _FakeProcess:
    def __init__(self):
        self.alive = True
        self.exitcode = None

    def is_alive(self):
        return self.alive


class _FakeWorker:
    """Steht für einen Typst-Prozess: antwortet erst, wenn der Test es freigibt."""

    instances: list = []

    def __init__(self, memory_limit_bytes=0):
        import queue

        self.task_queue = queue.Queue()
        self.result_queue = queue.Queue()
        self.process = _FakeProcess()
        self.compiles = 0
        self.killed = False
        _FakeWorker.instances.append(self)

    def kill(self):
        self.killed = True
        self.process.alive = False

    def answer(self, result):
        self.result_queue.put(result)


@pytest.fixture
def fake_workers(monkeypatch):
    from app.documents import renderer as renderer_module

    _FakeWorker.instances = []
    monkeypatch.setattr(renderer_module, "_RenderWorker", _FakeWorker)
    monkeypatch.setattr(renderer_module, "_POLL_SECONDS", 0.01)
    return _FakeWorker.instances


async def _until(predicate, timeout=2.0):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        assert loop.time() < deadline, "Bedingung nicht erreicht"
        await asyncio.sleep(0.01)


def test_cancelled_preview_keeps_the_slot_until_the_compile_finished(fake_workers):
    """TYPST-005: Ein abgebrochener Request gibt seinen Compile-Platz erst frei, wenn der Prozess
    fertig ist - sonst liefen mehr Compiles parallel als erlaubt."""
    from app.documents import renderer as renderer_module

    renderer = renderer_module.DocumentRenderer(concurrency=1, timeout_seconds=30, memory_limit_mb=512)

    async def scenario():
        task = asyncio.ensure_future(renderer._run("{}", renderer_module.RenderAssets(), "png", 40, 1))
        await _until(lambda: fake_workers)
        task.cancel()
        await asyncio.sleep(0.05)
        assert renderer._compile_slots().locked(), "Platz wurde vor Ende des Compiles freigegeben"
        fake_workers[0].answer(renderer_module.CompileResult(ok=True, output=[]))
        await _until(lambda: not renderer._compile_slots().locked())

    asyncio.run(scenario())
    renderer.shutdown()


def test_timeout_kills_only_the_hanging_worker(fake_workers):
    """CONC-004: ein hängender Compile beendet nur seinen eigenen Prozess; ein paralleler Compile
    (anderer Mandant) läuft zu Ende, statt mit dem ganzen Pool abgebrochen zu werden."""
    from app.documents import renderer as renderer_module

    renderer = renderer_module.DocumentRenderer(concurrency=2, timeout_seconds=0.3, memory_limit_mb=512)

    async def scenario():
        hanging = asyncio.ensure_future(renderer._run("{}", renderer_module.RenderAssets(), "pdf", None, tenant_id=1))
        await _until(lambda: len(fake_workers) == 1)
        healthy = asyncio.ensure_future(renderer._run("{}", renderer_module.RenderAssets(), "pdf", None, tenant_id=2))
        await _until(lambda: len(fake_workers) == 2)
        with pytest.raises(DocumentRenderError) as excinfo:
            await hanging
        assert excinfo.value.key == "error.timeout"
        assert fake_workers[0].killed and not fake_workers[1].killed
        fake_workers[1].answer(renderer_module.CompileResult(ok=True, output=b"%PDF"))
        assert (await healthy).ok
        assert not renderer._compile_slots().locked()

    asyncio.run(scenario())
    # Der gesunde Worker kommt zurück in den Pool, der beendete nie.
    assert renderer._idle == [fake_workers[1]]
    renderer.shutdown()


def test_crashed_worker_is_replaced(fake_workers):
    from app.documents import renderer as renderer_module

    renderer = renderer_module.DocumentRenderer(concurrency=1, timeout_seconds=5, memory_limit_mb=512)

    async def scenario():
        task = asyncio.ensure_future(renderer._run("{}", renderer_module.RenderAssets(), "pdf", None))
        await _until(lambda: fake_workers)
        fake_workers[0].process.alive = False  # z. B. RLIMIT_AS / OOM-Killer
        with pytest.raises(DocumentRenderError) as excinfo:
            await task
        assert excinfo.value.key == "error.render"
        assert renderer._idle == []

    asyncio.run(scenario())
    renderer.shutdown()


def test_free_slots_go_to_exports_first_then_to_the_least_busy_tenant():
    from app.documents import renderer as renderer_module

    slots = renderer_module._CompileSlots(1)
    order = []

    async def wait(name, priority, tenant_id):
        await slots.acquire(priority=priority, tenant_id=tenant_id, timeout=2)
        order.append(name)

    async def scenario():
        await slots.acquire(priority=renderer_module.PRIORITY_PREVIEW, tenant_id=1, timeout=1)  # Mandant 1 belegt den Platz
        tasks = [
            asyncio.ensure_future(wait("thumbnail-2", renderer_module.PRIORITY_THUMBNAIL, 2)),
            asyncio.ensure_future(wait("preview-1", renderer_module.PRIORITY_PREVIEW, 1)),
            asyncio.ensure_future(wait("preview-2", renderer_module.PRIORITY_PREVIEW, 2)),
            asyncio.ensure_future(wait("export-3", renderer_module.PRIORITY_EXPORT, 3)),
        ]
        await asyncio.sleep(0.01)
        # Bei der ersten Freigabe hat Mandant 1 noch einen laufenden Compile
        slots.release(1)
        for _ in range(3):
            await asyncio.sleep(0.01)
            last = order[-1]
            slots.release(int(last.rsplit("-", 1)[1]))
        await asyncio.gather(*tasks)

    asyncio.run(scenario())
    assert order == ["export-3", "preview-1", "preview-2", "thumbnail-2"]


def test_tenant_with_running_compiles_waits_behind_others():
    from app.documents import renderer as renderer_module

    slots = renderer_module._CompileSlots(2)
    order = []

    async def wait(name, tenant_id):
        await slots.acquire(priority=renderer_module.PRIORITY_PREVIEW, tenant_id=tenant_id, timeout=2)
        order.append(name)

    async def scenario():
        await slots.acquire(priority=renderer_module.PRIORITY_PREVIEW, tenant_id=1, timeout=1)
        await slots.acquire(priority=renderer_module.PRIORITY_PREVIEW, tenant_id=2, timeout=1)
        first = asyncio.ensure_future(wait("tenant-1-again", 1))   # früher angekommen
        await asyncio.sleep(0.01)
        second = asyncio.ensure_future(wait("tenant-3", 3))
        await asyncio.sleep(0.01)
        slots.release(2)  # Mandant 1 hat noch einen laufenden, Mandant 3 keinen
        await asyncio.sleep(0.01)
        slots.release(1)
        await asyncio.gather(first, second)

    asyncio.run(scenario())
    assert order == ["tenant-3", "tenant-1-again"]


def test_real_worker_renders_and_is_reused(renderer):
    """Echter Typst-Prozess: zwei Compiles nacheinander laufen im selben Worker."""
    compiled = compile_scenario(scenarios()["long_table"])
    _render(renderer, compiled)
    workers = list(renderer._idle)
    _render(renderer, compiled)
    assert workers and renderer._idle == workers and workers[0].compiles >= 2
