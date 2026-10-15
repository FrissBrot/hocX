"""Visuelle Regression: gerenderte Seiten der Test-Szenarien gegen eingecheckte Golden-Bilder.

Abgedeckt (Masterprompt §20): einfaches und mehrseitiges Protokoll, Tabellen und Bilder,
Anwesenheitsliste, Finanz- und Statistikbericht, mehrspaltiges Layout, Titelseite mit freier
Ebene, eigene Kopf-/Fusszeile mit abweichender erster Seite, Bedingungen und Wiederholungen,
lange Tabelle (Seitenumbruch, wiederholter Kopf), Schriften, Seitengrössen A5/Letter quer,
alle Fachkomponenten, Unicode, Sprachen und die Varianten des Prüfvermerks.

Vergleich mit Toleranz (Anteil abweichender Pixel), damit minimale Kantenglättungsunterschiede
nicht stören. Bei Abweichung landen Ist-Bild und Differenzbild in ``DOCUMENT_GOLDEN_DIFF_DIR``
(CI lädt das Verzeichnis als Artefakt hoch).

Goldens bewusst aktualisieren: ``scripts/update-document-goldens.sh`` (setzt UPDATE_GOLDENS=1).
"""
from __future__ import annotations

import asyncio
import io
import os
from pathlib import Path

import pytest
from PIL import Image, ImageChops

from tests.documents.conftest import compiled_assets
from tests.documents.fixtures.scenarios import compile_scenario, scenarios

GOLDEN_DIR = Path(__file__).resolve().parent / "goldens"
DIFF_DIR = Path(os.environ.get("DOCUMENT_GOLDEN_DIFF_DIR", "/tmp/document-golden-diffs"))
UPDATE = os.environ.get("UPDATE_GOLDENS") == "1"
PPI = 40
# Anteil der Pixel, die sich (deutlich) unterscheiden dürfen
MAX_CHANGED_RATIO = 0.004
PIXEL_THRESHOLD = 48

SCENARIOS = scenarios()


def _changed_ratio(actual: Image.Image, expected: Image.Image) -> tuple[float, Image.Image]:
    if actual.size != expected.size:
        return 1.0, actual
    diff = ImageChops.difference(actual.convert("RGB"), expected.convert("RGB")).convert("L")
    mask = diff.point(lambda value: 255 if value > PIXEL_THRESHOLD else 0)
    changed = mask.histogram()[255]
    return changed / (actual.size[0] * actual.size[1]), mask


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_scenario_pages_match_goldens(renderer, name):
    scenario = SCENARIOS[name]
    compiled = compile_scenario(scenario)
    assert not [item for item in compiled.diagnostics if item.severity == "error"], compiled.diagnostics
    output = asyncio.run(renderer.render_preview(compiled.data, compiled_assets(compiled), max_pages=scenario.pages, ppi=PPI))
    assert output.pages
    failures: list[str] = []
    for index, png in enumerate(output.pages, start=1):
        file_name = f"{name}-{index}.png"
        golden = GOLDEN_DIR / file_name
        if UPDATE or not golden.exists():
            if not UPDATE:
                failures.append(f"{file_name}: kein Golden vorhanden (scripts/update-document-goldens.sh)")
                continue
            GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
            golden.write_bytes(png)
            continue
        actual = Image.open(io.BytesIO(png))
        ratio, mask = _changed_ratio(actual, Image.open(golden))
        if ratio > MAX_CHANGED_RATIO:
            DIFF_DIR.mkdir(parents=True, exist_ok=True)
            (DIFF_DIR / f"actual-{file_name}").write_bytes(png)
            mask.save(DIFF_DIR / f"diff-{file_name}")
            failures.append(f"{file_name}: {ratio:.2%} der Pixel weichen ab")
    assert failures == []
