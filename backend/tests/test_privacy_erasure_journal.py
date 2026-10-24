"""Datenschutz-Audit PRIV-010 (Umsetzungsplan Paket 4): Löschungen landen im Löschjournal und werden
nach einem Restore erneut angewendet; abschalten nur mit Begründung."""
from __future__ import annotations

import io
from datetime import UTC, date, datetime, timedelta

import pytest
from PIL import Image
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.core.storage import ABGABEBOX, get_object_store
from app.models import AppUser, Event, StoredFile, SubmissionAssignment, SubmissionUpload, SubmissionUploadFile
from app.services import backup_admin_service, erasure_journal
from app.services.event_service import EventService
from app.services.participant_service import ParticipantService
from tests.factories import make_app_user, make_event, make_tenant


@pytest.fixture(autouse=True)
def _isolated_storage(monkeypatch, tmp_path):
    from app.core.config import settings

    monkeypatch.setattr(settings, "storage_root", str(tmp_path / "storage"))
    monkeypatch.setattr(settings, "upload_root", str(tmp_path / "storage" / "uploads"))
    monkeypatch.setattr(settings, "abgabebox_storage_root", str(tmp_path / "abgabebox"))
    monkeypatch.setattr(settings, "thumbnail_root", str(tmp_path / "thumbnails"))


def _journal(db, kind: str, public_id) -> list:
    return list(db.execute(text("SELECT * FROM erasure_journal WHERE kind = :k AND subject_public_id = :p"), {"k": kind, "p": public_id}).all())


def _snapshot(db) -> datetime:
    return db.scalar(text("SELECT now() - interval '1 second'"))


def test_deleted_person_is_journaled_and_deleted_again_after_restore(db):
    tenant = make_tenant(db, "Journal")
    make_app_user(db, email="journal-admin@example.com", tenant_id=tenant.id, role_code="admin")
    person = make_app_user(db, email="journal@example.com", tenant_id=tenant.id)
    public_id, role_id = person.public_id, person.role_id
    snapshot = _snapshot(db)

    ParticipantService().delete_participant(db, person.id, tenant_id=tenant.id)
    assert len(_journal(db, "app_user", public_id)) == 1

    # Wie nach einem Restore: dieselbe Person ist wieder da.
    db.add(AppUser(public_id=public_id, tenant_id=tenant.id, role_id=role_id, display_name="Zurück", login_enabled=False))
    db.flush()
    result = erasure_journal.apply(db, erasure_journal.entries_since(db, snapshot))

    assert result["applied"] >= 1
    assert db.scalar(select(AppUser.id).where(AppUser.public_id == public_id)) is None


def test_apply_is_limited_to_the_given_tenant(db):
    tenant = make_tenant(db, "Quelle")
    other = make_tenant(db, "Kopie")
    person = make_app_user(db, email="nur-quelle@example.com", tenant_id=other.id)
    entry = erasure_journal.ErasureEntry("app_user", person.public_id, tenant.public_id, datetime.now(UTC))

    result = erasure_journal.apply(db, [entry], tenant_id=tenant.id)

    assert result["missing"] == 1
    assert db.get(AppUser, person.id) is not None


def test_tenant_entries_are_skipped_for_a_tenant_copy(db):
    tenant = make_tenant(db, "Kopie bleibt")
    entry = erasure_journal.ErasureEntry("tenant", tenant.public_id, tenant.public_id, datetime.now(UTC))

    result = erasure_journal.apply(db, [entry], tenant_id=tenant.id, skip_kinds=("tenant",))

    assert result["skipped"] == 1


def test_deleting_an_event_removes_its_submitted_files_and_journals_it(db):
    tenant = make_tenant(db, "Termin")
    event = make_event(db, tenant.id, title="Lager", event_date=date(2026, 7, 1))
    assignment = SubmissionAssignment(tenant_id=tenant.id, title="Fotos", public_slug="termin-fotos", source_type="events", tag_filter="lager")
    db.add(assignment)
    db.flush()
    upload = SubmissionUpload(assignment_id=assignment.id, event_id=event.id, status="submitted")
    db.add(upload)
    db.flush()
    buffer = io.BytesIO()
    Image.new("RGB", (4, 4), "white").save(buffer, format="PNG")
    get_object_store().put_bytes(db, ABGABEBOX, "termin/foto.png", buffer.getvalue(), content_type="image/png")
    stored = StoredFile(tenant_id=tenant.id, original_name="foto.png", mime_type="image/png", storage_path="termin/foto.png", scan_status="clean")
    db.add(stored)
    db.flush()
    db.add(SubmissionUploadFile(upload_id=upload.id, stored_file_id=stored.id))
    db.flush()
    stored_id, stored_public_id, event_public_id = stored.id, stored.public_id, event.public_id

    assert EventService().delete_event(db, event.id)

    assert db.get(StoredFile, stored_id) is None
    assert db.scalar(select(Event.id).where(Event.public_id == event_public_id)) is None
    assert _journal(db, "stored_file", stored_public_id) and _journal(db, "event", event_public_id)


def test_journal_purge_keeps_at_least_400_days(db):
    with pytest.raises(DBAPIError):
        nested = db.begin_nested()
        try:
            db.execute(text("SELECT erasure_journal_purge(30)"))
        finally:
            nested.rollback()
    assert db.scalar(text("SELECT has_table_privilege('hocx_app', 'erasure_journal', 'DELETE')")) is False


def test_switching_replay_off_needs_a_reason(db, monkeypatch):
    plan = type("Plan", (), {"blockers": [], "confirmation_phrase": "x"})()
    monkeypatch.setattr(backup_admin_service, "preview", lambda db, request: plan)
    fake = type("Request", (), {"kind": "full", "confirmation": "x", "skip_rescue_backup": False, "skip_rescue_reason": None,
                                "replay_erasures": False, "replay_erasures_reason": " "})()

    with pytest.raises(backup_admin_service.BackupAdminError) as exc:
        backup_admin_service.validate_restore(db, fake)
    assert exc.value.code == "erasure_reason_missing"
    fake.replay_erasures_reason = "Rechtsstreit: Daten müssen erhalten bleiben"
    assert backup_admin_service.validate_restore(db, fake) is plan
