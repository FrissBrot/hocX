"""Regression tests for DocumentTemplateService (previously zero coverage) - materializes a
tenant's document-template configuration into a real filesystem directory of .tex partials
that ExportService later compiles with pdflatex/xelatex. Focuses on: the filesystem
materialization actually happening with the expected structure, the auto-generated template
code deduplication, the is_default single-winner invariant, and the LaTeX-escaping helper that
protects free-text tenant/admin input (title/location/footer contact text) from breaking out of
the generated .tex source.

settings.storage_root is monkeypatched to a tmp_path for every test here - in the real running
stack it is bind-mounted to the host's ./storage directory (see docker-compose.yml), so writing
into it unmonkeypatched would leave real files behind on disk."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.schemas.document_template import DocumentTemplateCreate, DocumentTemplateUpdate
from app.services.document_template_service import DocumentTemplateService
from tests.factories import make_tenant


@pytest.fixture(autouse=True)
def _isolated_storage_root(monkeypatch, tmp_path):
    from app.core.config import settings

    monkeypatch.setattr(settings, "storage_root", str(tmp_path))
    return tmp_path


def test_create_document_template_materializes_expected_filesystem_structure(db):
    tenant = make_tenant(db, "Template Verein")
    service = DocumentTemplateService()

    result = service.create_document_template(
        db, DocumentTemplateCreate(name="Standard Protokoll"), tenant_id=tenant.id
    )

    output_dir = Path(result.filesystem_path)
    assert output_dir.exists()
    assert (output_dir / "main.tex").exists()
    assert (output_dir / "styles" / "theme.tex").exists()
    assert (output_dir / "preamble.tex").exists()
    assert (output_dir / "elements").is_dir()
    assert result.code == "standard-protokoll"


def test_create_document_template_as_default_unsets_previous_default(db):
    tenant = make_tenant(db, "Default Swap Verein")
    service = DocumentTemplateService()

    first = service.create_document_template(
        db, DocumentTemplateCreate(name="Erste Vorlage", is_default=True), tenant_id=tenant.id
    )
    assert first.is_default is True

    second = service.create_document_template(
        db, DocumentTemplateCreate(name="Zweite Vorlage", is_default=True), tenant_id=tenant.id
    )
    assert second.is_default is True

    refreshed_first = service.get_document_template(db, first.id)
    assert refreshed_first.is_default is False


def test_generate_template_code_dedupes_on_name_collision(db):
    tenant = make_tenant(db, "Code Collision Verein")
    service = DocumentTemplateService()

    first = service.create_document_template(db, DocumentTemplateCreate(name="Jahresbericht"), tenant_id=tenant.id)
    second = service.create_document_template(db, DocumentTemplateCreate(name="Jahresbericht"), tenant_id=tenant.id)

    assert first.code == "jahresbericht"
    assert second.code == "jahresbericht-2"


def test_delete_document_template_removes_directory_and_row(db):
    tenant = make_tenant(db, "Delete Verein")
    service = DocumentTemplateService()
    created = service.create_document_template(db, DocumentTemplateCreate(name="Zu löschen"), tenant_id=tenant.id)
    output_dir = Path(created.filesystem_path)
    assert output_dir.exists()

    deleted = service.delete_document_template(db, created.id)

    assert deleted is True
    assert service.get_document_template(db, created.id) is None
    assert not output_dir.exists()


def test_snapshot_template_for_protocol_raises_when_files_missing(db):
    from tests.factories import make_protocol, make_template

    tenant = make_tenant(db, "Snapshot Missing Verein")
    service = DocumentTemplateService()
    created = service.create_document_template(db, DocumentTemplateCreate(name="Kaputte Vorlage"), tenant_id=tenant.id)

    import shutil

    shutil.rmtree(created.filesystem_path)

    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id)

    with pytest.raises(ValueError, match="Document template files are missing"):
        service.snapshot_template_for_protocol(db, protocol, created.id)


# --- _escape_latex (protects free-text admin input from breaking the generated .tex) -----


def test_escape_latex_escapes_all_special_characters():
    raw = r"100% & $money$ #1 _underscore_ {brace} ~tilde ^caret \backslash"
    escaped = DocumentTemplateService._escape_latex(raw)

    assert "%" not in escaped.replace(r"\%", "")
    assert r"\&" in escaped
    assert r"\%" in escaped
    assert r"\$" in escaped
    assert r"\#" in escaped
    assert r"\_" in escaped
    assert r"\{" in escaped
    assert r"\}" in escaped
    assert r"\textasciitilde{}" in escaped
    assert r"\textasciicircum{}" in escaped
    assert r"\textbackslash{}" in escaped


# --- M9: partial-commit risk (DB row committed before filesystem I/O) --------------------


def test_create_document_template_rolls_back_row_on_filesystem_error(db, monkeypatch):
    """DocumentTemplateRepository.create() commits the DB row immediately, before
    _materialize_template()'s mkdir/copy2/write_text calls run. If those raise OSError (full
    disk, permission issue), the freshly-created row must not survive as an orphan with a
    broken filesystem_path - it should be deleted again."""
    from sqlalchemy import select

    from app.models import DocumentTemplate

    tenant = make_tenant(db, "OSError Create Verein")
    service = DocumentTemplateService()

    def _boom(self, db, template):
        raise OSError("no space left on device")

    monkeypatch.setattr(DocumentTemplateService, "_materialize_template", _boom)

    with pytest.raises(OSError):
        service.create_document_template(db, DocumentTemplateCreate(name="Kaputt beim Schreiben"), tenant_id=tenant.id)

    rows = db.scalars(select(DocumentTemplate).where(DocumentTemplate.tenant_id == tenant.id)).all()
    assert rows == []


def test_update_document_template_filesystem_error_keeps_existing_row(db, monkeypatch):
    """Unlike create, update_document_template's row already existed with a valid
    filesystem_path before the call - an OSError during rematerialization must not delete it,
    only fail loudly."""
    from app.models import DocumentTemplate

    tenant = make_tenant(db, "OSError Update Verein")
    service = DocumentTemplateService()
    created = service.create_document_template(db, DocumentTemplateCreate(name="Original"), tenant_id=tenant.id)

    def _boom(self, db, template):
        raise OSError("no space left on device")

    monkeypatch.setattr(DocumentTemplateService, "_materialize_template", _boom)

    with pytest.raises(OSError):
        service.update_document_template(db, created.id, DocumentTemplateUpdate(name="Neuer Name"))

    still_there = db.get(DocumentTemplate, created.id)
    assert still_there is not None


def test_update_document_template_partial_payload_rematerializes(db):
    tenant = make_tenant(db, "Update Verein")
    service = DocumentTemplateService()
    created = service.create_document_template(db, DocumentTemplateCreate(name="Original Name"), tenant_id=tenant.id)

    updated = service.update_document_template(db, created.id, DocumentTemplateUpdate(name="Neuer Name"))

    assert updated.name == "Neuer Name"
    assert Path(updated.filesystem_path).exists()
