"""Einheitstests ohne Test-S3: Konfiguration des Storage-Workers und Prüfung der
Migrationsoptionen."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from app.core.config import settings
from app.services import storage_migration_service as sms
from app.workers import storage_worker


def test_worker_spools_to_the_disk_work_root_not_to_tmpfs(tmp_path, monkeypatch):
    """S3-005: /tmp ist im Release ein tmpfs (zählt zum mem_limit) - Zwischenspeicher grosser
    Objekte gehören auf das Platten-Volume STORAGE_WORK_ROOT."""
    monkeypatch.setattr(settings, "storage_work_root", str(tmp_path / "work"))
    monkeypatch.setattr(tempfile, "tempdir", tempfile.tempdir)
    monkeypatch.setenv("TMPDIR", os.environ.get("TMPDIR", ""))
    path = storage_worker.configure_tempdir()
    assert Path(path).is_dir()
    assert Path(tempfile.gettempdir()).resolve() == Path(path).resolve()
    assert Path(path).resolve().is_relative_to((tmp_path / "work").resolve())


@pytest.mark.parametrize("options", [
    {"fallback_days": -5}, {"fallback_days": 0}, {"fallback_days": "x"}, {"parallelism": "x"},
    {"parallelism": None}, {"observe_seconds": "lang"}, {"max_object_attempts": [1]},
    {"bandwidth_limit_mbps": "schnell"}, {"bandwidth_limit_mbps": float("inf")}, {"auto_cutover": "ja"},
])
def test_invalid_migration_options_are_rejected_as_migration_error(options):
    """S3-010: ungültige Optionen sind eine erwartete Ablehnung (409), kein 500 und kein
    Abbruch erst im Cutover; eine negative Rückfallfrist hebelte die Schutzfrist aus."""
    with pytest.raises(sms.MigrationError):
        sms.merged_options(options, kind="live")


def test_valid_fallback_days_are_kept():
    assert sms.merged_options({"fallback_days": "30"}, kind="live")["fallback_days"] == 30
    assert sms.merged_options({}, kind="initial")["fallback_days"] is None
