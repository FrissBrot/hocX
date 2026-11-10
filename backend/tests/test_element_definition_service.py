"""ElementDefinitionService._normalize_blocks: Render-Typ und Mehrfachwerte kommen aus der
Elementtyp-Registry (element-types/registry.json), Altformate werden gehoben und jede
Konfiguration wird gegen das Schema ihres Typs geprüft.

Regression M7 (2026-08-13 audit): element_type_id "display" (4) fiel früher auf den
Absatz-Render-Typ zurück statt auf plain_text (6)."""
import pytest

from app.core.element_types import render_type_id
from app.services.element_definition_service import ElementDefinitionService


def test_render_type_for_display_element_is_plain_text():
    assert render_type_id(4) == 6


def test_registry_covers_types_the_frontend_and_backend_used_to_disagree_on():
    # Frontend kannte 16 nicht im Backend, Backend kannte 4 nicht im Frontend.
    assert render_type_id(16) == 5
    assert render_type_id(14) == 5


def test_normalize_blocks_sets_plain_text_render_type_for_display_blocks():
    service = ElementDefinitionService()
    blocks = [{"element_type_id": 4, "title": "Anzeige-Block"}]

    normalized = service._normalize_blocks(None, blocks, tenant_id=1)

    assert normalized[0]["render_type_id"] == 6


def test_normalize_blocks_ignores_client_render_type_and_multi_value_flag():
    service = ElementDefinitionService()
    blocks = [{"element_type_id": 2, "title": "Todos", "render_type_id": 2, "allows_multiple_values": False}]

    normalized = service._normalize_blocks(None, blocks, tenant_id=1)

    assert normalized[0]["render_type_id"] == 3
    assert normalized[0]["allows_multiple_values"] is True


def test_normalize_blocks_upgrades_legacy_keys_and_drops_foreign_ones():
    """Der frühere Editor speicherte alle Formularfelder bei jedem Typ - ein Textblock trug
    chart_type, mode, finance_filter_type usw. Nur Schlüssel des Typ-Schemas bleiben."""
    service = ElementDefinitionService()
    blocks = [{
        "element_type_id": 1,
        "title": "Text",
        "configuration_json": {
            "block_kind": "text",
            "block_type_code": "text",
            "title_as_subtitle": False,
            "chart_type": "",
            "mode": "manual",
            "finance_filter_type": "all",
            "event_tag_filter": "",
            "repeat_source": "none",
        },
    }]

    normalized = service._normalize_blocks(None, blocks, tenant_id=1)

    assert normalized[0]["title_as_subtitle"] is False
    assert normalized[0]["configuration_json"] == {"block_kind": "text", "repeat_source": "none"}


def test_normalize_blocks_rejects_unknown_type_and_invalid_values():
    service = ElementDefinitionService()
    with pytest.raises(ValueError):
        service._normalize_blocks(None, [{"element_type_id": 99, "title": "?"}], tenant_id=1)
    with pytest.raises(ValueError, match="event_filter"):
        service._normalize_blocks(
            None,
            [{"element_type_id": 7, "title": "Termine", "configuration_json": {"event_filter": {"limit": 9999}}}],
            tenant_id=1,
        )
