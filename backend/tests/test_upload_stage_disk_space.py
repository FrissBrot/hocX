"""Platzprüfung beim Zwischenspeichern: Eine Datei ohne bekannte Grösse darf nicht vorab
den Platz für das Maximum (Galerie-ZIP bis 10 GiB) verlangen, läuft die Platte beim
Schreiben voll, bricht der Upload mit 507 ab und hinterlässt keine Teildatei."""
import asyncio
import io
import shutil
from collections import namedtuple

import pytest
from fastapi import HTTPException
from starlette.datastructures import UploadFile

from app.services import upload_pipeline

_Usage = namedtuple("_Usage", "total used free")
GiB = 1024**3


def _upload(content: bytes, *, size: int | None) -> UploadFile:
    return UploadFile(io.BytesIO(content), filename="archiv.zip", size=size)


def _fake_free(monkeypatch, free_bytes):
    values = iter(free_bytes) if isinstance(free_bytes, list) else None

    def disk_usage(_path):
        free = next(values) if values is not None else free_bytes
        return _Usage(100 * GiB, 100 * GiB - free, free)

    monkeypatch.setattr(shutil, "disk_usage", disk_usage)


def test_unknown_size_needs_only_the_reserve_not_the_maximum(monkeypatch, tmp_path):
    # 1 GiB frei, Maximum 10 GiB: früher 507, obwohl die Datei nur ein paar Bytes hat.
    _fake_free(monkeypatch, 1 * GiB)
    path = asyncio.run(upload_pipeline.stage_upload_to_disk(
        _upload(b"PK\x05\x06" + b"\0" * 18, size=None), target_dir=tmp_path, max_bytes=10 * GiB, suffix=".zip",
    ))
    assert path.read_bytes().startswith(b"PK")


def test_known_size_is_checked_up_front(monkeypatch, tmp_path):
    _fake_free(monkeypatch, 1 * GiB)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(upload_pipeline.stage_upload_to_disk(
            _upload(b"x", size=2 * GiB), target_dir=tmp_path, max_bytes=10 * GiB, suffix=".zip",
        ))
    assert exc.value.status_code == 507
    assert list(tmp_path.iterdir()) == []


def test_disk_filling_up_while_writing_aborts_and_removes_the_partial_file(monkeypatch, tmp_path):
    # Vorabprüfung ok, nach dem ersten Chunk ist die Reserve unterschritten.
    _fake_free(monkeypatch, [1 * GiB, 1 * GiB, 10 * 1024**2])
    content = b"a" * (upload_pipeline.STAGE_CHUNK_BYTES * 2)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(upload_pipeline.stage_upload_to_disk(
            _upload(content, size=None), target_dir=tmp_path, max_bytes=10 * GiB, suffix=".zip",
        ))
    assert exc.value.status_code == 507
    assert list(tmp_path.iterdir()) == []
