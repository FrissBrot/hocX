"""Termin-CSV-Import mit kaputten Dateien (Bug-Bounty 2026-11-19, termine/eingaben).

Das csv-Modul wirft bei einem Feld über 128 KiB `csv.Error` (kein ValueError). Die Routen
fingen nur UnicodeDecodeError/ValueError ab: eine solche Datei ergab einen 500 samt Eintrag im
Fehlerprotokoll statt einer verständlichen 400."""
from __future__ import annotations

import asyncio
import io

import pytest
from fastapi import HTTPException, UploadFile
from starlette.datastructures import Headers

from app.api.routes import events as routes
from app.models.entities import Event
from tests.factories import make_current_user, make_tenant


def _upload(content: str) -> UploadFile:
    return UploadFile(file=io.BytesIO(content.encode()), filename="termine.csv", headers=Headers({"content-type": "text/csv"}))


_OVERSIZED_FIELD = "Datum;Titel;Beschreibung\n01.05.2026;Lager;" + "x" * 200_000 + "\n"


@pytest.mark.parametrize("impl", [routes._preview_events_csv_impl, routes._import_events_csv_impl])
def test_oversized_csv_field_is_a_400_not_a_500(db, impl):
    tenant = make_tenant(db)
    user = make_current_user(tenant.id, role="writer")

    with pytest.raises(HTTPException) as caught:
        asyncio.run(impl(file=_upload(_OVERSIZED_FIELD), column_map="", db=db, user=user))

    assert caught.value.status_code == 400
    assert db.query(Event).filter(Event.tenant_id == tenant.id).count() == 0
