"""Erzeugt die Testdokumente in diesem Ordner neu (einmalig, Ergebnis ist eingecheckt).

Ausführen im Backend-Test-Image (enthält LibreOffice, siehe backend/Dockerfile.test):

    docker compose -p hocx-tests -f docker-compose.tests.yml --profile tests run --rm \
        backend-test python3 tests/fixtures/documents/generate.py

Die DOCX entsteht mit python-docx, alle anderen Formate konvertiert echtes LibreOffice daraus -
die Parser werden damit gegen Dateien getestet, wie sie Office-Programme tatsächlich schreiben.
"""

from __future__ import annotations

import io
import shutil
import subprocess
import tempfile
from pathlib import Path

from docx import Document
from docx.shared import Inches
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent


def _png() -> bytes:
    image = Image.new("RGB", (120, 80), (40, 90, 160))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def build_docx(path: Path) -> None:
    document = Document()
    document.add_heading("Jahresbericht Pfadi Musterhausen", level=1)
    document.add_paragraph("Grüße aus dem Sommerlager – Ärger, Öl und Übermut gehören dazu.")
    document.add_heading("Aktivitäten", level=2)
    document.add_paragraph("Wanderung auf den Säntis", style="List Bullet")
    document.add_paragraph("Lagerfeuer am See", style="List Bullet")
    document.add_paragraph("Rückblick und Ausblick", style="List Number")
    document.add_paragraph("Planung Herbstlager", style="List Number")
    table = document.add_table(rows=3, cols=2)
    for row_index, (left, right) in enumerate([("Posten", "Betrag"), ("Material", "120.50"), ("Verpflegung", "340.00")]):
        table.cell(row_index, 0).text = left
        table.cell(row_index, 1).text = right
    document.add_paragraph("Logo des Vereins:")
    document.add_picture(io.BytesIO(_png()), width=Inches(1.0))
    document.add_heading("Schluss", level=2)
    document.add_paragraph("Allzeit bereit!")
    document.save(path)


def soffice(source: Path, target: str, out_dir: Path) -> Path:
    with tempfile.TemporaryDirectory() as profile:
        subprocess.run(
            ["soffice", "--headless", "--norestore", f"-env:UserInstallation=file://{profile}",
             "--convert-to", target, "--outdir", str(out_dir), str(source)],
            check=True, capture_output=True, timeout=180,
        )
    return out_dir / f"{source.stem}.{target.split(':')[0]}"


def build_scanned_pdf(path: Path) -> None:
    image = Image.new("L", (1240, 1754), 255)
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 44)
    except OSError:
        font = ImageFont.load_default()
    draw.text((120, 200), "Protokoll der Hauptversammlung", fill=0, font=font)
    draw.text((120, 300), "Der Vorstand wurde einstimmig gewählt.", fill=0, font=font)
    image.save(path, "PDF", resolution=150)


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        docx_path = work / "sample.docx"
        build_docx(docx_path)
        shutil.copy(docx_path, HERE / "sample.docx")
        for target in ("odt", "rtf", "doc:MS Word 97", "pdf"):
            produced = soffice(docx_path, target, work)
            shutil.copy(produced, HERE / produced.name)
    build_scanned_pdf(HERE / "scanned.pdf")
    (HERE / "sample.md").write_text(
        "# Lagerplanung\n\nEinleitung mit **Markdown**.\n\n## Material\n\n- Zelte\n- Kocher\n  - Gas\n\n"
        "1. Packen\n2. Losfahren\n\n| Tag | Ort |\n| --- | --- |\n| Mo | Bern |\n| Di | Thun |\n\n![Karte](karte.png)\n",
        encoding="utf-8",
    )
    (HERE / "sample-cp1252.txt").write_bytes("Grüße aus Zürich\r\n\r\nZweiter Absatz – mit Gedankenstrich.\r\n".encode("cp1252"))
    (HERE / "sample.csv").write_text("Name;Funktion\nAnna;Leitung\nBeat;Kasse\n", encoding="utf-8")


if __name__ == "__main__":
    main()
