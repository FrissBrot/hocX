"""Kamera-Kürzel für Altfotos nachtragen (Migration 0253, services/camera_serial_backfill.py):
mandantengetrennt, in Chargen, wiederaufnehmbar, nie die Seriennummer im Klartext."""

import uuid

from sqlalchemy import select, text, update

from app.core.config import settings
from app.core.tenant_scope import bind_tenant_scope
from app.models.entities import StoredFile
from app.models.upload_history_entities import CameraSerialBackfill
from app.services import camera_serial, camera_serial_backfill
from tests.factories import make_tenant
from tests.test_upload_job_cameras import _job_with, _photo


def _old_photos(db, tenant, serials):
    """Fotos wie vor 1.6: Datei mit Seriennummer in der EXIF, aber ohne Kürzel in der DB."""
    files = [(f"{uuid.uuid4().hex[:6]}.jpg", _photo((index * 30 % 255, 10, 10), serial=serial)) for index, serial in enumerate(serials)]
    _user, job = _job_with(db, tenant, files)
    ids = list(db.scalars(select(StoredFile.id).where(StoredFile.upload_job_id == job.id).order_by(StoredFile.id)))
    # Ohne ClamAV im Test bleiben neue Dateien «pending» - Altfotos sind längst geprüft
    db.execute(update(StoredFile).where(StoredFile.id.in_(ids)).values(camera_serial_key=None, scan_status="clean"))
    db.commit()
    return ids


def _enroll(db):
    camera_serial_backfill.run_tick(db, max_files=0)


def _state(db, tenant_id):
    db.expire_all()
    return db.get(CameraSerialBackfill, tenant_id)


def _keys(db, ids):
    db.expire_all()
    return [db.get(StoredFile, file_id).camera_serial_key for file_id in ids]


def test_backfill_sets_per_tenant_keys_in_resumable_batches_without_plain_serial(db, monkeypatch):
    monkeypatch.setattr(settings, "thumbnail_root", "/tmp/hocx-test-thumbs")
    monkeypatch.setattr(camera_serial_backfill, "BATCH_SIZE", 2)
    tenant, other = make_tenant(db), make_tenant(db)
    ids = _old_photos(db, tenant, ["SN-1111", "SN-1111", "SN-2222"])
    other_ids = _old_photos(db, other, ["SN-1111"])
    _enroll(db)
    state = _state(db, tenant.id)
    assert state.upper_file_id >= ids[-1] and state.last_file_id == 0 and state.finished_at is None

    # Erste Charge: zwei Dateien, Stand committet - ein Abbruch danach verliert nichts
    assert camera_serial_backfill.process_batch(db, state) == 2
    state = _state(db, tenant.id)
    assert state.last_file_id == ids[1] and state.keyed == 2
    first = _keys(db, ids)
    assert first[0] and first[0] == first[1] and first[2] is None

    # Fortsetzen: dritte Datei, dann leere Charge schliesst den Mandanten ab
    camera_serial_backfill.process_batch(db, state)
    camera_serial_backfill.process_batch(db, _state(db, tenant.id))
    state = _state(db, tenant.id)
    assert state.finished_at is not None and (state.checked, state.keyed, state.no_serial) == (3, 3, 0)
    keys = _keys(db, ids)
    assert keys[2] and keys[2] != keys[0]
    assert keys[0] == camera_serial.serial_key(tenant.id, "Canon", "EOS R6", "SN-1111")

    # Fremder Mandant: unberührt, bis seine eigene Charge läuft - dann mit seinem Schlüssel
    assert _keys(db, other_ids) == [None]
    camera_serial_backfill.process_batch(db, _state(db, other.id))
    [other_key] = _keys(db, other_ids)
    assert other_key and other_key != keys[0]
    assert other_key == camera_serial.serial_key(other.id, "Canon", "EOS R6", "SN-1111")

    # Klartext nie gespeichert
    rows = db.execute(text("SELECT row_to_json(s)::text FROM stored_file s WHERE s.id = ANY(:ids)"), {"ids": ids + other_ids}).scalars().all()
    rows += db.execute(text("SELECT row_to_json(b)::text FROM camera_serial_backfill b WHERE b.tenant_id IN (:a, :b)"), {"a": tenant.id, "b": other.id}).scalars().all()
    assert rows and not any("SN-1111" in row or "SN-2222" in row for row in rows)


def test_backfill_state_is_tenant_isolated(db, monkeypatch):
    """RLS: im Bereich eines Mandanten ist nur dessen Stand sichtbar und änderbar."""
    tenant, other = make_tenant(db), make_tenant(db)
    db.add_all([CameraSerialBackfill(tenant_id=tenant.id, upper_file_id=10), CameraSerialBackfill(tenant_id=other.id, upper_file_id=10)])
    db.commit()
    connection = db.connection()
    connection.execute(text("SAVEPOINT rls"))
    connection.execute(text("SET LOCAL ROLE hocx_app"))
    try:
        bind_tenant_scope(db, tenant.id)
        visible = set(db.scalars(select(CameraSerialBackfill.tenant_id).where(CameraSerialBackfill.tenant_id.in_([tenant.id, other.id]))))
        changed = db.execute(text("UPDATE camera_serial_backfill SET last_file_id = 5 WHERE tenant_id = :t"), {"t": other.id}).rowcount
    finally:
        bind_tenant_scope(db, None)
        connection.execute(text("ROLLBACK TO SAVEPOINT rls"))
    assert visible == {tenant.id}
    assert changed == 0


def test_missing_original_and_photo_without_serial_are_counted_and_skipped(db, monkeypatch):
    monkeypatch.setattr(settings, "thumbnail_root", "/tmp/hocx-test-thumbs")
    tenant = make_tenant(db)
    ids = _old_photos(db, tenant, [None])
    gone = StoredFile(
        tenant_id=tenant.id, original_name="weg.jpg", mime_type="image/jpeg", storage_path=f"uploads/tenant-{tenant.id}/weg-{uuid.uuid4().hex}.jpg",
        camera_make="Canon", camera_model="EOS R6", scan_status="clean",
    )
    db.add(gone)
    db.commit()
    _enroll(db)
    camera_serial_backfill.process_batch(db, _state(db, tenant.id))
    state = _state(db, tenant.id)
    assert (state.checked, state.keyed, state.no_serial, state.missing) == (2, 0, 1, 1)
    assert _keys(db, ids + [gone.id]) == [None, None]


def test_process_without_secret_does_nothing(db, monkeypatch):
    monkeypatch.setattr(settings, "process_kind", "document-worker")
    assert settings.is_secretless_process
    tenant = make_tenant(db)
    report = camera_serial_backfill.run_tick(db)
    assert report.checked == 0
    assert db.get(CameraSerialBackfill, tenant.id) is None


def test_job_is_registered_with_a_unique_lock():
    from app.core.background_loops import BACKGROUND_LOCK_IDS
    from app.core.job_registry import JOBS_BY_NAME
    from app.core.loops import JOB_WORKER_LOOPS, camera_serial_backfill_loop

    assert "camera_serial_backfill" in BACKGROUND_LOCK_IDS
    assert JOBS_BY_NAME["camera_serial_backfill"].service == "job-worker"
    assert camera_serial_backfill_loop in JOB_WORKER_LOOPS


def test_a_broken_file_is_counted_and_does_not_stop_the_batch(db, monkeypatch):
    monkeypatch.setattr(settings, "thumbnail_root", "/tmp/hocx-test-thumbs")
    tenant = make_tenant(db)
    ids = _old_photos(db, tenant, ["SN-3333", "SN-4444"])
    _enroll(db)
    real = camera_serial_backfill._read_metadata

    def flaky(session, stored):
        if stored.id == ids[0]:
            raise RuntimeError("S3 AccessDenied")
        return real(session, stored)

    monkeypatch.setattr(camera_serial_backfill, "_read_metadata", flaky)
    camera_serial_backfill.process_batch(db, _state(db, tenant.id))
    state = _state(db, tenant.id)
    assert (state.checked, state.failed, state.keyed) == (2, 1, 1) and state.last_file_id == ids[1]
    assert _keys(db, ids)[0] is None and _keys(db, ids)[1]
