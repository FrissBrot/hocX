"""Gezielter Metadaten-Backfill (image_metadata_backfill.run_backfill)."""

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.core.config import settings
from app.models.entities import GalleryImage, StoredFile
from app.services.image_metadata_backfill import run_backfill
from tests.factories import make_tenant
from tests.image_fixtures import jpeg


@pytest.fixture(autouse=True)
def _isolated_storage_root(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "storage_root", str(tmp_path))


def _stored(db, tenant_id, content: bytes | None, name: str, **values) -> StoredFile:
    if content is not None:
        (Path(settings.storage_root) / name).write_bytes(content)
    row = StoredFile(
        tenant_id=tenant_id, original_name=name, mime_type="image/jpeg", storage_path=name,
        checksum_sha256=hashlib.sha256(content or name.encode()).hexdigest(), scan_status="clean", width=32, height=24, **values,
    )
    db.add(row)
    db.flush()
    db.add(GalleryImage(tenant_id=tenant_id, stored_file_id=row.id))
    db.flush()
    return row


def test_reconstructs_date_and_gps_handles_missing_and_empty_files_and_is_idempotent(db):
    tenant = make_tenant(db)
    rich = _stored(db, tenant.id, jpeg(taken_at=datetime(2012, 12, 12, 12, 12), latitude=-1.25, longitude=36.8, model="X100"), "rich.jpg")
    empty = _stored(db, tenant.id, jpeg(), "empty.jpg")
    missing = _stored(db, tenant.id, None, "missing.jpg")
    broken = _stored(db, tenant.id, b"\xff\xd8 not really", "broken.jpg")
    # Bereits vollständig: kein Kandidat.
    complete = _stored(
        db, tenant.id, jpeg(), "complete.jpg", exif_taken_at=datetime(2000, 1, 1, tzinfo=UTC),
        gps_latitude=1.0, gps_longitude=1.0, camera_model="Y",
    )
    other_tenant = _stored(db, make_tenant(db).id, jpeg(taken_at=datetime(2001, 1, 1, 1, 1)), "other.jpg")

    report = run_backfill(db, tenant_id=tenant.id)
    assert report.as_dict() == {
        "checked": 4, "taken_at_added": 1, "gps_added": 1, "other_added": 1, "not_reconstructable": 1,
        "no_metadata": 1, "missing_files": 1, "failed": 1, "conflicts": 0, "converted_sources": 0,
    }
    for row in (rich, empty, missing, broken, complete, other_tenant):
        db.refresh(row)
    assert rich.exif_taken_at == datetime(2012, 12, 12, 12, 12, tzinfo=UTC)
    assert rich.gps_latitude == pytest.approx(-1.25, abs=1e-4) and rich.gps_source == "backfill"
    assert rich.exif_taken_source == "backfill" and rich.camera_model == "X100"
    assert (empty.metadata_scan_status, missing.metadata_scan_status, broken.metadata_scan_status) == ("no_metadata", "missing_file", "unreadable")
    assert empty.exif_taken_at is None
    assert complete.metadata_scanned_at is None
    assert other_tenant.exif_taken_at is None  # anderer Mandant nicht angefasst

    # Wiederholung: nichts mehr zu tun, keine Änderungen.
    assert run_backfill(db, tenant_id=tenant.id).checked == 0
    # --rescan prüft erneut, ergänzt aber nur - vorhandene Werte bleiben.
    rescan = run_backfill(db, tenant_id=tenant.id, rescan=True)
    assert rescan.taken_at_added == 0 and rescan.gps_added == 0
    db.refresh(rich)
    assert rich.exif_taken_at == datetime(2012, 12, 12, 12, 12, tzinfo=UTC)


def test_interrupted_run_resumes_where_it_stopped(db):
    tenant = make_tenant(db)
    rows = [_stored(db, tenant.id, jpeg(color=(i, i, i), taken_at=datetime(2010, 1, i + 1, 8, 0)), f"r{i}.jpg") for i in range(5)]
    first = run_backfill(db, tenant_id=tenant.id, limit=2, batch_size=1)
    assert first.checked == 2
    second = run_backfill(db, tenant_id=tenant.id, batch_size=2)
    assert second.checked == 3 and second.taken_at_added == 3
    for row in rows:
        db.refresh(row)
        assert row.exif_taken_at is not None


def test_dry_run_changes_nothing(db):
    tenant = make_tenant(db)
    row = _stored(db, tenant.id, jpeg(taken_at=datetime(2014, 4, 4, 4, 4)), "dry.jpg")
    report = run_backfill(db, tenant_id=tenant.id, dry_run=True)
    assert report.taken_at_added == 1
    db.refresh(row)
    assert row.exif_taken_at is None and row.metadata_scanned_at is None


def test_failing_write_of_one_file_does_not_block_the_run(db, monkeypatch):
    """IMGMETA-003: Verletzt eine Datei beim Speichern einen CHECK (früher: Blickrichtung 360.0),
    wird nur sie zurückgerollt und markiert; die übrigen werden gespeichert, ein erneuter Lauf
    hängt nicht an derselben Datei."""
    from app.services import image_metadata_service

    tenant = make_tenant(db)
    bad = _stored(db, tenant.id, jpeg(color=(1, 1, 1), taken_at=datetime(2015, 5, 5, 5, 5)), "bad.jpg")
    good = _stored(db, tenant.id, jpeg(color=(2, 2, 2), taken_at=datetime(2016, 6, 6, 6, 6)), "good.jpg")
    original_apply = image_metadata_service.apply_server_analysis

    def apply_with_invalid_direction(target, metadata, **kwargs):
        outcome = original_apply(target, metadata, **kwargs)
        if target.original_name == "bad.jpg":
            target.gps_latitude, target.gps_longitude, target.gps_direction_deg = 1.0, 1.0, 360.0
        return outcome

    monkeypatch.setattr(image_metadata_service, "apply_server_analysis", apply_with_invalid_direction)
    report = run_backfill(db, tenant_id=tenant.id)
    assert report.checked == 2 and report.failed == 1 and report.taken_at_added == 1
    assert report.errors and report.errors[0].startswith(f"{bad.id}:")
    db.refresh(bad)
    db.refresh(good)
    assert good.exif_taken_at == datetime(2016, 6, 6, 6, 6, tzinfo=UTC)
    assert bad.metadata_scan_status == "unreadable" and bad.gps_direction_deg is None and bad.exif_taken_at is None
    assert run_backfill(db, tenant_id=tenant.id).checked == 0
