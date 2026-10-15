"""Restore-Wege gegen echte Komponenten: Mandanten-Restore als Kopie (historische Quelle, kein
ZIP) und Voll-Restore über die unabhängige Recovery-CLI in eine neue Datenbank und einen neuen
Objektspeicher (Restore nach Anbieterwechsel). Der Voll-Restore über das Admin-Portal mit
Datenbanktausch steht in test_zz_backup_full_restore.py (läuft zuletzt)."""

from __future__ import annotations

import os
import uuid

from sqlalchemy import create_engine, select, text
from sqlalchemy.pool import NullPool

from app.backup import jobs
from app.backup.cli import main as cli_main
from app.backup.pgtools import PgTarget, PgTools
from app.core.config import settings
from app.core.db import SessionLocal, engine
from app.core.objstore_client import ProfileConfig, S3Backend
from app.core.storage import get_object_store
from app.models import BackupRestoreJob, BackupSet, StoredFile, Tenant
from app.services import tenant_import_service
from app.workers import backup_worker
from tests.backup_support import backup_env  # noqa: F401 - Fixture
from tests.backup_support import put_object, requires_borg, run_backup_job
from tests.factories import make_app_user
from tests.storage_support import S3_ENDPOINT, committed_storage, make_committed_tenant, requires_s3  # noqa: F401 - Fixture

pytestmark = [requires_borg, requires_s3]


def _run_restore(env, archive: str, kind: str, options: dict) -> BackupRestoreJob:
    with SessionLocal() as db:
        job = BackupRestoreJob(kind=kind, archive_name=archive, options=options, requested_by_email="owner@example.com")
        db.add(job)
        db.commit()
        job_id = job.id
    for _ in range(10):
        ctx = jobs.claim(engine, BackupRestoreJob, "test-worker")
        if ctx is None:
            break
        backup_worker.run_job(env, ctx)
        with SessionLocal() as db:
            job = db.get(BackupRestoreJob, job_id)
            if job.state in jobs.TERMINAL_RESTORE_STATES:
                return job
    return job


def test_tenant_restore_as_copy_from_historical_backup(backup_env, monkeypatch):  # noqa: F811
    db, env, _ = backup_env
    monkeypatch.setattr(tenant_import_service.scanner, "scan_file", lambda *args, **kwargs: "clean")
    tenant = make_committed_tenant(db, "Original")
    make_app_user(db, f"copy-{uuid.uuid4().hex[:6]}@example.com", tenant_id=tenant.id)
    keys = [f"uploads/tenant-{tenant.id}/gallery/{uuid.uuid4().hex}.jpg" for _ in range(3)]
    for i, key in enumerate(keys):
        put_object(db, key, f"historisch-{i}".encode())
        db.add(StoredFile(tenant_id=tenant.id, original_name=f"{i}.jpg", storage_path=key, mime_type="image/jpeg"))
    db.commit()
    backup = run_backup_job(env)
    assert backup.state == "completed", backup.error_message
    archive = db.get(BackupSet, backup.backup_set_id).archive_name

    # Nach dem Backup ändert sich das Original - die Kopie muss den alten Stand zeigen.
    original_name = tenant.name
    first = db.scalars(select(StoredFile).where(StoredFile.storage_path == keys[0])).one()
    db.delete(first)
    get_object_store().delete(db, "main", keys[0])
    db.commit()

    new_name = f"Kopie {uuid.uuid4().hex[:6]}"
    job = _run_restore(env, archive, "tenant_copy", {"source_tenant_id": tenant.id, "new_name": new_name})
    assert job.state == "completed", (job.error_code, job.error_message)
    db.expire_all()
    copy = db.get(Tenant, job.result["tenant_id"])
    db.info["test_tenant_ids"].append(copy.id)
    assert copy.name == new_name and copy.id != tenant.id
    files = db.scalars(select(StoredFile).where(StoredFile.tenant_id == copy.id)).all()
    assert len(files) == 3
    contents = sorted(get_object_store().get_bytes("main", f.storage_path) for f in files)
    assert contents == [b"historisch-0", b"historisch-1", b"historisch-2"]
    assert all(f.storage_path.startswith(f"tenant_imports/tenant-{copy.id}/") for f in files)
    assert job.result["file_check"] == {"checked": 3, "missing": 0}
    # Original unverändert, Benutzer mit bestehender E-Mail nicht übernommen (Warnung).
    assert db.get(Tenant, tenant.id).name == original_name
    assert any("existiert auf dieser Installation bereits" in w for w in job.result["warnings"])
    # Restore-Bereich und temporäre Datenbank sind weg.
    assert not list(env.store.active_backend(force=True).list("main", "_hocx-restore/"))
    with PgTools(PgTarget.from_url(settings.database_url)) as pg:
        assert not pg.database_exists(f"hocx_tsrc_{job.id.hex[:12]}")


def test_tenant_restore_of_unknown_tenant_fails_cleanly(backup_env):  # noqa: F811
    db, env, _ = backup_env
    put_object(db, "uploads/x/a.bin", b"a")
    backup = run_backup_job(env)
    archive = db.get(BackupSet, backup.backup_set_id).archive_name
    job = _run_restore(env, archive, "tenant_copy", {"source_tenant_id": 987654321, "new_name": "Gibt es nicht"})
    assert job.state == "failed" and job.error_code == "tenant_not_in_backup"
    assert db.scalar(select(Tenant.id).where(Tenant.name == "Gibt es nicht")) is None


def test_cli_full_restore_into_new_database_and_new_provider(backup_env, tmp_path, monkeypatch):  # noqa: F811
    """Restore ohne laufendes Backend: CLI liest nur das Repository, schreibt in eine neue
    Datenbank und in einen ANDEREN Speicher (neuer Präfix = anderer Anbieter)."""
    db, env, _ = backup_env
    tenant = make_committed_tenant(db, "CLI")
    key = f"uploads/tenant-{tenant.id}/a.bin"
    put_object(db, key, b"cli-inhalt")
    db.add(StoredFile(tenant_id=tenant.id, original_name="a.bin", storage_path=key))
    db.commit()
    backup = run_backup_job(env)
    archive = db.get(BackupSet, backup.backup_set_id).archive_name
    (tmp_path / "ak").write_text(os.environ["TEST_S3_ACCESS_KEY"])
    (tmp_path / "sk").write_text(os.environ["TEST_S3_SECRET_KEY"])
    for name, value in (("BACKUP_REPOSITORY_URL", env.config.repository_url), ("BACKUP_PASSPHRASE_FILE", str(env.config.passphrase_file)),
                        ("BACKUP_WORK_DIR", str(env.config.work_dir)), ("BACKUP_ENABLED", "true")):
        monkeypatch.setenv(name, value)
    target_db = f"hocx_cli_{uuid.uuid4().hex[:8]}"
    prefix = f"cli-{uuid.uuid4().hex[:8]}"
    try:
        assert cli_main(["--json", "list"]) == 0
        rc = cli_main(["restore-full", "--archive", archive, "--target-db", target_db, "--storage", "s3", "--s3-provider", "garage_local",
                       "--s3-endpoint", S3_ENDPOINT, "--s3-region", "garage", "--s3-bucket", "hocx-main", "--s3-abgabebox-bucket", "hocx-abgabebox",
                       "--s3-prefix", prefix, "--s3-addressing", "path", "--s3-access-key-file", str(tmp_path / "ak"),
                       "--s3-secret-key-file", str(tmp_path / "sk"), "--s3-insecure", "--database-url", settings.database_url, "--yes"])
        assert rc == 0
        url = PgTarget.from_url(settings.database_url).with_database(target_db).sqlalchemy_url()
        restored = create_engine(url, poolclass=NullPool)
        with restored.connect() as conn:
            state = conn.execute(text("""
                SELECT s.active_generation, p.prefix, p.bucket, s.write_fenced FROM storage_state s JOIN storage_profile p ON p.id = s.active_profile_id
            """)).one()
            maintenance = conn.execute(text("SELECT COUNT(*) FROM maintenance_window WHERE reason_code = 'backup_restore' AND state = 'active'")).scalar()
        restored.dispose()
        assert state.prefix == prefix and not state.write_fenced and maintenance == 1
        backend = S3Backend(ProfileConfig(profile_id=0, generation=state.active_generation, provider="garage_local", endpoint_url=S3_ENDPOINT,
                                          region="garage", bucket="hocx-main", abgabebox_bucket="hocx-abgabebox", prefix=prefix,
                                          addressing_style="path", access_key=os.environ["TEST_S3_ACCESS_KEY"],
                                          secret_key=os.environ["TEST_S3_SECRET_KEY"], tls_verify=False))
        assert b"".join(backend.open_read("main", key)) == b"cli-inhalt"
        # Ein zweiter Restore in dieselbe Datenbank wird verweigert (nie überschreiben).
        assert cli_main(["restore-full", "--archive", archive, "--target-db", target_db, "--storage", "filesystem",
                         "--filesystem-root", str(tmp_path / "fs"), "--database-url", settings.database_url, "--yes"]) == 1
    finally:
        with PgTools(PgTarget.from_url(settings.database_url)) as pg:
            pg.drop_database(target_db)


def test_cli_rejects_untrusted_archive_names(backup_env, monkeypatch, capsys):  # noqa: F811
    _db, env, _ = backup_env
    for name, value in (("BACKUP_REPOSITORY_URL", env.config.repository_url), ("BACKUP_PASSPHRASE_FILE", str(env.config.passphrase_file)),
                        ("BACKUP_WORK_DIR", str(env.config.work_dir))):
        monkeypatch.setenv(name, value)
    assert cli_main(["show", "../../etc/passwd"]) == 1
    assert cli_main(["restore-full", "--archive", "x", "--target-db", "Robert'); DROP TABLE x;--", "--storage", "filesystem",
                     "--database-url", "postgresql://u:p@localhost/db"]) == 1
