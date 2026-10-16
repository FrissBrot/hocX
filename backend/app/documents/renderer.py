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
Wall-Clock-Timeout pro Compile (danach wird der Pool beendet und neu gestartet) und ein
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
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
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
        self._executor: ProcessPoolExecutor | None = None
        self._lock = threading.Lock()
        self._semaphores: dict[int, asyncio.Semaphore] = {}

    def _pool(self) -> ProcessPoolExecutor:
        with self._lock:
            if self._executor is None:
                self._executor = ProcessPoolExecutor(
                    max_workers=self.concurrency,
                    # spawn statt fork: der Backend-Prozess ist multithreaded (uvicorn,
                    # Hintergrund-Loops); ein Fork könnte gehaltene Locks mitkopieren.
                    mp_context=multiprocessing.get_context("spawn"),
                    initializer=_init_worker,
                    initargs=(self.memory_limit_bytes,),
                )
            return self._executor

    def _reset_pool(self) -> None:
        """Beendet alle Worker (z. B. nach einem Timeout) - der nächste Compile startet neu."""
        with self._lock:
            executor, self._executor = self._executor, None
        if executor is None:
            return
        for process in list(getattr(executor, "_processes", {}).values()):
            try:
                process.terminate()
            except Exception:  # noqa: BLE001 - Prozess bereits weg
                pass
        executor.shutdown(wait=False, cancel_futures=True)

    def shutdown(self) -> None:
        self._reset_pool()

    def _semaphore(self) -> asyncio.Semaphore:
        loop = asyncio.get_running_loop()
        key = id(loop)
        if key not in self._semaphores:
            self._semaphores[key] = asyncio.Semaphore(self.concurrency)
        return self._semaphores[key]

    async def _acquire_slot(self) -> asyncio.Semaphore:
        """Freien Compile-Platz holen; die Warteschlange ist zeitlich begrenzt, damit sich bei
        vielen gleichzeitigen Vorschauen keine Requests unbegrenzt stauen."""
        semaphore = self._semaphore()
        try:
            await asyncio.wait_for(semaphore.acquire(), timeout=self.queue_timeout_seconds)
        except asyncio.TimeoutError as exc:
            raise DocumentRenderError("error.busy", detail=f"Kein freier Compile-Platz nach {self.queue_timeout_seconds}s") from exc
        return semaphore

    async def _run(
        self, document_json: str, assets: RenderAssets, fmt: OutputFormat, ppi: float | None, max_pages: int | None = None,
    ) -> CompileResult:
        semaphore = await self._acquire_slot()
        release_on_done = False
        try:
            loop = asyncio.get_running_loop()
            future = loop.run_in_executor(self._pool(), _compile_job, document_json, assets.files, assets.fonts, fmt, ppi, max_pages)
            try:
                # shield: ein Abbruch des Requests (Vorschau ersetzt durch neuere) bricht nur das
                # Warten ab; der Compile-Platz bleibt belegt, bis der Prozess wirklich fertig ist.
                return await asyncio.wait_for(asyncio.shield(future), timeout=self.timeout_seconds)
            except asyncio.CancelledError:
                release_on_done = True
                future.add_done_callback(lambda _: semaphore.release())
                raise
            except asyncio.TimeoutError as exc:
                self._reset_pool()
                raise DocumentRenderError("error.timeout", detail=f"Typst-Compile nach {self.timeout_seconds}s abgebrochen") from exc
            except BrokenProcessPool as exc:
                # Worker abgestürzt (z. B. Speicherlimit) oder Pool wegen Timeout eines
                # parallelen Compiles beendet.
                self._reset_pool()
                raise DocumentRenderError("error.render", detail=f"Typst-Worker beendet: {exc}") from exc
        finally:
            if not release_on_done:
                semaphore.release()

    async def render(self, document: dict, assets: RenderAssets | None = None, *, fmt: OutputFormat = "pdf", max_pages: int | None = None, ppi: float | None = None) -> RenderOutput:
        assets = assets or RenderAssets()
        result = await self._run(_dump(document), assets, fmt, ppi if fmt == "png" else None, max_pages if fmt == "png" else None)
        if not result.ok:
            located = await self._locate_failing_node(document, assets)
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

    async def render_pdf(self, document: dict, assets: RenderAssets | None = None) -> RenderOutput:
        return await self.render(document, assets, fmt="pdf")

    async def render_preview(self, document: dict, assets: RenderAssets | None = None, *, max_pages: int | None = None, ppi: float = PREVIEW_PPI) -> RenderOutput:
        return await self.render(document, assets, fmt="png", max_pages=max_pages or settings.document_preview_max_pages, ppi=ppi)

    async def _locate_failing_node(self, document: dict, assets: RenderAssets) -> tuple[str, str] | None:
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
                result = await self._run(_dump(probe), assets, "pdf", None)
            except DocumentRenderError as exc:
                # Ein Timeout setzt den Pool zurück; weitere Proben würden parallele Compiles
                # anderer Requests erneut abbrechen. Ohne eindeutigen Befund aufhören.
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
    """Prozessweiter Renderer (ein Pool pro Backend-Prozess)."""
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
