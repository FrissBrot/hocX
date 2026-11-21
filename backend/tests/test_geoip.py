"""Länder-Geolocation (app/core/geoip.py) mit kleiner Test-MMDB - ohne Netzzugriff.

Lookup (nur Ländercode, private Adressen nie), stiller Ausfall ohne Datenbank, Prüfung neuer
Dateien und die monatliche Aktualisierung (Download gemockt, atomarer Ersatz).
"""
from __future__ import annotations

import gzip
import urllib.error
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.core import geoip
from app.core.config import settings
from tests.mmdb_fixture import write_mmdb

NETWORKS = {"81.0.0.0/8": "CH", "8.8.8.0/24": "US", "1.1.1.0/24": "AU", "2001:4860::/32": "US", "5.0.0.0/8": "DE"}
# Genug Knoten für die Grössenprüfung (MIN_NODE_COUNT) von validate_file
PAD = geoip.MIN_NODE_COUNT


@pytest.fixture
def geo_db(tmp_path, monkeypatch):
    path = write_mmdb(tmp_path / "dbip-country-lite.mmdb", NETWORKS)
    monkeypatch.setattr(settings, "geoip_db_path", str(path))
    geoip.reset()
    yield path
    geoip.reset()


def test_lookup_returns_only_the_country_code(geo_db):
    assert geoip.country_for("81.62.1.2") == "CH"
    assert geoip.country_for("8.8.8.8") == "US"
    assert geoip.country_for("2001:4860:4860::8888") == "US"
    assert geoip.country_for("9.9.9.9") is None


@pytest.mark.parametrize("address", ["10.1.2.3", "192.168.1.1", "127.0.0.1", "::1", "fd00::1", "203.0.113.5", "", None, "kein-ip"])
def test_private_reserved_and_invalid_addresses_are_never_looked_up(geo_db, address):
    assert geoip.country_for(address) is None


def test_missing_database_drops_the_signal_silently(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "geoip_db_path", str(tmp_path / "fehlt.mmdb"))
    geoip.reset()
    assert geoip.country_for("81.62.1.2") is None
    assert geoip.status() == {"available": False, "auto_update": settings.geoip_auto_update}


def test_broken_database_drops_the_signal_silently(tmp_path, monkeypatch):
    path = tmp_path / "kaputt.mmdb"
    path.write_bytes(b"keine mmdb")
    monkeypatch.setattr(settings, "geoip_db_path", str(path))
    geoip.reset()
    assert geoip.country_for("81.62.1.2") is None


def test_status_reports_build_date(geo_db):
    info = geoip.status()
    assert info["available"] is True and info["age_days"] == 0 and info["build_date"]


def test_country_names_are_translated():
    assert geoip.country_name("CH", "de") == "Schweiz"
    assert geoip.country_name("CH", "fr") == "Suisse"
    assert geoip.country_name("CH", "xx") == "Schweiz"  # unbekannte Sprache -> Standardsprache
    assert geoip.country_name("ch", "en") == "Switzerland"
    assert geoip.country_name("<script>", "de") is None


# ── Prüfung und Aktualisierung ─────────────────────────────────────────


def test_validate_accepts_a_plausible_country_database(tmp_path):
    path = write_mmdb(tmp_path / "neu.mmdb", NETWORKS, pad_nodes=PAD)
    info = geoip.validate_file(path)
    assert info["database_type"] == "DBIP-Country-Lite" and info["nodes"] > PAD


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"database_type": "DBIP-City-Lite"}, "Datenbanktyp"),
        ({"build": datetime.now(UTC) - timedelta(days=200)}, "Erstelldatum"),
        ({"build": datetime.now(UTC) + timedelta(days=30)}, "Erstelldatum"),
    ],
)
def test_validate_rejects_implausible_files(tmp_path, kwargs, message):
    path = write_mmdb(tmp_path / "neu.mmdb", NETWORKS, pad_nodes=PAD, **kwargs)
    with pytest.raises(geoip.GeoIPUpdateError, match=message):
        geoip.validate_file(path)


def test_validate_rejects_tiny_or_empty_databases(tmp_path):
    with pytest.raises(geoip.GeoIPUpdateError, match="zu klein"):
        geoip.validate_file(write_mmdb(tmp_path / "klein.mmdb", NETWORKS))
    with pytest.raises(geoip.GeoIPUpdateError, match="Stichproben"):
        geoip.validate_file(write_mmdb(tmp_path / "leer.mmdb", {"81.0.0.0/8": "CH"}, pad_nodes=PAD))
    garbage = tmp_path / "garbage.mmdb"
    garbage.write_bytes(b"\x00" * 100)
    with pytest.raises(geoip.GeoIPUpdateError, match="nicht lesbar"):
        geoip.validate_file(garbage)


def _fake_download(source: Path, calls: list[str], missing: set[str] = frozenset()):
    def download(url: str, target: Path) -> None:
        calls.append(url)
        if any(month in url for month in missing):
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        target.write_bytes(source.read_bytes())

    return download


def test_update_downloads_validates_and_replaces_atomically(tmp_path, monkeypatch):
    target = tmp_path / "geoip" / "dbip-country-lite.mmdb"
    monkeypatch.setattr(settings, "geoip_db_path", str(target))
    monkeypatch.setattr(settings, "geoip_auto_update", True)
    now = datetime.now(UTC)
    source = write_mmdb(tmp_path / "quelle.mmdb", NETWORKS, pad_nodes=PAD, build=now)
    calls: list[str] = []
    result = geoip.update_database(now=now, download=_fake_download(source, calls))
    assert result["updated"] == now.strftime("%Y-%m")
    assert calls == [geoip.DOWNLOAD_URL.format(month=now.strftime("%Y-%m"))]
    assert target.exists() and not list(target.parent.glob(".geoip-*"))
    assert geoip.country_for("81.62.1.2") == "CH"
    # Zweiter Lauf im selben Monat: nichts zu tun, kein Download
    assert geoip.update_database(now=now, download=_fake_download(source, calls))["skipped"] == "current"
    assert len(calls) == 1
    geoip.reset()


def test_update_keeps_the_old_file_when_the_new_one_is_invalid(tmp_path, monkeypatch):
    target = tmp_path / "dbip-country-lite.mmdb"
    now = datetime.now(UTC)
    write_mmdb(target, NETWORKS, pad_nodes=PAD, build=now - timedelta(days=40))
    before = target.read_bytes()
    monkeypatch.setattr(settings, "geoip_db_path", str(target))
    monkeypatch.setattr(settings, "geoip_auto_update", True)
    bad = write_mmdb(tmp_path / "bad.mmdb", NETWORKS, database_type="DBIP-City-Lite", pad_nodes=PAD, build=now)
    with pytest.raises(geoip.GeoIPUpdateError):
        geoip.update_database(now=now, download=_fake_download(bad, []))
    assert target.read_bytes() == before
    assert not list(tmp_path.glob(".geoip-*"))


def test_new_month_not_yet_published_keeps_old_file_or_loads_previous_month(tmp_path, monkeypatch):
    now = datetime(2026, 12, 1, 3, 0, tzinfo=UTC)
    target = tmp_path / "dbip-country-lite.mmdb"
    monkeypatch.setattr(settings, "geoip_db_path", str(target))
    monkeypatch.setattr(settings, "geoip_auto_update", True)
    source = write_mmdb(tmp_path / "quelle.mmdb", NETWORKS, pad_nodes=PAD, build=datetime(2026, 11, 1, tzinfo=UTC))
    calls: list[str] = []
    # Ohne Datei: Dezember fehlt noch -> November wird geladen
    result = geoip.update_database(now=now, download=_fake_download(source, calls, missing={"2026-12"}))
    assert result["updated"] == "2026-11" and calls[-1].endswith("2026-11.mmdb.gz")
    # Mit November-Datei: Dezember fehlt -> alte Datei bleibt, kein Fehler
    result = geoip.update_database(now=now, download=_fake_download(source, calls, missing={"2026-12"}))
    assert result == {"skipped": "not_published", "build_month": "2026-11"}
    geoip.reset()


def test_auto_update_off_never_downloads(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "geoip_auto_update", False)
    monkeypatch.setattr(settings, "geoip_db_path", str(tmp_path / "x.mmdb"))
    assert geoip.update_database(download=lambda *_: pytest.fail("kein Download")) == {"skipped": "disabled"}


def test_download_limits_the_unpacked_size(tmp_path, monkeypatch):
    payload = gzip.compress(b"\x00" * (2 * 1024 * 1024))

    class _Response:
        def __init__(self):
            self.rest = payload

        def read(self, size=-1):
            chunk, self.rest = self.rest[:size], self.rest[size:]
            return chunk

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    monkeypatch.setattr(geoip._opener, "open", lambda request, timeout=None: _Response())
    monkeypatch.setattr(geoip, "MAX_UNCOMPRESSED_BYTES", 1024 * 1024)
    with pytest.raises(geoip.GeoIPUpdateError, match="zu gross"):
        geoip._download("https://download.db-ip.com/free/x.mmdb.gz", tmp_path / "out.mmdb")
    assert not (tmp_path / "out.mmdb.gz").exists()


def test_job_is_registered_with_lock_id():
    from app.core.background_loops import BACKGROUND_LOCK_IDS
    from app.core.job_registry import JOBS_BY_NAME
    from app.core.loops import JOB_WORKER_LOOPS, geoip_update_loop

    assert "geoip_update" in BACKGROUND_LOCK_IDS and JOBS_BY_NAME["geoip_update"].service == "job-worker"
    assert geoip_update_loop in JOB_WORKER_LOOPS
