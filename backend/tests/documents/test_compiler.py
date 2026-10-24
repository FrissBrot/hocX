"""Layout-Compiler: Bindungen, Bedingungen, Wiederholungen, Fachkomponenten, Fehlerbehandlung
im strikten Modus (Export) und in der Vorschau, statische Prüfung von Vorlagen."""
from __future__ import annotations

import pytest

from app.documents.compiler import CompileError, validate_template
from app.documents.layout import TemplateContent
from tests.documents.fixtures.scenarios import Scenario, compile_scenario, system


def _find(nodes, node_id):
    for node in nodes:
        if node.get("id") == node_id:
            return node
        found = _find(node.get("children", []), node_id)
        if found:
            return found
    return None


def _body(compiled):
    return [node for segment in compiled.data["segments"] for node in segment["nodes"]]


def test_text_bindings_keys_and_translations_resolve():
    content = {"masters": [{"id": "default"}], "body": [
        {"type": "text", "id": "t", "content": {
            "default": [{"t": "key", "key": "docType.protocol"}, {"t": "text", "v": " – "}, {"t": "bind", "path": "document.title"}],
            "translations": {"fr": [{"t": "text", "v": "Version française"}]},
        }},
    ]}
    compiled = compile_scenario(Scenario(content, document_type="custom"))
    assert _find(_body(compiled), "t")["spans"] == [{"v": "Protokoll"}, {"v": " – "}, {"v": "Fixture-Dokument"}]
    french = compile_scenario(Scenario(content, document_type="custom", language="fr"))
    assert _find(_body(french), "t")["spans"] == [{"v": "Version française"}]


def test_colors_fonts_and_lengths_are_resolved():
    content = {"masters": [{"id": "default"}], "body": [
        {"type": "container", "id": "c", "style": {"width": "60%", "background": "$brand.primary", "border": {"width": 1, "color": "$brand.custom.rot"}, "text": {"font": "$brand.font.heading", "size": 12}}, "children": []},
        {"type": "text", "id": "t", "style": {"text": {"color": "$brand.status.danger"}}, "content": {"default": [{"t": "text", "v": "x"}]}},
    ]}
    compiled = compile_scenario(Scenario(content, document_type="custom", brand={"colors": {"custom": [{"key": "rot", "value": "#AA0000"}]}}))
    container = _find(_body(compiled), "c")
    assert container["s"]["w"] == {"k": "pct", "v": 60.0}
    assert container["s"]["bg"] == "#174B7A" and container["s"]["border"]["c"] == "#AA0000"
    assert container["s"]["text"]["font"][0] == "Inter"
    assert _find(_body(compiled), "t")["s"]["text"]["color"] == "#DC2626"


def test_unknown_color_is_a_warning_with_fallback():
    content = {"masters": [{"id": "default"}], "body": [{"type": "text", "id": "t", "style": {"background": "$brand.custom.fehlt"}, "content": {"default": [{"t": "text", "v": "x"}]}}]}
    compiled = compile_scenario(Scenario(content, document_type="custom"))
    assert [(item.node_id, item.code, item.severity) for item in compiled.diagnostics] == [("t", "unknownColor", "warning")]


def test_repeat_table_and_list_bindings_expand():
    compiled = compile_scenario(Scenario(system("agenda_standard"), document_type="agenda"))
    agenda = _find(_body(compiled), "agenda-list")
    assert agenda["marker"] == "number" and len(agenda["items"]) == 4


def test_absolute_layer_on_title_page_offsets_by_margins():
    content = {"page": {"margins": {"top": 25, "right": 20, "bottom": 20, "left": 18}}, "masters": [{"id": "default"}], "title_page": {"enabled": True, "children": [
        {"type": "absolute_layer", "id": "l", "anchor": "page", "children": [{"type": "spacer", "id": "s", "frame": {"x": 5, "y": 6}}]},
    ]}, "body": []}
    compiled = compile_scenario(Scenario(content, document_type="custom"))
    layer = compiled.data["title_page"]["children"][0]
    assert layer["offset"] == [-18, -25] and layer["children"][0]["frame"]["x"] == 5


def test_title_page_condition_follows_brand_default():
    hidden = compile_scenario(Scenario(system("protocol_standard"), {"protocol": []}))
    shown = compile_scenario(Scenario(system("protocol_standard"), {"protocol": []}, brand={"layout": {"title_page": True}}))
    assert hidden.data["title_page"] is None and shown.data["title_page"] is not None


def test_page_break_with_master_starts_new_segment():
    content = {"masters": [{"id": "default"}, {"id": "quer", "orientation": "landscape"}], "body": [
        {"type": "text", "id": "a", "content": {"default": [{"t": "text", "v": "a"}]}},
        {"type": "page_break", "id": "pb", "master": "quer"},
        {"type": "text", "id": "b", "content": {"default": [{"t": "text", "v": "b"}]}},
    ]}
    compiled = compile_scenario(Scenario(content, document_type="custom"))
    assert [segment["master"] for segment in compiled.data["segments"]] == [None, "quer"]
    assert compiled.data["masters"]["quer"]["orientation"] == "landscape"


def test_draft_watermark_only_for_drafts():
    final = compile_scenario(Scenario(system("protocol_standard"), {"protocol": []}))
    draft = compile_scenario(Scenario(system("protocol_standard"), {"protocol": []}, is_draft=True))
    assert final.data["masters"]["default"]["background"] == []
    assert draft.data["masters"]["default"]["background"][0]["t"] == "watermark"


def test_auto_verify_note_unless_template_has_one():
    assert compile_scenario(Scenario(system("protocol_compact"), {"protocol": []})).data["verify"]["auto"] is True
    content = {"masters": [{"id": "default"}], "body": [{"type": "verify_note", "id": "v"}]}
    assert compile_scenario(Scenario(content, document_type="custom")).data["verify"]["auto"] is False


def test_preview_marks_bad_component_and_strict_mode_raises():
    from app.documents.brand_service import resolve_brand
    from app.documents.compiler import CompileInput, LayoutCompiler
    from app.documents.context import BuildContext
    from app.documents.model import DocumentMeta
    from app.documents.strings import strings_for

    content = TemplateContent.model_validate({"masters": [{"id": "default"}], "body": [
        {"type": "data_block", "id": "bad", "component": "todo_table", "params": {"status": "irgendwas"}},
        {"type": "text", "id": "unbound", "content": {"default": [{"t": "bind", "path": "item.name"}]}},
    ]})

    class NoDb:
        def get(self, *args, **kwargs):
            return None

        def scalars(self, *args, **kwargs):
            return []

    def run(strict: bool):
        data = CompileInput(content=content, brand=resolve_brand(NoDb(), 1, None), ctx=BuildContext(db=NoDb(), tenant_id=1, language="de"), meta=DocumentMeta(document_type="custom", title="T"), strings=strings_for("de"), mode="sample", strict=strict)
        return LayoutCompiler(data, NoDb()).compile()

    preview = run(strict=False)
    assert _find(_body(preview), "bad")["t"] == "error"
    assert {item.code for item in preview.diagnostics} == {"invalidParams"}
    with pytest.raises(CompileError) as excinfo:
        run(strict=True)
    assert excinfo.value.node_id == "bad"


class _NoDb:
    def get(self, *args, **kwargs):
        return None

    def query(self, *args, **kwargs):
        raise AssertionError("keine Datenbank erwartet")


def _validate(body, document_type="custom", **extra):
    return [(item.node_id, item.code, item.severity) for item in validate_template(_NoDb(), None, TemplateContent.model_validate({"masters": [{"id": "default"}], "body": body, **extra}), document_type=document_type)]


def test_static_validation_finds_binding_errors():
    result = _validate([
        {"type": "text", "id": "a", "content": {"default": [{"t": "bind", "path": "protocol.gibts_nicht"}]}},
        {"type": "text", "id": "b", "content": {"default": [{"t": "bind", "path": "item.name"}]}},
        {"type": "image", "id": "c", "source": {"kind": "binding", "path": "document.title"}},
        {"type": "table", "id": "d", "source": "document.title", "columns": [{"id": "x"}]},
        {"type": "stack", "id": "e", "repeat": {"source": "protocol.participants"}, "children": [{"type": "text", "id": "f", "content": {"default": [{"t": "bind", "path": "item.name"}]}}]},
        {"type": "text", "id": "g", "visible_if": {"op": "exists", "path": "nichts.da"}},
    ])
    assert ("a", "unknownBinding", "error") in result
    assert ("b", "unknownBinding", "error") in result
    assert ("c", "bindingTypeMismatch", "error") in result
    assert ("d", "bindingTypeMismatch", "error") in result
    assert ("g", "unknownBinding", "error") in result
    assert not [item for item in result if item[0] == "f"]
    assert ("e", "bindingNeedsProtocol", "warning") in result


def test_static_validation_of_components():
    result = _validate([
        {"type": "data_block", "id": "a", "component": "gibts_nicht"},
        {"type": "data_block", "id": "b", "component": "todo_table", "params": {"status": "x"}},
        {"type": "data_block", "id": "c", "component": "protocol_element"},
    ])
    assert ("a", "unknownComponent", "error") in result
    assert ("b", "invalidParams", "error") in result
    assert ("c", "needsProtocol", "warning") in result
    assert _validate([{"type": "data_block", "id": "c", "component": "protocol_element"}], document_type="protocol") == []


def test_draft_watermark_is_enforced_without_template_node():
    """STUDIO-007: Eine Vorlage ohne Wasserzeichen-Knoten kennzeichnet Entwürfe trotzdem."""
    content = {"masters": [{"id": "default"}], "body": [{"type": "text", "id": "t", "content": {"default": [{"t": "text", "v": "x"}]}}]}
    final = compile_scenario(Scenario(content, document_type="custom"))
    draft = compile_scenario(Scenario(content, document_type="custom", is_draft=True))
    assert final.data["masters"]["default"]["background"] == []
    assert [node["t"] for node in draft.data["masters"]["default"]["background"]] == ["watermark"]
