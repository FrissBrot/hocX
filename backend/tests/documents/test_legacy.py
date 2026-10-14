"""Übersetzung alter TeX-basierter Dokumentvorlagen in Hausstil-Tokens (Migration 0115, Import alter Archive)."""
from __future__ import annotations

from app.documents.legacy import has_custom_slots, legacy_part_refs, tokens_from_legacy


def test_full_legacy_configuration_is_translated():
    config = {
        "theme": {"primary_color": "A83F2F", "secondary_color": "#6F675D", "font_size": "12pt", "font_family": "uploaded", "font_parts": {"font_regular": 7, "font_bold": 8}},
        "options": {"orientation": "landscape", "numbering_mode": "none", "toc_spacing": "compact"},
        "presets": {"header": "logo_bar", "footer": "with_version", "title_page": "combined_toc", "toc": "standard"},
        "title_assets": {"header_image_part_id": 3, "footer_image_part_id": 4},
        "title_text": {"location": "Zürich", "footer_contact": "Verein\nPostfach"},
        "slots": {"preamble": 9},
    }
    assert legacy_part_refs(config) == {"logo": 3, "footer_image": 4, "font_regular": 7, "font_bold": 8}
    assert has_custom_slots(config)
    tokens = tokens_from_legacy(config, {"logo": "0192f0aa-0000-7000-8000-000000000001", "font_regular": "0192f0aa-0000-7000-8000-000000000002"})
    assert tokens.primary_color == "#a83f2f" and tokens.secondary_color == "#6f675d"
    assert tokens.base_size == 12 and tokens.orientation == "landscape" and tokens.numbering is False
    assert tokens.header == "logo" and tokens.footer == "with_version" and tokens.title_page == "cover"
    assert tokens.toc == "compact"
    assert tokens.font == "custom" and str(tokens.custom_fonts.regular).endswith("0002")
    assert str(tokens.logo_asset_id).endswith("0001") and tokens.footer_image_asset_id is None
    assert tokens.place == "Zürich" and tokens.sender == "Verein\nPostfach"


def test_minimal_and_invalid_values_fall_back():
    tokens = tokens_from_legacy({"theme": {"primary_color": "rot", "font_family": "arial", "font_size": "9pt"}, "options": {"show_toc": False}})
    assert tokens.primary_color == "#174b7a" and tokens.font == "liberation_sans" and tokens.base_size == 10
    assert tokens.toc == "off" and tokens.title_page == "modern"
    custom_without_file = tokens_from_legacy({"theme": {"font_family": "uploaded"}, "presets": {"toc": "none"}})
    assert custom_without_file.font == "style" and custom_without_file.toc == "off"
    assert not has_custom_slots({"slots": {"preamble": None}})
