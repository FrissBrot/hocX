"""SHA-256-Vorab-Abgleich (POST /files/upload-precheck), Metadaten-Ergänzung ohne erneuten
Upload, Galerie-Upload mit Schätzdatum/Ergebnissen je Datei und die Bearbeitung des
geschätzten Aufnahmedatums."""

import asyncio
import hashlib
import io
import json
from datetime import UTC, date, datetime
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException, UploadFile
from starlette.datastructures import Headers

from app.api.routes import files as files_routes
from app.core.config import settings
from app.models.entities import GalleryImage, GalleryUploadJob, StoredFile
from app.schemas.files import CaptureDateUpdate, UploadPrecheckRequest
from app.services import file_service as file_service_module
from app.services.file_service import FileService
from tests.factories import make_app_user, make_current_user, make_event, make_tenant
from tests.image_fixtures import jpeg

service = FileService()


@pytest.fixture(autouse=True)
def _isolated_storage_root(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "storage_root", str(tmp_path))
    monkeypatch.setattr(settings, "upload_root", str(tmp_path / "uploads"))
    monkeypatch.setattr(settings, "thumbnail_root", str(tmp_path / "thumbnails"))


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _gallery_file(db, tenant_id: int, content: bytes, *, name="foto.jpg", **values) -> StoredFile:
    (settings_path := __import__("pathlib").Path(settings.storage_root)).mkdir(parents=True, exist_ok=True)
    (settings_path / name).write_bytes(content)
    values.setdefault("width", 32)
    values.setdefault("height", 24)
    row = StoredFile(
        tenant_id=tenant_id, original_name=name, mime_type="image/jpeg", storage_path=name,
        checksum_sha256=values.pop("checksum_sha256", _sha(content)), scan_status="clean", **values,
    )
    db.add(row)
    db.flush()
    db.add(GalleryImage(tenant_id=tenant_id, stored_file_id=row.id))
    db.flush()
    return row


def _writer(db, tenant_id):
    user = make_app_user(db, email=f"w{tenant_id}-{datetime.now().timestamp()}@example.com", tenant_id=tenant_id, role_code="writer")
    return make_current_user(tenant_id, role="writer", user_id=user.id)


def _precheck(db, user, files, estimated=None, context="gallery"):
    return files_routes.precheck_uploads(
        UploadPrecheckRequest(context=context, estimated_taken_on=estimated, files=files), db=db, user=user
    ).results


def _entry(content: bytes, client_id="a", **metadata):
    return {"client_id": client_id, "sha256": _sha(content), "name": "x.jpg", "size": len(content), "metadata": metadata or None}


def _upload_file(content: bytes, filename: str) -> UploadFile:
    return UploadFile(file=io.BytesIO(content), filename=filename, headers=Headers({"content-type": "image/jpeg"}))


# --- Vorab-Abgleich -----------------------------------------------------------------------


def test_unknown_hash_requires_upload_and_known_hash_is_skipped(db):
    tenant = make_tenant(db)
    user = _writer(db, tenant.id)
    known = jpeg(color=(1, 2, 3))
    _gallery_file(db, tenant.id, known)
    results = _precheck(db, user, [_entry(known, "known"), _entry(jpeg(color=(200, 1, 1)), "new")])
    by_id = {result.client_id: result for result in results}
    assert by_id["known"].status == "already_exists" and by_id["known"].applied == []
    assert by_id["new"].status == "upload_required" and by_id["new"].file_id is None


def test_existing_image_gets_missing_estimate_without_upload_and_second_check_is_noop(db):
    tenant = make_tenant(db)
    user = _writer(db, tenant.id)
    content = jpeg()
    row = _gallery_file(db, tenant.id, content)
    before = (settings_path := __import__("pathlib").Path(settings.storage_root) / "foto.jpg").read_bytes()

    first = _precheck(db, user, [_entry(content)], estimated=date(1998, 8, 1))[0]
    assert first.status == "metadata_updated"
    assert first.applied == ["estimated_taken_on"]
    assert first.file_id == row.public_id
    db.refresh(row)
    assert row.estimated_taken_on == date(1998, 8, 1)
    assert row.exif_taken_at is None
    assert row.estimated_taken_set_by == user.user_id
    assert settings_path.read_bytes() == before  # Datei unverändert, nichts übertragen

    again = _precheck(db, user, [_entry(content)], estimated=date(1998, 8, 1))[0]
    assert again.status == "already_exists" and again.applied == []

    different = _precheck(db, user, [_entry(content)], estimated=date(2005, 1, 1))[0]
    assert different.status == "already_exists" and different.conflicts == ["estimated_taken_on"]
    db.refresh(row)
    assert row.estimated_taken_on == date(1998, 8, 1)  # nie still überschrieben


def test_byte_identical_file_is_verified_by_the_server_not_by_client_claims(db):
    tenant = make_tenant(db)
    user = _writer(db, tenant.id)
    content = jpeg(taken_at=datetime(2015, 5, 5, 15, 0), latitude=-34.6, longitude=-58.4)
    row = _gallery_file(db, tenant.id, content)
    # Client behauptet andere Werte - der Server liest sein eigenes, byte-gleiches Original.
    result = _precheck(db, user, [_entry(content, taken_at="2000-01-01T00:00:00", gps={"latitude": 1.0, "longitude": 1.0})])[0]
    assert result.status == "metadata_updated"
    assert set(result.applied) == {"taken_at", "gps"}
    db.refresh(row)
    assert row.exif_taken_at == datetime(2015, 5, 5, 15, 0, tzinfo=UTC)
    assert row.gps_latitude == pytest.approx(-34.6, abs=1e-4)
    assert row.gps_longitude == pytest.approx(-58.4, abs=1e-4)
    assert (row.exif_taken_source, row.gps_source) == ("server", "server")


def test_false_client_claims_for_a_file_without_metadata_change_nothing(db):
    tenant = make_tenant(db)
    user = _writer(db, tenant.id)
    content = jpeg()
    row = _gallery_file(db, tenant.id, content)
    result = _precheck(db, user, [_entry(content, taken_at="2000-01-01T00:00:00")])[0]
    assert result.status == "already_exists" and result.applied == []
    db.refresh(row)
    assert row.exif_taken_at is None


def test_converted_heic_accepts_validated_client_gps_via_source_hash(db):
    tenant = make_tenant(db)
    user = _writer(db, tenant.id)
    heic_original = b"original HEIC bytes"
    row = _gallery_file(db, tenant.id, jpeg(), source_checksum_sha256=_sha(heic_original))
    result = _precheck(
        db, user,
        [_entry(heic_original, gps={"latitude": 46.95, "longitude": 7.44, "altitude_m": 540}, orientation=6, width=4032, height=3024)],
    )[0]
    assert result.status == "metadata_updated" and result.applied == ["gps"]
    db.refresh(row)
    assert (row.gps_latitude, row.gps_longitude, row.gps_altitude_m, row.gps_source) == (46.95, 7.44, 540.0, "client")
    assert row.orientation is None  # gilt nicht für das gedrehte JPEG


def test_existing_gps_is_not_overwritten(db):
    tenant = make_tenant(db)
    user = _writer(db, tenant.id)
    heic_original = b"another HEIC"
    row = _gallery_file(db, tenant.id, jpeg(), source_checksum_sha256=_sha(heic_original), gps_latitude=10.0, gps_longitude=10.0)
    result = _precheck(db, user, [_entry(heic_original, gps={"latitude": 20.0, "longitude": 20.0})])[0]
    assert result.status == "already_exists" and result.conflicts == ["gps"]
    db.refresh(row)
    assert (row.gps_latitude, row.gps_longitude) == (10.0, 10.0)


def test_other_tenants_hashes_are_never_revealed_or_modified(db):
    tenant, other = make_tenant(db), make_tenant(db)
    user = _writer(db, tenant.id)
    content = jpeg()
    foreign = _gallery_file(db, other.id, content)
    result = _precheck(db, user, [_entry(content)], estimated=date(2000, 1, 1))[0]
    assert result.status == "upload_required" and result.file_id is None
    db.refresh(foreign)
    assert foreign.estimated_taken_on is None


def test_precheck_requires_writer_role(db):
    tenant = make_tenant(db)
    with pytest.raises(HTTPException) as exc:
        _precheck(db, make_current_user(tenant.id, role="reader"), [_entry(jpeg())])
    assert exc.value.status_code == 403


def test_document_context_only_checks_hashes(db):
    tenant = make_tenant(db)
    user = _writer(db, tenant.id)
    content = jpeg()
    row = _gallery_file(db, tenant.id, content)
    result = _precheck(db, user, [_entry(content)], estimated=date(2000, 1, 1), context="document")[0]
    assert result.status == "already_exists"
    db.refresh(row)
    assert row.estimated_taken_on is None


def test_infected_matches_do_not_count(db):
    tenant = make_tenant(db)
    user = _writer(db, tenant.id)
    content = jpeg()
    row = _gallery_file(db, tenant.id, content)
    row.scan_status = "infected"
    db.flush()
    assert _precheck(db, user, [_entry(content)])[0].status == "upload_required"


def test_invalid_hash_is_rejected_by_the_schema():
    with pytest.raises(ValueError):
        UploadPrecheckRequest(files=[{"client_id": "a", "sha256": "xyz", "size": 1}])


def test_single_file_failure_falls_back_to_normal_upload(db, monkeypatch):
    tenant = make_tenant(db)
    user = _writer(db, tenant.id)
    content = jpeg()
    _gallery_file(db, tenant.id, content)

    def explode(*args, **kwargs):
        raise RuntimeError("kaputt")

    monkeypatch.setattr(file_service_module.upload_precheck_service, "enrich_existing", explode)
    result = _precheck(db, user, [_entry(content)], estimated=date(2000, 1, 1))[0]
    assert result.status == "fallback_required"


# --- Galerie-Upload mit Schätzdatum ------------------------------------------------------


def _queue_and_process(db, user, files, **form):
    queued = asyncio.run(
        files_routes.upload_gallery_images(
            files=[_upload_file(content, name) for name, content in files],
            tags=None, event_id=None, submission_assignment_id=None, submission_element_ref=None, cycle_config_id=None,
            db=db, user=user, **form,
        )
    )
    service.process_pending_gallery_upload_jobs(db)
    return files_routes.get_gallery_upload_job(queued.id, db=db, user=user)


def test_estimate_applies_only_to_images_without_real_date_and_upload_date_stays_separate(db):
    tenant = make_tenant(db)
    user = _writer(db, tenant.id)
    with_date = jpeg(color=(1, 1, 1), taken_at=datetime(2010, 10, 10, 10, 10))
    without_date = jpeg(color=(250, 250, 250))
    detail = _queue_and_process(db, user, [("mit.jpg", with_date), ("ohne.jpg", without_date)], estimated_taken_on=date(1995, 7, 1))

    assert sorted(result.status for result in detail.file_results) == ["uploaded", "uploaded"]
    rows = {row.original_name: row for row in db.query(StoredFile).filter(StoredFile.tenant_id == tenant.id)}
    assert rows["mit.jpg"].exif_taken_at == datetime(2010, 10, 10, 10, 10, tzinfo=UTC)
    assert rows["mit.jpg"].estimated_taken_on is None
    assert rows["ohne.jpg"].exif_taken_at is None
    assert rows["ohne.jpg"].estimated_taken_on == date(1995, 7, 1)
    assert rows["ohne.jpg"].created_at.date() == date.today()
    items = {item.original_name: item for item in detail.imported_items}
    assert (items["mit.jpg"].date_source, items["mit.jpg"].group_date) == ("exif", date(2010, 10, 10))
    assert (items["ohne.jpg"].date_source, items["ohne.jpg"].group_date) == ("estimated", date(1995, 7, 1))


def test_reupload_of_existing_image_adds_estimate_and_reports_it(db):
    tenant = make_tenant(db)
    user = _writer(db, tenant.id)
    content = jpeg(color=(9, 9, 9))
    first = _queue_and_process(db, user, [("a.jpg", content)])
    assert [result.status for result in first.file_results] == ["uploaded"]

    second = _queue_and_process(db, user, [("a-kopie.jpg", content)], estimated_taken_on=date(1980, 1, 1))
    assert [(r.status, r.applied) for r in second.file_results] == [("metadata_updated", ["estimated_taken_on"])]
    assert second.imported_items == []

    third = _queue_and_process(db, user, [("a-nochmal.jpg", content)])
    assert [(r.status, r.applied) for r in third.file_results] == [("skipped", [])]
    assert db.query(StoredFile).filter(StoredFile.tenant_id == tenant.id).count() == 1


def test_parallel_uploads_of_the_same_file_store_it_once(db):
    tenant = make_tenant(db)
    user = _writer(db, tenant.id)
    content = jpeg(color=(3, 4, 5))
    for _ in range(2):
        asyncio.run(
            files_routes.upload_gallery_images(
                files=[_upload_file(content, "gleich.jpg")], tags=None, event_id=None, submission_assignment_id=None,
                submission_element_ref=None, cycle_config_id=None, db=db, user=user,
            )
        )
    service.process_pending_gallery_upload_jobs(db)
    jobs = db.query(GalleryUploadJob).filter(GalleryUploadJob.tenant_id == tenant.id).order_by(GalleryUploadJob.created_at).all()
    statuses = sorted(result["status"] for job in jobs for result in job.file_results)
    assert statuses == ["skipped", "uploaded"]
    assert db.query(StoredFile).filter(StoredFile.tenant_id == tenant.id).count() == 1


def test_file_metadata_hints_only_apply_when_the_server_hash_matches(db):
    tenant = make_tenant(db)
    user = _writer(db, tenant.id)
    content = jpeg(color=(70, 80, 90))
    hints = json.dumps([
        {"sha256": "0" * 64, "metadata": {"gps": {"latitude": 1, "longitude": 1}}},
        {"sha256": "nonsense", "metadata": {}},
    ])
    detail = _queue_and_process(db, user, [("hint.jpg", content)], file_metadata=hints)
    assert [result.status for result in detail.file_results] == ["uploaded"]
    row = db.query(StoredFile).filter(StoredFile.tenant_id == tenant.id).one()
    assert row.gps_latitude is None


def test_gallery_upload_rejects_an_implausible_estimate(db):
    tenant = make_tenant(db)
    user = _writer(db, tenant.id)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            files_routes.upload_gallery_images(
                files=[_upload_file(jpeg(), "x.jpg")], tags=None, event_id=None, submission_assignment_id=None,
                submission_element_ref=None, cycle_config_id=None, db=db, user=user, estimated_taken_on=date(1700, 1, 1),
            )
        )
    assert exc.value.status_code == 422


def test_unsupported_format_is_reported_as_failed(db):
    tenant = make_tenant(db)
    user = _writer(db, tenant.id)
    detail = _queue_and_process(db, user, [("kein-bild.jpg", b"definitely not an image")])
    assert [result.status for result in detail.file_results] == ["failed"]
    assert detail.file_results[0].message
    # IMGMETA-012: maschinenlesbarer Grund, den das Frontend übersetzt.
    assert detail.file_results[0].code == "unsupported_format"


def test_upload_rejections_carry_a_code_and_parameters(db):
    """IMGMETA-012: ingest_file lehnt mit Code ab; der deutsche Text bleibt als detail."""
    from app.services import upload_pipeline

    tenant = make_tenant(db)
    with pytest.raises(upload_pipeline.UploadRejected) as too_large:
        upload_pipeline.ingest_file(
            db, tenant_id=tenant.id, content=b"x" * 2048, original_filename="gross.jpg", scan_status="clean",
            sniff=upload_pipeline._sniff_image_mime, max_bytes=1024, storage_subdir_parts=("test",),
            enable_perceptual_dedupe=False, enable_thumbnail=False, created_by=None,
        )
    assert (too_large.value.status_code, too_large.value.code) == (413, "too_large")
    assert too_large.value.params == {"max_mb": 0}
    failure = upload_pipeline.upload_failure("gross.jpg", too_large.value)
    assert failure["code"] == "too_large" and failure["message"] == too_large.value.detail

    with pytest.raises(upload_pipeline.UploadRejected) as infected:
        upload_pipeline.ingest_file(
            db, tenant_id=tenant.id, content=jpeg(), original_filename="virus.jpg", scan_status="infected",
            sniff=upload_pipeline._sniff_image_mime, max_bytes=10 * 1024 * 1024, storage_subdir_parts=("test",),
            enable_perceptual_dedupe=False, enable_thumbnail=False, created_by=None,
        )
    assert infected.value.code == "infected"


def test_mixed_batch_counts_each_file_exactly_once(db, monkeypatch):
    tenant = make_tenant(db)
    user = _writer(db, tenant.id)
    existing = jpeg(color=(11, 12, 13))
    _queue_and_process(db, user, [("alt.jpg", existing)])
    detail = _queue_and_process(
        db, user,
        [("neu.jpg", jpeg(color=(100, 0, 0))), ("alt-kopie.jpg", existing), ("kaputt.jpg", b"xx")],
        estimated_taken_on=date(1990, 1, 1),
    )
    statuses = sorted(result.status for result in detail.file_results)
    assert statuses == ["failed", "metadata_updated", "uploaded"]
    assert len(detail.file_results) == 3


# --- Geschätztes Datum bearbeiten ---------------------------------------------------------


def test_writer_can_set_change_and_remove_the_estimate(db):
    tenant = make_tenant(db)
    user = _writer(db, tenant.id)
    row = _gallery_file(db, tenant.id, jpeg(), exif_taken_at=None)
    created_at = row.created_at

    metadata = files_routes.update_stored_file_capture_date(row.public_id, CaptureDateUpdate(estimated_taken_on=date(1970, 3, 1)), db=db, user=user)
    assert (metadata.estimated_taken_on, metadata.date_source, metadata.effective_date) == (date(1970, 3, 1), "estimated", date(1970, 3, 1))
    assert metadata.can_edit_capture_date is True

    metadata = files_routes.update_stored_file_capture_date(row.public_id, CaptureDateUpdate(estimated_taken_on=date(1971, 4, 2)), db=db, user=user)
    assert metadata.estimated_taken_on == date(1971, 4, 2)

    metadata = files_routes.update_stored_file_capture_date(row.public_id, CaptureDateUpdate(estimated_taken_on=None), db=db, user=user)
    assert metadata.estimated_taken_on is None and metadata.date_source == "upload"
    db.refresh(row)
    assert row.created_at == created_at and row.exif_taken_at is None


def test_capture_date_edit_requires_writer_and_same_tenant(db):
    tenant, other = make_tenant(db), make_tenant(db)
    row = _gallery_file(db, tenant.id, jpeg())
    with pytest.raises(HTTPException) as exc:
        files_routes.update_stored_file_capture_date(row.public_id, CaptureDateUpdate(estimated_taken_on=date(2000, 1, 1)), db=db, user=make_current_user(tenant.id, role="reader"))
    assert exc.value.status_code == 403
    with pytest.raises(HTTPException) as exc:
        files_routes.update_stored_file_capture_date(row.public_id, CaptureDateUpdate(estimated_taken_on=date(2000, 1, 1)), db=db, user=_writer(db, other.id))
    assert exc.value.status_code == 404


def test_metadata_shows_three_separate_dates_and_gps_to_the_own_tenant_only(db):
    tenant, other = make_tenant(db), make_tenant(db)
    row = _gallery_file(
        db, tenant.id, jpeg(), exif_taken_at=datetime(2001, 1, 1, 12, 0, tzinfo=UTC), estimated_taken_on=date(1999, 1, 1),
        gps_latitude=-10.5, gps_longitude=-20.25, metadata_scanned_at=datetime.now(UTC),
    )
    metadata = files_routes.get_stored_file_metadata(row.public_id, db=db, user=_writer(db, tenant.id))
    assert metadata.exif_taken_at == datetime(2001, 1, 1, 12, 0, tzinfo=UTC)
    assert metadata.estimated_taken_on == date(1999, 1, 1)
    assert metadata.date_source == "exif" and metadata.effective_date == date(2001, 1, 1)
    assert metadata.gps.latitude == -10.5 and metadata.gps.longitude == -20.25
    assert metadata.can_edit_capture_date is True
    # Kassier darf lesen (bestehende Regel), aber nichts bearbeiten.
    assert files_routes.get_stored_file_metadata(row.public_id, db=db, user=make_current_user(tenant.id, role="kassier")).can_edit_capture_date is False
    # Leser haben auf Galeriebilder keinen Zugriff - auch nicht auf deren Standort.
    with pytest.raises(HTTPException) as exc:
        files_routes.get_stored_file_metadata(row.public_id, db=db, user=make_current_user(tenant.id, role="reader"))
    assert exc.value.status_code == 403
    with pytest.raises(HTTPException):
        files_routes.get_stored_file_metadata(row.public_id, db=db, user=_writer(db, other.id))


def test_later_real_date_changes_gallery_order_and_estimate_never_auto_links(db):
    tenant = make_tenant(db)
    user = _writer(db, tenant.id)
    event = make_event(db, tenant.id, event_date=date(2003, 3, 3))
    older = _gallery_file(db, tenant.id, jpeg(color=(1, 0, 0)), name="a.jpg", estimated_taken_on=date(1999, 9, 9))
    newer = _gallery_file(db, tenant.id, jpeg(color=(0, 1, 0)), name="b.jpg", estimated_taken_on=date(2001, 1, 1))

    def order():
        return [item.original_name for item in service.list_tenant_files(db, tenant.id, sort_by="group_date", sort_dir="desc", only_images=True)]

    assert order() == ["b.jpg", "a.jpg"]
    image = db.query(GalleryImage).filter(GalleryImage.stored_file_id == older.id).one()
    assert image.event_id is None

    # Später nachgeliefertes echtes Datum (z. B. via Hash-Abgleich) gewinnt sofort.
    older.exif_taken_at = datetime(2003, 3, 3, 9, 0, tzinfo=UTC)
    file_service_module.photo_event_link_service.resync_photo_after_date_change(db, older)
    db.flush()
    assert order() == ["a.jpg", "b.jpg"]
    db.refresh(image)
    assert image.event_id == event.id and image.event_auto_linked is True
    items = {item.original_name: item for item in service.list_tenant_files(db, tenant.id, only_images=True)}
    assert items["a.jpg"].date_source == "exif" and items["b.jpg"].date_source == "estimated"


# --- HEIC/HEIF und Protokollbilder --------------------------------------------------------


def _heic_with_metadata() -> bytes:
    from PIL import Image as PILImage

    from tests.image_fixtures import build_exif

    exif = build_exif(taken_at=datetime(2024, 6, 1, 18, 45, 0), offset="+02:00", latitude=46.2, longitude=-6.1, orientation=6)
    buffer = io.BytesIO()
    PILImage.new("RGB", (64, 48), (200, 40, 40)).save(buffer, format="HEIF", exif=exif.tobytes())
    return buffer.getvalue()


def test_heic_upload_keeps_capture_metadata_and_is_found_again_by_its_source_hash(db):
    tenant = make_tenant(db)
    user = _writer(db, tenant.id)
    heic = _heic_with_metadata()
    detail = _queue_and_process(db, user, [("IMG_0001.HEIC", heic)], estimated_taken_on=date(1999, 1, 1))
    assert [result.status for result in detail.file_results] == ["uploaded"]
    row = db.query(StoredFile).filter(StoredFile.tenant_id == tenant.id).one()
    assert row.mime_type == "image/jpeg" and row.source_checksum_sha256 == _sha(heic)
    assert row.exif_taken_at == datetime(2024, 6, 1, 18, 45, tzinfo=UTC) and row.exif_taken_offset == "+02:00"
    assert row.gps_latitude == pytest.approx(46.2, abs=1e-4) and row.gps_longitude == pytest.approx(-6.1, abs=1e-4)
    assert row.estimated_taken_on is None  # echtes Datum gefunden, Schätzung nicht übernommen
    assert row.orientation is None  # JPEG ist bereits gedreht

    # Erneute Auswahl desselben HEIC im Browser: Vorab-Abgleich über den Quell-Hash.
    assert _precheck(db, user, [_entry(heic)])[0].status == "already_exists"


def test_protocol_images_store_capture_date_and_gps(db, monkeypatch):
    import threading

    from app.services import image_metadata_service
    from tests.factories import make_protocol, make_protocol_element, make_protocol_element_block, make_template

    # IMGMETA-013: die Analyse läuft nicht auf dem Event-Loop-Thread des Requests.
    threads = []
    original_extract = image_metadata_service.extract_image_metadata
    monkeypatch.setattr(
        image_metadata_service, "extract_image_metadata", lambda content: threads.append(threading.current_thread()) or original_extract(content)
    )

    tenant = make_tenant(db)
    protocol = make_protocol(db, tenant.id, make_template(db, tenant.id).id)
    block = make_protocol_element_block(db, make_protocol_element(db, protocol.id, sort_index=0).id, configuration_snapshot_json={})
    content = jpeg(taken_at=datetime(2026, 3, 3, 19, 0), latitude=47.0, longitude=8.0)
    upload = UploadFile(file=io.BytesIO(content), filename="p.jpg", headers=Headers({"content-type": "image/jpeg"}))
    asyncio.run(service.save_protocol_image(db, protocol_element_block=block, file=upload))
    row = db.query(StoredFile).filter(StoredFile.tenant_id == tenant.id).one()
    assert row.exif_taken_at == datetime(2026, 3, 3, 19, 0, tzinfo=UTC)
    assert (row.gps_latitude, row.gps_longitude) == (pytest.approx(47.0, abs=1e-4), pytest.approx(8.0, abs=1e-4))
    assert row.metadata_scan_status == "ok"
    assert threads and all(thread is not threading.main_thread() for thread in threads)


def test_file_hints_are_cleared_when_the_job_ends(db):
    """IMGMETA-004: Browser-Hinweise (inkl. GPS) bleiben nicht dauerhaft im Upload-Auftrag."""
    tenant = make_tenant(db)
    user = _writer(db, tenant.id)
    content = jpeg(color=(71, 81, 91))
    hints = json.dumps([{"sha256": hashlib.sha256(content).hexdigest(), "metadata": {"gps": {"latitude": 47.1, "longitude": 8.2}}}])
    queued = asyncio.run(
        files_routes.upload_gallery_images(
            files=[_upload_file(content, "hint.jpg")], tags=None, event_id=None, submission_assignment_id=None,
            submission_element_ref=None, cycle_config_id=None, db=db, user=user, file_metadata=hints,
        )
    )
    job = db.get(GalleryUploadJob, queued.id)
    assert job.file_hints  # bis zur Verarbeitung vorhanden (Wiederaufnahme nach Abbruch)
    service.process_pending_gallery_upload_jobs(db)
    db.refresh(job)
    assert job.status == "done" and job.file_hints == {}


def test_byte_identical_file_is_analyzed_at_most_once_regardless_of_client_claims(db, monkeypatch):
    """IMGMETA-009: Erfundene Client-Werte lösen kein wiederholtes Einlesen der Datei aus."""
    from app.services import upload_precheck_service

    tenant = make_tenant(db)
    user = _writer(db, tenant.id)
    content = jpeg(color=(33, 44, 55), taken_at=datetime(2012, 3, 4, 5, 6))
    row = _gallery_file(db, tenant.id, content)
    calls = []
    original = upload_precheck_service.analyze_stored_file
    monkeypatch.setattr(upload_precheck_service, "analyze_stored_file", lambda db, stored: calls.append(stored.id) or original(db, stored))

    claims = {"gps": {"latitude": 10.0, "longitude": 20.0}, "camera_model": "Erfunden"}
    first = _precheck(db, user, [_entry(content, **claims)])[0]
    assert first.status == "metadata_updated" and "taken_at" in first.applied
    for _ in range(3):
        again = _precheck(db, user, [_entry(content, **claims)])[0]
        assert again.status == "already_exists"
    assert calls == [row.id]
    db.refresh(row)
    assert row.gps_latitude is None and row.camera_model is None  # Client-Werte nie übernommen


def test_source_checksum_match_of_another_tenant_is_not_revealed_or_enriched(db):
    """IMGMETA-015: Quell-Hash-Treffer (konvertierte HEIC) sind mandantengebunden wie Original-Hashes."""
    tenant = make_tenant(db)
    other = make_tenant(db)
    user = _writer(db, tenant.id)
    heic_hash = "c" * 64
    foreign = _gallery_file(db, other.id, jpeg(color=(9, 9, 9)), name="fremd.jpg", source_checksum_sha256=heic_hash)
    entry = {"client_id": "x", "sha256": heic_hash, "name": "IMG_1.HEIC", "size": 1, "metadata": {"gps": {"latitude": 1.0, "longitude": 2.0}}}
    result = _precheck(db, user, [entry], estimated=date(2000, 1, 1))[0]
    assert result.status == "upload_required" and result.file_id is None
    db.refresh(foreign)
    assert foreign.gps_latitude is None and foreign.estimated_taken_on is None
