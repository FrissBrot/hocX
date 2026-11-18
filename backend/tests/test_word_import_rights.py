"""Rechte des Word-Imports (Nachtlauf 2026-11-18, Feld dokumente/rechte).

Der Word-Import ist ``meetings.edit`` (RBAC E-10). Namen, die keiner Person zugeordnet
werden können, legt er auf Wunsch («Neu anlegen») als Personen an und ordnet sie der
Sitzungsvorlage zu - beides verlangt sonst ``participants.manage`` (POST /participants,
PUT /templates/{id}/participants). Eine Protokollführung ohne Teilnehmerpflege darf
deshalb importieren, aber keine Personen anlegen.
"""
from datetime import date

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.api.routes import word_import as word_import_routes
from app.models import Participant
from app.schemas.word_import import (
    PublicWordImportAttendanceCommit,
    PublicWordImportCommit,
    PublicWordImportFormFieldValue,
    PublicWordImportNameResolution,
    PublicWordImportTextCommit,
)
from tests.factories import make_current_user, make_template, make_tenant, system_role_permissions
from tests.test_word_import_e2e import _build_template

PROTOKOLLFUEHRUNG = frozenset({"meetings.read", "meetings.read_drafts", "meetings.edit"})


def _participant_count(db, tenant_id: int) -> int:
    return db.scalar(select(func.count(Participant.id)).where(Participant.tenant_id == tenant_id))


def _attendance_payload(template, *, create_new: bool, participant=None) -> PublicWordImportCommit:
    return PublicWordImportCommit(
        template_id=template.public_id,
        protocol_date=date(2026, 3, 5),
        attendance=[
            PublicWordImportAttendanceCommit(
                raw_name="Ganz Neue Person",
                participant_id=participant.public_id if participant is not None else None,
                participant_name="Ganz Neue Person",
                status="present",
                create_new=create_new,
            )
        ],
    )


def test_word_import_without_participant_rights_cannot_create_people_from_attendance(db):
    ctx = _build_template(db)
    tenant, template = ctx["tenant"], ctx["template"]
    before = _participant_count(db, tenant.id)
    user = make_current_user(tenant.id, permissions=PROTOKOLLFUEHRUNG)

    with pytest.raises(HTTPException) as exc_info:
        word_import_routes.commit_word_import(_attendance_payload(template, create_new=True), db=db, user=user)
    assert exc_info.value.status_code == 403
    assert _participant_count(db, tenant.id) == before


def test_word_import_without_participant_rights_cannot_create_people_from_form_names(db):
    tenant = make_tenant(db, "Word-Import Rechte B")
    template = make_template(db, tenant.id, name="Hock")
    db.flush()
    user = make_current_user(tenant.id, permissions=PROTOKOLLFUEHRUNG)
    payload = PublicWordImportCommit(
        template_id=template.public_id,
        protocol_date=date(2026, 3, 5),
        texts=[
            PublicWordImportTextCommit(
                extracted_heading="Scharanlässe",
                content="",
                is_form_block=True,
                form_fields=[
                    PublicWordImportFormFieldValue(
                        row_id="r1", label="Leitung", row_type="participant",
                        names=[PublicWordImportNameResolution(raw_name="Ganz Neue Person", create_new=True)],
                    )
                ],
            )
        ],
    )
    with pytest.raises(HTTPException) as exc_info:
        word_import_routes.commit_word_import(payload, db=db, user=user)
    assert exc_info.value.status_code == 403


def test_word_import_with_participant_rights_still_creates_people(db):
    """Gegenprobe: Standardrolle Schreiber (meetings.edit + participants.manage)."""
    ctx = _build_template(db)
    tenant, template = ctx["tenant"], ctx["template"]
    before = _participant_count(db, tenant.id)
    writer = make_current_user(tenant.id, permissions=system_role_permissions("writer"))
    word_import_routes.commit_word_import(_attendance_payload(template, create_new=True), db=db, user=writer)
    assert _participant_count(db, tenant.id) == before + 1


def test_word_import_without_participant_rights_still_links_existing_people(db):
    """Gegenprobe: Protokollführung ohne Teilnehmerpflege importiert weiter, solange sie nur
    bestehende Personen zuordnet."""
    ctx = _build_template(db)
    tenant, template = ctx["tenant"], ctx["template"]
    before = _participant_count(db, tenant.id)
    protokollfuehrung = make_current_user(tenant.id, permissions=PROTOKOLLFUEHRUNG)
    word_import_routes.commit_word_import(
        _attendance_payload(template, create_new=False, participant=ctx["participants"]["Timo Weber"]), db=db, user=protokollfuehrung
    )
    assert _participant_count(db, tenant.id) == before
