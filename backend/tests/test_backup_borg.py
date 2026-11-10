"""Integration der Borg-Hülle gegen echte Repositories (lokal und über SSH mit
`borg serve --append-only`) - Grundlage, auf die sich der Backup-Worker verlässt."""

from __future__ import annotations

import hashlib
import uuid

import pytest

from app.backup.borg import Borg, BorgError
from app.backup.manifest import pool_archive_name, pool_path
from app.backup.repository import RepositoryView
from app.backup.tarstream import ContentMismatch, TarStreamWriter
from tests.backup_support import SshBorgServer, local_config, requires_borg, requires_sshd

pytestmark = requires_borg


def _blob(n: int) -> tuple[str, bytes]:
    data = f"content-{n}-".encode() * (n + 1)
    return hashlib.sha256(data).hexdigest(), data


def _write_pool(borg: Borg, name: str, blobs: list[tuple[str, bytes]]) -> dict:
    process = borg.import_tar(name)
    writer = TarStreamWriter(process.stdin)
    for sha, data in blobs:
        writer.add_chunks(pool_path(sha), len(data), [data], expected_sha256=sha)
    writer.close()
    return process.finish()


@pytest.fixture
def borg(tmp_path):
    instance = Borg(local_config(tmp_path))
    instance.init()
    yield instance
    instance.close()


def test_import_list_extract_and_export(borg):
    blobs = [_blob(i) for i in range(5)]
    pool = pool_archive_name(uuid.uuid4(), 0)
    stats = _write_pool(borg, pool, blobs)
    assert stats["archive"]["name"] == pool
    view = RepositoryView(borg)
    assert view.pool_contents(pool) == {sha: len(data) for sha, data in blobs}
    sha, data = blobs[2]
    with borg.extract_stream(pool, pool_path(sha)) as stream:
        assert stream.read() == data
    received = {}

    def sink(content_sha, size, chunks, targets):
        received[content_sha] = b"".join(chunks)

    from app.backup.manifest import ManifestEntry

    entries = [ManifestEntry("main", f"k/{i}", len(d), s, 1, pool) for i, (s, d) in enumerate(blobs[:3])]
    report = view.fetch_contents(entries, sink)
    assert report.ok and report.fetched == 3
    assert received == {s: d for s, d in blobs[:3]}


def test_aborted_or_inconsistent_import_creates_no_archive(borg):
    pool = pool_archive_name(uuid.uuid4(), 0)
    process = borg.import_tar(pool)
    writer = TarStreamWriter(process.stdin)
    sha, data = _blob(1)
    with pytest.raises(ContentMismatch):
        writer.add_chunks(pool_path(sha), len(data), [data], expected_sha256="0" * 64)
    process.abort()
    assert [a["name"] for a in borg.list_archives()] == []
    # Abbruch mitten im Inhalt (Prozessabsturz des Erzeugers)
    process = borg.import_tar(pool)
    process.stdin.write(TarStreamWriter(process.stdin)._header(pool_path(sha), 10_000))
    process.stdin.write(b"x" * 100)
    with pytest.raises(BorgError):
        process.finish()
    assert borg.list_archives() == []


def test_recreate_exclude_changes_archive_id_and_delete_many(borg):
    blobs = [_blob(i) for i in range(3)]
    pool = pool_archive_name(uuid.uuid4(), 0)
    _write_pool(borg, pool, blobs)
    before = {a["name"]: a["id"] for a in borg.list_archives()}[pool]
    borg.recreate_exclude(pool, [pool_path(blobs[0][0])])
    after = {a["name"]: a["id"] for a in borg.list_archives()}[pool]
    assert before != after
    assert set(RepositoryView(borg).pool_contents(pool)) == {blobs[1][0], blobs[2][0]}
    other = pool_archive_name(uuid.uuid4(), 1)
    _write_pool(borg, other, blobs[:1])
    borg.delete_archives([pool, other])
    assert borg.list_archives() == []


def test_error_classification(tmp_path, borg):
    wrong = local_config(tmp_path)
    (tmp_path / "secrets" / "passphrase").write_text("wrong\n")
    with pytest.raises(BorgError) as info:
        Borg(wrong).list_archives()
    assert info.value.code == "passphrase_wrong"
    missing = Borg(local_config(tmp_path / "other", repository_url_override=str(tmp_path / "nope")))
    with pytest.raises(BorgError) as info:
        missing.list_archives()
    assert info.value.code == "repository_missing"
    with pytest.raises(BorgError) as info:
        borg.rename("../x", "y")
    assert info.value.code == "invalid_argument"


@requires_sshd
def test_ssh_append_only_and_host_key_pinning(tmp_path):
    server = SshBorgServer(tmp_path / "server")
    try:
        maintenance = Borg(server.config(tmp_path / "m", maintenance=True))
        maintenance.init()
        backup = Borg(server.config(tmp_path / "b"))
        pool = pool_archive_name(uuid.uuid4(), 0)
        _write_pool(backup, pool, [_blob(1)])
        assert [a["name"] for a in backup.list_archives()] == [pool]
        info = backup.repo_info()
        assert len(info["repository"]["id"]) == 64
        # Append-only: löschen entfernt das Archiv nur logisch, compact gibt nichts frei.
        segments_before = sorted(p.name for p in (server.repo / "data").rglob("*") if p.is_file())
        backup.delete_archives([pool])
        backup.compact()
        segments_after = sorted(p.name for p in (server.repo / "data").rglob("*") if p.is_file())
        assert set(segments_before) <= set(segments_after)
        # Fingerprint-Pinning statt known_hosts
        pinned = Borg(server.config(tmp_path / "f", known_hosts_file=None, host_fingerprint=server.fingerprint))
        pinned.list_archives()
        # Falscher Host-Key: Verbindung wird verweigert, nie automatisch akzeptiert.
        bad = tmp_path / "bad_known_hosts"
        bad.write_text(f"[127.0.0.1]:{server.port} ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIGQ9w9a1Hcv6b8QvBm0bmq7fW5mJ0w3Ka4V3UQ3BvR6p\n")
        with pytest.raises(BorgError) as info:
            Borg(server.config(tmp_path / "x", known_hosts_file=bad)).list_archives()
        assert info.value.code == "host_key_mismatch"
        wrong_fp = "SHA256:" + "A" * 43
        with pytest.raises(BorgError) as info:
            Borg(server.config(tmp_path / "y", known_hosts_file=None, host_fingerprint=wrong_fp)).list_archives()
        assert info.value.code == "host_key_mismatch"
    finally:
        server.stop()


@requires_sshd
def test_unreachable_storage_box_is_transient(tmp_path):
    server = SshBorgServer(tmp_path / "server")
    server.stop()
    with pytest.raises(BorgError) as info:
        Borg(server.config(tmp_path / "b")).list_archives()
    assert info.value.code in ("repository_unreachable", "connection_lost")
    assert info.value.transient
