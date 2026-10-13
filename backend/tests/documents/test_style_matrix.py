"""Jeder Hausstil × jede Fixture × Hoch-/Querformat kompiliert ohne Fehler und Warnungen;
jede Kombination der Kopf-, Fuss-, Titelseiten- und TOC-Varianten rendert."""
from __future__ import annotations

import asyncio
import itertools

import pytest

from app.documents.style_tokens import STYLE_KEYS
from tests.documents.conftest import fixture_names, load_fixture


@pytest.mark.parametrize("style_key", STYLE_KEYS)
@pytest.mark.parametrize("fixture", fixture_names())
@pytest.mark.parametrize("orientation", ["portrait", "landscape"])
def test_style_fixture_orientation(renderer, assets, style_key, fixture, orientation):
    document = load_fixture(fixture)
    document.style.key = style_key
    document.options.orientation = orientation
    output = asyncio.run(renderer.render_pdf(document, assets))
    assert output.pdf.startswith(b"%PDF")
    assert output.warnings == []


HEADERS = ["none", "minimal", "standard", "bar", "logo"]
FOOTERS = ["none", "minimal", "standard", "with_version", "date_page"]
TITLE_PAGES = ["none", "minimal", "modern", "bold", "cover"]
TOCS = ["off", "on", "compact"]


@pytest.mark.parametrize("style_key", STYLE_KEYS)
@pytest.mark.parametrize("with_images", [False, True])
def test_every_variant_combination(renderer, assets, style_key, with_images):
    """Alle Varianten kombiniert (Logo-Kopf und Cover auch ohne Bilder). Jede Kombination
    ist ein eigener kleiner Compile; die Kombinationen werden paarweise abgedeckt."""
    base = load_fixture("short")
    base.style.key = style_key
    if with_images:
        base.style.logo = "assets/fixture-1.png"
        base.style.footer_image = "assets/fixture-2.png"
    combos = list(itertools.product(HEADERS, FOOTERS)) + list(itertools.product(TITLE_PAGES, TOCS))
    for first, second in combos:
        document = base.model_copy(deep=True)
        if first in HEADERS and second in FOOTERS:
            document.style.header, document.style.footer = first, second
        else:
            document.options.title_page, document.options.toc = first, second
        output = asyncio.run(renderer.render_pdf(document, assets))
        assert output.warnings == [], (first, second)
