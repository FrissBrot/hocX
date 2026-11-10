"""OCR-Fallback für gescannte PDFs: pdftoppm (Poppler) rendert Seiten als Graustufenbild,
Tesseract erkennt den Text. Beides läuft im Sandbox-Kindprozess. Fehlt eines der Programme,
liefert ocr_available() False und die Extraktion endet mit Status ocr_required."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from app.services.documents import sandbox
from app.services.documents.content import ParsedContent, paragraph

PREFERRED_LANGUAGES = ("deu", "eng", "fra", "ita")
RENDER_DPI = 200


def ocr_available() -> bool:
    return shutil.which("tesseract") is not None and shutil.which("pdftoppm") is not None


def _languages() -> str:
    try:
        output = subprocess.run(["tesseract", "--list-langs"], capture_output=True, timeout=20, check=False).stdout
    except (OSError, subprocess.TimeoutExpired):
        return "eng"
    installed = {line.strip() for line in output.decode("utf-8", "replace").splitlines()[1:]}
    selected = [lang for lang in PREFERRED_LANGUAGES if lang in installed]
    return "+".join(selected) if selected else "eng"


def tesseract_version() -> str:
    try:
        output = subprocess.run(["tesseract", "--version"], capture_output=True, timeout=20, check=False).stdout
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    first = output.decode("utf-8", "replace").splitlines()[:1]
    return first[0].replace("tesseract", "").strip() if first else "unknown"


def ocr_pdf(data: bytes, *, page_count: int, work_dir: Path, limits: sandbox.Limits) -> ParsedContent:
    source = work_dir / "input.pdf"
    source.write_bytes(data)
    pages_dir = work_dir / "pages"
    pages_dir.mkdir(exist_ok=True)
    sandbox.run(
        ["pdftoppm", "-r", str(RENDER_DPI), "-gray", "-f", "1", "-l", str(page_count), str(source), str(pages_dir / "page")],
        work_dir=work_dir, limits=limits,
    )
    languages = _languages()
    blocks = []
    images = sorted(pages_dir.glob("page-*.pgm"), key=lambda path: int(re.search(r"-(\d+)\.pgm$", path.name).group(1)))
    for image in images:
        page_number = int(re.search(r"-(\d+)\.pgm$", image.name).group(1))
        result = sandbox.run(["tesseract", str(image), "stdout", "-l", languages, "--psm", "3"], work_dir=work_dir, limits=limits)
        text = result.stdout.decode("utf-8", "replace")
        for part in re.split(r"\n[ \t]*\n", text):
            if part.strip():
                blocks.append(paragraph(part, page=page_number))
        image.unlink(missing_ok=True)
    return ParsedContent(
        parser="pdf+ocr",
        parser_version=f"tesseract-{tesseract_version()}",
        blocks=blocks,
        page_count=page_count,
        warnings=["ocr_text_unverified"],
        ocr_applied=True,
    )
