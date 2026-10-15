"""Brand-Profil: Schema, Referenzen, Startprofile."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.documents.brand import BRAND_PRESETS, BrandTokens, color_references, preset_tokens, resolve_color


def test_color_references_resolve():
    tokens = BrandTokens.model_validate({"colors": {"primary": "#112233", "custom": [{"key": "signal", "value": "#ff8800"}]}})
    assert resolve_color("$brand.primary", tokens) == "#112233"
    assert resolve_color("$brand.custom.signal", tokens) == "#FF8800"
    assert resolve_color("$brand.status.warning", tokens) == tokens.colors.warning.upper()
    assert resolve_color("#abcdef", tokens) == "#ABCDEF"
    assert resolve_color("$brand.custom.fehlt", tokens, default="#000000") == "#000000"
    assert resolve_color("$brand.custom", tokens) is None
    assert "$brand.custom.signal" in color_references(tokens) and "$brand.primary" in color_references(tokens)


def test_invalid_brand_values_are_rejected():
    for data in (
        {"colors": {"primary": "red"}},
        {"colors": {"custom": [{"key": "a", "value": "#000000"}, {"key": "a", "value": "#111111"}]}},
        {"colors": {"custom": [{"key": "Böse Taste", "value": "#000000"}]}},
        {"typography": {"base_size": 40}},
        {"typography": {"body": {"builtin": "comic_sans"}}},
        {"layout": {"table_style": "neon"}},
        {"unknown": True},
    ):
        with pytest.raises(ValidationError):
            BrandTokens.model_validate(data)


@pytest.mark.parametrize("key", sorted(BRAND_PRESETS))
def test_presets_are_valid(key):
    assert isinstance(preset_tokens(key), BrandTokens)


def test_asset_ids_cover_images_and_fonts():
    logo = "0192f0aa-0000-7000-8000-000000000001"
    font = "0192f0aa-0000-7000-8000-000000000002"
    tokens = BrandTokens.model_validate({"assets": {"logo": logo, "images": [{"key": "signet", "asset_id": logo}]}, "typography": {"heading": {"builtin": None, "asset_ids": [font]}}})
    assert {str(value) for value in tokens.asset_ids()} == {logo, font}
