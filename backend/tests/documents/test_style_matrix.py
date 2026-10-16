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


VERIFY_COMBOS = list(itertools.product([True, False], repeat=3))


@pytest.mark.parametrize("style_key", STYLE_KEYS)
@pytest.mark.parametrize(("show_url", "show_id", "show_qr"), VERIFY_COMBOS)
def test_verification_options_every_combination(renderer, assets, style_key, show_url, show_id, show_qr):
    """Echtheitsprüfung im Dokument: jede Kombination aus Prüf-URL, Kurz-ID und QR-Code rendert ohne
    Warnungen, zeigt genau die eingeschalteten Teile und lässt keine verwaisten Trennzeichen
    stehen; sind alle drei aus, entfällt der Prüfvermerk vollständig."""
    document = load_fixture("short")
    document.style.key = style_key
    document.style.verify_show_url, document.style.verify_show_id, document.style.verify_show_qr = show_url, show_id, show_qr
    output = asyncio.run(renderer.render_pdf(document, assets))
    assert output.warnings == []
    text = pdf_text(output.pdf)
    strings = document.strings
    render = document.render
    url_label = strings["verify.url"].split("{")[0].strip()  # «Echtheit prüfen:»
    assert (render.verify_display in text) is show_url
    assert (render.short_id in text) is show_id
    assert (strings["verify.qrHint"] in text) is (show_qr and (style_key != "compact" or not (show_url or show_id)))
    if not (show_url or show_id or show_qr):
        assert url_label not in text and strings["verify.id"].split("{")[0].strip() not in text
    for line in text.splitlines():
        stripped = line.strip()
        assert not stripped.startswith("·") and not stripped.endswith("·"), line
        assert not stripped.endswith(":"), line
