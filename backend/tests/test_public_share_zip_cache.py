"""Concurrency-Audit CONC-009: öffentliche Album-ZIPs - gleiche Auswahl wird wiederverwendet,
höchstens wenige Builds gleichzeitig, Platzprüfung vor dem Bau."""
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.routes import public_share
from app.services.photo_metadata_privacy import MetadataPolicy

POLICY = MetadataPolicy(location=False, capture_date=True, camera=True)


def _files(count=2):
    return [
        SimpleNamespace(id=i, public_id=uuid.uuid4(), checksum_sha256=f"c{i}", updated_at="t", original_name=f"bild{i}.jpg",
                        storage_path=f"k{i}", file_size_bytes=10, mime_type="image/jpeg")
        for i in range(count)
    ]


@pytest.fixture
def share_env(monkeypatch, tmp_path):
    monkeypatch.setattr(public_share.settings, "upload_root", str(tmp_path))
    built = []
    monkeypatch.setattr(public_share, "get_object_store", lambda: SimpleNamespace(exists=lambda ns, key: True))
    monkeypatch.setattr(public_share, "_needs_sanitizing", lambda policy, stored_file: False)

    def write(archive, namespace, key, name):
        built.append(key)
        archive.writestr(name, b"x")

    monkeypatch.setattr(public_share, "write_object_to_zip", write)
    return built


def test_same_selection_is_built_once(share_env):
    link = SimpleNamespace(id=1, name="Lager", updated_at="u")
    files = _files()
    policies = {f.id: POLICY for f in files}
    first = public_share._cached_share_zip(link, files, policies)
    second = public_share._cached_share_zip(link, files, policies)
    assert first == second and first.exists()
    assert len(share_env) == 2  # nur ein Build für beide Anfragen


def test_changed_policy_builds_a_new_zip(share_env):
    link = SimpleNamespace(id=1, name="Lager", updated_at="u")
    files = _files(1)
    a = public_share._cached_share_zip(link, files, {files[0].id: POLICY})
    b = public_share._cached_share_zip(link, files, {files[0].id: MetadataPolicy(location=True, capture_date=True, camera=True)})
    assert a != b


def test_busy_slots_answer_503(share_env, monkeypatch):
    monkeypatch.setattr(public_share, "_SHARE_ZIP_SLOT_WAIT_SECONDS", 0.05)
    held = [public_share._SHARE_ZIP_SLOTS.acquire(blocking=False) for _ in range(2)]
    try:
        with pytest.raises(HTTPException) as excinfo:
            public_share._cached_share_zip(SimpleNamespace(id=2, name="X", updated_at="u"), _files(1), {0: POLICY})
        assert excinfo.value.status_code == 503
    finally:
        for ok in held:
            if ok:
                public_share._SHARE_ZIP_SLOTS.release()


def test_insufficient_space_answers_507(share_env, monkeypatch):
    monkeypatch.setattr(public_share.shutil, "disk_usage", lambda path: SimpleNamespace(free=0))
    with pytest.raises(HTTPException) as excinfo:
        public_share._cached_share_zip(SimpleNamespace(id=3, name="Y", updated_at="u"), _files(1), {0: POLICY})
    assert excinfo.value.status_code == 507


def test_submission_zip_is_built_on_disk_not_in_memory(monkeypatch, tmp_path, db):
    """CONC-009: der Abgaben-Download baute das ganze ZIP als BytesIO im Backend-Prozess."""
    import zipfile as zipmod

    from fastapi.responses import FileResponse

    from app.api.routes import submission_assignments as routes
    from tests.factories import make_current_user

    monkeypatch.setattr(routes.settings, "upload_root", str(tmp_path))
    monkeypatch.setattr(routes, "_get_assignment_or_404", lambda db, assignment_id, user: SimpleNamespace(id=1, title="Sommerlager Fotos"))
    monkeypatch.setattr(routes.service, "get_assignment_elements", lambda db, assignment: [])
    response = routes.download_all_files_zip(uuid.uuid4(), db=db, user=make_current_user(1, role="admin"))
    assert isinstance(response, FileResponse)
    assert str(response.path).startswith(str(tmp_path))
    with zipmod.ZipFile(response.path) as archive:
        assert archive.namelist() == []


def test_partial_selections_are_not_cached(share_env):
    link = SimpleNamespace(id=4, name="Teil")
    files = _files(1)
    first = public_share._cached_share_zip(link, files, {0: POLICY}, cache=False)
    second = public_share._cached_share_zip(link, files, {0: POLICY}, cache=False)
    assert first != second
    assert len(share_env) == 2


def test_changed_estimated_date_builds_a_new_zip(share_env):
    link = SimpleNamespace(id=5, name="Datum")
    files = _files(1)
    a = public_share._cached_share_zip(link, files, {0: POLICY})
    files[0].estimated_taken_on = "2026-07-01"
    b = public_share._cached_share_zip(link, files, {0: POLICY})
    assert a != b
