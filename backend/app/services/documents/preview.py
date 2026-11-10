"""Vorschaubild der ersten PDF-Seite (PNG) über pdftoppm im Sandbox-Kindprozess."""

from __future__ import annotations

import shutil
from pathlib import Path

from app.services.documents import sandbox

PREVIEW_MAX_PIXELS = 1000


def preview_available() -> bool:
    return shutil.which("pdftoppm") is not None


def render_first_page(pdf: bytes, *, work_dir: Path, limits: sandbox.Limits) -> bytes:
    source = work_dir / "preview-input.pdf"
    source.write_bytes(pdf)
    target = work_dir / "preview"
    sandbox.run(
        ["pdftoppm", "-png", "-f", "1", "-l", "1", "-singlefile", "-scale-to", str(PREVIEW_MAX_PIXELS), str(source), str(target)],
        work_dir=work_dir, limits=limits,
    )
    result = target.with_suffix(".png")
    data = result.read_bytes()
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise sandbox.SandboxError("Vorschau ist kein PNG")
    return data
