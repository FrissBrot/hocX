"""Typst-Rendering der Dokument-Engine.

Ablauf pro Compile (in einem Worker-Prozess, siehe ``_compile_job``):

1. Frisches Temp-Verzeichnis. Compile-Root ist ``<tmp>/root`` und enthält nur die Typst-Module
   (``typst/``), ``document.json`` (Ausgabe des Layout-Compilers) und die Bilder unter
   ``assets/``. Typst kann ausserhalb des Roots nichts lesen.
2. Schriften: die mitgelieferten aus ``fonts/`` (pro Worker einmal geladen) plus hochgeladene
   Mandantenschriften in ``<tmp>/fonts`` (ausserhalb des Roots). Keine Systemschriften, damit
   Dev, CI und Produktion identisch rendern.
3. Pakete: ``package_path`` zeigt auf die vendorten Pakete im Repo, der Download-Cache auf ein
   leeres Temp-Verzeichnis. Die Module importieren nur vendorte Pakete
   (``scripts/check-document-catalog.py`` prüft das), Benutzerinhalt wird nie zu Code - der
   Compile greift also nie aufs Netz zu.

Grenzen wie beim früheren TeX-basierten Compile: Parallelitätslimit (Semaphore + Poolgrösse),
Wall-Clock-Timeout pro Compile (danach wird nur dieser Worker-Prozess beendet und ersetzt) und ein
Speicherlimit (``RLIMIT_AS``) pro Worker. Ein CPU-Limit pro Prozess entfällt bewusst: es würde
sich über die Lebensdauer eines Workers aufsummieren.
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import multiprocessing
import resource
import shutil
import tempfile
import threading
import unicodedata
import queue as queue_module
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from app.core.config import settings

logger = logging.getLogger(__name__)

PACKAGE_ROOT = Path(__file__).resolve().parent
TYPST_DIR = PACKAGE_ROOT / "typst"
FONTS_DIR = PACKAGE_ROOT / "fonts"
PACKAGES_DIR = PACKAGE_ROOT / "typst_packages"

PDF_STANDARD = "a-2b"
PREVIEW_PPI = 96
# Höchstens so viele Compiles, um einen fehlerhaften Knoten zu finden.
_MAX_DIAGNOSE_COMPILES = 80
# ... und höchstens so viele Compile-Timeouts an Gesamtzeit.
_DIAGNOSE_TIME_FACTOR = 2

OutputFormat = Literal["pdf", "png"]


@dataclass
class RenderAssets:
    """Dateien für den Compile. ``files``: Pfad im Root (``assets/<name>``) → Inhalt.
    ``fonts``: Dateiname → Inhalt (hochgeladene Mandantenschriften)."""

    files: dict[str, bytes] = field(default_factory=dict)
    fonts: dict[str, bytes] = field(default_factory=dict)


@dataclass
class CompileResult:
    ok: bool
    output: bytes | list[bytes] | None = None
    warnings: list[str] = field(default_factory=list)
    error: str | None = None
    hints: list[str] = field(default_factory=list)
    trace: list[str] = field(default_factory=list)
    # Gesamtzahl der Seiten, wenn nur ein Teil gerastert wurde
    page_count: int | None = None


@dataclass
class RenderOutput:
    pdf: bytes | None = None
    pages: list[bytes] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    # Seiten insgesamt (PNG-Vorschau liefert höchstens max_pages davon)
    page_count: int = 0


class DocumentRenderError(Exception):
    """Kuratierter Renderfehler. ``key`` ist ein Text-Schlüssel aus documentPdf (error.*),
    ``block_label`` der Name des verursachenden Knotens, ``node_id`` seine ID (Fehlerhinweis am
    Element im Designer), ``detail`` die Typst-Diagnose fürs Admin-Log (nie für Benutzer)."""

    def __init__(self, key: str, *, block_label: str | None = None, node_id: str | None = None, detail: str | None = None) -> None:
        super().__init__(detail or key)
        self.key = key
        self.block_label = block_label
        self.node_id = node_id
        self.detail = detail


# ── Zeichenabdeckung ─────────────────────────────────────────────────────────
#
# PDF/A verbietet Zeichen ohne Glyphe. Damit beliebiges Unicode (z. B. CJK, für das keine Schrift
# mitgeliefert wird) nie einen Export abbricht, ersetzt der Worker vor dem Compile jedes Zeichen,
# das keine verfügbare Schrift abdeckt, durch U+FFFD. Formatzeichen (ZWJ, Variantenselektoren,
# Emoji-Tags) bleiben erhalten; die Typst-Formung behandelt sie selbst.

REPLACEMENT_CHARACTER = "\ufffd"
_COVERAGE_CACHE: dict[tuple[str, ...], frozenset[int]] = {}


def font_coverage(extra_font_files: tuple[str, ...] = (), cache_key: tuple[str, ...] = ()) -> frozenset[int]:
    """Alle Codepoints der mitgelieferten (und optional hochgeladenen) Schriften. Gecacht pro
    Worker; ``cache_key`` identifiziert hochgeladene Schriften über ihren Inhalt."""
    key = cache_key
    if key not in _COVERAGE_CACHE:
        from fontTools.ttLib import TTFont

        codepoints: set[int] = set()
        files = sorted(str(path) for path in FONTS_DIR.iterdir() if path.suffix.lower() in (".ttf", ".otf")) + list(extra_font_files)
        for path in files:
            try:
                font = TTFont(path, lazy=True, fontNumber=0)
                codepoints.update(font.getBestCmap() or {})
                font.close()
            except Exception:  # noqa: BLE001 - unlesbare Mandantenschrift deckt nichts ab
                logger.warning("Schrift ohne lesbare cmap: %s", path)
        _COVERAGE_CACHE[key] = frozenset(codepoints)
    return _COVERAGE_CACHE[key]


def sanitize_text(value: str, coverage: frozenset[int]) -> str:
    out: list[str] = []
    for character in value:
        code = ord(character)
        if character in "\n\t" or code in coverage:
            out.append(character)
            continue
        category = unicodedata.category(character)
        if category == "Cf":
            out.append(character)
        elif category in ("Cc", "Cs", "Co", "Cn"):
            # Steuerzeichen, Surrogate, private und nicht zugewiesene Zeichen entfallen.
            continue
        else:
            out.append(REPLACEMENT_CHARACTER)
    return "".join(out)


def sanitize_document_json(document_json: str, coverage: frozenset[int]) -> str:
    def walk(value):
        if isinstance(value, str):
            return sanitize_text(value, coverage)
        if isinstance(value, list):
            return [walk(item) for item in value]
        if isinstance(value, dict):
            return {key: walk(item) for key, item in value.items()}
        return value

    return json.dumps(walk(json.loads(document_json)), ensure_ascii=False)


# ── Worker ───────────────────────────────────────────────────────────────────

_WORKER_FONTS = None


def _init_worker(memory_limit_bytes: int) -> None:
    global _WORKER_FONTS
    if memory_limit_bytes > 0:
        resource.setrlimit(resource.RLIMIT_AS, (memory_limit_bytes, memory_limit_bytes))
    import typst

    _WORKER_FONTS = typst.Fonts(include_system_fonts=False, include_embedded_fonts=True, font_paths=[str(FONTS_DIR)])


def _safe_name(name: str) -> str:
    candidate = Path(name)
    if candidate.is_absolute() or ".." in candidate.parts or len(candidate.parts) != 1:
        raise ValueError(f"unzulässiger Dateiname: {name!r}")
    return candidate.name


def _rasterize(pdf: bytes, *, ppi: float, max_pages: int) -> tuple[list[bytes], int]:
    """Nur die ersten ``max_pages`` Seiten als PNG und die Gesamtzahl der Seiten (STUDIO-015):
    typst-py rastert sonst immer alle Seiten - ein Thumbnail kostete den ganzen Satz."""
    import pypdfium2

    document = pypdfium2.PdfDocument(pdf)
    try:
        pages: list[bytes] = []
        for index in range(min(max_pages, len(document))):
            page = document[index]
            try:
                image = page.render(scale=ppi / 72).to_pil()
            finally:
                page.close()
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            pages.append(buffer.getvalue())
        return pages, len(document)
    finally:
        document.close()


def _compile_job(
    document_json: str, files: dict[str, bytes], fonts: dict[str, bytes], fmt: str, ppi: float | None, max_pages: int | None = None,
) -> CompileResult:
    import typst

    global _WORKER_FONTS
    if _WORKER_FONTS is None:
        _WORKER_FONTS = typst.Fonts(include_system_fonts=False, include_embedded_fonts=True, font_paths=[str(FONTS_DIR)])

    with tempfile.TemporaryDirectory(prefix="hocx-doc-") as tmp:
        tmp_path = Path(tmp)
        root = tmp_path / "root"
        if fonts:
            custom_dir = tmp_path / "fonts"
            custom_dir.mkdir()
            for name, content in fonts.items():
                (custom_dir / _safe_name(name)).write_bytes(content)
        shutil.copytree(TYPST_DIR, root / "typst", ignore=shutil.ignore_patterns("__pycache__"))
        custom_fonts = tuple(str(tmp_path / "fonts" / _safe_name(name)) for name in fonts)
        coverage_key = tuple(sorted(hashlib.sha256(content).hexdigest() for content in fonts.values()))
        document_json = sanitize_document_json(document_json, font_coverage(custom_fonts, coverage_key))
        (root / "document.json").write_text(document_json, encoding="utf-8")
        assets_dir = root / "assets"
        assets_dir.mkdir()
        for name, content in files.items():
            relative = Path(name)
            if relative.parts[:1] != ("assets",) or len(relative.parts) != 2:
                return CompileResult(ok=False, error=f"unzulässiger Asset-Pfad: {name}")
            (assets_dir / _safe_name(relative.parts[1])).write_bytes(content)

        font_source = _WORKER_FONTS
        if fonts:
            custom_dir = tmp_path / "fonts"
            font_source = typst.Fonts(
                include_system_fonts=False,
                include_embedded_fonts=True,
                font_paths=[str(FONTS_DIR), str(custom_dir)],
            )

        cache_dir = tmp_path / "package-cache"
        cache_dir.mkdir()
        compiler = typst.Compiler(
            str(root / "typst" / "main.typ"),
            root=str(root),
            font_paths=font_source,
            ignore_system_fonts=True,
            package_path=str(PACKAGES_DIR),
            package_cache_path=str(cache_dir),
        )
        # Vorschau mit Seitenlimit: einmal als PDF kompilieren und nur die nötigen Seiten rastern.
        rasterize_pages = fmt == "png" and max_pages is not None
        try:
            rasterize_pages = fmt == "png" and max_pages is not None
            output, warnings = compiler.compile_with_warnings(
                format="pdf" if rasterize_pages else fmt,
                ppi=None if rasterize_pages else ppi,
                pdf_standards=[PDF_STANDARD] if fmt == "pdf" else [],
                timestamp=datetime.now(UTC).replace(microsecond=0),
            )
            page_count = None
            if rasterize_pages:
                output, page_count = _rasterize(output, ppi=ppi or PREVIEW_PPI, max_pages=max_pages)
        except typst.TypstError as exc:
            return CompileResult(
                ok=False,
                error=getattr(exc, "message", str(exc)),
                hints=list(getattr(exc, "hints", []) or []),
                trace=list(getattr(exc, "trace", []) or []),
            )
        except Exception as exc:  # noqa: BLE001 - Diagnose wird als Daten zurückgegeben
            return CompileResult(ok=False, error=f"{type(exc).__name__}: {exc}")
        return CompileResult(ok=True, output=output, warnings=[getattr(w, "message", str(w)) for w in warnings], page_count=page_count)


# ── Pool ─────────────────────────────────────────────────────────────────────
#
# Eigene Worker-Prozesse statt ProcessPoolExecutor (Concurrency-Audit CONC-004): ein Executor
# kann einen einzelnen hängenden Compile nicht beenden - bisher wurde nach einem Timeout der
# ganze Pool zurückgesetzt und damit jeder parallele Compile (auch anderer Mandanten)
# abgebrochen. Jetzt wird nur der betroffene Prozess beendet und ersetzt (Muster wie
# ``services/isolated_parse.py``).

# Prioritäten der Compile-Plätze (kleiner = zuerst): Export vor Vorschau vor Thumbnail.
PRIORITY_EXPORT = 0
PRIORITY_PREVIEW = 1
PRIORITY_THUMBNAIL = 2

# Native Allokationen (Typst, pdfium) gehen nicht immer an das System zurück: Worker nach so
# vielen Compiles ersetzen, damit sich der Speicher nicht bis zum RLIMIT_AS aufsummiert.
MAX_COMPILES_PER_WORKER = 50
_POLL_SECONDS = 0.25
_ENV_ALLOWLIST = {"PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "TMP", "TZ"}
_mp_context = multiprocessing.get_context("spawn")


def _worker_loop(task_queue, result_queue, memory_limit_bytes: int) -> None:
    """Läuft im Kindprozess: ein Compile pro Auftrag, bis ``None`` kommt oder der Elternprozess
    den Prozess beendet (Timeout)."""
    import os

    _init_worker(memory_limit_bytes)
    # Der Compile braucht keine Zugangsdaten; spawn vererbt aber die ganze Umgebung des
    # Backends. Nach den Imports auf das Nötigste kürzen - das ist nur Schadensbegrenzung, keine
    # Isolation: /proc/self/environ, die importierten settings und *_FILE-Secrets bleiben im
    # Prozess erreichbar. Der eigentliche Schutz ist, dass Typst nur das Compile-Root liest und
    # Benutzerinhalt nie Code wird (siehe Moduldokumentation).
    for key in list(os.environ):
        if key not in _ENV_ALLOWLIST:
            del os.environ[key]
    while True:
        task = task_queue.get()
        if task is None:
            return
        try:
            result_queue.put(_compile_job(*task))
        except BaseException as exc:  # noqa: BLE001 - der Prozess darf nicht stumm sterben
            result_queue.put(CompileResult(ok=False, error=f"{type(exc).__name__}: {exc}"))


class _RenderWorker:
    def __init__(self, memory_limit_bytes: int) -> None:
        # spawn statt fork: der Backend-Prozess ist multithreaded (uvicorn, Hintergrund-Loops);
        # ein Fork könnte gehaltene Locks mitkopieren.
        self.task_queue = _mp_context.Queue()
        self.result_queue = _mp_context.Queue()
        self.process = _mp_context.Process(target=_worker_loop, args=(self.task_queue, self.result_queue, memory_limit_bytes), daemon=True)
        self.process.start()
        self.compiles = 0

    def kill(self) -> None:
        self.process.terminate()
        self.process.join(2)
        if self.process.is_alive():
            self.process.kill()
            self.process.join()
        for queue in (self.task_queue, self.result_queue):
            queue.cancel_join_thread()
            queue.close()


class _CompileTimeout(Exception):
    pass


class _WorkerDied(Exception):
    pass


class _CompileSlots:
    """Begrenzte Compile-Plätze je Event-Loop mit Vorrang: zuerst nach Priorität, dann der
    Mandant mit den wenigsten laufenden Compiles, dann in Ankunftsreihenfolge. Ein Mandant
    mit vielen Vorschauen belegt so nicht alle Plätze, während andere warten; ist niemand
    sonst da, nutzt er alle."""

    def __init__(self, capacity: int) -> None:
        self.capacity = capacity
        self.running = 0
        self._per_tenant: dict[int | None, int] = {}
        self._waiters: list[tuple[int, int, int | None, asyncio.Future]] = []
        self._sequence = 0

    def locked(self) -> bool:
        return self.running >= self.capacity

    def _take(self, tenant_id: int | None) -> None:
        self.running += 1
        self._per_tenant[tenant_id] = self._per_tenant.get(tenant_id, 0) + 1

    async def acquire(self, *, priority: int, tenant_id: int | None, timeout: float) -> None:
        if self.running < self.capacity and not self._waiters:
            self._take(tenant_id)
            return
        future = asyncio.get_running_loop().create_future()
        self._sequence += 1
        entry = (priority, self._sequence, tenant_id, future)
        self._waiters.append(entry)
        try:
            await asyncio.wait_for(future, timeout=timeout)
        except BaseException:
            if entry in self._waiters:
                self._waiters.remove(entry)
            if future.done() and not future.cancelled():
                # Platz wurde gerade noch zugeteilt - zurückgeben.
                self.release(tenant_id)
            raise

    def release(self, tenant_id: int | None) -> None:
        self.running -= 1
        remaining = self._per_tenant.get(tenant_id, 1) - 1
        if remaining > 0:
            self._per_tenant[tenant_id] = remaining
        else:
            self._per_tenant.pop(tenant_id, None)
        self._dispatch()

    def _dispatch(self) -> None:
        while self.running < self.capacity and self._waiters:
            entry = min(self._waiters, key=lambda item: (item[0], self._per_tenant.get(item[2], 0), item[1]))
            self._waiters.remove(entry)
            future = entry[3]
            if future.done():
                continue
            self._take(entry[2])
            future.set_result(None)


class DocumentRenderer:
    def __init__(
        self,
        *,
        concurrency: int | None = None,
        timeout_seconds: float | None = None,
        memory_limit_mb: int | None = None,
        queue_timeout_seconds: float | None = None,
    ) -> None:
        self.concurrency = max(1, concurrency or settings.document_render_concurrency)
        self.timeout_seconds = timeout_seconds or settings.document_render_timeout_seconds
        self.queue_timeout_seconds = queue_timeout_seconds or settings.document_render_queue_timeout_seconds
        self.memory_limit_bytes = int(memory_limit_mb if memory_limit_mb is not None else settings.document_render_memory_limit_mb) * 1024 * 1024
        self._idle: list[_RenderWorker] = []
        self._lock = threading.Lock()
        self._closed = False
        self._slots: dict[int, _CompileSlots] = {}
        # Eigene Threads für das blockierende Warten auf die Worker (nicht der Default-Executor
        # des Loops, den die Laufzeitkennzahlen als Warteschlange messen).
        self._threads = ThreadPoolExecutor(max_workers=self.concurrency * 2, thread_name_prefix="typst-wait")

    # ── Worker ──

    def _checkout(self) -> _RenderWorker:
        with self._lock:
            if self._idle:
                return self._idle.pop()
        return _RenderWorker(self.memory_limit_bytes)

    def _checkin(self, worker: _RenderWorker) -> None:
        with self._lock:
            if not self._closed and worker.compiles < MAX_COMPILES_PER_WORKER and len(self._idle) < self.concurrency:
                self._idle.append(worker)
                return
        worker.kill()

    def _execute(self, task: tuple) -> CompileResult:
        """Blockierend (eigener Thread): einen Compile auf einem Worker ausführen. Ein Worker,
        der nicht rechtzeitig antwortet oder abstürzt, wird beendet und nie wiederverwendet -
        andere laufende Compiles bleiben unberührt."""
        worker = self._checkout()
        worker.task_queue.put(task)
        deadline = time.monotonic() + self.timeout_seconds
        while True:
            try:
                result = worker.result_queue.get(timeout=_POLL_SECONDS)
                break
            except queue_module.Empty:
                if not worker.process.is_alive():
                    exitcode = worker.process.exitcode
                    worker.kill()
                    raise _WorkerDied(f"Exitcode {exitcode}") from None
                if time.monotonic() >= deadline:
                    worker.kill()
                    raise _CompileTimeout from None
        worker.compiles += 1
        self._checkin(worker)
        return result

    def shutdown(self) -> None:
        with self._lock:
            self._closed = True
            idle, self._idle = self._idle, []
        for worker in idle:
            worker.kill()
        self._threads.shutdown(wait=False, cancel_futures=True)

    # ── Plätze ──

    def _compile_slots(self) -> _CompileSlots:
        loop = asyncio.get_running_loop()
        key = id(loop)
        if key not in self._slots:
            self._slots[key] = _CompileSlots(self.concurrency)
        return self._slots[key]

    async def _acquire_slot(self, *, priority: int = PRIORITY_PREVIEW, tenant_id: int | None = None) -> _CompileSlots:
        """Freien Compile-Platz holen; die Warteschlange ist zeitlich begrenzt, damit sich bei
        vielen gleichzeitigen Vorschauen keine Requests unbegrenzt stauen."""
        slots = self._compile_slots()
        try:
            await slots.acquire(priority=priority, tenant_id=tenant_id, timeout=self.queue_timeout_seconds)
        except asyncio.TimeoutError as exc:
            raise DocumentRenderError("error.busy", detail=f"Kein freier Compile-Platz nach {self.queue_timeout_seconds}s") from exc
        return slots

    async def _run(
        self, document_json: str, assets: RenderAssets, fmt: OutputFormat, ppi: float | None, max_pages: int | None = None,
        *, priority: int = PRIORITY_PREVIEW, tenant_id: int | None = None,
    ) -> CompileResult:
        slots = await self._acquire_slot(priority=priority, tenant_id=tenant_id)
        release_on_done = False
        try:
            loop = asyncio.get_running_loop()
            future = loop.run_in_executor(self._threads, self._execute, (document_json, assets.files, assets.fonts, fmt, ppi, max_pages))
            try:
                # shield: ein Abbruch des Requests (Vorschau ersetzt durch neuere) bricht nur das
                # Warten ab; der Compile-Platz bleibt belegt, bis der Prozess wirklich fertig ist.
                # Das Warten selbst endet spätestens nach timeout_seconds (_execute).
                return await asyncio.shield(future)
            except asyncio.CancelledError:
                release_on_done = True
                future.add_done_callback(lambda _: slots.release(tenant_id))
                raise
            except _CompileTimeout as exc:
                raise DocumentRenderError("error.timeout", detail=f"Typst-Compile nach {self.timeout_seconds}s abgebrochen") from exc
            except _WorkerDied as exc:
                # Worker abgestürzt (z. B. Speicherlimit)
                raise DocumentRenderError("error.render", detail=f"Typst-Worker beendet: {exc}") from exc
        finally:
            if not release_on_done:
                slots.release(tenant_id)

    async def render(
        self, document: dict, assets: RenderAssets | None = None, *, fmt: OutputFormat = "pdf", max_pages: int | None = None, ppi: float | None = None,
        priority: int | None = None, tenant_id: int | None = None,
    ) -> RenderOutput:
        """``priority``: Vorrang beim Compile-Platz (Default: PDF = Export, PNG = Vorschau);
        ``tenant_id``: Fairness zwischen Mandanten beim Warten auf einen Platz."""
        assets = assets or RenderAssets()
        if priority is None:
            priority = PRIORITY_EXPORT if fmt == "pdf" else PRIORITY_PREVIEW
        slot = {"priority": priority, "tenant_id": tenant_id}
        result = await self._run(_dump(document), assets, fmt, ppi if fmt == "png" else None, max_pages if fmt == "png" else None, **slot)
        if not result.ok:
            located = await self._locate_failing_node(document, assets, slot)
            detail = _format_diagnostic(result)
            if located is not None:
                raise DocumentRenderError("error.block", block_label=located[1], node_id=located[0], detail=detail)
            raise DocumentRenderError("error.render", detail=detail)
        if fmt == "pdf":
            return RenderOutput(pdf=result.output if isinstance(result.output, bytes) else None, warnings=result.warnings)
        pages = result.output if isinstance(result.output, list) else [result.output] if result.output else []
        total = result.page_count if result.page_count is not None else len(pages)
        if max_pages is not None:
            pages = pages[:max_pages]
        return RenderOutput(pages=list(pages), warnings=result.warnings, page_count=total)

    async def render_pdf(self, document: dict, assets: RenderAssets | None = None, *, tenant_id: int | None = None) -> RenderOutput:
        return await self.render(document, assets, fmt="pdf", tenant_id=tenant_id)

    async def render_preview(
        self, document: dict, assets: RenderAssets | None = None, *, max_pages: int | None = None, ppi: float = PREVIEW_PPI, tenant_id: int | None = None,
    ) -> RenderOutput:
        return await self.render(document, assets, fmt="png", max_pages=max_pages or settings.document_preview_max_pages, ppi=ppi, tenant_id=tenant_id)

    async def _locate_failing_node(self, document: dict, assets: RenderAssets, slot: dict | None = None) -> tuple[str, str] | None:
        """Kompiliert die Knoten der obersten Ebene (und bei Fachkomponenten deren Blöcke)
        einzeln, um den Verursacher eines Fehlers zu finden: (Knoten-ID, Bezeichnung)."""
        budget = _MAX_DIAGNOSE_COMPILES
        # Gesamtzeit der Diagnose begrenzen (sonst bis 80 × Timeout für einen Request).
        loop = asyncio.get_running_loop()
        deadline = loop.time() + _DIAGNOSE_TIME_FACTOR * self.timeout_seconds
        strings = document.get("strings", {})

        def label(node: dict) -> str:
            if node.get("t") == "data":
                blocks = node.get("blocks") or [{}]
                first = blocks[0]
                return (first.get("title") or "").strip() or strings.get(f"blockType.{first.get('type')}", str(first.get("type")))
            return strings.get(f"nodeType.{node.get('t')}", str(node.get("t")))

        class _Abort(Exception):
            """Diagnose abbrechen: Probe-Compile selbst gescheitert (Timeout, Worker weg,
            keine freien Plätze) oder Zeitbudget aufgebraucht."""

        async def fails(nodes: list[dict]) -> bool:
            nonlocal budget
            budget -= 1
            if loop.time() >= deadline:
                raise _Abort
            probe = {**document, "title_page": None, "segments": [{"master": None, "nodes": nodes}], "masters": {key: {"header": None, "footer": None, "background": []} for key in document.get("masters", {})}}
            try:
                result = await self._run(_dump(probe), assets, "pdf", None, **(slot or {}))
            except DocumentRenderError as exc:
                # Probe selbst gescheitert (Timeout, Worker weg, kein Platz): weitere Proben
                # kosteten nur Zeit und Plätze anderer Requests. Ohne eindeutigen Befund aufhören.
                raise _Abort from exc
            return not result.ok

        candidates: list[dict] = []
        for segment in document.get("segments", []):
            candidates.extend(segment.get("nodes", []))
        if document.get("title_page"):
            candidates.extend(document["title_page"].get("children", []))
        try:
            for node in candidates:
                if budget <= 0:
                    return None
                if not await fails([node]):
                    continue
                if node.get("t") == "data":
                    for block in node.get("blocks", []):
                        if budget <= 0:
                            break
                        if await fails([{**node, "blocks": [block]}]):
                            return node.get("id", ""), (block.get("title") or "").strip() or label(node)
                return node.get("id", ""), label(node)
        except _Abort:
            logger.info("Fehlersuche im Dokument abgebrochen (Zeitbudget oder Probe-Compile gescheitert)")
            return None
        return None


def _dump(document: dict) -> str:
    return json.dumps(document, ensure_ascii=False)


def _format_diagnostic(result: CompileResult) -> str:
    parts = [result.error or "unbekannter Fehler"]
    parts += [f"hint: {hint}" for hint in result.hints]
    parts += [f"trace: {item}" for item in result.trace]
    return "\n".join(parts)


_renderer: DocumentRenderer | None = None
_renderer_lock = threading.Lock()


def get_renderer() -> DocumentRenderer:
    """Prozessweiter Renderer (ein Worker-Pool pro Backend-Prozess)."""
    global _renderer
    with _renderer_lock:
        if _renderer is None:
            _renderer = DocumentRenderer()
        return _renderer


def shutdown_renderer() -> None:
    global _renderer
    with _renderer_lock:
        renderer, _renderer = _renderer, None
    if renderer is not None:
        renderer.shutdown()
