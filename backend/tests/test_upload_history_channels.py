"""Upload-Verlauf, weitere Kanäle (Plan Phase 4): Protokollbilder (ein Vorgang je Protokoll und
Tag), persönlicher Abgabe-Link, Abgabebox-Trigger (ohne zusätzliche Rechte der Abgabebox),
Word-Import, Datei-Import, Bulk «Termin zuordnen»."""

import asyncio
import io
import uuid
from datetime import UTC, date, datetime

import pytest
from fastapi import HTTPException, UploadFile
from PIL import Image
from sqlalchemy import select, text
from starlette.datastructures import Headers

from app.api.routes import files as files_routes
from app.api.routes import public_submission_access as access_route
from app.models.entities import GalleryImage, StoredFile, SubmissionUpload, SubmissionUploadFile
from app.models.upload_history_entities import UploadJob, UploadJobItem
from app.schemas.files import FileBulkEventLink
from tests.factories import (
    make_app_user,
    make_current_user,
    make_event,
    make_protocol,
    make_protocol_element,
    make_protocol_element_block,
    make_template,
    make_tenant,
)
from tests.test_submission_done_notifications import box  # noqa: F401 (Fixture)
from tests.test_submission_owner_access import _client, _issue, _manage
from tests.test_submission_upload_rules import PDF


def _png(color=(10, 20, 30)) -> UploadFile:
    buffer = io.BytesIO()
    Image.new("RGB", (40, 30), color=color).save(buffer, format="PNG")
    buffer.seek(0)
    return UploadFile(file=buffer, filename=f"bild-{color[0]}.png", headers=Headers({"content-type": "image/png"}))


def _writer(db, tenant):
    account = make_app_user(db, email=f"{uuid.uuid4().hex[:10]}@example.com", tenant_id=tenant.id, role_code="writer")
    return make_current_user(tenant.id, role="writer", user_id=account.id)


def _jobs(db, tenant_id, channel):
    return list(db.scalars(select(UploadJob).where(UploadJob.tenant_id == tenant_id, UploadJob.channel == channel)))


def test_protocol_images_of_one_protocol_and_day_share_a_job(db, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "thumbnail_root", "/tmp/hocx-test-thumbs")
    tenant = make_tenant(db)
    user = _writer(db, tenant)
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id, protocol_number="P-1")
    block = make_protocol_element_block(db, make_protocol_element(db, protocol.id).id, configuration_snapshot_json={})
    for color in ((10, 20, 30), (200, 20, 30)):
        asyncio.run(files_routes.upload_image(block.public_id, file=_png(color), title=None, caption=None, db=db, user=user))
    jobs = _jobs(db, tenant.id, "protocol_image")
    assert len(jobs) == 1 and jobs[0].protocol_id == protocol.id and jobs[0].uploaded == 2
    assert jobs[0].group_day is not None


def test_abgabebox_trigger_records_a_job_without_new_rights_for_the_restricted_role(db, box):
    """Die Abgabebox schreibt mit hocx_abgabebox nur ihre INSERTs - der Trigger legt Vorgang, Item
    und stored_file.upload_job_id an (SECURITY DEFINER). Lesen darf die Rolle den Verlauf nicht."""
    from app.models.entities import SubmissionLink

    link_token = db.scalar(select(SubmissionLink.token).where(SubmissionLink.tenant_id == box["tenant"].id))
    upload = SubmissionUpload(assignment_id=box["assignment"].id, event_id=box["event"].id, status="submitted", submitted_at=datetime.now(UTC))
    db.add(upload)
    db.flush()
    stored = StoredFile(tenant_id=box["tenant"].id, original_name="foto.jpg", mime_type="image/jpeg", storage_path="t/foto.jpg", file_size_bytes=12)
    db.add(stored)
    db.flush()
    connection = db.connection()
    connection.execute(text("SAVEPOINT as_abgabebox"))
    connection.execute(text("SET LOCAL ROLE hocx_abgabebox"))
    # Wie abgabebox-backend/app/link_scope.py: Link-Kontext für die RLS der Rolle
    connection.execute(text("SELECT set_config('app.abgabebox_link', :token, true)"), {"token": link_token})
    try:
        connection.execute(text("INSERT INTO submission_upload_file (upload_id, stored_file_id, sort_index) VALUES (:u, :f, 0)"), {"u": upload.id, "f": stored.id})
        denied = None
        connection.execute(text("SAVEPOINT read_history"))
        try:
            connection.execute(text("SELECT count(*) FROM upload_job"))
        except Exception as exc:  # noqa: BLE001 - erwartet: keine Rechte
            denied = str(exc)
        connection.execute(text("ROLLBACK TO SAVEPOINT read_history"))
    finally:
        connection.execute(text("RESET ROLE"))
    assert denied is not None and "permission denied" in denied
    db.expire_all()
    job = db.scalar(select(UploadJob).where(UploadJob.submission_upload_id == upload.id))
    assert job is not None and job.channel == "abgabebox" and job.actor_kind == "anonymous_link" and job.created_by is None
    assert (job.total, job.uploaded, job.tenant_id) == (1, 1, box["tenant"].id)
    assert db.get(StoredFile, stored.id).upload_job_id == job.id
    item = db.scalar(select(UploadJobItem).where(UploadJobItem.upload_job_id == job.id))
    assert item.original_name == "foto.jpg" and item.stored_file_id == stored.id


def test_abgabebox_trigger_ignores_a_file_of_another_tenant(db, box):
    other = make_tenant(db)
    upload = SubmissionUpload(assignment_id=box["assignment"].id, event_id=box["event"].id, status="submitted", submitted_at=datetime.now(UTC))
    db.add(upload)
    db.flush()
    foreign = StoredFile(tenant_id=other.id, original_name="x.pdf", mime_type="application/pdf", storage_path="t/x.pdf")
    db.add(foreign)
    db.flush()
    db.add(SubmissionUploadFile(upload_id=upload.id, stored_file_id=foreign.id, sort_index=0))
    db.flush()
    assert db.scalar(select(UploadJob).where(UploadJob.submission_upload_id == upload.id)) is None


def test_personal_link_upload_is_a_submission_link_job(db, box, monkeypatch):
    from app.services import file_service as file_service_module
    from app.services.submission_service import local_today

    async def clean_scan(contents, **kwargs):
        return ["clean"] * len(contents)

    monkeypatch.setattr(file_service_module.scanner, "scan_many", clean_scan)
    monkeypatch.setattr(access_route, "enforce_rate_limit", lambda *args, **kwargs: None)
    box["event"].event_date = local_today()
    _manage(box)
    token = _issue(db, box)
    response = _client(db).post(
        "/api/public/submission-access/upload", headers={access_route.TOKEN_HEADER: token},
        files=[("files", ("bericht.pdf", PDF, "application/pdf"))],
    )
    assert response.status_code == 200, response.text
    job = _jobs(db, box["tenant"].id, "submission_link")[0]
    assert job.actor_kind == "submission_person" and job.uploaded == 1 and job.status == "done"
    assert job.submission_assignment_id == box["assignment"].id


def test_bulk_event_link_sets_and_returns_to_auto(db):
    tenant, other = make_tenant(db), make_tenant(db)
    user = _writer(db, tenant)
    saturday = make_event(db, tenant_id=tenant.id, title="Samstag", event_date=date(2026, 5, 2))
    party = make_event(db, tenant_id=tenant.id, title="Fest", event_date=date(2026, 6, 1))
    foreign_event = make_event(db, tenant_id=other.id, title="Fremd", event_date=date(2026, 5, 2))
    stored = StoredFile(
        tenant_id=tenant.id, original_name="a.jpg", mime_type="image/jpeg", storage_path=f"u/{uuid.uuid4().hex}.jpg",
        exif_taken_at=datetime(2026, 5, 2, 9, 0, tzinfo=UTC), metadata_scanned_at=datetime.now(UTC),
    )
    db.add(stored)
    db.flush()
    db.add(GalleryImage(tenant_id=tenant.id, stored_file_id=stored.id, event_id=saturday.id, event_auto_linked=True))
    db.flush()
    result = files_routes.bulk_link_event(FileBulkEventLink(file_ids=[stored.public_id, uuid.uuid4()], mode="set", event_id=party.public_id), db=db, user=user)
    assert result.updated_ids == [stored.public_id] and len(result.not_found_ids) == 1
    link = db.scalar(select(GalleryImage).where(GalleryImage.stored_file_id == stored.id))
    assert (link.event_id, link.event_auto_linked) == (party.id, False)
    files_routes.bulk_link_event(FileBulkEventLink(file_ids=[stored.public_id], mode="auto"), db=db, user=user)
    db.refresh(link)
    assert (link.event_id, link.event_auto_linked) == (saturday.id, True)
    with pytest.raises(HTTPException) as caught:
        files_routes.bulk_link_event(FileBulkEventLink(file_ids=[stored.public_id], mode="set", event_id=foreign_event.public_id), db=db, user=user)
    assert caught.value.status_code == 404


def test_cloud_import_is_one_job_with_items_and_report_link(db, monkeypatch, tmp_path):
    from app.core.config import settings
    from app.api.routes import cloud_import as import_routes
    from types import SimpleNamespace

    from app.services.cloud_import import jobs as import_jobs
    from tests.test_cloud_import_jobs import _admin, _png as import_png, _pdf, _run_worker, _zip_job

    # Plattenreserve unabhängig vom Füllstand des Test-Hosts
    monkeypatch.setattr(import_jobs.shutil, "disk_usage", lambda _path: SimpleNamespace(total=100 * 1024**3, used=0, free=100 * 1024**3))
    monkeypatch.setattr(settings, "storage_root", str(tmp_path))
    monkeypatch.setattr(settings, "upload_root", str(tmp_path / "uploads"))
    monkeypatch.setattr(settings, "thumbnail_root", str(tmp_path / "thumbnails"))
    monkeypatch.setattr(import_routes, "enforce_rate_limit", lambda *args, **kwargs: None)
    tenant = make_tenant(db)
    owner = _admin(db, tenant)
    job = _zip_job(db, owner, {"a/x.png": import_png((200, 10, 10)), "a/y.pdf": _pdf("y"), "b/x.png": import_png((200, 10, 10))})
    import_routes.start_import_job(job.id, db=db, user=owner)
    _run_worker(db)
    [history] = _jobs(db, tenant.id, "cloud_import")
    assert history.import_job_id == job.id and history.status == "done"
    assert (history.uploaded, history.duplicates) == (2, 1)
    assert len(list(db.scalars(select(StoredFile).where(StoredFile.upload_job_id == history.id)))) == 2


def test_word_import_request_is_one_job(db, monkeypatch):
    from app.api.routes import word_import as word_routes
    from tests.word_import_fixtures import default_spec, render_docx

    tenant = make_tenant(db)
    user = _writer(db, tenant)
    template = make_template(db, tenant.id)
    files = [
        UploadFile(file=io.BytesIO(b"hallo"), filename="notiz.txt", headers=Headers({"content-type": "text/plain"})),
        UploadFile(file=io.BytesIO(render_docx(default_spec())), filename="protokoll.docx", headers=Headers({"content-type": "application/octet-stream"})),
    ]
    asyncio.run(word_routes.ingest_word_import_documents(template_id=template.public_id, files=files, db=db, user=user))
    [job] = _jobs(db, tenant.id, "word_import")
    names = {item.original_name: item.status for item in db.scalars(select(UploadJobItem).where(UploadJobItem.upload_job_id == job.id))}
    assert names["notiz.txt"] == "rejected" and "protokoll.docx" in names
    assert job.status in ("done", "partial", "failed") and job.total == 2


def test_abgabebox_trigger_ignores_an_older_file_linked_later(db, box):
    """Security-Review N-1: eine schon vorhandene Datei des Mandanten, die nachträglich mit einer
    Einreichung verknüpft wird, bekommt keinen Vorgang (Name bleibt aus dem Verlauf)."""
    old = StoredFile(tenant_id=box["tenant"].id, original_name="protokollbild.jpg", mime_type="image/jpeg", storage_path="t/alt.jpg")
    db.add(old)
    db.flush()
    db.execute(text("UPDATE stored_file SET created_at = now() - interval '2 days' WHERE id = :id"), {"id": old.id})
    upload = SubmissionUpload(assignment_id=box["assignment"].id, event_id=box["event"].id, status="submitted", submitted_at=datetime.now(UTC))
    db.add(upload)
    db.flush()
    db.add(SubmissionUploadFile(upload_id=upload.id, stored_file_id=old.id, sort_index=0))
    db.flush()
    assert db.scalar(select(UploadJob).where(UploadJob.submission_upload_id == upload.id)) is None


def test_assigned_only_scope_hides_gallery_jobs_of_foreign_submissions(db, box, monkeypatch):
    """Security-Review M-1: Uploads mit Abgabe-Bezug folgen der Reichweite «nur zugewiesene»."""
    from app.api.routes import upload_jobs as routes
    from app.services import context_visibility_service, upload_job_service

    tenant = box["tenant"]
    writer = _writer(db, tenant)
    upload_job_service.open_job(db, tenant_id=tenant.id, channel="gallery", created_by=writer.user_id, status="done",
                                submission_assignment_id=box["assignment"].id)
    plain = upload_job_service.open_job(db, tenant_id=tenant.id, channel="gallery", created_by=writer.user_id, status="done")
    db.flush()
    listed = lambda: [job.id for job in routes.list_upload_jobs(  # noqa: E731
        mine=False, channel=None, problems=False, date_from=None, date_to=None, cursor=None, limit=50, db=db, user=writer).items]
    assert len(listed()) == 2
    monkeypatch.setattr(context_visibility_service, "readable_assignment_ids", lambda db_, user: set())
    assert listed() == [plain.id]
