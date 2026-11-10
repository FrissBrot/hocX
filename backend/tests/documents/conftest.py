"""Gemeinsame Fixtures der Document-Studio-Tests."""
from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

import pytest

from app.documents.renderer import DocumentRenderer, RenderAssets
from tests.documents.fixtures.scenarios import compile_scenario, scenarios


@pytest.fixture(scope="session")
def renderer():
    instance = DocumentRenderer(concurrency=2, timeout_seconds=120)
    yield instance
    instance.shutdown()


@pytest.fixture(scope="session")
def scenario_map():
    return scenarios()


def compiled_assets(compiled) -> RenderAssets:
    return RenderAssets(files=compiled.files, fonts=compiled.fonts)


def compile_named(name: str):
    return compile_scenario(scenarios()[name])


def pdf_text(pdf: bytes) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "doc.pdf"
        path.write_bytes(pdf)
        return subprocess.run(["pdftotext", "-enc", "UTF-8", str(path), "-"], check=True, capture_output=True, text=True).stdout


def pdf_pages(pdf: bytes) -> list[str]:
    return pdf_text(pdf).split("\f")


def normalize(text: str) -> str:
    """Silbentrennung und Leerraum entfernen, damit Zeilenumbrüche im PDF nicht stören."""
    text = re.sub(r"-\n", "", text)
    return re.sub(r"\s+", "", text)


@pytest.fixture(autouse=True)
def _system_templates(request):
    """DB-Tests: Systemvorlagen wie beim App-Start in der Testtransaktion synchronisieren."""
    if "db" not in request.fixturenames:
        return
    from app.documents.system_templates import sync_system_templates

    db = request.getfixturevalue("db")
    sync_system_templates(db)
    db.flush()
