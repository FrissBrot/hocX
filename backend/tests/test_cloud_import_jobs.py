"""Datei-Import: Aufträge, Quellen (ZIP/Takeout, Ordner), Vorschau, Start, Worker, Rechte, Grenzen,
Mandantentrennung (routes/cloud_import.py, services/cloud_import/jobs.py, worker.py)."""

import asyncio
import io
import uuid
import zipfile
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, UploadFile
from PIL import Image
from sqlalchemy import func, select
from starlette.datastructures import Headers

from app.api.routes import cloud_import as routes
from app.core.config import settings
from app.models.entities import PhotoAlbum, PhotoAlbumItem, StoredFile
from app.models.import_entities import ImportItem, ImportJob
from app.services.cloud_import import jobs, paths, worker
from tests.factories import make_app_user, make_current_user, make_tenant
from tests.test_tenant_rls import as_app


@pytest.fixture(autouse=True)
def _isolated_storage(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "storage_root", str(tmp_path))
    monkeypatch.setattr(settings, "upload_root", str(tmp_path / "uploads"))
    monkeypatch.setattr(settings, "thumbnail_root", str(tmp_path / "thumbnails"))


@pytest.fixture(autouse=True)
def _ample_disk(monkeypatch):
    """Plattenreserve unabhängig vom Füllstand des Test-Hosts (eigener Test unten)."""
    monkeypatch.setattr(jobs.shutil, "disk_usage", lambda _path: SimpleNamespace(total=100 * 1024**3, used=0, free=100 * 1024**3))


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch):
    monkeypatch.setattr(routes, "enforce_rate_limit", lambda *args, **kwargs: None)


def _png(color=(10, 20, 30), size=(40, 30)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color=color).save(buffer, format="PNG")
    return buffer.getvalue()


def _pdf(text: str = "x") -> bytes:
    return b"%PDF-1.4\n% " + text.encode() + b"\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def _zip(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def _upload(content: bytes, name: str) -> UploadFile:
    return UploadFile(file=io.BytesIO(content), filename=name, size=len(content), headers=Headers({"content-type": "application/octet-stream"}))


def _admin(db, tenant):
    account = make_app_user(db, f"{uuid.uuid4().hex[:12]}@example.com", tenant_id=tenant.id, role_code="admin")
    return make_current_user(tenant.id, role="admin", user_id=account.id)


def _create(db, user, source="zip", **kwargs):
    return routes.create_import_job(routes.ImportJobCreate(source=source, **kwargs), db=db, user=user)


def _add_zip(db, user, job_id, entries, name="export.zip"):
    return asyncio.run(routes._upload_archive_impl(job_id=job_id, file=_upload(_zip(entries), name), db=db, user=user))


def _preview(db, user, job_id, rules=(), **kwargs):
    payload = routes.PreviewRequest(rules=[routes.RuleIn.model_validate(rule) for rule in rules], **kwargs)
    return routes.preview_import_job(job_id, payload, db=db, user=user)


def _run_worker(db, rounds=5):
    for _ in range(rounds):
        worker.process_pending(db)


def _items(db, job_id):
    return {item.path: item for item in db.scalars(select(ImportItem).where(ImportItem.job_id == job_id))}


# --- Rechte, Mandantentrennung ----------------------------------------------------------------


def test_only_files_import_may_use_the_importer(db):
    tenant = make_tenant(db)
    writer = make_current_user(tenant.id, role="writer")
    with pytest.raises(HTTPException) as exc:
        _create(db, writer)
    assert exc.value.status_code == 403
    with pytest.raises(HTTPException) as exc:
        routes.list_import_jobs(db=db, user=writer)
    assert exc.value.status_code == 403


def test_foreign_tenant_job_is_not_found(db):
    tenant, other = make_tenant(db, "A"), make_tenant(db, "B")
    owner = _admin(db, tenant)
    job = _create(db, owner)
    stranger = _admin(db, other)
    for call in (
        lambda: routes.get_import_job(job.id, db=db, user=stranger),
        lambda: routes.cancel_import_job(job.id, db=db, user=stranger),
        lambda: routes.list_import_items(job.id, item_status=None, offset=0, limit=10, db=db, user=stranger),
        lambda: _preview(db, stranger, job.id),
    ):
        with pytest.raises(HTTPException) as exc:
            call()
        assert exc.value.status_code == 404
    unknown = uuid.uuid4()
    with pytest.raises(HTTPException) as exc:
        routes.get_import_job(unknown, db=db, user=owner)
    assert exc.value.status_code == 404


def test_other_admin_sees_but_cannot_change_a_job(db):
    tenant = make_tenant(db)
    owner, colleague = _admin(db, tenant), _admin(db, tenant)
    job = _create(db, owner)
    assert routes.get_import_job(job.id, db=db, user=colleague).is_owner is False
    with pytest.raises(HTTPException) as exc:
        _add_zip(db, colleague, job.id, {"a.png": _png()})
    assert exc.value.status_code == 403
    # Abbrechen darf jede Person mit files.import (Transparenz)
    assert routes.cancel_import_job(job.id, db=db, user=colleague).status == "cancelled"


def test_one_import_per_tenant_at_a_time(db):
    tenant, other = make_tenant(db, "A"), make_tenant(db, "B")
    owner = _admin(db, tenant)
    _create(db, owner)
    with pytest.raises(HTTPException) as exc:
        _create(db, _admin(db, tenant), source="folder")
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "import_active"
    _create(db, _admin(db, other))  # anderer Verein unabhängig


def test_rls_hides_import_rows_of_other_tenants(db):
    tenant, other = make_tenant(db, "A"), make_tenant(db, "B")
    owner = _admin(db, tenant)
    job = _create(db, owner)
    _add_zip(db, owner, job.id, {"a.png": _png()})
    with as_app(db, other.id):
        assert db.scalar(select(func.count()).select_from(ImportJob)) == 0
        assert db.scalar(select(func.count()).select_from(ImportItem)) == 0
    with as_app(db, tenant.id):
        assert db.scalar(select(func.count()).select_from(ImportItem)) == 1


def test_import_item_must_belong_to_the_tenant_of_its_job(db):
    """Security-Review 1.6, F-2: zusammengesetzter Fremdschlüssel (tenant_id, job_id)."""
    from sqlalchemy.exc import IntegrityError

    tenant, other = make_tenant(db, "A"), make_tenant(db, "B")
    job = _create(db, _admin(db, tenant))
    savepoint = db.begin_nested()
    db.add(ImportItem(tenant_id=other.id, job_id=job.id, path="x.png", kind="image"))
    with pytest.raises(IntegrityError):
        db.flush()
    savepoint.rollback()


# --- ZIP-Quelle -------------------------------------------------------------------------------


def test_zip_listing_normalizes_names_and_never_uses_them_as_paths(db, tmp_path):
    tenant = make_tenant(db)
    owner = _admin(db, tenant)
    job = _create(db, owner)
    read = _add_zip(
        db, owner, job.id,
        {
            "../../evil/../x.png": _png(),
            "Ordner\\Unter\\b.pdf": _pdf(),
            "__MACOSX/._b.pdf": b"junk",
            "c.exe": b"MZ",
        },
    )
    assert read.total_items == 3
    items = _items(db, job.id)
    assert set(items) == {"evil/x.png", "Ordner/Unter/b.pdf", "c.exe"}
    assert items["c.exe"].listing_code == "unsupported_format"
    # Nichts ausserhalb des Staging-Verzeichnisses entstanden
    assert not (tmp_path / "evil").exists()
    staged = list(jobs.staging_dir(job.id).iterdir())
    assert len(staged) == 1 and staged[0].suffix == ".zip"


def test_takeout_prefix_is_stripped_and_sidecars_skipped(db):
    tenant = make_tenant(db)
    owner = _admin(db, tenant)
    job = _create(db, owner)
    _add_zip(
        db, owner, job.id,
        {
            "Takeout/Google Fotos/Lager 2019/a.png": _png(),
            "Takeout/Google Fotos/Lager 2019/a.png.supplemental-metadata.json": b"{}",
            "Takeout/archive_browser.html": b"<html>",
        },
        name="takeout-001.zip",
    )
    items = _items(db, job.id)
    assert set(items) == {"Google Fotos/Lager 2019/a.png", "Google Fotos/Lager 2019/a.png.supplemental-metadata.json", "archive_browser.html"}
    assert items["archive_browser.html"].listing_code == "takeout_metadata"
    assert routes.get_import_job(job.id, db=db, user=owner).takeout is True


def test_job_limits_on_files_and_bytes(db, monkeypatch):
    tenant = make_tenant(db)
    owner = _admin(db, tenant)
    job = _create(db, owner)
    monkeypatch.setattr(settings, "cloud_import_max_job_files", 2)
    with pytest.raises(HTTPException) as exc:
        _add_zip(db, owner, job.id, {"a.png": _png(), "b.png": _png(), "c.png": _png()})
    assert exc.value.status_code == 413 and exc.value.detail["code"] == "too_many_files"
    assert list(jobs.staging_dir(job.id).iterdir()) == []  # abgelehntes Archiv sofort weg
    monkeypatch.setattr(settings, "cloud_import_max_job_files", 50_000)
    monkeypatch.setattr(settings, "cloud_import_max_job_bytes", 100)
    with pytest.raises(HTTPException) as exc:
        _add_zip(db, owner, job.id, {"a.png": _png()})
    assert exc.value.detail["code"] == "too_many_bytes"


def test_invalid_zip_is_rejected(db):
    tenant = make_tenant(db)
    owner = _admin(db, tenant)
    job = _create(db, owner)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(routes._upload_archive_impl(job_id=job.id, file=_upload(b"not a zip", "x.zip"), db=db, user=owner))
    assert exc.value.detail["code"] == "zip_invalid"


# --- Vorschau, Start, Worker ------------------------------------------------------------------


def _zip_job(db, owner, entries):
    job = _create(db, owner)
    _add_zip(db, owner, job.id, entries)
    routes.finish_import_listing(job.id, db=db, user=owner)
    return job


def test_preview_counts_rules_and_saves_valid_settings(db):
    tenant = make_tenant(db)
    owner = _admin(db, tenant)
    job = _zip_job(db, owner, {"Lager/a.png": _png((1, 2, 3)), "Lager/b.pdf": _pdf(), "tmp/c.png": _png((9, 9, 9))})
    rules = [
        {"id": "tags", "match": {"folder": "Lager"}, "action": {"type": "add_tags", "tags": ["Lager"]}},
        {"id": "skip", "match": {"folder": "tmp"}, "action": {"type": "skip"}},
    ]
    preview = _preview(db, owner, job.id, rules)
    assert preview.saved is True
    assert preview.summary.importable == 2
    assert preview.summary.skipped == {"excluded_by_rule": 1}
    assert preview.summary.per_rule == {"tags": 2, "skip": 1}
    assert preview.folders == ["Lager", "tmp"]
    stored = routes.get_import_job(job.id, db=db, user=owner)
    assert [rule["id"] for rule in stored.rules] == ["tags", "skip"]

    # Ungültige Regel: Fehler zurück, nichts gespeichert
    bad = _preview(db, owner, job.id, [{"id": "r", "match": {"name_regex": r"(a)\1"}, "action": {"type": "skip"}}])
    assert bad.saved is False and bad.errors[0].code == "regex_unsupported"
    assert [rule["id"] for rule in routes.get_import_job(job.id, db=db, user=owner).rules] == ["tags", "skip"]

    filtered = _preview(db, owner, job.id, rules, view="skipped")
    assert [item.path for item in filtered.items] == ["tmp/c.png"]
    assert filtered.items[0].reason == "excluded_by_rule"


def test_full_zip_import_with_tags_date_albums_and_duplicates(db):
    tenant = make_tenant(db)
    owner = _admin(db, tenant)
    job = _zip_job(
        db, owner,
        {
            "Lager 2019/a.png": _png((200, 10, 10)),
            "Lager 2019/b.pdf": _pdf("b"),
            "Kopie/a.png": _png((200, 10, 10)),  # exaktes Duplikat innerhalb des Imports
            "tmp/skip.png": _png((5, 5, 5)),
        },
    )
    rules = [
        {"id": "tag", "match": {"folder": "Lager 2019"}, "action": {"type": "add_tags", "tags": ["Lager"]}},
        {"id": "date", "match": {"path_glob": "*.png"}, "action": {"type": "set_date", "date": "2019-07-15"}},
        {"id": "album", "match": {}, "action": {"type": "folder_to_album"}},
        {"id": "skip", "match": {"folder": "tmp"}, "action": {"type": "skip"}},
    ]
    assert _preview(db, owner, job.id, rules, albums_enabled=True).saved
    started = routes.start_import_job(job.id, db=db, user=owner)
    assert started.status == "queued"

    _run_worker(db)

    final = routes.get_import_job(job.id, db=db, user=owner)
    assert final.status == "done"
    items = _items(db, job.id)
    assert items["tmp/skip.png"].status == "skipped" and items["tmp/skip.png"].result_code == "excluded_by_rule"
    image = items["Lager 2019/a.png"]
    assert image.status == "imported"
    stored = db.get(StoredFile, image.stored_file_id)
    assert stored.tags == ["Lager"]
    assert stored.estimated_taken_on.isoformat() == "2019-07-15"  # PNG ohne EXIF: Schätzdatum greift
    assert stored.original_name == "a.png"
    document = db.get(StoredFile, items["Lager 2019/b.pdf"].stored_file_id)
    assert document.tags == ["Lager"] and document.estimated_taken_on is None
    assert items["Kopie/a.png"].status == "duplicate"
    album = db.scalar(select(PhotoAlbum).where(PhotoAlbum.tenant_id == tenant.id, PhotoAlbum.name == "Lager 2019"))
    assert album is not None and album.kind == "manual"
    assert db.scalar(select(PhotoAlbumItem).where(PhotoAlbumItem.album_id == album.id, PhotoAlbumItem.file_id == stored.public_id))
    assert final.counts == {"imported": 2, "duplicate": 1, "skipped": 1}

    report = routes.list_import_items(job.id, item_status="imported", offset=0, limit=50, db=db, user=owner)
    assert {item.path for item in report.items} == {"Lager 2019/a.png", "Lager 2019/b.pdf"}
    assert all(item.file_id is not None for item in report.items)
    # Archiv nach Abschluss weg
    assert not jobs.staging_dir(job.id).exists()


def test_start_needs_area_permissions_and_valid_quota(db):
    tenant = make_tenant(db)
    owner = _admin(db, tenant)
    importer_without_photos = make_current_user(tenant.id, user_id=owner.user_id, permissions=frozenset({"files.import", "files.manage", "files.read"}))
    job = _zip_job(db, owner, {"a.png": _png()})
    with pytest.raises(HTTPException) as exc:
        routes.start_import_job(job.id, db=db, user=importer_without_photos)
    assert exc.value.status_code == 403
    tenant.storage_quota_bytes = 10
    db.flush()
    with pytest.raises(HTTPException) as exc:
        routes.start_import_job(job.id, db=db, user=owner)
    assert exc.value.detail["code"] == "quota_exceeded"


def test_stream_is_capped_even_when_the_zip_lies_about_sizes(db, monkeypatch):
    """Zip-Bomb-Schutz: gelesen wird höchstens Limit+1 Byte, unabhängig von der Angabe im ZIP."""
    tenant = make_tenant(db)
    owner = _admin(db, tenant)
    job = _zip_job(db, owner, {"big.pdf": _pdf("y" * 5000)})
    routes.start_import_job(job.id, db=db, user=owner)
    monkeypatch.setitem(paths.MAX_BYTES_BY_KIND, paths.KIND_DOCUMENT, 1000)
    _run_worker(db)
    item = _items(db, job.id)["big.pdf"]
    assert item.status == "failed" and item.result_code == "too_large"


def test_declared_oversize_entries_are_reported_without_extracting(db):
    tenant = make_tenant(db)
    owner = _admin(db, tenant)
    job = _create(db, owner)
    _add_zip(db, owner, job.id, {"huge.pdf": b"\0" * (21 * 1024 * 1024)})
    assert _items(db, job.id)["huge.pdf"].listing_code == "too_large"


def test_cancel_running_job_keeps_imported_files(db):
    tenant = make_tenant(db)
    owner = _admin(db, tenant)
    job = _zip_job(db, owner, {"a.png": _png((1, 1, 1)), "b.png": _png((2, 2, 2))})
    routes.start_import_job(job.id, db=db, user=owner)
    assert routes.cancel_import_job(job.id, db=db, user=owner).status == "cancel_requested"
    _run_worker(db)
    final = routes.get_import_job(job.id, db=db, user=owner)
    assert final.status == "cancelled"
    assert set(final.counts) == {"cancelled"}
    # danach ist ein neuer Import möglich
    _create(db, owner)


# --- Ordner-Quelle ----------------------------------------------------------------------------


def test_folder_import_uploads_only_needed_files(db):
    tenant = make_tenant(db)
    owner = _admin(db, tenant)
    job = _create(db, owner, source="folder", type_filter="images")
    a, b = _png((3, 3, 3)), _png((4, 4, 4))
    routes.add_import_manifest(
        job.id,
        routes.ManifestRequest(entries=[
            {"path": "Verein/a.png", "size": len(a)},
            {"path": "Verein/b.png", "size": len(b)},
            {"path": "Verein/doc.pdf", "size": 10},
            {"path": "Verein/.DS_Store", "size": 10},
        ]),
        db=db, user=owner,
    )
    routes.finish_import_listing(job.id, db=db, user=owner)
    preview = _preview(db, owner, job.id, [{"id": "s", "match": {"name_regex": "^b"}, "action": {"type": "skip"}}], type_filter="images")
    assert preview.summary.importable == 1
    assert preview.summary.skipped == {"type_filtered": 1, "excluded_by_rule": 1}
    routes.start_import_job(job.id, db=db, user=owner)

    pending = routes.list_pending_uploads(job.id, offset=0, limit=100, db=db, user=owner)
    assert [item.path for item in pending.items] == ["Verein/a.png"]

    result = asyncio.run(routes._upload_files_impl(
        job_id=job.id, files=[_upload(a, "a.png"), _upload(b, "b.png")], paths_json='["Verein/a.png", "Verein/b.png"]', db=db, user=owner,
    ))
    assert result.staged == 1 and result.rejected == {"Verein/b.png": "not_expected"}
    _run_worker(db)
    final = routes.get_import_job(job.id, db=db, user=owner)
    assert final.status == "done"
    assert final.counts == {"imported": 1, "skipped": 2}
    assert routes.list_pending_uploads(job.id, offset=0, limit=100, db=db, user=owner).total == 0


def test_folder_job_waits_for_uploads_and_rejects_bad_requests(db):
    tenant = make_tenant(db)
    owner = _admin(db, tenant)
    job = _create(db, owner, source="folder")
    routes.add_import_manifest(job.id, routes.ManifestRequest(entries=[{"path": "x/a.pdf", "size": 100}]), db=db, user=owner)
    routes.finish_import_listing(job.id, db=db, user=owner)
    routes.start_import_job(job.id, db=db, user=owner)
    _run_worker(db)
    assert routes.get_import_job(job.id, db=db, user=owner).status == "running"  # wartet auf den Browser
    with pytest.raises(HTTPException) as exc:
        asyncio.run(routes._upload_files_impl(job_id=job.id, files=[_upload(b"x", "a.pdf")], paths_json='["a", "b"]', db=db, user=owner))
    assert exc.value.detail["code"] == "invalid_paths"
    big = asyncio.run(routes._upload_files_impl(
        job_id=job.id, files=[_upload(b"%PDF" + b"0" * (21 * 1024 * 1024), "a.pdf")], paths_json='["x/a.pdf"]', db=db, user=owner,
    ))
    assert big.rejected == {"x/a.pdf": "too_large"}
    assert _items(db, job.id)["x/a.pdf"].status == "failed"


def test_infected_file_is_reported_and_not_stored(db, monkeypatch):
    from app.services import file_service as file_service_module

    async def infected(contents, host, port):
        return ["infected" for _ in contents]

    monkeypatch.setattr(file_service_module.scanner, "scan_many", infected)
    tenant = make_tenant(db)
    owner = _admin(db, tenant)
    job = _zip_job(db, owner, {"virus.pdf": _pdf("eicar")})
    routes.start_import_job(job.id, db=db, user=owner)
    _run_worker(db)
    item = _items(db, job.id)["virus.pdf"]
    assert item.status == "failed" and item.result_code == "infected" and item.stored_file_id is None


def test_report_retention_follows_imported_files(db):
    from datetime import UTC, datetime, timedelta

    tenant = make_tenant(db)
    owner = _admin(db, tenant)
    job = _zip_job(db, owner, {"a.pdf": _pdf("keep")})
    routes.start_import_job(job.id, db=db, user=owner)
    _run_worker(db)
    row = db.get(ImportJob, job.id)
    row.finished_at = datetime.now(UTC) - timedelta(days=30)
    db.commit()
    worker.cleanup(db)
    assert db.get(ImportJob, job.id) is not None  # importierte Datei existiert noch
    item = _items(db, job.id)["a.pdf"]
    item.stored_file_id = None  # wie nach dem endgültigen Löschen (FK SET NULL)
    db.commit()
    worker.cleanup(db)
    db.expire_all()
    assert db.get(ImportJob, job.id) is None


# --- Security-Review-Folgen -------------------------------------------------------------------


def test_zip_directory_is_checked_before_parsing(db, monkeypatch, tmp_path):
    """Speicher-DoS: zu viele Einträge werden am End-Satz erkannt, bevor zipfile alles einliest."""
    archive = tmp_path / "many.zip"
    archive.write_bytes(_zip({f"f{i}.txt": b"x" for i in range(10)}))
    monkeypatch.setattr(settings, "cloud_import_max_job_files", 3)
    with pytest.raises(jobs.ImportFailure) as exc:
        jobs.check_zip_directory(archive)
    assert exc.value.code == "too_many_files"
    broken = tmp_path / "broken.zip"
    broken.write_bytes(b"PK\x03\x04 kein Ende")
    with pytest.raises(jobs.ImportFailure) as exc:
        jobs.check_zip_directory(broken)
    assert exc.value.code == "zip_invalid"


def test_upload_precheck_rejects_wrong_status_and_quota(db):
    tenant = make_tenant(db)
    owner = _admin(db, tenant)
    job = db.get(ImportJob, _create(db, owner).id)
    jobs.check_upload_allowed(db, job, kind="archive", content_length=1000)
    with pytest.raises(jobs.ImportFailure) as exc:
        jobs.check_upload_allowed(db, job, kind="files", content_length=1000)
    assert exc.value.code == "invalid_status"
    tenant.storage_quota_bytes = 1
    db.flush()
    with pytest.raises(jobs.ImportFailure) as exc:
        jobs.check_upload_allowed(db, job, kind="archive", content_length=500 * 1024**2)
    assert exc.value.code == "quota_exceeded"


def test_archive_after_staging_counts_earlier_archives_against_quota(db, monkeypatch):
    """Security-Review 1.6, F-1: ohne Content-Length prüft erst add_archive - und zwar die Summe
    aller gestagten Archive des Auftrags, nicht nur das neue."""
    tenant = make_tenant(db)
    owner = _admin(db, tenant)
    job = _create(db, owner)
    _add_zip(db, owner, job.id, {"a.txt": b"x" * 2000}, name="teil-1.zip")
    first = db.get(ImportJob, job.id)
    staged_first = sum(int(archive["size"]) for archive in first.archives)
    monkeypatch.setattr(jobs, "STAGING_QUOTA_TOLERANCE", 0)
    tenant.storage_quota_bytes = staged_first + 50
    db.flush()
    with pytest.raises(HTTPException) as exc:
        _add_zip(db, owner, job.id, {"b.txt": b"y" * 2000}, name="teil-2.zip")
    assert exc.value.detail["code"] == "quota_exceeded"
    assert len(db.get(ImportJob, job.id).archives) == 1


def test_archive_is_rejected_when_the_disk_reserve_would_be_used(db, monkeypatch):
    """Plattenreserve auch nach dem Empfang (F-1): ein Archiv ohne Content-Length darf die
    letzten 10 % des Datenträgers nicht belegen."""
    tenant = make_tenant(db)
    owner = _admin(db, tenant)
    job = _create(db, owner)
    monkeypatch.setattr(jobs.shutil, "disk_usage", lambda _path: SimpleNamespace(total=1000, used=950, free=50))
    with pytest.raises(HTTPException) as exc:
        _add_zip(db, owner, job.id, {"a.txt": b"x"})
    assert exc.value.status_code == 507
    assert db.get(ImportJob, job.id).archives == []


def test_import_stops_when_the_requester_lost_the_permission(db):
    from app.models import AppUser

    tenant = make_tenant(db)
    owner = _admin(db, tenant)
    job = _zip_job(db, owner, {"a.pdf": _pdf("perm")})
    routes.start_import_job(job.id, db=db, user=owner)
    db.get(AppUser, owner.user_id).is_active = False
    db.commit()
    _run_worker(db)
    final = routes.get_import_job(job.id, db=db, user=owner)
    assert final.status == "failed" and final.error == "requester_unauthorized"
    assert final.counts == {"queued": 1}


def test_statistics_are_refreshed_after_large_imports_and_at_the_end(db, monkeypatch):
    """Hinweis aus fix/search-perf-1.5.1: nach Massenimport ANALYZE (alle N Dateien und am Ende)."""
    calls: list[int] = []
    original = worker.analyze_upload_tables
    monkeypatch.setattr(worker, "analyze_upload_tables", lambda session: (calls.append(1), original(session)))
    monkeypatch.setattr(worker, "ANALYZE_EVERY_FILES", 2)
    tenant = make_tenant(db)
    owner = _admin(db, tenant)
    job = _zip_job(db, owner, {f"d{i}.pdf": _pdf(f"stat{i}") for i in range(3)})
    routes.start_import_job(job.id, db=db, user=owner)
    _run_worker(db)
    assert routes.get_import_job(job.id, db=db, user=owner).status == "done"
    assert len(calls) == 2  # einmal nach 2 Dateien (gleicher Batch: 3 ≥ 2), einmal am Ende


def test_analyze_function_runs_as_app_role(db):
    from sqlalchemy import text

    with as_app(db, None):
        db.execute(text("SELECT public.hocx_analyze_upload_tables()"))



# --- Entscheide 2026-11-22: Alben optional, Wiederverwendung, Duplikate ergänzen, Takeout-Datum ----


def test_album_rules_are_off_by_default(db):
    tenant = make_tenant(db)
    owner = _admin(db, tenant)
    job = _zip_job(db, owner, {"Lager/a.png": _png((31, 2, 3))})
    rules = [{"id": "album", "match": {}, "action": {"type": "folder_to_album"}}]
    preview = _preview(db, owner, job.id, rules)
    assert preview.items[0].albums == [] and preview.summary.per_rule == {}
    routes.start_import_job(job.id, db=db, user=owner)
    _run_worker(db)
    assert db.scalar(select(func.count()).select_from(PhotoAlbum).where(PhotoAlbum.tenant_id == tenant.id)) == 0
    assert _items(db, job.id)["Lager/a.png"].status == "imported"


def test_existing_album_with_the_same_name_is_reused_oldest_first(db):
    from datetime import UTC, datetime, timedelta

    tenant, other = make_tenant(db, "A"), make_tenant(db, "B")
    owner = _admin(db, tenant)
    old = PhotoAlbum(tenant_id=tenant.id, name="Lager", kind="manual", created_at=datetime.now(UTC) - timedelta(days=9))
    newer = PhotoAlbum(tenant_id=tenant.id, name="Lager", kind="manual")
    foreign = PhotoAlbum(tenant_id=other.id, name="Lager", kind="manual")
    db.add_all([old, newer, foreign])
    db.commit()
    job = _zip_job(db, owner, {"Lager/a.png": _png((41, 2, 3))})
    rules = [{"id": "album", "match": {}, "action": {"type": "folder_to_album"}}]
    preview = _preview(db, owner, job.id, rules, albums_enabled=True)
    assert preview.existing_albums == ["Lager"]
    routes.start_import_job(job.id, db=db, user=owner)
    _run_worker(db)
    stored = db.get(StoredFile, _items(db, job.id)["Lager/a.png"].stored_file_id)
    in_albums = set(db.scalars(select(PhotoAlbumItem.album_id).where(PhotoAlbumItem.file_id == stored.public_id)))
    assert in_albums == {old.id}
    assert db.scalar(select(func.count()).select_from(PhotoAlbum).where(PhotoAlbum.tenant_id == tenant.id)) == 2
    report = routes.get_import_job(job.id, db=db, user=owner)
    assert [(a.name, a.reused, a.candidates) for a in report.albums] == [("Lager", True, 2)]


def test_duplicates_get_tags_and_albums_added_never_removed(db):
    from app.services.file_service import FileService

    tenant = make_tenant(db)
    owner = _admin(db, tenant)
    content = _png((51, 2, 3))
    items, _errors = asyncio.run(FileService().save_gallery_uploads(db, tenant_id=tenant.id, files=[("alt.png", content)], tags=["Alt"], created_by=owner.user_id))
    existing = db.scalar(select(StoredFile).where(StoredFile.public_id == items[0].id))
    job = _zip_job(db, owner, {"Lager/neu.png": content})
    rules = [
        {"id": "tag", "match": {}, "action": {"type": "add_tags", "tags": ["Lager"]}},
        {"id": "album", "match": {}, "action": {"type": "folder_to_album"}},
    ]
    _preview(db, owner, job.id, rules, albums_enabled=True)
    routes.start_import_job(job.id, db=db, user=owner)
    _run_worker(db)
    item = _items(db, job.id)["Lager/neu.png"]
    assert item.status == "duplicate" and item.result_code == "duplicate_enriched"
    assert item.existing_file_id == existing.id and item.stored_file_id is None
    db.refresh(existing)
    assert existing.tags == ["Alt", "Lager"]
    album = db.scalar(select(PhotoAlbum).where(PhotoAlbum.tenant_id == tenant.id, PhotoAlbum.name == "Lager"))
    assert db.scalar(select(PhotoAlbumItem).where(PhotoAlbumItem.album_id == album.id, PhotoAlbumItem.file_id == existing.public_id))
    report = routes.list_import_items(job.id, item_status="duplicate", offset=0, limit=10, db=db, user=owner)
    assert report.items[0].result_code == "duplicate_enriched" and report.items[0].file_id == existing.public_id


def test_takeout_metadata_date_fills_only_missing_capture_dates(db):
    import json as jsonlib
    from datetime import date, datetime

    tenant = make_tenant(db)
    owner = _admin(db, tenant)
    stamp = int(datetime(2018, 6, 3, 12).timestamp())
    meta = jsonlib.dumps({"photoTakenTime": {"timestamp": str(stamp)}}).encode()
    buffer = io.BytesIO()
    exif_image = Image.new("RGB", (30, 20), color=(9, 9, 9))
    exif = Image.Exif()
    exif[306] = "2015:01:02 10:00:00"
    exif_image.save(buffer, format="JPEG", exif=exif)
    job = _create(db, owner)
    _add_zip(
        db, owner, job.id,
        {
            "Takeout/Google Fotos/Lager/ohne.png": _png((61, 2, 3)),
            "Takeout/Google Fotos/Lager/ohne.png.supplemental-metadata.json": meta,
            "Takeout/Google Fotos/Lager/mit-exif.jpg": buffer.getvalue(),
            "Takeout/Google Fotos/Lager/mit-exif.jpg.json": meta,
            "Takeout/Google Fotos/Lager/kaputt.png": _png((62, 2, 3)),
            "Takeout/Google Fotos/Lager/kaputt.png.json": b"{nicht json",
        },
        name="takeout.zip",
    )
    items = _items(db, job.id)
    assert items["Google Fotos/Lager/ohne.png"].hint_date == date(2018, 6, 3)
    assert items["Google Fotos/Lager/kaputt.png"].hint_date is None
    routes.finish_import_listing(job.id, db=db, user=owner)
    rules = [{"id": "d", "match": {}, "action": {"type": "set_date", "date": "2020-01-01"}}]
    preview = _preview(db, owner, job.id, rules)
    by_path = {item.path: item for item in preview.items}
    assert (by_path["Google Fotos/Lager/ohne.png"].date, by_path["Google Fotos/Lager/ohne.png"].date_source) == (date(2018, 6, 3), "takeout")
    assert (by_path["Google Fotos/Lager/kaputt.png"].date, by_path["Google Fotos/Lager/kaputt.png"].date_source) == (date(2020, 1, 1), "rule")
    routes.start_import_job(job.id, db=db, user=owner)
    _run_worker(db)
    items = _items(db, job.id)
    without = db.get(StoredFile, items["Google Fotos/Lager/ohne.png"].stored_file_id)
    assert without.estimated_taken_on == date(2018, 6, 3)
    with_exif = db.get(StoredFile, items["Google Fotos/Lager/mit-exif.jpg"].stored_file_id)
    assert with_exif.exif_taken_at.date() == date(2015, 1, 2)  # EXIF hat Vorrang (Schätzdatum greift nicht)
    assert with_exif.estimated_taken_on is None


def test_duplicates_are_not_enriched_without_write_access(db, monkeypatch):
    """Security-Review M1: dieselbe Schreibprüfung wie bulk-tags (z. B. Bilder aus nicht lesbaren
    Protokollen) - sonst weder Tags noch Alben."""
    from app.services.access_service import AccessService
    from app.services.file_service import FileService

    tenant = make_tenant(db)
    owner = _admin(db, tenant)
    content = _png((71, 2, 3))
    items, _errors = asyncio.run(FileService().save_gallery_uploads(db, tenant_id=tenant.id, files=[("alt.png", content)], tags=["Alt"], created_by=owner.user_id))
    existing = db.scalar(select(StoredFile).where(StoredFile.public_id == items[0].id))

    def deny(self, db_, user, stored_file_id, *, allow_context_grant=True):
        assert allow_context_grant is False
        raise HTTPException(status_code=404, detail="nicht lesbar")

    monkeypatch.setattr(AccessService, "ensure_can_read_stored_file", deny)
    job = _zip_job(db, owner, {"Lager/neu.png": content})
    _preview(db, owner, job.id, [{"id": "tag", "match": {}, "action": {"type": "add_tags", "tags": ["Lager"]}}])
    routes.start_import_job(job.id, db=db, user=owner)
    _run_worker(db)
    item = _items(db, job.id)["Lager/neu.png"]
    assert item.status == "duplicate" and item.result_code == "duplicate" and item.existing_file_id is None
    db.refresh(existing)
    assert existing.tags == ["Alt"]
