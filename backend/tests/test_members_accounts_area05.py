"""Bereichs-Audit 05 (Mitglieder, Rollen, Konto), 2026-11: Regressionstests zu den Befunden."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi import HTTPException, Response
from sqlalchemy import select, update

from app.api.routes import participants as participant_routes
from app.api.routes import users as user_routes
from app.core.permissions import P
from app.core.security import verify_password
from app.models import AccountToken, ListDefinition, ListEntry, Participant, SystemErrorLog
from app.notifications import account
from app.schemas.participant import ParticipantCreate, ParticipantUpdate
from app.schemas.user import UserPasswordChange, UserUpdate
from app.services import role_service
from app.services.participant_service import ParticipantService
from tests.factories import assign_roles, make_app_user, make_current_user, make_participant, make_tenant

PASSWORD = "ein-sehr-langes-passwort"


def _admin(tenant, user_id: int = 999999):
    actor = make_current_user(tenant.id, role="admin", user_id=user_id)
    actor.current_tenant_public_id = tenant.public_id
    return actor


# ── notify_without_login ging beim Admin-Speichern verloren ──


def test_admin_save_keeps_notify_without_login(db):
    tenant = make_tenant(db)
    person = make_participant(db, tenant.id, "Ohne Login")
    person.email = "ohne-login@example.com"
    db.flush()
    # So schickt das Frontend als Admin: immer mit login_enabled -> Weg über UserService.
    payload = ParticipantUpdate(display_name="Ohne Login", login_enabled=False, notify_without_login=True)
    participant_routes.patch_participant(person.public_id, payload, db, _admin(tenant))
    db.refresh(person)
    assert person.notify_without_login is True

    participant_routes.patch_participant(person.public_id, ParticipantUpdate(login_enabled=False, notify_without_login=False), db, _admin(tenant))
    db.refresh(person)
    assert person.notify_without_login is False


def test_explicit_null_does_not_clear_notify_without_login(db):
    tenant = make_tenant(db)
    person = make_participant(db, tenant.id, "Person")
    person.notify_without_login = True
    db.flush()
    participant_routes.patch_participant(person.public_id, ParticipantUpdate(login_enabled=False, notify_without_login=None), db, _admin(tenant))
    db.refresh(person)
    assert person.notify_without_login is True


# ── CSV-Import: Duplikate über alle Personen, kuratierte Fehler ──


def test_csv_import_detects_duplicates_beyond_first_hundred(db):
    tenant = make_tenant(db)
    service = ParticipantService()
    for index in range(120):
        db.add(Participant(tenant_id=tenant.id, display_name=f"Person {index:03d}", login_enabled=False))
    db.flush()
    # «Zz»-Namen sortieren hinter die ersten 100 - früher fielen sie aus der Duplikatprüfung.
    db.add(Participant(tenant_id=tenant.id, display_name="Zz Späte Person", email="spaet@example.com", login_enabled=False))
    db.flush()
    csv_text = "Vorname;Nachname;E-Mail\nZz Späte;Person;\nPerson;119;\nNeu;Anders;spaet@example.com\nWirklich;Neu;neu@example.com\n"
    result = service.import_csv(db, csv_text, tenant_id=tenant.id)
    assert sorted(result.duplicates) == ["Neu Anders", "Person 119", "Zz Späte Person"]
    assert [row.display_name for row in result.imported] == ["Wirklich Neu"]
    # Spalte «E-Mail» wird erkannt (früher nur «Haupt-E-Mail»).
    assert result.imported[0].email == "neu@example.com"
    # Erneuter Import legt nichts doppelt an.
    again = service.import_csv(db, csv_text, tenant_id=tenant.id)
    assert again.imported == []


def test_csv_import_errors_are_curated_and_logged(db, monkeypatch):
    tenant = make_tenant(db)

    def boom(_db, _participant):
        raise RuntimeError("geheimes SQL-Detail")

    monkeypatch.setattr(role_service, "assign_default_role", boom)
    result = ParticipantService().import_csv(db, "Vorname;Nachname\nAnna;Muster\n", tenant_id=tenant.id)
    assert result.errors == ["2"]
    assert all("SQL" not in error for error in result.errors)
    logged = db.scalars(select(SystemErrorLog).where(SystemErrorLog.tenant_id == tenant.id)).all()
    assert any("geheimes SQL-Detail" in (row.error_message or "") for row in logged)


# ── Deaktivieren über /participants beendet Sessions ──


def test_deactivation_via_participants_revokes_sessions(db):
    tenant = make_tenant(db)
    make_app_user(db, "admin@example.com", tenant_id=tenant.id, role_code="admin")
    person = make_app_user(db, "person@example.com", tenant_id=tenant.id)
    assert person.session_revoke_at is None
    ParticipantService().update_participant(db, person.id, ParticipantUpdate(is_active=False), tenant_id=tenant.id)
    assert person.session_revoke_at is not None


def test_reactivation_does_not_touch_session_revoke(db):
    tenant = make_tenant(db)
    person = make_participant(db, tenant.id, "Ohne Login")
    person.is_active = False
    db.flush()
    ParticipantService().update_participant(db, person.id, ParticipantUpdate(is_active=True), tenant_id=tenant.id)
    assert person.session_revoke_at is None


# ── Massenlöschen: gesammelt, Listenverweise einmal bereinigt ──


def test_bulk_delete_clears_list_references_for_all(db):
    tenant = make_tenant(db)
    people = [make_participant(db, tenant.id, f"Weg {index}") for index in range(3)]
    keep = make_participant(db, tenant.id, "Bleibt")
    definition = ListDefinition(tenant_id=tenant.id, name="Liste", column_one_title="A", column_one_value_type="participants", column_two_title="B", column_two_value_type="text")
    db.add(definition)
    db.flush()
    entry = ListEntry(list_definition_id=definition.id, column_one_value_json={"participant_ids": [people[0].id, keep.id, people[2].id]}, column_two_value_json={})
    db.add(entry)
    db.flush()
    deleted = ParticipantService().delete_participants(db, [person.id for person in people] + [987654321], tenant_id=tenant.id)
    assert deleted == 3
    db.refresh(entry)
    assert entry.column_one_value_json["participant_ids"] == [keep.id]


# ── Einladung an Höherberechtigte ──


def test_invite_of_higher_privileged_person_is_rejected(db, monkeypatch):
    monkeypatch.setattr(participant_routes, "enforce_rate_limit", lambda *args, **kwargs: None)
    tenant = make_tenant(db)
    target = make_participant(db, tenant.id, "Künftige Admin")
    target.email = "kuenftig@example.com"
    assign_roles(db, target, "admin")
    db.flush()
    limited = make_current_user(tenant.id, role="writer", user_id=999999, permissions=frozenset({P.PARTICIPANTS_MANAGE.value, P.ACCESS_MANAGE.value}))
    with pytest.raises(HTTPException) as error:
        participant_routes.invite_participant(target.public_id, db, limited)
    assert error.value.status_code == 403
    assert error.value.detail["code"] == "permission_not_held"


# ── Einlösen: Zeilensperre sieht den aktuellen Stand ──


def test_complete_rejects_link_used_concurrently(db, monkeypatch):
    tenant = make_tenant(db)
    person = make_participant(db, tenant.id, "Eingeladen")
    person.email = "eingeladen@example.com"
    db.flush()
    row = account.invite(db, person, actor_user_id=person.id)
    row.token_hash = account.hash_token("geheimer-token")
    row.expires_at = datetime.now(timezone.utc) + timedelta(days=1)
    db.flush()
    stale = db.get(AccountToken, row.id)
    # Ein zweiter Request hat den Link inzwischen eingelöst - an der Identity-Map vorbei.
    db.execute(
        update(AccountToken).where(AccountToken.id == row.id).values(used_at=datetime.now(timezone.utc)).execution_options(synchronize_session=False)
    )
    assert stale.used_at is None
    monkeypatch.setattr(account, "_valid_token", lambda _db, _token: (stale, person))
    with pytest.raises(HTTPException) as error:
        account.complete(db, "geheimer-token", PASSWORD)
    assert error.value.status_code == 400
    assert not person.login_enabled


# ── PATCH /users: ValueError -> 400, eigener Passwortwechsel mit neuem Cookie ──


def test_patch_user_with_left_before_joined_is_400(db):
    tenant = make_tenant(db)
    person = make_participant(db, tenant.id, "Person")
    with pytest.raises(HTTPException) as error:
        user_routes.patch_user(person.public_id, UserUpdate(joined_at=date(2026, 5, 1), left_at=date(2026, 1, 1)), db, _admin(tenant))
    assert error.value.status_code == 400


def test_own_password_change_issues_new_session_cookie(db):
    tenant = make_tenant(db)
    person = make_app_user(db, "selbst@example.com", password=PASSWORD, tenant_id=tenant.id)
    actor = make_current_user(tenant.id, role="reader", user_id=person.id)
    response = Response()
    user_routes.change_my_password(UserPasswordChange(current_password=PASSWORD, new_password="noch-ein-langes-passwort"), response, db, actor)
    assert "hocx_session=" in response.headers.get("set-cookie", "")
    assert verify_password("noch-ein-langes-passwort", person.password_hash)
    assert person.session_revoke_at is not None


def test_wrong_current_password_has_stable_code(db):
    tenant = make_tenant(db)
    person = make_app_user(db, "falsch@example.com", password=PASSWORD, tenant_id=tenant.id)
    actor = make_current_user(tenant.id, role="reader", user_id=person.id)
    with pytest.raises(HTTPException) as error:
        user_routes.change_my_password(UserPasswordChange(current_password="nicht-das-passwort", new_password="noch-ein-langes-passwort"), Response(), db, actor)
    assert error.value.status_code == 400
    assert error.value.detail["code"] == "wrong_current_password"


def test_invite_link_marks_purpose_in_fragment(db, monkeypatch):
    tenant = make_tenant(db)
    person = make_participant(db, tenant.id, "Link")
    person.email = "link@example.com"
    db.flush()
    row = account.invite(db, person, actor_user_id=person.id)
    notification = type("N", (), {"id": 1, "subject_id": row.id, "tenant_id": tenant.id, "kind": "account.invite"})()
    items = account.link_items_for(db, [notification], person.id, base_url="https://app.example.com")
    assert items[1]["link"].endswith("&kind=invite")
    assert "#token=" in items[1]["link"]


def test_create_participant_unaffected(db):
    tenant = make_tenant(db)
    created = ParticipantService().create_participant(db, ParticipantCreate(display_name="Neu"), tenant_id=tenant.id)
    assert created.session_revoke_at is None
