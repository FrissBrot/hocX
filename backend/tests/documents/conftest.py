"""Gemeinsame Fixtures der Dokument-Engine-Tests."""
from __future__ import annotations

import json
import re
import subprocess
import tempfile
from pathlib import Path

import pytest

from app.documents.model import Document
from app.documents.renderer import DocumentRenderer, RenderAssets
from tests.documents.fixtures.generate import FIXTURE_DIR, fixture_assets


def load_fixture(name: str) -> Document:
    return Document.model_validate(json.loads((FIXTURE_DIR / f"{name}.json").read_text(encoding="utf-8")))


def fixture_names() -> list[str]:
    return sorted(path.stem for path in FIXTURE_DIR.glob("*.json"))


@pytest.fixture(scope="session")
def renderer():
    instance = DocumentRenderer(concurrency=2, timeout_seconds=120)
    yield instance
    instance.shutdown()


@pytest.fixture(scope="session")
def assets() -> RenderAssets:
    return RenderAssets(files=fixture_assets())


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


@pytest.fixture
def signing_cert(tmp_path, monkeypatch):
    """Dev-Zertifikat (wie scripts/generate-dev-signing-cert.sh) und Konfiguration dafür."""
    from app.core.config import settings
    from app.documents import signing
    from app.documents.devcert import generate

    key_path, cert_path = generate(tmp_path / "signing", password="test-passwort")
    monkeypatch.setattr(settings, "document_signing_key_path", str(key_path))
    monkeypatch.setattr(settings, "document_signing_cert_path", str(cert_path))
    monkeypatch.setattr(settings, "document_signing_key_password", "test-passwort")
    monkeypatch.setattr(settings, "document_signing_chain_path", None)
    monkeypatch.setattr(settings, "document_signing_tsa_url", None)
    signing.reset_signer_cache()
    yield cert_path
    signing.reset_signer_cache()
