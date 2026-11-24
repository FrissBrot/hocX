"""Upload-Verlauf (Migration 0250, services/upload_job_service.py, routes/upload_jobs.py):
Vorgang öffnen/aufnehmen/abschliessen, Items je Kanal, Sichtbarkeit, Fremd-Mandant, Aufbewahrung."""

import asyncio
import hashlib
import io
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException, UploadFile
from sqlalchemy import select, text
from starlette.datastructures import Headers

from app.api.routes import files as files_routes
from app.api.routes import upload_jobs as routes
from app.core.config import settings
from app.models.entities import GalleryUploadJob, StoredFile
from app.models.upload_history_entities import UploadJob, UploadJobItem
from app.schemas.files import UploadPrecheckFile, UploadPrecheckRequest
from app.schemas.upload_jobs import UploadClientResult, UploadClientResults, UploadJobCreate
from app.services import file_service as file_service_module
from app.services import retention_service, upload_job_service
from app.services.file_service import FileService
from tests.factories import make_app_user, make_current_user, make_tenant
from tests.image_fixtures import jpeg

service = FileService()
PDF = b"%PDF-1.7\n%test\n"


@pytest.fixture(autouse=True)
def _isolated_storage_root(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "storage_root", str(tmp_path))
    monkeypatch.setattr(settings, "upload_root", str(tmp_path / "uploads"))
    monkeypatch.setattr(settings, "thumbnail_root", str(tmp_path / "thumbnails"))


def _user(db, tenant_id, role="writer"):
    account = make_app_user(db, email=f"u{uuid.uuid4().hex[:10]}@example.com", tenant_id=tenant_id, role_code=role)
    return make_current_user(tenant_id, role=role, user_id=account.id)


def _file(content: bytes, name: str, content_type="application/octet-stream") -> UploadFile:
    return UploadFile(file=io.BytesIO(content), filename=name, headers=Headers({"content-type": content_type}))


def _gallery(db, user, files, **form):
    kwargs = dict(tags=None, event_id=None, submission_assignment_id=None, submission_element_ref=None, cycle_config_id=None)
    kwargs.update(form)
    return asyncio.run(files_routes.upload_gallery_images(files=files, db=db, user=user, **kwargs))


def _documents(db, user, files, **form):
    kwargs = dict(tags=None, event_id=None, submission_assignment_id=None, submission_element_ref=None, cycle_config_id=None)
    kwargs.update(form)
    return asyncio.run(files_routes.upload_documents(files=files, db=db, user=user, **kwargs))


def _open(db, user, channel="gallery"):
    return routes.create_upload_job(UploadJobCreate(channel=channel), db=db, user=user)


def test_gallery_dialog_flow_collects_all_packets_precheck_and_finishes(db):
    tenant = make_tenant(db)
    user = _user(db, tenant.id)
    existing = jpeg(color=(1, 2, 3))
    asyncio.run(service.save_gallery_uploads(db, tenant_id=tenant.id, files=[("alt.jpg", existing)], tags=[], created_by=user.user_id))

    opened = _open(db, user)
    assert opened.status == "open" and opened.is_mine
    files_routes.precheck_uploads(
        UploadPrecheckRequest(
            upload_job_id=opened.id,
            files=[UploadPrecheckFile(client_id="1", sha256=hashlib.sha256(existing).hexdigest(), name="alt-kopie.jpg", size=len(existing))],
        ),
        db=db, user=user,
    )
    first = _gallery(db, user, [_file(jpeg(color=(200, 10, 10)), "a.jpg", "image/jpeg")], upload_job_id=opened.id)
    second = _gallery(db, user, [_file(b"kein bild", "b.jpg", "image/jpeg")], upload_job_id=opened.id)
    assert first.upload_job_id == second.upload_job_id == opened.id
    service.process_pending_gallery_upload_jobs(db)
    # Noch offen, bis der Browser fertig meldet
    assert db.get(UploadJob, opened.id).status == "processing"

    done = routes.complete_upload_job(opened.id, db=db, user=user)
    assert done.status == "partial"
    assert (done.counts.total, done.counts.uploaded, done.counts.duplicates, done.counts.rejected) == (3, 1, 1, 1)
    items = routes.list_upload_job_items(opened.id, status=None, cursor=None, limit=100, db=db, user=user).items
    by_name = {item.name: item for item in items}
    assert by_name["alt-kopie.jpg"].status == "duplicate" and by_name["alt-kopie.jpg"].existing_file.id is not None
    assert by_name["b.jpg"].status == "rejected" and by_name["b.jpg"].reason_code == "unsupported_format"
    uploaded = by_name["a.jpg"].file
    # Ohne ClamAV im Test: «Prüfung ausstehend» (mit ClamAV «ok» samt Vorschaubild)
    assert uploaded.state in ("ok", "scan_pending") and uploaded.id is not None
    stored = db.scalar(select(StoredFile).where(StoredFile.public_id == uploaded.id))
    assert stored.upload_job_id == opened.id
    # Filter der Galerie und «Alle N auswählen»
    listed = files_routes.list_files(upload_job_id=opened.id, db=db, user=user, **_list_defaults())
    assert [item.id for item in listed] == [uploaded.id]
    ids = routes.list_upload_job_file_ids(opened.id, only_images=False, camera=None, db=db, user=user)
    assert ids.file_ids == [uploaded.id] and ids.total == 1


def _list_defaults():
    return dict(
        skip=0, limit=60, source=None, album_id=None, exclude_album_id=None, share_pending=None, only_images=False,
        exclude_images=False, search=None, tags=None, sort_by="created_at", sort_dir="desc", date_from=None, date_to=None,
    )


def test_upload_without_job_id_creates_its_own_job_compatibly(db):
    tenant = make_tenant(db)
    user = _user(db, tenant.id)
    queued = _gallery(db, user, [_file(jpeg(color=(9, 9, 200)), "x.jpg", "image/jpeg")])
    assert queued.upload_job_id is not None
    service.process_pending_gallery_upload_jobs(db)
    job = db.get(UploadJob, queued.upload_job_id)
    db.refresh(job)
    assert job.status == "done" and job.uploaded == 1

    result = _documents(db, user, [_file(PDF, "protokoll.pdf")])
    doc_job = db.get(UploadJob, result.upload_job_id)
    assert doc_job.channel == "document" and doc_job.status == "done" and doc_job.uploaded == 1


def test_foreign_old_closed_or_wrong_person_job_is_404(db):
    tenant, other_tenant = make_tenant(db), make_tenant(db)
    owner, colleague = _user(db, tenant.id), _user(db, tenant.id)
    stranger = _user(db, other_tenant.id)
    job = _open(db, owner)
    for user in (colleague, stranger):
        with pytest.raises(HTTPException) as caught:
            routes.complete_upload_job(job.id, db=db, user=user)
        assert caught.value.status_code == 404
        with pytest.raises(HTTPException) as caught:
            routes.report_client_results(job.id, UploadClientResults(items=[UploadClientResult(name="x")]), db=db, user=user)
        assert caught.value.status_code == 404
    # Fremder Mandant sieht den Vorgang auch lesend nicht
    with pytest.raises(HTTPException) as caught:
        routes.get_upload_job(job.id, db=db, user=stranger)
    assert caught.value.status_code == 404
    with pytest.raises(HTTPException):
        files_routes.list_files(upload_job_id=job.id, db=db, user=stranger, **_list_defaults())
    # Alt (> 24 h) und abgeschlossen
    row = db.get(UploadJob, job.id)
    row.created_at = datetime.now(UTC) - timedelta(hours=25)
    db.flush()
    with pytest.raises(HTTPException) as caught:
        routes.complete_upload_job(job.id, db=db, user=owner)
    assert caught.value.status_code == 404


def test_visibility_follows_area_permission(db):
    tenant = make_tenant(db)
    writer = _user(db, tenant.id)
    reader = _user(db, tenant.id, role="reader")
    _documents(db, writer, [_file(PDF, "a.pdf")])
    # Leser ohne files.manage sieht Ablage-Vorgänge nicht
    hidden = routes.list_upload_jobs(mine=False, channel=None, problems=False, date_from=None, date_to=None, cursor=None, limit=50, db=db, user=reader)
    assert hidden.items == []
    colleague = _user(db, tenant.id)
    listed = routes.list_upload_jobs(mine=False, channel=None, problems=False, date_from=None, date_to=None, cursor=None, limit=50, db=db, user=colleague)
    assert len(listed.items) == 1 and not listed.items[0].is_mine
    mine = routes.list_upload_jobs(mine=True, channel=None, problems=False, date_from=None, date_to=None, cursor=None, limit=50, db=db, user=colleague)
    assert mine.items == []


def test_list_pages_with_cursor(db):
    tenant = make_tenant(db)
    user = _user(db, tenant.id)
    for index in range(3):
        _documents(db, user, [_file(PDF + str(index).encode(), f"d{index}.pdf")])
    first = routes.list_upload_jobs(mine=False, channel=["document"], problems=False, date_from=None, date_to=None, cursor=None, limit=2, db=db, user=user)
    assert len(first.items) == 2 and first.next_cursor
    rest = routes.list_upload_jobs(mine=False, channel=["document"], problems=False, date_from=None, date_to=None, cursor=first.next_cursor, limit=2, db=db, user=user)
    assert len(rest.items) == 1 and rest.next_cursor is None
    assert {i.id for i in first.items}.isdisjoint({i.id for i in rest.items})


def test_client_results_are_marked_as_browser_reported(db):
    tenant = make_tenant(db)
    user = _user(db, tenant.id)
    job = _open(db, user)
    routes.report_client_results(job.id, UploadClientResults(items=[UploadClientResult(name="riesig.jpg", size=99, code="too_large")]), db=db, user=user)
    items = routes.list_upload_job_items(job.id, status=None, cursor=None, limit=100, db=db, user=user).items
    assert [(i.name, i.status, i.source, i.reason_code) for i in items] == [("riesig.jpg", "rejected", "client", "too_large")]


def test_job_disappears_with_its_last_file_and_names_of_erased_files_are_cleared(db):
    tenant = make_tenant(db)
    user = _user(db, tenant.id)
    result = _documents(db, user, [_file(PDF, "a.pdf"), _file(PDF + b"2", "b.pdf")])
    job_id = result.upload_job_id
    files = list(db.scalars(select(StoredFile).where(StoredFile.upload_job_id == job_id)))
    assert len(files) == 2
    _hard_delete(db, files[0].id)
    assert db.get(UploadJob, job_id) is not None
    names = sorted((item.original_name or "-") for item in db.scalars(select(UploadJobItem).where(UploadJobItem.upload_job_id == job_id)))
    assert names == ["-", "b.pdf"]
    _hard_delete(db, files[1].id)
    db.expire_all()
    assert db.get(UploadJob, job_id) is None


def _hard_delete(db, stored_file_id):
    # Endgültig löschen wie Papierkorb-Frist bzw. Löschdienst (FileEraser)
    from app.models.entities import GalleryImage
    from app.services.file_eraser import FileEraser

    db.execute(text("DELETE FROM gallery_image WHERE stored_file_id = :id"), {"id": stored_file_id})
    FileEraser().erase(db, db.get(StoredFile, stored_file_id))
    db.flush()


def test_retention_removes_only_finished_jobs_without_files(db, monkeypatch):
    tenant = make_tenant(db)
    user = _user(db, tenant.id)
    empty = upload_job_service.open_job(db, tenant_id=tenant.id, channel="gallery", created_by=user.user_id, status="done")
    empty.finished_at = datetime.now(UTC) - timedelta(days=40)
    empty_id = empty.id
    with_file = _documents(db, user, [_file(PDF, "bleibt.pdf")]).upload_job_id
    db.execute(text("UPDATE upload_job SET finished_at = now() - interval '40 days' WHERE id = :id"), {"id": with_file})
    db.flush()
    monkeypatch.setattr(db, "commit", db.flush)
    retention_service.cleanup(db)
    db.expire_all()
    assert db.get(UploadJob, empty_id) is None
    assert db.get(UploadJob, with_file) is not None


def test_close_stale_finishes_abandoned_jobs(db, monkeypatch):
    tenant = make_tenant(db)
    user = _user(db, tenant.id)
    job = _open(db, user)
    db.execute(text("UPDATE upload_job SET created_at = now() - interval '2 days' WHERE id = :id"), {"id": job.id})
    db.flush()
    monkeypatch.setattr(db, "commit", db.flush)
    upload_job_service.close_stale(db)
    row = db.get(UploadJob, job.id)
    db.refresh(row)
    assert row.status == "cancelled"


def test_item_cannot_point_to_a_job_of_another_tenant(db):
    tenant, other = make_tenant(db), make_tenant(db)
    job = upload_job_service.open_job(db, tenant_id=tenant.id, channel="gallery", created_by=None)
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        with db.begin_nested():
            db.add(UploadJobItem(upload_job_id=job.id, tenant_id=other.id, status="failed"))
            db.flush()


def test_metadata_shows_upload_job_only_to_people_who_may_see_it(db):
    tenant = make_tenant(db)
    writer = _user(db, tenant.id)
    queued = _gallery(db, writer, [_file(jpeg(color=(40, 90, 10)), "m.jpg", "image/jpeg")])
    service.process_pending_gallery_upload_jobs(db)
    stored = db.scalar(select(StoredFile).where(StoredFile.upload_job_id == queued.upload_job_id))
    meta = files_routes.get_stored_file_metadata(stored.public_id, db=db, user=writer)
    assert meta.upload_job is not None and meta.upload_job.uploaded_count == 1
    reader = make_current_user(tenant.id, role="writer", user_id=writer.user_id, permissions=frozenset({"meetings.read", "photos.read"}))
    assert files_routes.get_stored_file_metadata(stored.public_id, db=db, user=reader).upload_job is None


def test_discard_marks_items_as_discarded(db):
    tenant = make_tenant(db)
    user = _user(db, tenant.id)
    job = _open(db, user, channel="document")
    result = _documents(db, user, [_file(PDF, "weg.pdf")], upload_job_id=job.id)
    from app.schemas.files import FileDiscardUploadsRequest

    file_id = result.items[0].id
    files_routes.discard_unlinked_uploads(FileDiscardUploadsRequest(file_ids=[file_id]), db=db, user=user)
    row = db.get(UploadJob, job.id)
    db.refresh(row)
    assert (row.uploaded, row.discarded) == (0, 1)


def test_backfill_reconstructs_exact_and_heuristic_jobs_idempotently(db):
    from app.models.entities import GalleryImage
    from app.services.upload_history_backfill import backfill_tenant

    tenant = make_tenant(db)
    user = _user(db, tenant.id)
    base = datetime(2026, 1, 10, 9, 0, tzinfo=UTC)
    files = []
    for minute in (0, 4, 30):  # zwei Fotos im Abstand von 4 min, eines 26 min später
        stored = StoredFile(
            tenant_id=tenant.id, original_name=f"alt{minute}.jpg", mime_type="image/jpeg", storage_path=f"u/{uuid.uuid4().hex}.jpg",
            created_by=user.user_id,
        )
        db.add(stored)
        db.flush()
        stored.created_at = base + timedelta(minutes=minute)
        db.add(GalleryImage(tenant_id=tenant.id, stored_file_id=stored.id, created_by=user.user_id))
        files.append(stored)
    db.flush()
    db.commit = db.flush  # Testtransaktion offen halten
    report = backfill_tenant(db, tenant.id)
    assert report.jobs == {"gallery:heuristic": 2} and report.files == 3
    jobs = list(db.scalars(select(UploadJob).where(UploadJob.tenant_id == tenant.id)))
    assert all(job.reconstructed and job.options["reconstruction"] == "heuristic" for job in jobs)
    assert sorted(job.uploaded for job in jobs) == [1, 2]
    assert backfill_tenant(db, tenant.id).files == 0


def test_upload_history_hides_files_carried_into_an_unreadable_draft(db):
    """Integration 1.6 mit 1.5.2 (ProtocolReadScope): ein Foto, das nur an einem nicht lesbaren
    Protokollentwurf hängt, ist in GET /files verborgen - der Upload-Verlauf nennt es dann weder
    in «Alle auswählen» (file-ids, auch nicht in total) noch in den Zählern des Vorgangs."""
    import dataclasses
    from datetime import date

    from app.models.entities import ProtocolImage
    from tests.factories import make_protocol, make_protocol_element, make_protocol_element_block, make_template

    tenant = make_tenant(db)
    writer = _user(db, tenant.id)
    opened = _open(db, writer)
    _gallery(db, writer, [_file(jpeg(color=(9, 90, 9)), "lager.jpg", "image/jpeg")], upload_job_id=opened.id)
    service.process_pending_gallery_upload_jobs(db)
    stored = db.scalar(select(StoredFile).where(StoredFile.upload_job_id == opened.id))
    template = make_template(db, tenant.id)
    draft = make_protocol(db, tenant.id, template.id, protocol_number="9/2026", protocol_date=date(2026, 5, 1))
    block = make_protocol_element_block(db, make_protocol_element(db, draft.id).id, configuration_snapshot_json={})
    db.add(ProtocolImage(protocol_element_block_id=block.id, stored_file_id=stored.id, sort_index=0))
    db.commit()
    photographer = dataclasses.replace(
        make_current_user(tenant.id, role="writer"),
        permissions=frozenset({"meetings.read", "photos.read", "photos.manage"}),
    )

    mine = routes.list_upload_job_file_ids(opened.id, only_images=True, camera=None, db=db, user=writer)
    assert mine.file_ids == [stored.public_id] and mine.total == 1
    theirs = routes.list_upload_job_file_ids(opened.id, only_images=True, camera=None, db=db, user=photographer)
    assert theirs.file_ids == [] and theirs.total == 0
    detail = routes.get_upload_job(opened.id, db=db, user=photographer)
    assert (detail.file_count, detail.image_count) == (0, 0)
    assert routes.get_upload_job(opened.id, db=db, user=writer).image_count == 1
