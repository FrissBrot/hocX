"""Modus «Einfach»: die Beschreibung der Bausteine (simple.py) passt zu den Modellen, zur
Bibliothek und zu den mitgelieferten Vorlagen."""
from __future__ import annotations

import pytest

from app.documents.appearance import APPEARANCE_VARIANTS, DESIGN_KEYS
from app.documents.catalog import CATALOG
from app.documents.components import LIBRARY, catalog_payload
from app.documents.examples import EXAMPLES, build_example_content
from app.documents.layout import NODE_MODELS, TemplateContent
from app.documents.simple import CONDITION_PRESETS, SIMPLE_ADD, SIMPLE_BLOCKS
from app.documents.system_templates import SYSTEM_TEMPLATES


def _types(block: dict) -> list[str]:
    value = block["match"]["type"]
    return value if isinstance(value, list) else [value]


def _matches(block: dict, node: dict) -> bool:
    match = block["match"]
    if node.get("type") not in _types(block):
        return False
    if "component" in match and node.get("component") not in match["component"]:
        return False
    if "role" in match and node.get("role", "paragraph") not in match["role"]:
        return False
    return True


@pytest.mark.parametrize("block", SIMPLE_BLOCKS, ids=lambda item: item["key"])
def test_setting_paths_exist_in_the_models(block):
    assert len(block["settings"]) <= 3
    for node_type in _types(block):
        assert node_type in NODE_MODELS, node_type
        fields = NODE_MODELS[node_type].model_fields
        for setting in block["settings"]:
            if setting["kind"] in ("variant", "condition"):
                continue
            head, _, rest = setting["path"].partition(".")
            assert head in fields, (block["key"], setting["path"])
            if head == "params":
                for component in block["match"].get("component", []):
                    assert rest in CATALOG[component].params.model_fields, (component, rest)
    for setting in block["settings"]:
        if setting["kind"] == "variant":
            assert setting["options"] == list(APPEARANCE_VARIANTS[setting["appearance"]])


def test_conditions_are_valid_visibility_rules_and_add_entries_exist():
    for name, condition in CONDITION_PRESETS.items():
        TemplateContent.model_validate({"masters": [{"id": "default"}], "body": [{"type": "section", "id": name, "visible_if": condition}]})
    library = {entry.key for entry in LIBRARY}
    assert set(SIMPLE_ADD) <= library
    assert len(SIMPLE_ADD) == 8
    assert catalog_payload()["simple"]["styles"] == list(DESIGN_KEYS)


def _bodies():
    for template in SYSTEM_TEMPLATES:
        yield template.key, template.build()["body"]
    for example in EXAMPLES:
        yield example.key, build_example_content(example).model_dump(mode="json")["body"]


@pytest.mark.parametrize("key,body", list(_bodies()), ids=lambda item: item if isinstance(item, str) else "")
def test_every_shipped_block_is_known_to_simple_mode(key, body):
    for node in body:
        assert any(_matches(block, node) for block in SIMPLE_BLOCKS), (key, node.get("type"), node.get("id"))
