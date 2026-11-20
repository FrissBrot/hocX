"""Nebenläufigkeit: Dokument löschen, während der document-worker sein Ergebnis speichert.

«Endgültig löschen» im Papierkorb (file_trash_service.purge → FileEraser → document_service.
delete_document) sperrte zuerst das Dokument und erst über die Kaskade den Auftrag in
document_job. Der Worker sperrt beim Speichern zuerst den Auftrag (_lock_owned_job) und schreibt
dann Zeilen, die per Fremdschlüssel auf das Dokument zeigen - gegenläufige Reihenfolge, Postgres
brach einen der beiden mit «deadlock detected» ab (E2E file-trash: «Dateien konnten nicht
endgültig gelöscht werden»). Erwartet: das Löschen wartet auf den Worker.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from app.core.db import engine
from app.models.document_entities import Document, DocumentJob
from app.models.entities import Tenant
from app.services import document_service
from tests.document_support import document_storage, gallery_document  # noqa: F401  (Fixture)
from tests.factories import make_tenant


def _wait_until_blocked(timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    with engine.connect() as probe:
        while time.monotonic() < deadline:
            waiting = probe.scalar(
                text("SELECT count(*) FROM pg_stat_activity WHERE wait_event_type = 'Lock' AND datname = current_database()")
            )
            if waiting:
                return True
            time.sleep(0.05)
    return False


def test_deleting_a_document_waits_for_the_worker_instead_of_deadlocking(document_storage):  # noqa: F811
    with Session(engine) as setup:
        tenant = make_tenant(setup, "Dokument löschen parallel")
        stored_file = gallery_document(setup, tenant.id, "sample.docx")
        document = document_service.register_upload(setup, stored_file)
        setup.commit()
        tenant_id, document_id, version_id = tenant.id, document.id, document.current_version_id
        job_id = setup.scalar(
            select(DocumentJob.id).where(DocumentJob.document_version_id == version_id).order_by(DocumentJob.id).limit(1)
        )
    assert job_id is not None

    def delete_in_other_request() -> None:
        with Session(engine) as db:
            document_service.delete_document(db, db.get(Document, document_id))
            db.commit()

    try:
        with Session(engine) as worker, ThreadPoolExecutor(1) as pool:
            # Worker: Auftrag gesperrt wie in _lock_owned_job, Ergebnis noch nicht geschrieben
            worker.execute(select(DocumentJob.id).where(DocumentJob.id == job_id).with_for_update())
            future = pool.submit(delete_in_other_request)
            assert _wait_until_blocked(), "Löschen wartet nicht auf den gesperrten Auftrag"
            # Worker schreibt jetzt Zeilen, die auf das Dokument zeigen (Fremdschlüssel-Sperre)
            worker.execute(text("SELECT id FROM document WHERE id = :id FOR KEY SHARE"), {"id": document_id})
            worker.commit()
            future.result(timeout=30)

        with Session(engine) as check:
            assert check.get(Document, document_id) is None
            assert check.scalar(
                select(func.count()).select_from(DocumentJob).where(DocumentJob.document_version_id == version_id)
            ) == 0
    finally:
        with Session(engine) as cleanup:
            cleanup.execute(delete(Tenant).where(Tenant.id == tenant_id))
            cleanup.commit()
