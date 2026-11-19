"""Nebenläufigkeit beim Löschen eines Termins (PRIV-003).

delete_event löscht zuerst die Dateien der Abgabe-Einreichungen zum Termin (eigener Commit) und
danach den Termin; die Einreichungen fallen per Kaskade weg. Trifft genau dazwischen ein Upload
der Abgabebox ein, verschwindet seine Einreichung mit dem Termin, die Datei (stored_file und
Objekt im Abgabebox-Speicher) bleibt aber ohne jeden Bezug liegen. Erwartet: auch diese Datei
wird gelöscht.
"""

from __future__ import annotations

import io
from datetime import UTC, datetime

import pytest
from PIL import Image
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.db import engine
from app.core.storage import ABGABEBOX, get_object_store
from app.models import Event, Tenant
from app.models.entities import StoredFile, SubmissionAssignment, SubmissionUpload, SubmissionUploadFile
from app.services import deletion_service, storage_migration_service
from app.services.event_service import EventService
from tests.factories import make_event, make_tenant


@pytest.fixture(autouse=True)
def _isolated_storage(monkeypatch, tmp_path):
    from app.core.config import settings

    monkeypatch.setattr(settings, "storage_root", str(tmp_path / "storage"))
    monkeypatch.setattr(settings, "upload_root", str(tmp_path / "storage" / "uploads"))
    monkeypatch.setattr(settings, "abgabebox_storage_root", str(tmp_path / "abgabebox"))
    monkeypatch.setattr(settings, "thumbnail_root", str(tmp_path / "thumbnails"))
    monkeypatch.setattr(settings, "storage_work_root", str(tmp_path / "work"))


def _png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (8, 6), "white").save(buffer, format="PNG")
    return buffer.getvalue()


def _upload(db: Session, *, tenant_id: int, assignment_id: int, event_id: int, key: str) -> int:
    """Wie abgabebox insert_full_upload: Einreichung + Datei in einer Transaktion, committet."""
    get_object_store().put_bytes(db, ABGABEBOX, key, _png(), content_type="image/png")
    upload = SubmissionUpload(assignment_id=assignment_id, event_id=event_id, status="submitted", submitted_at=datetime.now(UTC))
    stored_file = StoredFile(tenant_id=tenant_id, original_name="bericht.png", mime_type="image/png", storage_path=key, scan_status="clean")
    db.add_all([upload, stored_file])
    db.flush()
    db.add(SubmissionUploadFile(upload_id=upload.id, stored_file_id=stored_file.id))
    db.commit()
    return stored_file.id


def test_upload_arriving_while_event_is_deleted_leaves_no_orphan(monkeypatch):
    with Session(engine) as setup:
        tenant = make_tenant(setup, "Termin löschen parallel")
        event = make_event(setup, tenant.id, title="Badetag")
        event.tag = "lager"
        assignment = SubmissionAssignment(tenant_id=tenant.id, title="Berichte", public_slug="berichte-race", source_type="events", tag_filter="lager")
        setup.add(assignment)
        setup.flush()
        tenant_id, event_id, assignment_id = tenant.id, event.id, assignment.id
        early_file_id = _upload(setup, tenant_id=tenant_id, assignment_id=assignment_id, event_id=event_id, key="race/frueh.png")

    original_erase = deletion_service.erase_uploads_of
    late_file_ids: list[int] = []

    def erase_then_concurrent_upload(db, **kwargs):
        erased = original_erase(db, **kwargs)
        if not late_file_ids:
            # Upload der Abgabebox trifft zwischen Datei-Löschung und Termin-Löschung ein
            with Session(engine) as abgabebox:
                late_file_ids.append(_upload(abgabebox, tenant_id=tenant_id, assignment_id=assignment_id, event_id=event_id, key="race/spaet.png"))
        return erased

    monkeypatch.setattr(deletion_service, "erase_uploads_of", erase_then_concurrent_upload)
    try:
        with Session(engine) as db:
            assert EventService().delete_event(db, event_id) is True
        with Session(engine) as check:
            assert check.get(Event, event_id) is None
            assert check.get(StoredFile, early_file_id) is None
            assert check.get(StoredFile, late_file_ids[0]) is None, "Datei der gleichzeitigen Einreichung bleibt verwaist zurück"
            storage_migration_service.purge_deleted_objects(check)
            assert not get_object_store().exists(ABGABEBOX, "race/spaet.png")
    finally:
        with Session(engine) as cleanup:
            cleanup.execute(delete(StoredFile).where(StoredFile.tenant_id == tenant_id))
            cleanup.execute(delete(Tenant).where(Tenant.id == tenant_id))
            cleanup.commit()
