"""Übernahme früherer Gestaltungsdaten: TeX-Vorlagen und Hausstile → Brand-Profile, Rezepte →
Vorlagen (Migrationen 0115/0118, Import alter Mandanten-Archive)."""
from __future__ import annotations

import pytest

from app.documents.layout import TemplateContent
from app.documents.legacy import (
    brand_tokens_from_legacy,
    brand_tokens_from_style,
    content_from_recipe,
    has_custom_slots,
    legacy_part_refs,
    tokens_from_legacy,
)

LOGO = "0192f0aa-0000-7000-8000-000000000001"
FONT = "0192f0aa-0000-7000-8000-000000000002"


def test_full_legacy_configuration_is_translated():
    config = {
        "theme": {"primary_color": "A83F2F", "secondary_color": "#6F675D", "font_size": "12pt", "font_family": "uploaded", "font_parts": {"font_regular": 7, "font_bold": 8}},
        "options": {"orientation": "landscape", "numbering_mode": "none", "hide_metadata": True},
        "presets": {"header": "logo_bar", "footer": "with_version", "title_page": "combined_toc", "toc": "standard"},
        "title_assets": {"header_image_part_id": 3, "footer_image_part_id": 4},
        "title_text": {"location": "Zürich", "footer_contact": "Verein\nPostfach"},
        "slots": {"preamble": 9},
    }
    assert legacy_part_refs(config) == {"logo": 3, "footer_image": 4, "font_regular": 7, "font_bold": 8}
    assert has_custom_slots(config)
    tokens = tokens_from_legacy(config, {"logo": LOGO, "font_regular": FONT})
    assert tokens["primary_color"] == "#a83f2f" and tokens["font"] == "custom" and tokens["title_page"] == "cover"

    brand = brand_tokens_from_legacy(config, {"logo": LOGO, "font_regular": FONT})
    assert brand.colors.primary == "#A83F2F" and brand.colors.secondary == "#6F675D"
    assert str(brand.assets.logo) == LOGO and [str(value) for value in brand.typography.body.asset_ids] == [FONT]
    assert brand.layout.orientation == "landscape" and brand.layout.title_page and brand.layout.toc
    assert brand.layout.heading_numbering is False and brand.layout.show_metadata is False
    assert brand.layout.header_footer.header_show_logo and brand.layout.header_footer.footer_show_number
    assert brand.organization.place == "Zürich" and brand.organization.address == "Verein\nPostfach"


def test_minimal_and_invalid_values_fall_back():
    brand = brand_tokens_from_legacy({"theme": {"primary_color": "rot", "font_family": "arial"}, "options": {"show_toc": False}})
    assert brand.colors.primary == "#174B7A" and brand.typography.body.builtin == "liberation_sans"
    assert brand.layout.toc is False and brand.layout.title_page is True  # alte Standardvorlage hatte Titelseite
    assert not has_custom_slots({"slots": {"preamble": None}})


@pytest.mark.parametrize("style_key", ["modern", "classic", "compact"])
def test_every_house_style_becomes_a_valid_brand(style_key):
    brand = brand_tokens_from_style(style_key, {"primary_color": "#112233", "margins": "wide", "header": "minimal", "footer": "none", "numbering": True, "verify_show_qr": False})
    assert brand.colors.primary == "#112233"
    assert brand.layout.margins.top == 30 and brand.layout.heading_numbering
    assert not brand.layout.header_footer.header_show_title and not brand.layout.header_footer.footer_show_pages
    assert brand.verify.show_qr is False
    assert brand.typography.body.builtin == {"modern": "inter", "classic": "liberation_serif", "compact": "liberation_sans"}[style_key]


def test_broken_style_tokens_never_fail():
    brand = brand_tokens_from_style("unbekannt", {"primary_color": 5, "logo_asset_id": "keine-uuid", "font": "custom", "custom_fonts": {"regular": "kaputt"}})
    assert brand.colors.primary == "#174B7A" and brand.assets.logo is None and brand.typography.body.builtin == "inter"


def test_recipe_becomes_valid_template_content():
    blocks = [
        {"type": "heading", "params": {"text": "Titel"}},
        {"type": "richtext", "title": "Text", "params": {"markdown": "**fett**"}},
        {"type": "spacer", "params": {"size": "l"}},
        {"type": "divider"},
        {"type": "bullet_list", "params": {"items": ["a", " "]}},
        {"type": "generic_table", "params": {"headers": ["A", "B"], "rows": [["1", "2"]]}},
        {"type": "qr_link", "params": {"target": "url", "url": "https://hocx.ch", "label": "Link"}},
        {"type": "todo_table", "title": "Offen", "hide_if_empty": False, "params": {"status": "open"}},
        {"type": "page_break"},
        {"type": "gibts_nicht"},
    ]
    content = TemplateContent.model_validate(content_from_recipe(blocks, {"title_page": "modern", "toc": "on", "orientation": "landscape", "numbering": True}))
    types = [node.type for node in content.body]
    assert types == ["toc", "text", "text", "rich_text", "spacer", "divider", "list", "table", "qr_code", "data_block", "page_break"]
    data = content.body[9]
    assert data.component == "todo_table" and data.title_mode == "custom" and data.hide_if_empty is False and data.params == {"status": "open"}
    assert content.title_page.enabled and content.page.orientation == "landscape" and content.settings.heading_numbering
