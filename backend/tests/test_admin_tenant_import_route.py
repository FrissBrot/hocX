"""Audit MAIN-BE-010: Der Mandanten-Import blockiert den Event-Loop nicht und liest den
Upload nicht komplett in den Speicher."""
import asyncio
import io
import threading
from pathlib import Path

import pytest
from fastapi import HTTPException, UploadFile
from starlette.datastructures import Headers

from app.api.routes import admin as admin_routes


def test_import_runs_in_threadpool_and_cleans_up_staged_upload(db, monkeypatch):
    seen: dict[str, object] = {}

    def fake_import_zip(_db, zip_path: Path, new_name: str):
        seen["thread"] = threading.get_ident()
        seen["path"] = zip_path
        seen["content"] = zip_path.read_bytes()
        raise ValueError("Testabbruch")

    monkeypatch.setattr(admin_routes.import_service, "import_zip", fake_import_zip)
    upload = UploadFile(file=io.BytesIO(b"PK-test-bytes"), filename="export.zip", headers=Headers({"content-type": "application/zip"}))

    async def run():
        seen["loop_thread"] = threading.get_ident()
        return await admin_routes.import_tenant(new_name="Neu", file=upload, db=db, current_admin=None)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(run())

    assert exc.value.status_code == 400
    assert seen["content"] == b"PK-test-bytes"
    assert seen["thread"] != seen["loop_thread"]
    assert not Path(seen["path"]).exists()
