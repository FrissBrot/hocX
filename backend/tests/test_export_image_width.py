"""ExportService._image_width_latex: protocol images are not stretched beyond their natural
size (96 dpi), so small screenshots stay sharp in the PDF instead of being upscaled to the
full text width; large images stay capped at 0.82\\textwidth."""
from __future__ import annotations

from pathlib import Path

from PIL import Image

from app.services.export_service import ExportService


def test_small_image_uses_natural_width(tmp_path: Path) -> None:
    image_path = tmp_path / "small.png"
    Image.new("RGB", (600, 400), "white").save(image_path)

    latex = "\n".join(ExportService._image_width_latex(image_path))

    assert "\\setlength{\\HocxImageWidth}{0.82\\textwidth}" in latex
    # 600 px at 96 dpi = 450 bp
    assert "\\ifdim450.00bp<\\HocxImageWidth\\setlength{\\HocxImageWidth}{450.00bp}\\fi" in latex


def test_unreadable_image_falls_back_to_text_width(tmp_path: Path) -> None:
    image_path = tmp_path / "broken.png"
    image_path.write_bytes(b"not an image")

    lines = ExportService._image_width_latex(image_path)

    assert lines[-1] == "\\setlength{\\HocxImageWidth}{0.82\\textwidth}"
    assert not any("\\ifdim" in line for line in lines)
