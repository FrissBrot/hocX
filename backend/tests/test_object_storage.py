"""Objektspeicher-Abstraktion: Keys, Dateisystem- und S3-Backend, Schreibprotokoll mit Fence und
Journal, Range-Downloads (docs-site/docs/technik/storage/architektur.md)."""

from __future__ import annotations

import hashlib
import io
import os
import threading
import time
import uuid
from pathlib import Path

import pytest
from botocore.exceptions import ClientError, ConnectTimeoutError
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.config import settings
from app.core.db import SessionLocal, engine
from app.core.objstore_client import (
    FilesystemBackend,
    InvalidObjectKey,
    ObjectNotFound,
    ProfileConfig,
    S3Backend,
    StorageIntegrityError,
    StorageThrottled,
    StorageUnavailable,
    StorageWriteFenced,
    _map_client_error,
    decrypt_credential,
    encrypt_credential,
    new_object_key,
    safe_suffix,
    validate_key,
)
from app.core.storage import MAIN, get_object_store, object_response
from tests.storage_support import requires_s3

# --- Keys -------------------------------------------------------------------------------------


@pytest.mark.parametrize("key", [
    "", "/etc/passwd", "../x", "a/../b", "a//b", "a/./b", "a\\b", "a\x00b", "a\nb", "x" * 1025, "a/", "./a",
])
def test_validate_key_rejects_traversal_and_control_characters(key):
    with pytest.raises(InvalidObjectKey):
        validate_key(key)


@pytest.mark.parametrize("key", ["uploads/tenant-1/gallery/abc.jpg", "quarantine/tenant-2/assignment-3/x.pdf", "a b/ä.png"])
def test_validate_key_accepts_normal_keys(key):
    assert validate_key(key) == key


def test_safe_suffix_never_takes_unsafe_client_input():
    assert safe_suffix("photo.JPG") == ".jpg"
    assert safe_suffix("evil.php%00.jpg") == ".jpg"
    assert safe_suffix("../../x") == ".bin"
    assert safe_suffix("archive.tar gz") == ".bin"
    assert safe_suffix(None) == ".bin"
    key = new_object_key("uploads", "tenant-1", filename="Bild.HEIC")
    assert key.startswith("uploads/tenant-1/") and key.endswith(".heic")


def test_credentials_roundtrip_and_wrong_key_fails_closed():
    token = encrypt_credential("geheim", "k" * 40)
    assert token != "geheim"
    assert decrypt_credential(token, "k" * 40) == "geheim"
    with pytest.raises(Exception):
        decrypt_credential(token, "z" * 40)


# --- Dateisystem-Backend ----------------------------------------------------------------------


def _fs(tmp_path: Path) -> FilesystemBackend:
    return FilesystemBackend(ProfileConfig(profile_id=1, generation=0, provider="filesystem"), {"main": tmp_path / "main", "abgabebox": tmp_path / "box"})


def test_filesystem_backend_writes_atomically_and_verifies_integrity(tmp_path):
    backend = _fs(tmp_path)
    data = b"hallo welt"
    info = backend.put_stream("main", "a/b.txt", io.BytesIO(data), size=len(data), sha256=hashlib.sha256(data).hexdigest(), content_type=None)
    assert info.size == len(data) and (tmp_path / "main" / "a" / "b.txt").read_bytes() == data
    # Falscher Hash: Ziel bleibt unverändert, keine halbe Datei, keine Temp-Reste.
    with pytest.raises(StorageIntegrityError):
        backend.put_stream("main", "a/b.txt", io.BytesIO(b"anders"), size=6, sha256="0" * 64, content_type=None)
    assert (tmp_path / "main" / "a" / "b.txt").read_bytes() == data
    assert not list((tmp_path / "main" / "a").glob(".hocx-upload-*"))


def test_filesystem_backend_range_list_and_traversal_guard(tmp_path):
    backend = _fs(tmp_path)
    backend.put_stream("main", "x/one.bin", io.BytesIO(b"0123456789"), size=10, sha256=hashlib.sha256(b"0123456789").hexdigest(), content_type=None)
    assert b"".join(backend.open_read("main", "x/one.bin", start=2, end=4)) == b"234"
    assert [i.key for i in backend.list("main", "x/")] == ["x/one.bin"]
    with pytest.raises(ObjectNotFound):
        list(backend.open_read("main", "x/missing.bin"))
    with pytest.raises(InvalidObjectKey):
        backend.head("main", "../outside")


# --- Schreibprotokoll -------------------------------------------------------------------------


def test_put_and_delete_are_journaled_with_increasing_versions(db, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_root", str(tmp_path))
    store = get_object_store()
    key = f"uploads/test/{uuid.uuid4().hex}.txt"
    store.put_bytes(db, MAIN, key, b"v1")
    store.put_bytes(db, MAIN, key, b"v2")
    store.delete(db, MAIN, key)
    rows = db.execute(text("SELECT op, version, sha256 FROM storage_change_outbox WHERE namespace='main' AND key=:k ORDER BY seq"), {"k": key}).all()
    assert [(r.op, r.version) for r in rows] == [("put", 1), ("put", 2), ("delete", 3)]
    assert rows[1].sha256 == hashlib.sha256(b"v2").hexdigest()
    registry = db.execute(text("SELECT status, version FROM storage_object WHERE namespace='main' AND key=:k"), {"k": key}).one()
    assert (registry.status, registry.version) == ("deleted", 3)
    # S3-008: physisch entfernt erst der Purge nach dem Commit.
    assert (tmp_path / key).exists()
    store.purge_deleted(db)
    assert not (tmp_path / key).exists()


def test_write_is_rejected_while_storage_is_fenced(db, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_root", str(tmp_path))
    db.execute(text("UPDATE storage_state SET write_fenced = true, fence_reason = 'test' WHERE id = 1"))
    with pytest.raises(StorageWriteFenced):
        get_object_store().put_bytes(db, MAIN, "uploads/fenced.txt", b"x")
    assert not (tmp_path / "uploads" / "fenced.txt").exists()


def test_register_write_rejects_a_stale_generation(db):
    """Ein Schreiber mit veralteter Generation (Cutover dazwischen) darf nichts registrieren."""
    db.execute(text("SELECT * FROM storage_begin_write()"))
    with pytest.raises(DBAPIError, match="HOCX_STORAGE_GENERATION_CHANGED"):
        db.execute(text("SELECT storage_register_write('main', 'x/y', 'put', 1, NULL, NULL, 999999)"))


def test_register_write_rejects_invalid_keys_in_the_database_as_well(db):
    db.execute(text("SELECT * FROM storage_begin_write()"))
    with pytest.raises(DBAPIError, match="invalid storage key"):
        db.execute(text("SELECT storage_register_write('main', '../etc/passwd', 'put', 1, NULL, NULL, 0)"))


def test_fence_waits_for_open_write_transactions():
    """Der Cutover (UPDATE auf storage_state) wartet, bis offene Schreibtransaktionen (FOR SHARE
    aus storage_begin_write) abgeschlossen sind - danach schreibt niemand mehr in die alte Quelle."""
    writer = SessionLocal()
    writer.execute(text("SELECT * FROM storage_begin_write()"))
    fenced_at: list[float] = []

    def fence() -> None:
        with engine.begin() as conn:
            conn.execute(text("SET LOCAL lock_timeout = '10s'"))
            conn.execute(text("UPDATE storage_state SET fence_token = fence_token WHERE id = 1"))
            fenced_at.append(time.monotonic())

    thread = threading.Thread(target=fence)
    thread.start()
    time.sleep(0.5)
    assert not fenced_at, "Fence darf nicht vor dem Ende der Schreibtransaktion greifen"
    released = time.monotonic()
    writer.rollback()
    writer.close()
    thread.join(timeout=10)
    assert fenced_at and fenced_at[0] >= released


# --- S3-Backend (isoliertes test-s3) ----------------------------------------------------------


def _s3(prefix: str | None = None, generation: int = 1) -> S3Backend:
    return S3Backend(ProfileConfig(
        profile_id=99, generation=generation, provider="garage_local", endpoint_url=os.environ["TEST_S3_ENDPOINT"],
        region="garage", bucket="hocx-main", abgabebox_bucket="hocx-abgabebox", prefix=prefix or f"unit-{uuid.uuid4().hex[:8]}",
        addressing_style="path", access_key=os.environ["TEST_S3_ACCESS_KEY"], secret_key=os.environ["TEST_S3_SECRET_KEY"], tls_verify=False,
    ))


@requires_s3
def test_s3_backend_roundtrip_range_list_copy_delete():
    backend = _s3()
    data = os.urandom(1000)
    sha = hashlib.sha256(data).hexdigest()
    backend.put_stream("main", "t/a.bin", io.BytesIO(data), size=len(data), sha256=sha, content_type="application/octet-stream")
    head = backend.head("main", "t/a.bin")
    assert head.size == 1000 and head.sha256 == sha
    assert b"".join(backend.open_read("main", "t/a.bin", start=10, end=19)) == data[10:20]
    copied = backend.copy("main", "t/a.bin", "t/b.bin")
    assert copied.sha256 == sha
    assert sorted(i.key for i in backend.list("main", "t/")) == ["t/a.bin", "t/b.bin"]
    backend.delete("main", "t/a.bin")
    backend.delete("main", "t/b.bin")
    backend.delete("main", "t/never-existed.bin")  # idempotent
    assert backend.head("main", "t/a.bin") is None
    with pytest.raises(ObjectNotFound):
        list(backend.open_read("main", "t/a.bin"))


@requires_s3
def test_s3_backend_multipart_upload_of_a_large_file_streams_and_verifies():
    backend = _s3()
    data = os.urandom(20 * 1024 * 1024)  # > Multipart-Schwelle (16 MiB)
    sha = hashlib.sha256(data).hexdigest()
    info = backend.put_stream("main", "big/file.bin", io.BytesIO(data), size=len(data), sha256=sha, content_type=None)
    assert info.size == len(data)
    digest = hashlib.sha256()
    for chunk in backend.open_read("main", "big/file.bin"):
        digest.update(chunk)
    assert digest.hexdigest() == sha
    backend.delete("main", "big/file.bin")


@requires_s3
def test_s3_backend_removes_an_object_whose_content_does_not_match_the_expected_hash():
    backend = _s3()
    with pytest.raises(StorageIntegrityError):
        backend.put_stream("main", "bad/x.bin", io.BytesIO(b"echter inhalt"), size=13, sha256="a" * 64, content_type=None)
    assert backend.head("main", "bad/x.bin") is None


@requires_s3
def test_s3_backend_aborts_interrupted_multipart_uploads():
    backend = _s3()
    upload = backend._client.create_multipart_upload(Bucket="hocx-main", Key=backend.physical_key("main", "mp/x.bin"))
    assert backend.abort_stale_multipart_uploads("main", 0) >= 1
    remaining = backend._client.list_multipart_uploads(Bucket="hocx-main", Prefix=backend.physical_prefix("main")).get("Uploads", [])
    assert all(u["UploadId"] != upload["UploadId"] for u in remaining)


@requires_s3
def test_restricted_abgabebox_credentials_cannot_reach_the_main_bucket():
    config = _s3().config
    restricted = S3Backend(ProfileConfig(**{**config.__dict__, "access_key": os.environ["TEST_S3_ABGABEBOX_ACCESS_KEY"], "secret_key": os.environ["TEST_S3_ABGABEBOX_SECRET_KEY"]}))
    restricted.put_stream("abgabebox", "ok.txt", io.BytesIO(b"x"), size=1, sha256=hashlib.sha256(b"x").hexdigest(), content_type=None)
    restricted.delete("abgabebox", "ok.txt")
    with pytest.raises(Exception):
        restricted.put_stream("main", "nope.txt", io.BytesIO(b"x"), size=1, sha256=hashlib.sha256(b"x").hexdigest(), content_type=None)


def test_client_errors_map_to_provider_independent_classes():
    def err(code: str, status: int) -> ClientError:
        return ClientError({"Error": {"Code": code}, "ResponseMetadata": {"HTTPStatusCode": status}}, "GetObject")

    assert isinstance(_map_client_error(err("NoSuchKey", 404), "k"), ObjectNotFound)
    assert isinstance(_map_client_error(err("SlowDown", 503), "k"), StorageThrottled)
    assert isinstance(_map_client_error(err("TooManyRequests", 429), "k"), StorageThrottled)
    assert isinstance(_map_client_error(err("InternalError", 500), "k"), StorageUnavailable)
    assert isinstance(_map_client_error(ConnectTimeoutError(endpoint_url="x"), "k"), StorageUnavailable)


@requires_s3
def test_unreachable_endpoint_is_reported_as_unavailable_not_as_missing():
    backend = S3Backend(ProfileConfig(
        profile_id=98, generation=1, provider="garage_local", endpoint_url="http://127.0.0.1:9", region="garage", bucket="hocx-main",
        access_key="x", secret_key="y", tls_verify=False,
    ), connect_timeout=1, read_timeout=1)
    with pytest.raises(StorageUnavailable):
        backend.head("main", "x")


# --- Downloads --------------------------------------------------------------------------------


class _Req:
    def __init__(self, range_header: str | None = None) -> None:
        self.headers = {"range": range_header} if range_header else {}


def test_object_response_uses_file_response_for_the_filesystem(db, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_root", str(tmp_path))
    get_object_store().put_bytes(db, MAIN, "uploads/r.txt", b"abcdef")
    response = object_response(_Req(), MAIN, "uploads/r.txt", media_type="text/plain")
    assert response.__class__.__name__ == "FileResponse"
