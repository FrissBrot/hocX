"""Brand-Profil: Schema, Referenzen, Startprofile."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.documents.brand import BRAND_PRESETS, BrandTokens, color_references, preset_tokens, resolve_appearance, resolve_color
from app.documents.layout import DataBlockNode


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


def test_template_overrides_win_over_brand():
    from app.documents.brand import apply_overrides
    from app.documents.layout import BrandOverrides

    tokens = BrandTokens.model_validate({"colors": {"primary": "#112233"}, "typography": {"body": {"builtin": None, "asset_ids": ["0192f0aa-0000-7000-8000-000000000002"]}}})
    assert apply_overrides(tokens, BrandOverrides()) is tokens
    merged = apply_overrides(tokens, BrandOverrides(primary="#FF0000", body_font="liberation_serif", base_size=12, logo_asset_id="0192f0aa-0000-7000-8000-000000000001"))
    assert merged.colors.primary == "#FF0000" and merged.colors.secondary == tokens.colors.secondary
    assert merged.typography.body.builtin == "liberation_serif" and merged.typography.body.asset_ids == []
    assert merged.typography.base_size == 12 and str(merged.assets.logo).endswith("0001")


# ── Erscheinungsbild: Grundstil → Brand-Übersteuerung → Block-Übersteuerung ──


def test_appearance_defaults_follow_base_and_layout():
    classic = resolve_appearance(BrandTokens())
    assert classic["session_date"] == {"variant": "line", "radius": 1.5}
    assert classic["table"]["variant"] == "lines"
    rounded = resolve_appearance(BrandTokens.model_validate({"appearance": {"base": "rounded"}, "layout": {"radius": 4, "table_style": "zebra"}}))
    assert rounded["session_date"] == {"variant": "box", "radius": 4}
    assert rounded["table"]["variant"] == "zebra"


def test_appearance_overrides_brand_then_block():
    tokens = BrandTokens.model_validate({"layout": {"radius": 0}, "appearance": {"elements": {"attendance": {"variant": "compact"}, "session_date": {"corners": "rounded"}}}})
    brand = resolve_appearance(tokens)
    assert brand["attendance"]["variant"] == "compact"
    assert brand["session_date"]["radius"] == 3.0  # abgerundet trotz eckigem Grundstil
    node = DataBlockNode(component="protocol_element", appearance={"attendance": {"variant": "table"}, "session_date": {"corners": "square"}})
    block = resolve_appearance(tokens, node.appearance)
    assert block["attendance"]["variant"] == "table"
    assert block["session_date"]["radius"] == 0


def test_appearance_rejects_unknown_values():
    with pytest.raises(ValidationError):
        BrandTokens.model_validate({"appearance": {"elements": {"attendance": {"variant": "pyramid"}}}})
    with pytest.raises(ValidationError):
        BrandTokens.model_validate({"appearance": {"elements": {"unknown": {"variant": "x"}}}})
    # Überschriften gelten global, nicht pro Block
    with pytest.raises(ValidationError):
        DataBlockNode(component="protocol_element", appearance={"heading": {"variant": "bar"}})
    # Leere Übersteuerungen werden nicht gespeichert
    assert BrandTokens.model_validate({"appearance": {"elements": {"form": {}}}}).appearance.elements == {}


def test_template_overrides_style_and_header_footer_without_touching_the_profile():
    """Einfach-Modus: Stil (Design) sowie Kopf- und Fusszeile gelten nur für diese Vorlage."""
    from app.documents.appearance import APPEARANCE_BASES
    from app.documents.brand import apply_overrides
    from app.documents.layout import BrandOverrides

    tokens = BrandTokens.model_validate({"appearance": {"elements": {"attendance": {"variant": "chips"}}}, "layout": {"header_footer": {"footer_text": "Profil"}}})
    merged = apply_overrides(tokens, BrandOverrides(appearance_base="signal", header_show_logo=False, footer_show_pages=False, footer_text="Vorlage"))
    assert merged.appearance.base == "signal"
    assert merged.layout.table_style == APPEARANCE_BASES["signal"]["layout"]["table_style"] and merged.layout.radius == 0
    assert merged.appearance.elements["attendance"].variant == "chips"
    resolved = resolve_appearance(merged)
    assert resolved["todo"]["variant"] == "status" and resolved["attendance"]["variant"] == "chips"
    footer = merged.layout.header_footer
    assert footer.header_show_logo is False and footer.header_show_title is True and footer.footer_show_pages is False and footer.footer_text == "Vorlage"
    # Das Profil selbst bleibt unverändert
    assert tokens.appearance.base == "classic" and tokens.layout.header_footer.footer_text == "Profil"
    with pytest.raises(ValidationError):
        BrandOverrides(appearance_base="neon")
