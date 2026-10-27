"""Wo jeder Knoten in der Vorschau steht: aus den Positionsmarken der Typst-Query
(``<hocx-node>``, siehe typst/theme.typ: node-mark) Rechtecke je Seite in pt.

Marken gibt es am Anfang und Ende jedes Knotens der obersten Ebene (Inhalt, Titelseite) und
jedes Bausteins einer Sitzungsvorlage (``source:<schlüssel>``). Die Breite ist die des
Satzspiegels: der Designer wählt per Klick nur Knoten untereinander aus.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

MM_TO_PT = 72 / 25.4
# Eine Anfangsmarke so nah am Seitenende gehört zum Knoten, der erst auf der nächsten Seite
# beginnt (unteilbare Blöcke rutschen ganz auf die nächste Seite, die Marke bleibt zurück).
_ORPHAN_START_PT = 12 * MM_TO_PT


@dataclass(frozen=True)
class NodeBox:
    node_id: str
    page: int
    x: float
    y: float
    width: float
    height: float

    def as_dict(self) -> dict[str, Any]:
        return {"node_id": self.node_id, "page": self.page, "x": self.x, "y": self.y, "width": self.width, "height": self.height}


def _pt(value: Any) -> float:
    text = str(value).strip()
    if text.endswith("pt"):
        text = text[:-2]
    return float(text)


def page_size_pt(page: dict[str, Any]) -> tuple[float, float]:
    width, height = float(page["width"]) * MM_TO_PT, float(page["height"]) * MM_TO_PT
    return width, height


def node_boxes(marks: list[dict[str, Any]] | None, page: dict[str, Any]) -> list[NodeBox]:
    """``page`` ist ``document["page"]`` (mm: width, height, margins [oben, rechts, unten, links])."""
    if not marks:
        return []
    width, height = page_size_pt(page)
    top, right, bottom, left = (float(value) * MM_TO_PT for value in page.get("margins") or (0, 0, 0, 0))
    content_top, content_bottom = top, height - bottom
    open_marks: dict[str, list[tuple[int, float]]] = {}
    boxes: list[NodeBox] = []
    for mark in marks:
        try:
            node_id = str(mark["id"])
            position = mark["pos"]
            current = (int(position["page"]), _pt(position["y"]))
        except (KeyError, TypeError, ValueError):
            continue
        if mark.get("edge") == "start":
            open_marks.setdefault(node_id, []).append(current)
            continue
        starts = open_marks.get(node_id)
        if not starts:
            continue
        start_page, start_y = starts.pop()
        end_page, end_y = current
        if end_page > start_page and content_bottom - start_y < _ORPHAN_START_PT:
            start_page, start_y = start_page + 1, content_top
        for number in range(start_page, end_page + 1):
            y0 = start_y if number == start_page else content_top
            y1 = end_y if number == end_page else content_bottom
            if y1 - y0 < 1:
                continue
            boxes.append(NodeBox(node_id, number, round(left, 2), round(y0, 2), round(width - left - right, 2), round(y1 - y0, 2)))
    return boxes
