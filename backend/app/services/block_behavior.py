from __future__ import annotations

BEHAVIOR_FIELDS = ("is_editable", "is_visible", "export_visible", "copy_from_last_protocol", "title_as_subtitle")


def block_defaults(block: dict) -> dict:
    """The behavior values baked into an ElementDefinition block, before any template override."""
    block_config = block.get("configuration_json") or {}
    return {
        "is_editable": block.get("is_editable", True),
        "is_visible": block.get("is_visible", True),
        "export_visible": block.get("export_visible", True),
        "copy_from_last_protocol": block.get("copy_from_last_protocol", False),
        "title_as_subtitle": block_config.get("title_as_subtitle", True),
    }


def resolve_block_behavior(template_element_configuration_json: dict | None, block: dict) -> dict:
    """Effective behavior values for one block within a template.

    Precedence (highest wins): per-block override > element-wide override > element definition default.
    """
    config = template_element_configuration_json or {}
    effective = block_defaults(block)
    element_wide = config.get("block_behavior_overrides") or {}
    for field in BEHAVIOR_FIELDS:
        if field in element_wide:
            effective[field] = element_wide[field]
    per_block = (config.get("block_overrides") or {}).get(str(block.get("id")), {})
    for field in BEHAVIOR_FIELDS:
        if field in per_block:
            effective[field] = per_block[field]
    return effective


def resolve_element_wide_behavior(template_element_configuration_json: dict | None, blocks: list[dict]) -> dict:
    """Representative behavior values for the whole element row (used by the "apply to all" icons)."""
    base = block_defaults(blocks[0]) if blocks else {field: (field != "copy_from_last_protocol") for field in BEHAVIOR_FIELDS}
    config = template_element_configuration_json or {}
    element_wide = config.get("block_behavior_overrides") or {}
    for field in BEHAVIOR_FIELDS:
        if field in element_wide:
            base[field] = element_wide[field]
    return base
