"""Upload-Verlauf 1.6: abgelehnte Dateien als Zeilen im Vorgang - ZIP-Einträge im Galerie-Ingest,
Protokollbilder (Vorgang je Protokoll und Tag) und Abgabebox (Trigger aus 0254, ohne neue Rechte
für hocx_abgabebox), jeweils mit Grund und mandantengetrennt."""

import asyncio
import io
import uuid
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException, UploadFile
from PIL import Image
from sqlalchemy import select, text
from starlette.datastructures import Headers

from app.api.routes import files as files_routes
from app.api.routes import upload_jobs as routes
from app.models.entities import StoredFile, SubmissionLink, SubmissionUpload, SubmissionUploadFile
from app.models.upload_history_entities import UploadJob, UploadJobItem
from app.services.file_service import FileService
from tests.factories import make_protocol, make_protocol_element, make_protocol_element_block, make_template, make_tenant
from tests.image_fixtures import jpeg
from tests.test_submission_done_notifications import box  # noqa: F401 (Fixture)
from tests.test_upload_jobs import _file, _gallery, _isolated_storage_root, _user  # noqa: F401 (Fixture)

service = FileService()


def _zip_of(entries: dict[str, bytes]) -> bytes:
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def _items(db, job_id):
    return {item.original_name: item for item in db.scalars(select(UploadJobItem).where(UploadJobItem.upload_job_id == job_id))}


def test_zip_entries_that_are_rejected_become_rows_with_reason_and_archive(db):
    tenant = make_tenant(db)
    user = _user(db, tenant.id)
    archive = _zip_of({"lager/bild.jpg": jpeg(color=(10, 200, 30)), "lager/plan.pdf": b"%PDF-1.7\nx\n", "notiz.txt": b"hallo"})
    queued = _gallery(db, user, [_file(archive, "lager.zip", "application/zip")])
    service.process_pending_gallery_upload_jobs(db)
    job = db.get(UploadJob, queued.upload_job_id)
    db.refresh(job)
    items = _items(db, job.id)
    assert items["plan.pdf"].status == "rejected" and items["plan.pdf"].reason_code == "not_image"
    assert items["plan.pdf"].reason_params == {"archive": "lager.zip"}
    assert items["notiz.txt"].reason_code == "not_image"
    assert items["bild.jpg"].status == "uploaded"
    assert (job.total, job.uploaded, job.rejected, job.status) == (3, 1, 2, "partial")
    # Die Ergebnisliste der API zeigt Grund und Archiv
    listed = [item for item in routes.list_upload_job_items(job.id, status=None, cursor=None, limit=100, db=db, user=user).items if item.status == "rejected"]
    assert {item.reason_code for item in listed} == {"not_image"} and listed[0].reason_params["archive"] == "lager.zip"
    # Bisherige Rückmeldung im Ingest-Auftrag bleibt unverändert
    gallery_job = routes_gallery_job(db, queued.id)
    assert "2 Dateien ohne Bildinhalt übersprungen (kein Bild)" in gallery_job.errors


def routes_gallery_job(db, job_id):
    from app.models.entities import GalleryUploadJob

    return db.scalar(select(GalleryUploadJob).where(GalleryUploadJob.id == job_id))


def test_empty_zip_is_rejected_as_a_row_and_a_broken_zip_already_at_upload(db):
    tenant = make_tenant(db)
    user = _user(db, tenant.id)
    # Ein kaputtes ZIP lehnt schon der Upload ab (der Browser meldet es als client-result)
    with pytest.raises(HTTPException) as caught:
        _gallery(db, user, [_file(b"PK\x03\x04kaputt", "kaputt.zip", "application/zip")])
    assert caught.value.status_code == 400
    empty = _gallery(db, user, [_file(_zip_of({}), "leer.zip", "application/zip")])
    service.process_pending_gallery_upload_jobs(db)
    items = _items(db, empty.upload_job_id)
    assert items["leer.zip"].status == "rejected" and items["leer.zip"].reason_code == "zip_no_images"


def _png_file(name="tafel.png", color=(10, 20, 30)) -> UploadFile:
    buffer = io.BytesIO()
    Image.new("RGB", (40, 30), color=color).save(buffer, format="PNG")
    buffer.seek(0)
    return UploadFile(file=buffer, filename=name, headers=Headers({"content-type": "image/png"}))


def _block(db, tenant):
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id, protocol_number=f"P-{uuid.uuid4().hex[:4]}")
    block = make_protocol_element_block(db, make_protocol_element(db, protocol.id).id, configuration_snapshot_json={})
    # Wie im Betrieb bereits gespeichert: die Ablehnung rollt nur die eigene Anfrage zurück
    db.commit()
    return protocol, block


def test_rejected_and_duplicate_protocol_images_are_rows_in_the_protocol_day_job(db, monkeypatch):
    # Die Test-Session rollt bei rollback() die ganze äussere Transaktion zurück (conftest), im
    # Betrieb nur die abgelehnte Anfrage. Beide Ablehnungen hier schreiben vorher nichts.
    monkeypatch.setattr(db, "rollback", lambda: None)
    tenant = make_tenant(db)
    user = _user(db, tenant.id)
    protocol, block = _block(db, tenant)
    asyncio.run(files_routes.upload_image(block.public_id, file=_png_file(), title=None, caption=None, db=db, user=user))
    # Gleiches Bild nochmals in denselben Block → 409, Zeile «Duplikat»
    with pytest.raises(HTTPException) as caught:
        asyncio.run(files_routes.upload_image(block.public_id, file=_png_file("tafel-2.png"), title=None, caption=None, db=db, user=user))
    assert caught.value.status_code == 409
    # Falsches Format (Inhalt passt nicht zum Typ) → abgelehnt
    fake = UploadFile(file=io.BytesIO(b"kein bild"), filename="fake.png", headers=Headers({"content-type": "image/png"}))
    with pytest.raises(HTTPException) as caught:
        asyncio.run(files_routes.upload_image(block.public_id, file=fake, title=None, caption=None, db=db, user=user))
    assert caught.value.status_code == 400
    [job] = db.scalars(select(UploadJob).where(UploadJob.tenant_id == tenant.id, UploadJob.channel == "protocol_image"))
    db.refresh(job)
    items = _items(db, job.id)
    assert items["tafel-2.png"].status == "duplicate" and items["tafel-2.png"].reason_code == "duplicate_exact"
    assert items["fake.png"].status == "rejected" and items["fake.png"].reason_code == "unsupported_format"
    assert (job.total, job.uploaded, job.duplicates, job.rejected, job.status) == (3, 1, 1, 1, "partial")
    assert job.protocol_id == protocol.id


def test_protocol_image_of_a_foreign_tenant_block_records_nothing(db):
    tenant, other = make_tenant(db), make_tenant(db)
    _protocol, foreign_block = _block(db, other)
    user = _user(db, tenant.id)
    fake = UploadFile(file=io.BytesIO(b"kein bild"), filename="fake.png", headers=Headers({"content-type": "image/png"}))
    with pytest.raises(HTTPException) as caught:
        asyncio.run(files_routes.upload_image(foreign_block.public_id, file=fake, title=None, caption=None, db=db, user=user))
    assert caught.value.status_code == 404
    assert db.scalar(select(UploadJob).where(UploadJob.tenant_id.in_([tenant.id, other.id]), UploadJob.channel == "protocol_image")) is None


def _as_abgabebox(db, box, statements):
    """Wie abgabebox-backend: Rolle hocx_abgabebox mit Link-Kontext, nur INSERT."""
    link_token = db.scalar(select(SubmissionLink.token).where(SubmissionLink.tenant_id == box["tenant"].id))
    connection = db.connection()
    connection.execute(text("SAVEPOINT as_abgabebox"))
    connection.execute(text("SET LOCAL ROLE hocx_abgabebox"))
    connection.execute(text("SELECT set_config('app.abgabebox_link', :token, true)"), {"token": link_token})
    try:
        for sql, params in statements:
            connection.execute(text(sql), params)
    finally:
        connection.execute(text("RESET ROLE"))
    db.expire_all()


_LOG = (
    "INSERT INTO submission_upload_log (assignment_id, element_ref, status, request_ref, upload_id, reason_code, file_name, file_size) "
    "VALUES (:a, 'event-1', :status, :ref, :upload, :reason, :name, :size)"
)


def test_abgabebox_rejections_of_one_request_form_one_job(db, box):
    ref = uuid.uuid4()
    rows = [
        {"a": box["assignment"].id, "status": "file_rejected", "ref": ref, "upload": None, "reason": "infected", "name": "virus.pdf", "size": 68},
        {"a": box["assignment"].id, "status": "file_rejected", "ref": ref, "upload": None, "reason": "too_large", "name": "riesig.pdf", "size": 99},
        # Unbekannter Grund wird ignoriert
        {"a": box["assignment"].id, "status": "file_rejected", "ref": ref, "upload": None, "reason": "erfunden", "name": "x.pdf", "size": 1},
    ]
    _as_abgabebox(db, box, [(_LOG, row) for row in rows])
    job = db.scalar(select(UploadJob).where(UploadJob.request_ref == ref))
    assert job.channel == "abgabebox" and job.actor_kind == "anonymous_link" and job.tenant_id == box["tenant"].id
    assert job.submission_assignment_id == box["assignment"].id
    assert (job.total, job.infected, job.rejected, job.status) == (2, 1, 1, "failed")
    items = _items(db, job.id)
    assert items["virus.pdf"].status == "infected" and items["riesig.pdf"].reason_code == "too_large"
    # Das Abgabe-Protokoll blendet die Datei-Zeilen aus
    from app.repositories.submission_repository import SubmissionRepository

    logged = SubmissionRepository().list_upload_log(db, assignment_id=box["assignment"].id, element_ref="event-1")
    assert all(row.status not in ("file_rejected", "file_duplicate") for row in logged)


def test_abgabebox_log_row_keeps_no_name_and_control_chars_are_removed(db, box):
    """Datensparsamkeit: Name und Grösse stehen nur im Vorgang, nicht im Abgabe-Protokoll;
    Steuer- und Bidi-Zeichen werden entfernt."""
    ref = uuid.uuid4()
    _as_abgabebox(db, box, [(_LOG, {"a": box["assignment"].id, "status": "file_rejected", "ref": ref, "upload": None, "reason": "too_large", "name": "rechnung\u202efdp.exe", "size": 5})])
    job = db.scalar(select(UploadJob).where(UploadJob.request_ref == ref))
    assert list(_items(db, job.id)) == ["rechnungfdp.exe"]
    left = db.execute(text("SELECT file_name, file_size FROM submission_upload_log WHERE request_ref = :r"), {"r": ref}).one()
    assert tuple(left) == (None, None)


def test_abgabebox_rejected_requests_are_capped_per_assignment_and_hour(db, box):
    statements = [
        (_LOG, {"a": box["assignment"].id, "status": "file_rejected", "ref": uuid.uuid4(), "upload": None, "reason": "too_large", "name": f"{i}.pdf", "size": 1})
        for i in range(55)
    ]
    _as_abgabebox(db, box, statements)
    count = db.scalar(select(text("count(*)")).select_from(UploadJob).where(UploadJob.submission_assignment_id == box["assignment"].id, UploadJob.request_ref.is_not(None)))
    assert count == 50


def test_abgabebox_duplicates_join_the_job_of_the_stored_submission(db, box):
    upload = SubmissionUpload(assignment_id=box["assignment"].id, event_id=box["event"].id, status="submitted", submitted_at=datetime.now(UTC))
    db.add(upload)
    db.flush()
    stored = StoredFile(tenant_id=box["tenant"].id, original_name="neu.pdf", mime_type="application/pdf", storage_path="t/neu.pdf", file_size_bytes=12)
    db.add(stored)
    db.flush()
    ref = uuid.uuid4()
    _as_abgabebox(db, box, [
        ("INSERT INTO submission_upload_file (upload_id, stored_file_id, sort_index) VALUES (:u, :f, 0)", {"u": upload.id, "f": stored.id}),
        (_LOG, {"a": box["assignment"].id, "status": "file_duplicate", "ref": ref, "upload": upload.id, "reason": "duplicate_exact", "name": "alt.pdf", "size": 12}),
    ])
    job = db.scalar(select(UploadJob).where(UploadJob.submission_upload_id == upload.id))
    assert (job.total, job.uploaded, job.duplicates, job.status) == (2, 1, 1, "done")
    assert _items(db, job.id)["alt.pdf"].status == "duplicate"
    assert db.scalar(select(UploadJob).where(UploadJob.request_ref == ref)) is None


def test_abgabebox_log_cannot_attach_to_a_submission_of_another_tenant(db, box):
    """upload_id einer fremden Einreichung (anderer Mandant): der Trigger hängt nichts an; die
    Zeile landet im eigenen Vorgang der Anfrage und im Mandanten der Abgabe."""
    from app.models.entities import SubmissionAssignment
    from app.schemas.submission import SubmissionAssignmentCreate, SubmissionLinkCreate
    from app.services.submission_link_service import SubmissionLinkService
    from app.services.submission_service import SubmissionService
    from tests.factories import make_event

    other = make_tenant(db)
    foreign_event = make_event(db, other.id, title="Fremd")
    link = SubmissionLinkService().create_link(db, SubmissionLinkCreate(name="Fremd"), tenant_id=other.id)
    created = SubmissionService().create_assignment(
        db, SubmissionAssignmentCreate(
            title="Fremd", public_slug=f"fremd-{uuid.uuid4().hex[:6]}", source_type="events", tag_filter="fremd", link_ids=[link.id],
        ),
        tenant_id=other.id,
    )
    foreign_assignment = db.scalar(select(SubmissionAssignment).where(SubmissionAssignment.public_id == created.id))
    foreign_upload = SubmissionUpload(assignment_id=foreign_assignment.id, event_id=foreign_event.id, status="submitted", submitted_at=datetime.now(UTC))
    db.add(foreign_upload)
    db.flush()
    foreign_file = StoredFile(tenant_id=other.id, original_name="f.pdf", mime_type="application/pdf", storage_path="t/f.pdf")
    db.add(foreign_file)
    db.flush()
    db.add(SubmissionUploadFile(upload_id=foreign_upload.id, stored_file_id=foreign_file.id, sort_index=0))
    db.flush()
    foreign_job = db.scalar(select(UploadJob).where(UploadJob.submission_upload_id == foreign_upload.id))
    assert foreign_job is not None and foreign_job.total == 1
    ref = uuid.uuid4()
    _as_abgabebox(db, box, [
        (_LOG, {"a": box["assignment"].id, "status": "file_duplicate", "ref": ref, "upload": foreign_upload.id, "reason": "duplicate_exact", "name": "y.pdf", "size": 1}),
    ])
    assert db.get(UploadJob, foreign_job.id).total == 1
    own = db.scalar(select(UploadJob).where(UploadJob.request_ref == ref))
    assert own is not None and own.tenant_id == box["tenant"].id and own.duplicates == 1
    assert own.submission_assignment_id == box["assignment"].id


def test_abgabebox_role_still_cannot_read_the_history(db, box):
    denied = None
    link_token = db.scalar(select(SubmissionLink.token).where(SubmissionLink.tenant_id == box["tenant"].id))
    connection = db.connection()
    connection.execute(text("SAVEPOINT as_abgabebox_read"))
    connection.execute(text("SET LOCAL ROLE hocx_abgabebox"))
    connection.execute(text("SELECT set_config('app.abgabebox_link', :token, true)"), {"token": link_token})
    try:
        connection.execute(text("SELECT count(*) FROM upload_job_item"))
    except Exception as exc:  # noqa: BLE001 - erwartet
        denied = str(exc)
    finally:
        connection.execute(text("ROLLBACK TO SAVEPOINT as_abgabebox_read"))
    assert denied is not None and "permission denied" in denied
