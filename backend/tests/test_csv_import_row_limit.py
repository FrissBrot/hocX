"""CSV-Importe (Termine, Personen) ohne Zeilenlimit (Nachtlauf 2026-11-19, Verdacht «CSV ohne
Zeilenlimit»): eine grosse Datei wurde vollständig in einer Transaktion verarbeitet bzw. als Vorschau
zurückgegeben. Jetzt: höchstens MAX_CSV_IMPORT_ROWS Datenzeilen, sonst 400 mit Code und Grenze."""
from __future__ import annotations

import asyncio
import io

import pytest
from fastapi import HTTPException, UploadFile
from sqlalchemy import func, select

from app.api.routes import events as events_routes
from app.api.routes import participants as participants_routes
from app.core import csv_limits
from app.core.csv_limits import MAX_CSV_IMPORT_ROWS
from app.models import Event, Participant
from tests.factories import make_current_user, make_tenant


def _upload(text: str) -> UploadFile:
    return UploadFile(file=io.BytesIO(text.encode("utf-8")), filename="import.csv")


def _event_csv(rows: int) -> str:
    return "Datum;Titel\n" + "".join(f"01.0{1 + i % 9}.2027;Termin {i}\n" for i in range(rows))


def _participant_csv(rows: int) -> str:
    return "Vorname;Nachname\n" + "".join(f"Vorname{i};Nachname{i}\n" for i in range(rows))


def _assert_too_many_rows(exc: pytest.ExceptionInfo[HTTPException]) -> None:
    assert exc.value.status_code == 400
    assert exc.value.detail["code"] == "csv_too_many_rows"
    assert exc.value.detail["params"] == {"max": MAX_CSV_IMPORT_ROWS}


def test_limit_csv_rows_passes_up_to_the_limit_and_rejects_more():
    assert list(csv_limits.limit_csv_rows(range(3), limit=3)) == [0, 1, 2]
    with pytest.raises(csv_limits.CsvTooManyRows):
        list(csv_limits.limit_csv_rows(range(4), limit=3))


def test_event_csv_preview_and_import_reject_too_many_rows(db, monkeypatch):
    tenant = make_tenant(db)
    user = make_current_user(tenant.id, role="admin")
    csv_text = _event_csv(MAX_CSV_IMPORT_ROWS + 1)
    with pytest.raises(HTTPException) as preview:
        asyncio.run(events_routes._preview_events_csv_impl(file=_upload(csv_text), column_map="", db=db, user=user))
    _assert_too_many_rows(preview)

    before = db.scalar(select(func.count()).select_from(Event).where(Event.tenant_id == tenant.id))
    monkeypatch.setattr(db, "rollback", db.expire_all)  # echtes Rollback verwürfe die Testtransaktion (conftest)
    with pytest.raises(HTTPException) as imported:
        asyncio.run(events_routes._import_events_csv_impl(file=_upload(csv_text), column_map="", db=db, user=user))
    _assert_too_many_rows(imported)
    assert db.scalar(select(func.count()).select_from(Event).where(Event.tenant_id == tenant.id)) == before


def test_event_csv_preview_at_the_limit_still_works(db):
    tenant = make_tenant(db)
    user = make_current_user(tenant.id, role="admin")
    preview = asyncio.run(events_routes._preview_events_csv_impl(file=_upload(_event_csv(MAX_CSV_IMPORT_ROWS)), column_map="", db=db, user=user))
    assert len(preview["rows"]) == MAX_CSV_IMPORT_ROWS


def test_participant_csv_import_rejects_too_many_rows_before_inserting(db, monkeypatch):
    tenant = make_tenant(db)
    user = make_current_user(tenant.id, role="admin")
    before = db.scalar(select(func.count()).select_from(Participant).where(Participant.tenant_id == tenant.id))
    monkeypatch.setattr(db, "rollback", db.expire_all)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(participants_routes._import_participants_csv_impl(file=_upload(_participant_csv(MAX_CSV_IMPORT_ROWS + 1)), db=db, user=user))
    _assert_too_many_rows(exc)
    assert db.scalar(select(func.count()).select_from(Participant).where(Participant.tenant_id == tenant.id)) == before
