"""Regression test for M7 (2026-08-13 audit) - element_type_id "display" (id 4, used by
ProtocolDisplaySnapshot blocks) was missing from ElementDefinitionService's render-type
mapping, so unmapped types silently fell back to the paragraph default (render_type_id 2)
instead of the correct plain_text (6) - the same render type static_text already gets, since
both element types only ever hold a plain rendered-text snapshot (ProtocolDisplaySnapshot's
compiled_text mirrors ProtocolText.content used by static_text blocks)."""
from app.services.element_definition_service import ElementDefinitionService


def test_render_type_for_display_element_is_plain_text():
    service = ElementDefinitionService()
    assert service._render_type_for_element_type(4) == 6


def test_normalize_blocks_sets_plain_text_render_type_for_display_blocks():
    service = ElementDefinitionService()
    blocks = [{"element_type_id": 4, "title": "Anzeige-Block"}]

    normalized = service._normalize_blocks(None, blocks, tenant_id=1)

    assert normalized[0]["render_type_id"] == 6
