"""Persönlicher Link für Verantwortliche einer Abgabe (Migration 0181,
app/services/submission_access_service.py, routes/public_submission_access.py)."""
from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.routes import public_submission_access as route
from app.core.db import get_db
from app.models import Notification, ProtocolTodo, SubmissionAccessToken, TodoStatus
from app.notifications import dispatch
from app.public_links import collect_all
from app.services import submission_access_service as access_service
from app.services.submission_service import SubmissionService
from tests.factories import make_app_user, make_tenant
from tests.test_submission_done_notifications import _enable_email, _submit, box, sent  # noqa: F401 (Fixtures)
from tests.test_submission_upload_rules import PDF


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch):
    monkeypatch.setattr(route, "enforce_rate_limit", lambda *args, **kwargs: None)


def _client(db) -> TestClient:
    app = FastAPI()
    app.include_router(route.router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


def _manage(box, level: str = "manage"):
    """Option setzen und Abgabebox buchen (Testmandanten haben sie standardmässig nicht)."""
    from sqlalchemy.orm import object_session

    from app.models.entities import TenantFeature

    box["assignment"].owner_access = level
    db = object_session(box["assignment"])
    exists = db.scalar(select(TenantFeature.id).where(TenantFeature.tenant_id == box["tenant"].id, TenantFeature.feature_code == "abgabebox"))
    if exists is None:
        db.add(TenantFeature(tenant_id=box["tenant"].id, feature_code="abgabebox"))
        db.flush()


def _element_ref(db, box) -> str:
    return SubmissionService().get_assignment_elements(db, box["assignment"])[0].element_ref


def _issue(db, box, person: str = "anna") -> str:
    token = access_service.issue(db, assignment=box["assignment"], element_ref=_element_ref(db, box), participant_id=box[person].id)
    db.flush()
    assert token
    return token


def _status_code(db, todo) -> str:
    db.refresh(todo)
    return db.scalar(select(TodoStatus.code).where(TodoStatus.id == todo.todo_status_id))


def test_link_needs_the_option_and_stores_only_a_hash(db, box):
    assert access_service.issue(db, assignment=box["assignment"], element_ref=_element_ref(db, box), participant_id=box["anna"].id) is None
    _manage(box)
    token = _issue(db, box)
    rows = db.scalars(select(SubmissionAccessToken)).all()
    assert len(rows) == 1 and rows[0].token_hash == access_service.hash_token(token) and token not in rows[0].token_hash
    access = access_service.resolve(db, token)
    assert access is not None and access.level == "manage" and access.person.id == box["anna"].id


def test_invalid_links_all_look_the_same(db, box):
    _manage(box)
    token = _issue(db, box)
    assert access_service.resolve(db, "x" * 43) is None
    # Option abgeschaltet
    box["assignment"].owner_access = "off"
    assert access_service.resolve(db, token) is None
    _manage(box)
    # abgelaufen und widerrufen
    row = db.scalar(select(SubmissionAccessToken))
    row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    assert access_service.resolve(db, token) is None
    row.expires_at = datetime.now(UTC) + timedelta(days=1)
    row.revoked_at = datetime.now(UTC)
    assert access_service.resolve(db, token) is None
    row.revoked_at = None
    # nicht mehr verantwortlich (auch nicht mehr an der Aufgabe)
    assert access_service.resolve(db, token) is not None
    box["event"].spezial1_ids = [box["ben"].id]
    todo: ProtocolTodo = box["todo"]
    todo.assigned_participant_id = box["ben"].id
    from app.services.task_package_service import set_todo_assignees

    set_todo_assignees(db, todo, [box["ben"].id])
    db.flush()
    assert access_service.resolve(db, token) is None


def test_view_only_link_cannot_withdraw_or_upload(db, box):
    _manage(box, "view")
    _submit(db, box)
    token = _issue(db, box)
    client = _client(db)
    view = client.post("/api/public/submission-access/view", json={"token": token}).json()
    assert view["can_withdraw"] is False and view["can_upload"] is False and len(view["files"]) == 1
    assert client.post("/api/public/submission-access/withdraw", json={"token": token, "confirm": True}).status_code == 409


def test_withdraw_keeps_files_reopens_the_todo_and_can_be_restored(db, box):
    _manage(box)
    _submit(db, box)
    assert _status_code(db, box["todo"]) == "done"
    token = _issue(db, box)
    client = _client(db)
    response = client.post("/api/public/submission-access/withdraw", json={"token": token, "confirm": True})
    assert response.status_code == 200, response.text
    view = response.json()
    assert view["files"] == [] and view["status"] == "open" and view["can_upload"] is True
    assert _status_code(db, box["todo"]) == "open"
    element = SubmissionService().get_assignment_elements(db, box["assignment"])[0]
    assert element.withdrawn_count == 1 and element.files == []
    # Verwaltung stellt wieder her
    restored = access_service.restore(db, box["assignment"], element.element_ref)
    assert restored == 1
    element = SubmissionService()._element_with_todo_sync(db, box["assignment"], element.element_ref)
    assert len(element.files) == 1 and element.withdrawn_count == 0


def test_upload_over_the_link_counts_for_the_element(db, box, monkeypatch):
    from app.services import file_service as file_service_module

    async def clean_scan(contents, **kwargs):
        return ["clean"] * len(contents)

    monkeypatch.setattr(file_service_module.scanner, "scan_many", clean_scan)
    from app.services.submission_service import local_today

    box["event"].event_date = local_today()  # Zeitfenster offen
    _manage(box)
    token = _issue(db, box)
    client = _client(db)
    response = client.post(
        "/api/public/submission-access/upload", headers={route.TOKEN_HEADER: token}, files=[("files", ("bericht.pdf", PDF, "application/pdf"))],
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["errors"] == [] and [file["name"] for file in body["view"]["files"]] == ["bericht.pdf"]
    assert _status_code(db, box["todo"]) == "done"


def test_download_only_files_of_the_own_element(db, box):
    _manage(box)
    _submit(db, box)
    token = _issue(db, box)
    client = _client(db)
    response = client.post("/api/public/submission-access/download", json={"token": token, "file_id": "00000000-0000-0000-0000-000000000000"})
    assert response.status_code == 404
    assert client.post("/api/public/submission-access/view", json={"token": "falsch-falsch-falsch"}).status_code == 404


def test_link_of_another_tenant_never_reaches_this_tenant(db, box):
    _manage(box)
    token = _issue(db, box)
    other = make_tenant(db, "Fremd")
    make_app_user(db, "fremd@example.com", tenant_id=other.id, first_name="F", last_name="F")
    access = access_service.resolve(db, token)
    assert access is not None and access.assignment.tenant_id == box["tenant"].id
    assert not any(link.kind == "submission_access" for link in collect_all(db, other.id))
    assert any(link.kind == "submission_access" for link in collect_all(db, box["tenant"].id))


def test_mails_carry_the_personal_link_also_without_login(db, box, sent):
    _manage(box)
    # Ben ohne Login, aber mit Mails ohne Login
    box["ben"].login_enabled = False
    box["ben"].password_hash = None
    box["ben"].notify_without_login = True
    _submit(db, box)
    _enable_email(db)
    from app.notifications import todos as todo_notifications

    todo_notifications.scan_submission_done(db)  # legt «Abgabe eingegangen» an (2 Minuten Bündelung)
    for row in db.scalars(select(Notification).where(Notification.status == "pending")):
        row.deliver_after = datetime.now(UTC) - timedelta(minutes=1)
    db.flush()
    dispatch.run(db)
    ben_mail = next(mail for mail in sent if mail.to == "ben@example.com")
    match = re.search(r"/abgabe/verwalten#([A-Za-z0-9_\-]+)", ben_mail.text)
    assert match, ben_mail.text
    assert "/todos" not in ben_mail.text  # sonst keine Links in die App ohne Login
    access = access_service.resolve(db, match.group(1))
    assert access is not None and access.person.id == box["ben"].id


def test_inactive_assignment_and_closed_window_limit_the_link(db, box):
    from app.services.submission_service import local_today

    box["event"].event_date = local_today()  # Zeitfenster offen
    _manage(box)
    _submit(db, box)
    token = _issue(db, box)
    access = access_service.resolve(db, token)
    assert access_service.can_upload(access) and access_service.can_withdraw(access)
    # Fenster vorbei: kein neues Hochladen, Zurückziehen geht weiter
    box["event"].event_date = local_today() - timedelta(days=30)
    db.flush()
    access = access_service.resolve(db, token)
    assert not access_service.can_upload(access) and access_service.can_withdraw(access)
    access_service.withdraw(db, access)
    access = access_service.resolve(db, token)
    assert access_service.can_upload(access)  # nach dem Zurückziehen darf neu abgegeben werden
    # Deaktiviert: nur noch ansehen
    box["assignment"].is_active = False
    db.flush()
    access = access_service.resolve(db, token)
    assert access.level == "view" and not access_service.can_upload(access) and not access_service.can_withdraw(access)


# ── Teil 2: abgeschlossen (Migration 0182) ───────────────────────────


def test_assignment_is_completed_when_everything_is_in_and_the_window_is_over(db, box):
    from app.services.submission_service import local_today

    service = SubmissionService()
    box["event"].event_date = local_today()  # Fenster läuft noch 7 Tage
    db.flush()
    _submit(db, box)
    service.sync_submission_todos(db, box["assignment"])
    assert box["assignment"].completed_at is None  # es kann noch etwas dazukommen
    box["event"].event_date = local_today() - timedelta(days=30)
    db.flush()
    service.sync_submission_todos(db, box["assignment"])
    assert box["assignment"].completed_at is not None
    # Zurückziehen öffnet die Abgabe wieder
    _manage(box)
    access = access_service.resolve(db, _issue(db, box))
    access_service.withdraw(db, access)
    assert box["assignment"].completed_at is None


def test_closed_elements_count_quarantine_does_not(db, box):
    from app.models import StoredFile
    from app.services.submission_service import local_today

    service = SubmissionService()
    box["event"].event_date = local_today() - timedelta(days=30)
    db.flush()
    _submit(db, box)
    db.execute(StoredFile.__table__.update().where(StoredFile.tenant_id == box["tenant"].id).values(scan_status="pending"))
    db.flush()
    assert service.assignment_completion(db, box["assignment"]) is False
    element = service.get_assignment_elements(db, box["assignment"])[0]
    service.close_element(db, box["assignment"], element.element_ref)
    assert box["assignment"].completed_at is not None


# ── Teil 3: Gültigkeit, Mail an die Verwaltung, Aufräumen ────────────


def test_link_validity_follows_the_assignment(db, box):
    _manage(box)
    box["assignment"].owner_access_days = 3
    _issue(db, box)
    row = db.scalar(select(SubmissionAccessToken))
    assert timedelta(days=2, hours=23) < row.expires_at - row.created_at <= timedelta(days=3)


def test_withdraw_notifies_the_managers_until_restored(db, box, sent):
    from app.notifications import preferences as notification_preferences
    from app.notifications import submissions as submission_notifications

    chef = make_app_user(db, "chef@example.com", tenant_id=box["tenant"].id, first_name="Chef", last_name="C", role_code="admin")
    assert submission_notifications.managers(db, box["tenant"].id) == [chef.id]
    # Die Einstellung sehen nur Personen, die Abgaben verwalten
    categories = lambda user: {p.category for p in notification_preferences.read(db, user.id, box["tenant"].id).preferences}  # noqa: E731
    assert "submission_changes" in categories(chef) and "submission_changes" not in categories(box["anna"])
    _manage(box)
    _submit(db, box)
    access_service.withdraw(db, access_service.resolve(db, _issue(db, box)))
    rows = db.scalars(select(Notification).where(Notification.kind == "submission.withdrawn")).all()
    assert [row.recipient_id for row in rows] == [chef.id]
    _enable_email(db)
    db.execute(Notification.__table__.update().values(deliver_after=datetime.now(UTC) - timedelta(minutes=1)))
    dispatch.run(db)
    [mail] = [mail for mail in sent if mail.to == "chef@example.com"]
    assert "Badetag" in mail.text and "Anna A" in mail.text
    # Wiederhergestellt, bevor die Mail rausging: überholt
    sent.clear()
    _submit(db, box)
    access_service.withdraw(db, access_service.resolve(db, _issue(db, box)))
    element = SubmissionService().get_assignment_elements(db, box["assignment"])[0]
    assert element.withdrawn_count == 2
    access_service.restore(db, box["assignment"], element.element_ref)
    db.flush()
    db.execute(Notification.__table__.update().values(deliver_after=datetime.now(UTC) - timedelta(minutes=1)))
    dispatch.run(db)
    assert not [mail for mail in sent if mail.to == "chef@example.com"]


def test_cleanup_removes_old_links_and_withdrawn_files(db, box):
    from app.models import SubmissionUploadFile

    _manage(box)
    _submit(db, box)
    token = _issue(db, box)
    access_service.withdraw(db, access_service.resolve(db, token))
    long_ago = datetime.now(UTC) - timedelta(days=31)
    db.execute(SubmissionUploadFile.__table__.update().values(withdrawn_at=long_ago))
    db.execute(SubmissionAccessToken.__table__.update().values(revoked_at=long_ago))
    db.flush()
    result = access_service.cleanup(db)
    assert result["tokens"] == 1 and result["files"] == 1
    assert db.scalar(select(SubmissionUploadFile.id)) is None
    assert db.scalar(select(SubmissionAccessToken.id)) is None
