"""Kameragruppen im Upload-Vorgang (Plan 7.6, E-13): Kürzel der Seriennummer je Mandant, nie
Klartext, GPS-Zeit-Vorschlag, «Nur diese Kamera»."""

import asyncio
import io
import json
import uuid
from datetime import UTC, datetime, timedelta

from PIL import Image
from PIL.TiffImagePlugin import IFDRational
from sqlalchemy import select

from app.api.routes import upload_jobs as routes
from app.core.config import settings
from app.models.entities import StoredFile
from app.services import camera_serial, upload_job_service
from app.services.file_service import FileService
from tests.factories import make_app_user, make_current_user, make_tenant

service = FileService()


def _photo(color, *, serial=None, model="EOS R6", taken=datetime(2026, 5, 2, 10, 0), offset=None, gps_time=None) -> bytes:
    exif = Image.Exif()
    exif[0x010F] = "Canon"
    exif[0x0110] = model
    ifd = {0x9003: taken.strftime("%Y:%m:%d %H:%M:%S")}
    if serial:
        ifd[0xA431] = serial
    if offset:
        ifd[0x9011] = offset
    exif[0x8769] = ifd
    if gps_time is not None:
        exif[0x8825] = {
            1: "N", 2: (IFDRational(47, 1), IFDRational(0, 1), IFDRational(0, 1)),
            3: "E", 4: (IFDRational(8, 1), IFDRational(0, 1), IFDRational(0, 1)),
            7: (IFDRational(gps_time.hour, 1), IFDRational(gps_time.minute, 1), IFDRational(gps_time.second, 1)),
            29: gps_time.strftime("%Y:%m:%d"),
        }
    buffer = io.BytesIO()
    Image.new("RGB", (32, 24), color=color).save(buffer, format="JPEG", exif=exif.tobytes())
    return buffer.getvalue()


def _job_with(db, tenant, files):
    account = make_app_user(db, email=f"{uuid.uuid4().hex[:10]}@example.com", tenant_id=tenant.id, role_code="writer")
    user = make_current_user(tenant.id, role="writer", user_id=account.id)
    job = upload_job_service.open_job(db, tenant_id=tenant.id, channel="gallery", created_by=user.user_id)
    results: list[dict] = []
    asyncio.run(service.save_gallery_uploads(db, tenant_id=tenant.id, files=files, tags=[], created_by=user.user_id, file_results=results))
    upload_job_service.record_results(db, job, results)
    db.flush()
    return user, job


def test_same_model_is_split_by_a_per_tenant_serial_key_that_never_leaves_the_server(db, monkeypatch):
    monkeypatch.setattr(settings, "thumbnail_root", "/tmp/hocx-test-thumbs")
    tenant, other = make_tenant(db), make_tenant(db)
    user, job = _job_with(db, tenant, [
        ("a.jpg", _photo((10, 0, 0), serial="SN-1111")),
        ("b.jpg", _photo((20, 0, 0), serial="SN-1111", taken=datetime(2026, 5, 2, 11, 0))),
        ("c.jpg", _photo((30, 0, 0), serial="SN-2222")),
    ])
    keys = set(db.scalars(select(StoredFile.camera_serial_key).where(StoredFile.upload_job_id == job.id)))
    assert len(keys) == 2 and all(key and len(key) == camera_serial.KEY_HEX_LENGTH for key in keys)
    assert "SN-1111" not in keys
    # Gleiche Kamera, anderer Mandant: anderes Kürzel
    assert camera_serial.serial_key(tenant.id, "Canon", "EOS R6", "SN-1111") != camera_serial.serial_key(other.id, "Canon", "EOS R6", "SN-1111")
    detail = routes.get_upload_job(job.id, db=db, user=user)
    groups = sorted(detail.cameras, key=lambda group: -group.count)
    assert [(group.count, group.device_index) for group in groups] == [(2, 1), (1, 2)] or [(g.count, g.device_index) for g in groups] == [(2, 2), (1, 1)]
    assert "SN-1111" not in detail.model_dump_json() and "SN-2222" not in json.dumps(detail.model_dump(mode="json"))
    ids = routes.list_upload_job_file_ids(job.id, only_images=True, camera=groups[0].key, db=db, user=user)
    assert len(ids.file_ids) == 2
    assert routes.list_upload_job_file_ids(job.id, only_images=True, camera="0" * 16, db=db, user=user).file_ids == []


def test_placeholder_serials_are_ignored():
    assert camera_serial.normalize_serial("0000000") is None
    assert camera_serial.normalize_serial(" ab 12 ") == "AB12"


def test_gps_time_suggests_a_shift_for_a_camera_running_ahead(db, monkeypatch):
    monkeypatch.setattr(settings, "thumbnail_root", "/tmp/hocx-test-thumbs")
    tenant = make_tenant(db)
    files = []
    for minute in range(4):
        taken = datetime(2026, 5, 2, 10, minute)
        # Kamera geht 1 h 14 min vor: Satellitenzeit (UTC) = lokale Zeit - Offset - 74 min
        gps = taken - timedelta(hours=2) - timedelta(minutes=74)
        files.append((f"g{minute}.jpg", _photo((minute * 40, 5, 5), taken=taken, offset="+02:00", gps_time=gps.replace(tzinfo=UTC))))
    user, job = _job_with(db, tenant, files)
    [group] = routes.get_upload_job(job.id, db=db, user=user).cameras
    assert group.with_gps_time == 4 and group.suggested_shift_minutes == -74
