"""Jeder Hausstil × jede Fixture × Hoch-/Querformat kompiliert ohne Fehler und Warnungen;
jede Kombination der Kopf-, Fuss-, Titelseiten- und TOC-Varianten rendert."""
from __future__ import annotations

import asyncio
import itertools
from typing import get_args

import pytest

from app.documents.style_tokens import STYLE_KEYS, FooterVariant, HeaderVariant, TitlePageVariant, TocVariant
from tests.documents.conftest import fixture_names, load_fixture, pdf_text


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


# Aus den Token-Typen abgeleitet: eine neue Variante ist automatisch abgedeckt.
HEADERS = list(get_args(HeaderVariant))
FOOTERS = list(get_args(FooterVariant))
TITLE_PAGES = list(get_args(TitlePageVariant))
TOCS = list(get_args(TocVariant))


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


@pytest.mark.parametrize("style_key", STYLE_KEYS)
@pytest.mark.parametrize("title_page", ["none", "cover"])
def test_metadata_box_and_sender_color(renderer, assets, style_key, title_page):
    """Früher «Metadaten anzeigen» und «Fussfarbe»: Kasten mit Nummer/Datum/Status am Anfang,
    eigene Farbe für den Absenderblock."""
    document = load_fixture("short")
    document.style.key = style_key
    document.style.sender = "Musterverein\nPostfach 1"
    document.style.sender_color = "#a83f2f"
    document.options.title_page = title_page
    document.options.show_metadata = True
    output = asyncio.run(renderer.render_pdf(document, assets))
    assert output.warnings == []
    text = pdf_text(output.pdf)
    assert document.strings["metadata.title"] in text
    if title_page == "cover":
        assert "Postfach 1" in text
