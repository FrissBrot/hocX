"""Audit MAIN-BE-004 / MAIN-BE-013: Exporte behalten je Protokoll und Format nur den neuesten
Cache, der Sweep löscht Zeilen und Dateien zusammen (finales PDF ausgenommen), und ein
LaTeX-Export erhöht die PDF-Version nicht."""
from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select

from app.core.config import settings
from app.models.entities import ProtocolExportCache, StoredFile
from app.services.export_service import ExportService
from app.core.storage import get_object_store
from tests.factories import make_protocol, make_protocol_element, make_template, make_tenant
from tests.test_export_service import _protocol_with_template_dir


def _pdf_caches(db, protocol_id: int) -> list[ProtocolExportCache]:
    return list(
        db.scalars(
            select(ProtocolExportCache).where(
                ProtocolExportCache.protocol_id == protocol_id, ProtocolExportCache.export_format == "pdf"
            )
        )
    )


def test_repeated_pdf_export_keeps_only_newest_cache_and_file(db):
    _, _, protocol = _protocol_with_template_dir(db)
    make_protocol_element(db, protocol.id, sort_index=0, section_name="Traktandum 1")
    service = ExportService()

    first = asyncio.run(service.export_pdf(db, protocol.id))
    first_file = db.scalar(select(StoredFile).where(StoredFile.public_id == first.generated_file_id))
    first_path = Path(settings.storage_root) / first_file.storage_path
    first_file_id = first_file.id
    assert first_path.exists()

    asyncio.run(service.export_pdf(db, protocol.id))

    caches = _pdf_caches(db, protocol.id)
    assert len(caches) == 1
    assert caches[0].generated_file_id != first_file_id
    assert db.get(StoredFile, first_file_id) is None
    # S3-008: physisch entfernt erst der Purge-Job nach dem Commit.
    get_object_store().purge_deleted(db)
    assert not first_path.exists()


def test_latex_export_does_not_bump_pdf_version(db):
    _, _, protocol = _protocol_with_template_dir(db)
    make_protocol_element(db, protocol.id, sort_index=0, section_name="Traktandum 1")
    service = ExportService()

    asyncio.run(service.export_pdf(db, protocol.id))
    service.export_latex(db, protocol.id)
    result = asyncio.run(service.export_pdf(db, protocol.id))

    db.refresh(protocol)
    assert protocol.version_minor == 0
    assert result.version_minor == 0


def _synthetic_export(db, protocol, name: str, *, age_days: int) -> tuple[ProtocolExportCache, Path]:
    generated = Path(settings.export_root) / "generated"
    generated.mkdir(parents=True, exist_ok=True)
    path = generated / name
    path.write_bytes(b"%PDF-test")
    old = (datetime.now() - timedelta(days=age_days)).timestamp()
    os.utime(path, (old, old))
    stored_file = StoredFile(
        tenant_id=protocol.tenant_id, original_name=name, mime_type="application/pdf",
        storage_path=str(path.relative_to(settings.storage_root)), file_size_bytes=9,
    )
    db.add(stored_file)
    db.flush()
    cache = ProtocolExportCache(
        protocol_id=protocol.id, export_format="pdf", latex_source="x", generated_file_id=stored_file.id, generator_version="t",
    )
    db.add(cache)
    db.flush()
    cache.created_at = datetime.now(UTC) - timedelta(days=age_days)
    db.flush()
    return cache, path


def test_sweep_deletes_rows_and_files_but_keeps_final_pdf(db, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "storage_root", str(tmp_path))
    monkeypatch.setattr(settings, "export_root", str(tmp_path / "exports"))
    tenant = make_tenant(db, "Sweep")
    template = make_template(db, tenant.id)
    open_protocol = make_protocol(db, tenant.id, template.id, protocol_number="P-offen")
    closed_protocol = make_protocol(db, tenant.id, template.id, protocol_number="P-zu", status="abgeschlossen")
    open_cache, open_path = _synthetic_export(db, open_protocol, "offen.pdf", age_days=40)
    older_closed, older_closed_path = _synthetic_export(db, closed_protocol, "zu-alt.pdf", age_days=60)
    final_cache, final_path = _synthetic_export(db, closed_protocol, "zu-final.pdf", age_days=45)
    open_file_id, older_file_id, final_file_id = open_cache.generated_file_id, older_closed.generated_file_id, final_cache.generated_file_id
    orphan = Path(settings.export_root) / "generated" / "waise.pdf"
    orphan.write_bytes(b"%PDF")
    old = (datetime.now() - timedelta(days=40)).timestamp()
    os.utime(orphan, (old, old))

    result = ExportService().cleanup_old_generated_exports(db, retention_days=30)

    assert result["deleted_rows"] == 2
    assert db.get(StoredFile, open_file_id) is None
    assert db.get(StoredFile, older_file_id) is None
    # S3-008: physisch entfernt erst der Purge-Job nach dem Commit.
    get_object_store().purge_deleted(db)
    assert not open_path.exists()
    assert not older_closed_path.exists()
    assert not orphan.exists()
    assert db.get(StoredFile, final_file_id) is not None
    assert final_path.exists()
