"""Mitglieder-CSV-Import mit kaputten Dateien (Bug-Bounty 2026-11-22, mitglieder-rollen/eingaben).

Das csv-Modul wirft bei einem Feld über 128 KiB `csv.Error`. Die Route fing nur CsvTooManyRows,
SQLAlchemyError und UnicodeDecodeError ab: eine solche Datei ergab einen 500 samt Eintrag im
Fehlerprotokoll statt einer verständlichen 400 (beim Termin-Import seit #66 behoben).
NUL-Zeichen in einer Zelle liessen den INSERT der Zeile scheitern; der Fehler landete als
«unerwarteter Fehler» im Fehlerprotokoll, obwohl es nur eine kaputte Eingabe ist."""
from __future__ import annotations

import asyncio
import io

import pytest
from fastapi import HTTPException, UploadFile
from sqlalchemy import select
from starlette.datastructures import Headers

from app.api.routes import participants as routes
from app.models import Participant, SystemErrorLog
from app.services.participant_service import ParticipantService
from tests.factories import make_current_user, make_tenant


def _upload(content: str) -> UploadFile:
    return UploadFile(file=io.BytesIO(content.encode()), filename="mitglieder.csv", headers=Headers({"content-type": "text/csv"}))


def _error_count(db, tenant_id: int) -> int:
    return len(db.scalars(select(SystemErrorLog.id).where(SystemErrorLog.tenant_id == tenant_id)).all())


def test_oversized_csv_field_is_a_400_not_a_500(db):
    tenant = make_tenant(db)
    user = make_current_user(tenant.id, role="admin")
    content = "Vorname;Nachname;Notiz\nAnna;Muster;" + "x" * 200_000 + "\n"

    with pytest.raises(HTTPException) as caught:
        asyncio.run(routes._import_participants_csv_impl(file=_upload(content), db=db, user=user))

    assert caught.value.status_code == 400
    assert db.query(Participant).filter(Participant.tenant_id == tenant.id).count() == 0


def test_nul_character_in_csv_cell_is_not_logged_as_system_error(db):
    tenant = make_tenant(db)

    result = ParticipantService().import_csv(db, "Vorname;Nachname\nAn\x00na;Muster\nBea;Beispiel\n", tenant_id=tenant.id)

    # Gültige Zeilen kommen an, kaputte Eingaben sind kein Systemfehler
    assert [p.display_name for p in result.imported] == ["Bea Beispiel"]
    assert result.errors == ["2"]
    assert _error_count(db, tenant.id) == 0
