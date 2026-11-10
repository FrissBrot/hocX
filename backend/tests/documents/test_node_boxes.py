"""Positionen der Knoten in der Vorschau (Klick im Designer): Marken aus Typst, Umrechnung in
Rechtecke, unverändertes Layout, Vorschau-Cache."""
from __future__ import annotations

import asyncio

from app.documents.node_boxes import MM_TO_PT, node_boxes
from app.documents.renderer import RenderOutput
from app.documents.service import _PreviewCache
from tests.documents.conftest import compiled_assets
from tests.documents.fixtures.scenarios import Scenario, all_blocks_content, all_data_blocks, compile_scenario, protocol_elements, system

A4 = {"width": 210, "height": 297, "margins": [20, 15, 20, 15]}


def _mark(node_id, edge, page, y):
    return {"id": node_id, "edge": edge, "pos": {"page": page, "x": "42.5pt", "y": f"{y}pt"}}


def test_boxes_follow_marks_across_pages_and_skip_orphaned_starts():
    top, bottom = 20 * MM_TO_PT, (297 - 20) * MM_TO_PT
    marks = [
        _mark("a", "start", 1, 100), _mark("a", "end", 1, 160),
        _mark("b", "start", 1, 700), _mark("b", "end", 3, 200),
        # Anfangsmarke knapp über dem Seitenende: der Knoten beginnt erst auf Seite 2
        _mark("c", "start", 3, bottom - 5), _mark("c", "end", 4, 150),
        _mark("lonely", "end", 1, 10), _mark("open", "start", 1, 10),
    ]
    boxes = [box.as_dict() for box in node_boxes(marks, A4)]
    assert [(box["node_id"], box["page"]) for box in boxes] == [("a", 1), ("b", 1), ("b", 2), ("b", 3), ("c", 4)]
    assert boxes[0]["y"] == 100 and boxes[0]["height"] == 60 and boxes[0]["x"] == round(15 * MM_TO_PT, 2)
    assert boxes[2]["y"] == round(top, 2) and boxes[2]["height"] == round(bottom - top, 2)
    assert boxes[4]["y"] == round(top, 2)
    assert node_boxes(None, A4) == [] and node_boxes([_mark("x", "start", 1, "kaputt")], A4) == []


def test_marks_locate_nodes_and_blocks_without_changing_the_layout(renderer):
    blocks = protocol_elements(3)
    for index, element in enumerate(blocks):
        for child_index, child in enumerate(element["children"]):
            child["source"] = f"00000000-0000-4000-8000-00000000000{index}:{child_index}"
    scenario = Scenario(system("protocol_standard"), {"protocol": blocks}, pages=2)
    compiled = compile_scenario(scenario)
    assets = compiled_assets(compiled)
    plain = asyncio.run(renderer.render(compiled.data, assets, fmt="png", max_pages=4, ppi=40))
    marked = asyncio.run(renderer.render({**compiled.data, "node_marks": True}, assets, fmt="png", max_pages=4, ppi=40))
    assert plain.marks is None
    assert marked.pages == plain.pages, "Positionsmarken dürfen das Layout nicht verändern"
    boxes = node_boxes(marked.marks, compiled.data["page"])
    ids = {box.node_id for box in boxes}
    assert "protocol" in ids
    assert any(node_id.startswith("source:00000000-0000-4000-8000-000000000000:") for node_id in ids)
    protocol = [box for box in boxes if box.node_id == "protocol"]
    first_block = next(box for box in boxes if box.node_id.startswith("source:") and box.page == protocol[0].page)
    # Der Baustein liegt innerhalb des Protokollinhalts
    assert protocol[0].y <= first_block.y and first_block.y + first_block.height <= protocol[0].y + protocol[0].height + 1


def test_marks_in_the_title_page_and_all_component_types(renderer):
    compiled = compile_scenario(Scenario(all_blocks_content(), {"all": all_data_blocks()}, document_type="custom", pages=6))
    output = asyncio.run(renderer.render({**compiled.data, "node_marks": True}, compiled_assets(compiled), fmt="png", max_pages=1, ppi=30))
    assert output.marks and {mark["edge"] for mark in output.marks} == {"start", "end"}


def test_preview_cache_returns_identical_results_and_stays_bounded(monkeypatch):
    from app.documents.renderer import RenderAssets

    cache = _PreviewCache()
    assets = RenderAssets(files={"assets/a.png": b"x"}, fonts={})
    key = _PreviewCache.key(1, {"body": [1]}, assets, 4)
    assert key == _PreviewCache.key(1, {"body": [1]}, assets, 4)
    assert key != _PreviewCache.key(2, {"body": [1]}, assets, 4)
    assert key != _PreviewCache.key(1, {"body": [1]}, RenderAssets(files={"assets/a.png": b"y"}, fonts={}), 4)
    assert key != _PreviewCache.key(1, {"body": [1]}, assets, 5)
    output = RenderOutput(pages=[b"p" * 10], page_count=1)
    cache.put(key, output)
    assert cache.get(key) is output
    monkeypatch.setattr(_PreviewCache, "MAX_BYTES", 25)
    cache.put("b", RenderOutput(pages=[b"q" * 10]))
    cache.put("c", RenderOutput(pages=[b"r" * 10]))
    assert cache.get(key) is None and cache.get("c") is not None
