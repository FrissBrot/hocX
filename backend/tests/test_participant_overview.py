"""Mitgliederliste und Personenseite (Konzept «Personen an einem Ort»): Login-Status, Rollen,
Tarif in der Liste und die Mehrfachaktionen Einladen / Rollen hinzufügen-entfernen."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api.routes import participants as participant_routes
from app.notifications import email_transport
from app.models import AppUser, FineTariffGroup
from app.schemas.participant import ParticipantBulkInvite, ParticipantBulkRoles
from app.services import role_service
from app.services.notification_settings_service import NotificationSettingsService
from tests.factories import assign_roles, make_app_user, make_current_user, make_participant, make_tenant


def _actor(db, tenant, role="admin"):
    """CurrentUser mit echtem Konto (Audit-Einträge verweisen per Fremdschlüssel auf app_user)."""
    account = make_app_user(db, f"actor-{role}-{tenant.id}@example.com", tenant_id=tenant.id, role_code=role)
    actor = make_current_user(tenant.id, role=role, user_id=account.id)
    actor.current_tenant_public_id = tenant.public_id
    return actor


@pytest.fixture
def mail(db, monkeypatch):
    row = NotificationSettingsService().get_row(db)
    row.email_enabled = True
    row.smtp_host = "smtp.example.com"
    row.email_from_address = "noreply@example.com"
    row.email_link_base_url = "https://app.example.com"
    monkeypatch.setattr(participant_routes, "enforce_rate_limit", lambda *args, **kwargs: None)
    email_transport.override_transport(lambda config, email: None)
    yield
    email_transport.override_transport(None)


def _person(db, tenant, name, email=None):
    person = make_participant(db, tenant.id, name)
    person.email = email
    db.flush()
    return person


def test_list_has_login_status_roles_and_tariff_only_for_finance(db, mail):
    tenant = make_tenant(db)
    login = make_app_user(db, "login@example.com", tenant_id=tenant.id, role_code="writer")
    invited = _person(db, tenant, "Eingeladen", "eingeladen@example.com")
    plain = _person(db, tenant, "Ohne")
    group = FineTariffGroup(tenant_id=tenant.id, name="Lernende", sort_index=1, is_default=False)
    db.add(group)
    db.flush()
    plain.fine_tariff_group_id = group.id
    db.flush()
    admin_actor = _actor(db, tenant)
    participant_routes.invite_participant(invited.public_id, db, admin_actor)

    rows = {row.id: row for row in participant_routes.list_participants(active_only=False, include_former=True, skip=0, limit=100, db=db, user=admin_actor)}
    assert rows[login.public_id].login_status == "active"
    assert [role.system_key for role in rows[login.public_id].roles] == ["writer"]
    assert rows[invited.public_id].login_status == "invited"
    assert rows[plain.public_id].login_status == "none"
    assert rows[plain.public_id].tariff_id == group.public_id

    # Ohne finances.read kein Tarif (der Tarif sagt etwas über die Person aus).
    writer = _actor(db, tenant, role="writer")
    writer.permissions = writer.permissions - {"finances.read", "finances.manage"}
    rows = {row.id: row for row in participant_routes.list_participants(active_only=False, include_former=True, skip=0, limit=100, db=db, user=writer)}
    assert rows[plain.public_id].tariff_id is None


def test_get_participant_of_other_tenant_is_404(db):
    own = make_tenant(db, "Own")
    other = make_tenant(db, "Other")
    stranger = _person(db, other, "Fremd")
    with pytest.raises(HTTPException) as exc_info:
        participant_routes.get_participant(stranger.public_id, db=db, user=_actor(db, own))
    assert exc_info.value.status_code == 404


def test_bulk_invite_skips_and_sets_role(db, mail):
    tenant = make_tenant(db)
    other = make_tenant(db, "Other")
    ok = _person(db, tenant, "Mit Mail", "mit-mail@example.com")
    no_mail = _person(db, tenant, "Ohne Mail")
    has_login = make_app_user(db, "hat-login@example.com", tenant_id=tenant.id)
    stranger = _person(db, other, "Fremd", "fremd@example.com")
    kassier = role_service.system_role(db, tenant.id, "kassier")

    result = participant_routes.bulk_invite_participants(
        ParticipantBulkInvite(participant_ids=[ok.public_id, no_mail.public_id, has_login.public_id, stranger.public_id], role_id=kassier.public_id),
        db=db, user=_actor(db, tenant),
    )

    assert result.done == [ok.public_id]
    reasons = {item.participant_id: item.reason for item in result.skipped}
    assert reasons == {no_mail.public_id: "no_email", has_login.public_id: "has_login", stranger.public_id: "not_found"}
    assert [role.system_key for role in role_service.roles_by_user(db, [ok.id])[ok.id]] == ["kassier"]
    assert role_service.roles_by_user(db, [no_mail.id]).get(no_mail.id, [])[0].system_key == "reader"


def test_bulk_routes_need_access_manage(db):
    tenant = make_tenant(db)
    person = _person(db, tenant, "Person", "person@example.com")
    reader = role_service.system_role(db, tenant.id, "reader")
    writer = _actor(db, tenant, role="writer")  # participants.manage, aber kein access.manage
    with pytest.raises(HTTPException) as exc_info:
        participant_routes.bulk_invite_participants(ParticipantBulkInvite(participant_ids=[person.public_id]), db=db, user=writer)
    assert exc_info.value.status_code == 403
    with pytest.raises(HTTPException) as exc_info:
        participant_routes.bulk_participant_roles(
            ParticipantBulkRoles(participant_ids=[person.public_id], role_ids=[reader.public_id], mode="add"), db=db, user=writer,
        )
    assert exc_info.value.status_code == 403


def test_bulk_roles_add_remove_and_guards(db):
    tenant = make_tenant(db)
    person = _person(db, tenant, "Person")
    writer_role = role_service.system_role(db, tenant.id, "writer")
    reader_role = role_service.system_role(db, tenant.id, "reader")
    admin_role = role_service.system_role(db, tenant.id, "admin")
    actor = _actor(db, tenant)
    admin = db.get(AppUser, actor.user_id)  # einziger Admin = der Handelnde selbst

    added = participant_routes.bulk_participant_roles(
        ParticipantBulkRoles(participant_ids=[person.public_id], role_ids=[writer_role.public_id], mode="add"), db=db, user=actor,
    )
    assert added.done == [person.public_id]
    assert {role.system_key for role in role_service.roles_by_user(db, [person.id])[person.id]} == {"reader", "writer"}

    # Entfernen der letzten Rolle wird übersprungen
    participant_routes.bulk_participant_roles(
        ParticipantBulkRoles(participant_ids=[person.public_id], role_ids=[reader_role.public_id], mode="remove"), db=db, user=actor,
    )
    only_writer = participant_routes.bulk_participant_roles(
        ParticipantBulkRoles(participant_ids=[person.public_id], role_ids=[writer_role.public_id], mode="remove"), db=db, user=actor,
    )
    assert [item.reason for item in only_writer.skipped] == ["no_roles_left"]

    # Letzter Administrator: Schutzregel aus role_service greift, wird übersprungen
    assign_roles(db, admin, "admin", "reader")
    db.commit()
    last_admin = participant_routes.bulk_participant_roles(
        ParticipantBulkRoles(participant_ids=[admin.public_id], role_ids=[admin_role.public_id], mode="remove"), db=db, user=actor,
    )
    assert last_admin.done == []
    assert [item.reason for item in last_admin.skipped] == ["protected"]


def test_bulk_invite_keeps_role_when_the_invite_fails(db, mail, monkeypatch):
    """Die Rolle soll nur ändern, wer tatsächlich eingeladen wird: scheitert die Einladung (hier am
    Benutzerlimit), bleibt die bisherige Rolle - die Person steht ja als übersprungen da."""
    tenant = make_tenant(db)
    actor = _actor(db, tenant)  # einziger Login
    tenant.user_limit_override = 1
    person = _person(db, tenant, "Am Limit", "am-limit@example.com")
    kassier = role_service.system_role(db, tenant.id, "kassier")
    person_id, person_public_id, kassier_id = person.id, person.public_id, kassier.public_id
    db.commit()
    # Die Testsitzung rollt bei db.rollback() alles zurück (auch Committetes); in Produktion bleibt
    # ein bereits committeter Rollenwechsel bestehen. Darum hier wie dort: nur Offenes verwerfen.
    monkeypatch.setattr(db, "rollback", lambda: None)
    result = participant_routes.bulk_invite_participants(
        ParticipantBulkInvite(participant_ids=[person_public_id], role_id=kassier_id), db=db, user=actor,
    )
    assert result.done == []
    assert [item.participant_id for item in result.skipped] == [person_public_id]
    assert [role.system_key for role in role_service.roles_by_user(db, [person_id])[person_id]] == ["reader"]


def test_user_limit_has_stable_code_and_own_bulk_reason(db, mail):
    """Benutzerlimit: deutscher Satz ohne Code erschien in en/fr/it roh; in der Mehrfach-Einladung
    hiess der Grund «Schutzregel, z. B. letzter Admin»."""
    tenant = make_tenant(db)
    actor = _actor(db, tenant)
    tenant.user_limit_override = 1  # der Admin selbst belegt den einzigen Platz
    db.flush()
    person = _person(db, tenant, "Zu viel", "zu-viel@example.com")
    with pytest.raises(HTTPException) as single:
        participant_routes.invite_participant(person.public_id, db=db, user=actor)
    assert single.value.status_code == 409
    assert single.value.detail["code"] == "user_limit_reached"
    assert single.value.detail["params"] == {"limit": 1}
    result = participant_routes.bulk_invite_participants(ParticipantBulkInvite(participant_ids=[person.public_id]), db=db, user=actor)
    assert [(item.participant_id, item.reason) for item in result.skipped] == [(person.public_id, "user_limit")]
