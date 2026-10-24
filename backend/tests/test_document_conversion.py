"""Sandbox-Kindprozesse, PDF-Konvertierung mit LibreOffice und OCR-Fallback.

Läuft gegen die echten Programme aus dem Backend-Image (backend/Dockerfile.test). Fehlen sie
(lokaler Lauf ausserhalb des Images), werden die betroffenen Tests übersprungen."""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from app.services.documents import formats, sandbox
from app.services.documents.content import build_content
from app.services.documents.convert import ConversionUnavailable, convert, soffice_binary
from app.services.documents.ocr import ocr_available, ocr_pdf
from app.services.documents.parsers import get_parser

FIXTURES = Path(__file__).parent / "fixtures" / "documents"
MB = 1024 * 1024
needs_soffice = pytest.mark.skipif(soffice_binary() is None, reason="LibreOffice nicht installiert")
needs_ocr = pytest.mark.skipif(not ocr_available(), reason="Tesseract/Poppler nicht installiert")

CONVERT_LIMITS = sandbox.Limits(timeout_seconds=120, memory_bytes=3072 * MB)


def _pdf_text(data: bytes) -> str:
    import pdfplumber

    with pdfplumber.open(io.BytesIO(data)) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


def test_sandbox_kills_process_group_on_timeout(tmp_path):
    with pytest.raises(sandbox.SandboxTimeout):
        sandbox.run(["sh", "-c", "sleep 30 & sleep 30"], work_dir=tmp_path, limits=sandbox.Limits(timeout_seconds=1, memory_bytes=256 * MB))


def test_sandbox_enforces_memory_limit(tmp_path):
    with pytest.raises(sandbox.SandboxError):
        sandbox.run(
            ["python3", "-c", "x = bytearray(600 * 1024 * 1024)"],
            work_dir=tmp_path, limits=sandbox.Limits(timeout_seconds=30, memory_bytes=256 * MB),
        )


def test_sandbox_enforces_file_size_limit(tmp_path):
    with pytest.raises(sandbox.SandboxError):
        sandbox.run(
            ["python3", "-c", "open('big', 'wb').write(b'0' * 2 * 1024 * 1024)"],
            work_dir=tmp_path, limits=sandbox.Limits(timeout_seconds=30, memory_bytes=256 * MB, file_size_bytes=1 * MB),
        )


def test_sandbox_environment_contains_no_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://geheim")
    monkeypatch.setenv("STORAGE_CREDENTIALS_KEY", "geheim")
    result = sandbox.run(["env"], work_dir=tmp_path, limits=sandbox.Limits(timeout_seconds=10, memory_bytes=256 * MB))
    names = {line.split("=", 1)[0] for line in result.stdout.decode().splitlines()}
    assert "DATABASE_URL" not in names and "STORAGE_CREDENTIALS_KEY" not in names
    assert names <= {"PATH", "HOME", "TMPDIR", "LANG", "LC_ALL", "OMP_THREAD_LIMIT", "OPENBLAS_NUM_THREADS", "PYTHONDONTWRITEBYTECODE", "PWD", "SHLVL", "_"}


def test_sandbox_error_message_is_truncated(tmp_path):
    with pytest.raises(sandbox.SandboxError) as info:
        sandbox.run(
            ["python3", "-c", "import sys; sys.stderr.write('x' * 10000); sys.exit(3)"],
            work_dir=tmp_path, limits=sandbox.Limits(timeout_seconds=10, memory_bytes=256 * MB),
        )
    assert len(str(info.value)) < sandbox.STDERR_LIMIT + 50


@needs_soffice
@pytest.mark.parametrize("name, mime_type", [("sample.docx", formats.DOCX), ("sample.odt", formats.ODT), ("sample.rtf", formats.RTF), ("sample.doc", formats.DOC)])
def test_office_documents_convert_to_pdf(tmp_path, name, mime_type):
    pdf = convert((FIXTURES / name).read_bytes(), mime_type, target="pdf", work_dir=tmp_path, limits=CONVERT_LIMITS)
    assert pdf.startswith(b"%PDF-")
    text = _pdf_text(pdf)
    assert "Jahresbericht Pfadi Musterhausen" in text
    assert "Grüße aus dem Sommerlager" in text


@needs_soffice
def test_text_conversion_uses_detected_encoding(tmp_path):
    pdf = convert((FIXTURES / "sample-cp1252.txt").read_bytes(), formats.TXT, target="pdf", work_dir=tmp_path, limits=CONVERT_LIMITS)
    assert "Grüße aus Zürich" in _pdf_text(pdf)


@needs_soffice
def test_csv_converts_to_pdf_table(tmp_path):
    pdf = convert((FIXTURES / "sample.csv").read_bytes(), formats.CSV, target="pdf", work_dir=tmp_path, limits=CONVERT_LIMITS)
    text = _pdf_text(pdf)
    assert "Anna" in text and "Leitung" in text


@needs_soffice
def test_doc_converts_to_docx_for_extraction(tmp_path):
    docx = convert((FIXTURES / "sample.doc").read_bytes(), formats.DOC, target="docx", work_dir=tmp_path, limits=CONVERT_LIMITS)
    content = build_content(get_parser("docx")(docx), mime_type=formats.DOC)
    headings = [block["text"] for block in content["blocks"] if block["type"] == "heading"]
    assert headings[0] == "Jahresbericht Pfadi Musterhausen"


@needs_soffice
def test_corrupt_office_file_fails_cleanly(tmp_path):
    with pytest.raises(sandbox.SandboxError):
        convert(b"PK\x03\x04 defekt", formats.DOCX, target="pdf", work_dir=tmp_path, limits=sandbox.Limits(timeout_seconds=60, memory_bytes=3072 * MB))


def test_conversion_reports_missing_libreoffice(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.documents.convert.soffice_binary", lambda: None)
    with pytest.raises(ConversionUnavailable):
        convert(b"x", formats.DOCX, target="pdf", work_dir=tmp_path, limits=CONVERT_LIMITS)


def test_unconvertible_format_is_rejected(tmp_path):
    if soffice_binary() is None:
        pytest.skip("LibreOffice nicht installiert")
    with pytest.raises(ValueError):
        convert(b"x", "application/zip", target="pdf", work_dir=tmp_path, limits=CONVERT_LIMITS)


@needs_ocr
def test_ocr_recognizes_scanned_pdf(tmp_path):
    parsed = ocr_pdf(
        (FIXTURES / "scanned.pdf").read_bytes(), page_count=1, work_dir=tmp_path,
        limits=sandbox.Limits(timeout_seconds=120, memory_bytes=1024 * MB),
    )
    content = build_content(parsed, mime_type=formats.PDF)
    text = " ".join(block["text"] for block in content["blocks"])
    assert "Hauptversammlung" in text
    assert parsed.ocr_applied is True
    assert parsed.parser == "pdf+ocr"
    assert all(block["page"] == 1 for block in content["blocks"])
