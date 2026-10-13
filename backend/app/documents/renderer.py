"""Typst-Rendering der Dokument-Engine.

Ablauf pro Compile (in einem Worker-Prozess, siehe ``_compile_job``):

1. Frisches Temp-Verzeichnis. Compile-Root ist ``<tmp>/root`` und enthält nur die Stil-Dateien
   (``styles/``), ``document.json`` und die Bilder unter ``assets/``. Typst kann ausserhalb
   des Roots nichts lesen.
2. Schriften: die mitgelieferten aus ``fonts/`` (pro Worker einmal geladen) plus hochgeladene
   Mandantenschriften in ``<tmp>/fonts`` (ausserhalb des Roots). Keine Systemschriften, damit
   Dev, CI und Produktion identisch rendern.
3. Pakete: ``package_path`` zeigt auf die vendorten Pakete im Repo, der Download-Cache auf ein
   leeres Temp-Verzeichnis. Die Stile importieren nur vendorte Pakete
   (``scripts/check-document-catalog.py`` prüft das), Benutzerinhalt wird nie zu Code - der
   Compile greift also nie aufs Netz zu.

Grenzen wie beim früheren LaTeX-Compile: Parallelitätslimit (Semaphore + Poolgrösse),
Wall-Clock-Timeout pro Compile (danach wird der Pool beendet und neu gestartet) und ein
Speicherlimit (``RLIMIT_AS``) pro Worker. Ein CPU-Limit pro Prozess entfällt bewusst: es würde
sich über die Lebensdauer eines Workers aufsummieren.
"""
from __future__ import annotations

import asyncio
import hashlib
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
from app.documents.model import Document, ProtocolElementBlock

logger = logging.getLogger(__name__)

PACKAGE_ROOT = Path(__file__).resolve().parent
STYLES_DIR = PACKAGE_ROOT / "styles"
FONTS_DIR = PACKAGE_ROOT / "fonts"
PACKAGES_DIR = PACKAGE_ROOT / "typst_packages"

PDF_STANDARD = "a-2b"
PREVIEW_PPI = 96
# Höchstens so viele Compiles, um einen fehlerhaften Block zu finden.
_MAX_DIAGNOSE_COMPILES = 80

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


@dataclass
class RenderOutput:
    pdf: bytes | None = None
    pages: list[bytes] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class DocumentRenderError(Exception):
    """Kuratierter Renderfehler. ``key`` ist ein Text-Schlüssel aus documentPdf (error.*),
    ``block_label`` der Name des verursachenden Blocks, ``detail`` die Typst-Diagnose fürs
    Admin-Log (nie für Benutzer)."""

    def __init__(self, key: str, *, block_label: str | None = None, detail: str | None = None) -> None:
        super().__init__(detail or key)
        self.key = key
        self.block_label = block_label
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


def _compile_job(document_json: str, files: dict[str, bytes], fonts: dict[str, bytes], fmt: str, ppi: float | None) -> CompileResult:
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
        shutil.copytree(STYLES_DIR, root / "styles", ignore=shutil.ignore_patterns("__pycache__"))
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
            str(root / "styles" / "main.typ"),
            root=str(root),
            font_paths=font_source,
            ignore_system_fonts=True,
            package_path=str(PACKAGES_DIR),
            package_cache_path=str(cache_dir),
        )
        try:
            output, warnings = compiler.compile_with_warnings(
                format=fmt,
                ppi=ppi,
                pdf_standards=[PDF_STANDARD] if fmt == "pdf" else [],
                timestamp=datetime.now(UTC).replace(microsecond=0),
            )
        except typst.TypstError as exc:
            return CompileResult(
                ok=False,
                error=getattr(exc, "message", str(exc)),
                hints=list(getattr(exc, "hints", []) or []),
                trace=list(getattr(exc, "trace", []) or []),
            )
        except Exception as exc:  # noqa: BLE001 - Diagnose wird als Daten zurückgegeben
            return CompileResult(ok=False, error=f"{type(exc).__name__}: {exc}")
        return CompileResult(ok=True, output=output, warnings=[getattr(w, "message", str(w)) for w in warnings])


# ── Pool ─────────────────────────────────────────────────────────────────────


class DocumentRenderer:
    def __init__(
        self,
        *,
        concurrency: int | None = None,
        timeout_seconds: float | None = None,
        memory_limit_mb: int | None = None,
    ) -> None:
        self.concurrency = max(1, concurrency or settings.document_render_concurrency)
        self.timeout_seconds = timeout_seconds or settings.document_render_timeout_seconds
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

    async def _run(self, document_json: str, assets: RenderAssets, fmt: OutputFormat, ppi: float | None) -> CompileResult:
        async with self._semaphore():
            loop = asyncio.get_running_loop()
            try:
                future = loop.run_in_executor(self._pool(), _compile_job, document_json, assets.files, assets.fonts, fmt, ppi)
                return await asyncio.wait_for(future, timeout=self.timeout_seconds)
            except asyncio.TimeoutError as exc:
                self._reset_pool()
                raise DocumentRenderError("error.timeout", detail=f"Typst-Compile nach {self.timeout_seconds}s abgebrochen") from exc
            except BrokenProcessPool as exc:
                # Worker abgestürzt (z. B. Speicherlimit) oder Pool wegen Timeout eines
                # parallelen Compiles beendet.
                self._reset_pool()
                raise DocumentRenderError("error.render", detail=f"Typst-Worker beendet: {exc}") from exc

    async def render(self, document: Document, assets: RenderAssets | None = None, *, fmt: OutputFormat = "pdf", max_pages: int | None = None, ppi: float | None = None) -> RenderOutput:
        assets = assets or RenderAssets()
        result = await self._run(_dump(document), assets, fmt, ppi if fmt == "png" else None)
        if not result.ok:
            label = await self._locate_failing_block(document, assets)
            detail = _format_diagnostic(result)
            if label:
                raise DocumentRenderError("error.block", block_label=label, detail=detail)
            raise DocumentRenderError("error.render", detail=detail)
        if fmt == "pdf":
            return RenderOutput(pdf=result.output if isinstance(result.output, bytes) else None, warnings=result.warnings)
        pages = result.output if isinstance(result.output, list) else [result.output] if result.output else []
        if max_pages is not None:
            pages = pages[:max_pages]
        return RenderOutput(pages=list(pages), warnings=result.warnings)

    async def render_pdf(self, document: Document, assets: RenderAssets | None = None) -> RenderOutput:
        return await self.render(document, assets, fmt="pdf")

    async def render_preview(self, document: Document, assets: RenderAssets | None = None, *, max_pages: int | None = None, ppi: float = PREVIEW_PPI) -> RenderOutput:
        return await self.render(document, assets, fmt="png", max_pages=max_pages or settings.document_preview_max_pages, ppi=ppi)

    async def _locate_failing_block(self, document: Document, assets: RenderAssets) -> str | None:
        """Kompiliert die Blöcke einzeln, um den Verursacher eines Fehlers zu finden."""
        budget = _MAX_DIAGNOSE_COMPILES
        strings = document.strings

        def label(block) -> str:
            return (block.title or "").strip() or strings.get(f"blockType.{block.type}", block.type)

        async def fails(blocks) -> bool:
            nonlocal budget
            budget -= 1
            probe = document.model_copy(
                update={
                    "blocks": blocks,
                    "options": document.options.model_copy(update={"title_page": "none", "toc": "off"}),
                }
            )
            try:
                result = await self._run(_dump(probe), assets, "pdf", None)
            except DocumentRenderError:
                return True
            return not result.ok

        for block in document.blocks:
            if budget <= 0:
                return None
            if not await fails([block]):
                continue
            if isinstance(block, ProtocolElementBlock):
                for child in block.children:
                    if budget <= 0:
                        break
                    if await fails([block.model_copy(update={"children": [child]})]):
                        return f"{label(block)} › {label(child)}"
            return label(block)
        return None


def _dump(document: Document) -> str:
    return json.dumps(document.model_dump(mode="json"), ensure_ascii=False)


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
