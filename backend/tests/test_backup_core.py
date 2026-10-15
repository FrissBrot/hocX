"""Unit-Tests der Backup-Kernbibliothek: Manifest, Tar-Stream, Retention, Konfiguration."""

from __future__ import annotations

import io
import tarfile
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.backup.config import BackupConfigError
from app.backup.manifest import (
    ManifestEntry,
    ManifestError,
    ManifestWriter,
    parse_metadata,
    parse_rp_name,
    pool_archive_name,
    pool_path,
    read_manifest,
    rp_archive_name,
    sha_from_pool_path,
)
from app.backup.retention import RestorePoint, RetentionPolicy, select_retained
from app.backup.tarstream import ContentMismatch, TarStreamWriter
from tests.backup_support import local_config

SHA_A = "a" * 64
SHA_B = "b" * 64


def _pool() -> str:
    return pool_archive_name(uuid.uuid4(), 0)


def test_manifest_roundtrip_and_hash(tmp_path):
    backup_id = uuid.uuid4()
    path = tmp_path / "m.jsonl.gz"
    writer = ManifestWriter(path, backup_id=backup_id, generation=3)
    pool = _pool()
    writer.add(ManifestEntry("main", "uploads/tenant-1/a.jpg", 10, SHA_A, 1, pool))
    writer.add(ManifestEntry("abgabebox", "tenant-1/x/b.pdf", 0, SHA_B, 2, pool))
    sha = writer.close()
    import hashlib

    assert sha == hashlib.sha256(path.read_bytes()).hexdigest()
    with path.open("rb") as handle:
        header, entries = read_manifest(handle)
        items = list(entries)
    assert header["backup_id"] == str(backup_id) and header["generation"] == 3
    assert [e.key for e in items] == ["uploads/tenant-1/a.jpg", "tenant-1/x/b.pdf"]
    assert writer.count == 2 and writer.total_bytes == 10


@pytest.mark.parametrize("data", [
    {"ns": "main", "key": "../etc/passwd", "size": 1, "sha256": SHA_A, "version": 1, "pool": "hocx-pool-" + "0" * 32 + "-0000"},
    {"ns": "other", "key": "a", "size": 1, "sha256": SHA_A, "version": 1, "pool": "hocx-pool-" + "0" * 32 + "-0000"},
    {"ns": "main", "key": "a", "size": -1, "sha256": SHA_A, "version": 1, "pool": "hocx-pool-" + "0" * 32 + "-0000"},
    {"ns": "main", "key": "a", "size": 1, "sha256": "zz", "version": 1, "pool": "hocx-pool-" + "0" * 32 + "-0000"},
    {"ns": "main", "key": "a", "size": 1, "sha256": SHA_A, "version": 1, "pool": "../../x"},
])
def test_manifest_rejects_untrusted_entries(data):
    with pytest.raises(ManifestError):
        ManifestEntry.parse(data)


def test_manifest_rejects_duplicate_keys(tmp_path):
    path = tmp_path / "m.jsonl.gz"
    writer = ManifestWriter(path, backup_id=uuid.uuid4(), generation=1)
    pool = _pool()
    writer.add(ManifestEntry("main", "a/b", 1, SHA_A, 1, pool))
    writer.add(ManifestEntry("main", "a/b", 1, SHA_B, 2, pool))
    writer.close()
    with path.open("rb") as handle:
        _, entries = read_manifest(handle)
        with pytest.raises(ManifestError):
            list(entries)


def test_archive_names_and_pool_paths():
    backup_id = uuid.uuid4()
    when = datetime(2026, 10, 15, 6, 15, 3, tzinfo=UTC)
    name = rp_archive_name(when, backup_id)
    assert parse_rp_name(name) == (when, backup_id, False)
    assert parse_rp_name(name + ".invalid")[2] is True
    assert parse_rp_name("hocx-rp-evil") is None
    assert pool_path(SHA_A) == f"pool/aa/{SHA_A}"
    assert sha_from_pool_path(pool_path(SHA_A)) == SHA_A
    assert sha_from_pool_path(f"pool/bb/{SHA_A}") is None
    with pytest.raises(ManifestError):
        pool_path("../x")


def test_metadata_validation():
    with pytest.raises(ManifestError):
        parse_metadata(b'{"format": "something-else"}')
    with pytest.raises(ManifestError):
        parse_metadata(b'{"format": "hocx-backup", "format_version": 1}')


def test_tar_stream_is_readable_and_verifies(tmp_path):
    buffer = io.BytesIO()
    writer = TarStreamWriter(buffer)
    import hashlib

    data = b"x" * 1000
    writer.add_chunks("pool/aa/one", len(data), [data[:300], data[300:]], expected_sha256=hashlib.sha256(data).hexdigest())
    writer.add_bytes("hocx-backup.json", b"{}")
    writer.close()
    buffer.seek(0)
    with tarfile.open(fileobj=buffer, mode="r|") as tar:
        names = [(m.name, m.size) for m in tar]
    assert names == [("pool/aa/one", 1000), ("hocx-backup.json", 2)]


@pytest.mark.parametrize("chunks,reason", [([b"abc"], "size_smaller"), ([b"abcdefgh"], "size_larger")])
def test_tar_stream_detects_size_mismatch(chunks, reason):
    with pytest.raises(ContentMismatch) as info:
        TarStreamWriter(io.BytesIO()).add_chunks("x", 5, chunks)
    assert info.value.reason == reason


def test_tar_stream_detects_hash_mismatch():
    with pytest.raises(ContentMismatch) as info:
        TarStreamWriter(io.BytesIO()).add_chunks("x", 3, [b"abc"], expected_sha256="0" * 64)
    assert info.value.reason == "sha256"


# --- Retention --------------------------------------------------------------------------------


def _six_hourly(now: datetime, days: int) -> list[RestorePoint]:
    points = []
    at = now
    while at > now - timedelta(days=days):
        points.append(RestorePoint(at.isoformat(), at, "completed"))
        at -= timedelta(hours=6)
    return points


def test_retention_default_policy_keeps_expected_points():
    now = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
    points = _six_hourly(now, 500)
    kept = select_retained(points, RetentionPolicy(), now)
    within = [p for p in points if p.at >= now - timedelta(days=14)]
    assert all(p.id in kept for p in within)  # alle 6-stündlichen der letzten 14 Tage
    weekly = {p.id for p in points if "weekly" in kept.get(p.id, [])}
    monthly = {p.id for p in points if "monthly" in kept.get(p.id, [])}
    daily = {p.id for p in points if "daily" in kept.get(p.id, [])}
    assert len(daily) == 14 and len(weekly) == 8 and len(monthly) == 12
    oldest_kept = min(p.at for p in points if p.id in kept)
    assert oldest_kept > now - timedelta(days=370)
    assert len(kept) < len(within) + 8 + 12 + 1


def test_retention_always_keeps_protected_and_latest_and_ignores_partial_for_periods():
    now = datetime(2026, 10, 15, tzinfo=UTC)
    old_protected = RestorePoint("rescue", now - timedelta(days=900), "completed", protected=True)
    old_partial = RestorePoint("partial", now - timedelta(days=70), "partial")
    latest = RestorePoint("latest", now - timedelta(days=60), "completed")
    kept = select_retained([old_protected, old_partial, latest], RetentionPolicy(keep_within_days=14, keep_daily=0, keep_weekly=0, keep_monthly=0), now)
    assert "rescue" in kept and "latest" in kept and "partial" not in kept


@pytest.mark.parametrize("keep_within_days", [0, 14])
def test_retention_never_removes_the_newest_usable_point_when_all_are_partial(keep_within_days):
    """BORG-001: gelingt jede Sicherung nur teilweise (z. B. ein dauerhaft fehlendes Objekt),
    darf die Retention trotzdem nie alle Punkte entfernen - auch nicht mit keep_within_days=0
    oder wenn der jüngste Punkt älter als das keep_within-Fenster ist."""
    now = datetime(2026, 10, 15, tzinfo=UTC)
    policy = RetentionPolicy(keep_within_days, 14, 8, 12)
    fresh = select_retained([RestorePoint("a", now - timedelta(hours=1), "partial")], policy, now)
    assert "a" in fresh
    old = [RestorePoint(f"p{i}", now - timedelta(days=30 + i), "partial") for i in range(10)]
    kept = select_retained(old, policy, now)
    assert set(kept) == {"p0"} and kept["p0"] == ["latest_usable"]


def test_retention_keeps_newest_partial_in_addition_to_newest_complete():
    now = datetime(2026, 10, 15, tzinfo=UTC)
    complete = RestorePoint("complete", now - timedelta(days=40), "completed")
    partial = RestorePoint("partial", now - timedelta(days=20), "partial")
    kept = select_retained([complete, partial], RetentionPolicy(0, 0, 0, 0), now)
    assert set(kept) == {"complete", "partial"}


def test_retention_rules_are_a_union():
    now = datetime(2026, 10, 15, tzinfo=UTC)
    points = _six_hourly(now, 100)
    only_daily = select_retained(points, RetentionPolicy(0, 14, 0, 0), now)
    only_monthly = select_retained(points, RetentionPolicy(0, 0, 0, 12), now)
    both = select_retained(points, RetentionPolicy(0, 14, 0, 12), now)
    assert set(both) == set(only_daily) | set(only_monthly)


def test_config_validation(tmp_path):
    config = local_config(tmp_path)
    config.validate()
    with pytest.raises(BackupConfigError):
        local_config(tmp_path, repository_url_override=None, host="evil host", user="u").validate(require_secrets=False)
    with pytest.raises(BackupConfigError):
        local_config(tmp_path, compression="zstd; rm -rf /").validate(require_secrets=False)
    remote = local_config(tmp_path, repository_url_override=None, host="u1.your-storagebox.de", user="u1", repository_path="hocx",
                          ssh_key_file=tmp_path / "missing")
    assert remote.repository_url == "ssh://u1@u1.your-storagebox.de:23/./hocx"
    with pytest.raises(BackupConfigError):
        remote.validate()
    assert "passphrase" not in str(remote.public_summary()).lower().replace("passphrase_configured", "")
