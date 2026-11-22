"""Nebenläufigkeit im Papierkorb: Wiederherstellen gleichzeitig mit endgültigem Löschen.

1. Der Job file_trash_purge prüfte «noch im Papierkorb?» ohne Sperre. Stellte jemand die Datei
   genau dann wieder her, wartete der Job am DELETE auf die Wiederherstellung und löschte die
   (jetzt wiederhergestellte) Datei danach trotzdem endgültig - die Person sah «wiederhergestellt»,
   die Datei war weg.
2. Umgekehrt meldete «Wiederherstellen» Erfolg, wenn die Datei während der Anfrage endgültig
   gelöscht wurde (UPDATE traf keine Zeile mehr).
Erwartet: wer zuerst sperrt, gewinnt; der andere Schritt erkennt den neuen Stand.
"""

from __future__ import annotations

import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, text, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import engine
from app.core.trash_scope import TRASH_RETENTION, include_trashed
from app.models import Tenant
from app.models.entities import AppUser, GalleryImage, StoredFile
from app.services import file_trash_service
from tests.factories import make_app_user, make_current_user, make_tenant
from tests.test_share_link_routes import _make_file


@pytest.fixture(autouse=True)
def _isolated_storage(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "storage_root", str(tmp_path / "storage"))
    monkeypatch.setattr(settings, "upload_root", str(tmp_path / "storage" / "uploads"))


def _wait_until_blocked(timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    with engine.connect() as probe:
        while time.monotonic() < deadline:
            if probe.scalar(text("SELECT count(*) FROM pg_locks WHERE NOT granted")):
                return True
            probe.rollback()
            time.sleep(0.05)
    return False


@pytest.fixture()
def trashed():
    with Session(engine) as setup:
        tenant = make_tenant(setup, "Papierkorb parallel")
        account = make_app_user(setup, email=f"trash-{uuid.uuid4().hex[:8]}@example.com", tenant_id=tenant.id, role_code="writer")
        stored_file = _make_file(setup, tenant.id, f"{uuid.uuid4().hex[:8]}.png")
        expired = datetime.now(UTC) - TRASH_RETENTION - timedelta(hours=1)
        setup.execute(update(StoredFile).where(StoredFile.id == stored_file.id).values(deleted_at=expired, deleted_by=account.id))
        setup.commit()
        ids = (tenant.id, account.id, stored_file.id, stored_file.public_id)
    yield ids
    tenant_id, user_id, _file_id, _public_id = ids
    with Session(engine) as cleanup:
        cleanup.execute(text("DELETE FROM storage_object WHERE namespace = 'main' AND key LIKE :prefix"), {"prefix": f"uploads/tenant-{tenant_id}/%"})
        cleanup.execute(delete(GalleryImage).where(GalleryImage.tenant_id == tenant_id))
        cleanup.execute(delete(StoredFile).where(StoredFile.tenant_id == tenant_id).execution_options(include_trashed=True))
        cleanup.execute(text("DELETE FROM audit_log WHERE tenant_id = :t"), {"t": tenant_id})
        cleanup.execute(delete(AppUser).where(AppUser.id == user_id))
        cleanup.execute(delete(Tenant).where(Tenant.id == tenant_id))
        cleanup.commit()


def _run_interleaved(first_step, second_step):
    """first_step läuft in einer Session, deren Commit erst nach dem Start von second_step
    (eigene Session, eigener Thread) durchgeht."""
    pool = ThreadPoolExecutor(1)
    first = Session(engine)
    try:
        original_commit = first.commit
        first.commit = first.flush
        try:
            first_result = first_step(first)
        finally:
            first.commit = original_commit
        future = pool.submit(second_step)
        blocked = _wait_until_blocked()
        first.commit()
        second_result = future.result(timeout=30)
    finally:
        first.rollback()
        first.close()
        pool.shutdown(wait=True)
    return blocked, first_result, second_result


def _file_state(file_id: int):
    with Session(engine) as check, include_trashed(check):
        row = check.get(StoredFile, file_id)
        return None if row is None else ("trashed" if row.deleted_at is not None else "restored")


def test_expiry_purge_does_not_delete_a_file_restored_at_the_same_time(trashed):
    tenant_id, user_id, file_id, public_id = trashed
    user = make_current_user(tenant_id, role="writer", user_id=user_id)

    def purge_job():
        with Session(engine) as db:
            try:
                return file_trash_service.purge_expired(db)
            except Exception as exc:  # Befund festhalten
                return type(exc).__name__

    blocked, restored, purge_result = _run_interleaved(lambda db: file_trash_service.restore(db, user, [public_id]), purge_job)

    assert restored == ([public_id], [])
    assert blocked, "Job wartet nicht auf die Wiederherstellung"
    assert _file_state(file_id) == "restored", f"wiederhergestellte Datei endgültig gelöscht (Job: {purge_result})"


def test_restore_does_not_report_success_for_a_file_purged_at_the_same_time(trashed):
    tenant_id, user_id, file_id, public_id = trashed
    user = make_current_user(tenant_id, role="writer", user_id=user_id)

    def restore_request():
        with Session(engine) as db:
            try:
                return file_trash_service.restore(db, user, [public_id])
            except Exception as exc:  # Befund festhalten
                return type(exc).__name__

    blocked, purged, restored = _run_interleaved(lambda db: file_trash_service.purge(db, user, [public_id]), restore_request)

    assert purged == ([public_id], [])
    assert _file_state(file_id) is None
    assert blocked, "Wiederherstellen wartet nicht auf das Löschen"
    assert restored == ([], ["Datei nicht im Papierkorb"]), f"Wiederherstellen meldet {restored}"
