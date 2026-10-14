"""Visuelle Regression: gerenderte Seiten gegen eingecheckte Golden-Bilder.

Vergleich mit Toleranz (Anteil abweichender Pixel), damit minimale Kantenglättungsunterschiede
nicht stören. Bei Abweichung landen Ist-Bild und Differenzbild in ``DOCUMENT_GOLDEN_DIFF_DIR``
(CI lädt das Verzeichnis als Artefakt hoch).

Goldens bewusst aktualisieren: ``scripts/update-document-goldens.sh`` (setzt UPDATE_GOLDENS=1).
"""
from __future__ import annotations

import asyncio
import io
import os
from pathlib import Path

import pytest
from PIL import Image, ImageChops

from app.documents.style_tokens import STYLE_KEYS
from tests.documents.conftest import load_fixture

GOLDEN_DIR = Path(__file__).resolve().parent / "goldens"
DIFF_DIR = Path(os.environ.get("DOCUMENT_GOLDEN_DIFF_DIR", "/tmp/document-golden-diffs"))
UPDATE = os.environ.get("UPDATE_GOLDENS") == "1"
PPI = 40
# Anteil der Pixel, die sich (deutlich) unterscheiden dürfen
MAX_CHANGED_RATIO = 0.004
PIXEL_THRESHOLD = 48

CASES = [("short", 1), ("all_blocks", 6), ("unicode", 3), ("landscape", 2), ("lang_fr", 1)]
# Echtheitsprüfung im Dokument: (Prüf-URL, Kurz-ID, QR-Code)
VERIFY_VARIANTS = {"verify-all": (True, True, True), "verify-qr": (False, False, True), "verify-url-id": (True, True, False), "verify-none": (False, False, False)}


def _changed_ratio(actual: Image.Image, expected: Image.Image) -> tuple[float, Image.Image]:
    if actual.size != expected.size:
        return 1.0, actual
    diff = ImageChops.difference(actual.convert("RGB"), expected.convert("RGB")).convert("L")
    mask = diff.point(lambda value: 255 if value > PIXEL_THRESHOLD else 0)
    histogram = mask.histogram()
    changed = histogram[255]
    return changed / (actual.size[0] * actual.size[1]), mask


def _compare(renderer, assets, document, pages: int, prefix: str) -> None:
    output = asyncio.run(renderer.render_preview(document, assets, max_pages=pages, ppi=PPI))
    assert output.pages
    failures: list[str] = []
    for index, png in enumerate(output.pages, start=1):
        name = f"{prefix}-{index}.png"
        golden = GOLDEN_DIR / name
        if UPDATE or not golden.exists():
            if not UPDATE:
                failures.append(f"{name}: kein Golden vorhanden (scripts/update-document-goldens.sh)")
                continue
            GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
            golden.write_bytes(png)
            continue
        actual = Image.open(io.BytesIO(png))
        ratio, mask = _changed_ratio(actual, Image.open(golden))
        if ratio > MAX_CHANGED_RATIO:
            DIFF_DIR.mkdir(parents=True, exist_ok=True)
            (DIFF_DIR / f"actual-{name}").write_bytes(png)
            mask.save(DIFF_DIR / f"diff-{name}")
            failures.append(f"{name}: {ratio:.2%} der Pixel weichen ab")
    assert failures == []


@pytest.mark.parametrize("style_key", STYLE_KEYS)
@pytest.mark.parametrize(("fixture", "pages"), CASES)
def test_pages_match_goldens(renderer, assets, style_key, fixture, pages):
    document = load_fixture(fixture)
    document.style.key = style_key
    _compare(renderer, assets, document, pages, f"{fixture}-{style_key}")


@pytest.mark.parametrize("style_key", STYLE_KEYS)
@pytest.mark.parametrize("variant", VERIFY_VARIANTS)
def test_verification_variants_match_goldens(renderer, assets, style_key, variant):
    document = load_fixture("short")
    document.style.key = style_key
    document.style.verify_show_url, document.style.verify_show_id, document.style.verify_show_qr = VERIFY_VARIANTS[variant]
    _compare(renderer, assets, document, 1, f"{variant}-{style_key}")
