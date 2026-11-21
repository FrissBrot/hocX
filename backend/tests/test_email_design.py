"""Mail-Design «hocX E-Mails» (app/notifications/render.py) und die Bussen-Mails M11/M12
(app/notifications/fines.py)."""
from __future__ import annotations

import re

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models import Notification
from app.notifications import dispatch, email_transport
from app.notifications import todos as todo_notifications
from app.notifications.render import Brand, render, render_test
from app.schemas.protocol import ProtocolUpdate
from app.services.notification_settings_service import NotificationSettingsService
from app.services.protocol_service import ProtocolService
from tests.factories import make_fine, make_protocol, make_template
from tests.test_todo_fines import TODAY, _complete, _rule, _todo, setup  # noqa: F401 (Fixture)

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


def _todo_items(due: date | None = date(2026, 11, 21)) -> list[dict]:
    return [{"kind": "todo.assigned", "task": "Zelt <flicken>", "due": due, "source": "Vorstand 9"}]


def _render(**overrides):
    args = dict(
        lang="de", group="todo.new", items=_todo_items(), recipient_name="Anna", tenant_name="Musterverein Seeland",
        base_url="https://app.example.com", can_login=True,
    )
    args.update(overrides)
    return render(**args)


def test_frame_has_brand_card_and_one_action_for_people_with_login():
    mail = _render()
    assert mail.subject == "Musterverein Seeland: Neue Aufgaben für dich"
    assert "Neue Aufgaben für dich" in mail.html and "über hocX" in mail.html
    assert "Neue Aufgaben · 1" in mail.html and "fällig 21.11.2026" in mail.html
    assert mail.html.count('href="https://app.example.com/todos"') == 1
    assert 'href="https://app.example.com/?profile=notifications"' in mail.html
    # Werte aus Daten escaped, kein Flexbox, keine nachgeladenen Ressourcen
    assert "Zelt &lt;flicken&gt;" in mail.html and "<flicken>" not in mail.html
    assert "display:flex" not in mail.html and "fonts.googleapis" not in mail.html
    # Apple Mail macht «In 3 Tagen» sonst zu einem blauen Kalender-Link
    assert 'content="telephone=no,date=no,address=no,email=no"' in mail.html and "x-apple-data-detectors" in mail.html
    # ohne Logo: Initialen, keine eingebetteten Bilder
    assert ">MS<" in mail.html and mail.images == ()


def test_no_links_into_the_app_without_login():
    mail = _render(can_login=False)
    assert "/todos" not in mail.html and "?profile=notifications" not in mail.html and "/todos" not in mail.text
    assert "Fragen zu dieser Nachricht? Wende dich an Musterverein Seeland." in mail.html


def test_logo_is_embedded_not_linked():
    mail = _render(brand=Brand("Musterverein Seeland", PNG))
    assert 'src="cid:hocx-tenant-logo"' in mail.html
    assert len(mail.images) == 1 and mail.images[0].data == PNG
    message = email_transport._message(
        email_transport.EmailConfig(host="h", port=25, security="none", username=None, password=None, from_address="n@example.com", from_name="hocX", link_base_url=None),
        email_transport.OutgoingEmail(to="a@example.com", subject=mail.subject, text=mail.text, html=mail.html, images=mail.images),
    )
    related = [part for part in message.walk() if part.get_content_type() == "image/png"]
    assert len(related) == 1 and related[0]["Content-ID"] == "<hocx-tenant-logo>"


def test_reminder_lists_overdue_first():
    items = [
        {"kind": "todo.due_soon", "task": "Bald", "due": date(2026, 11, 17), "source": None},
        {"kind": "todo.overdue", "task": "Spät", "due": date(2026, 11, 13), "source": None},
    ]
    mail = _render(group="todo.reminder", items=items)
    assert mail.html.index("Seit gestern überfällig") < mail.html.index("In 3 Tagen fällig")
    assert mail.text.index("Spät") < mail.text.index("Bald")


def test_security_mail_links_only_to_profile_security_and_has_no_settings_hint():
    """Einziger Link: «Sicherheit prüfen» in die App (Profil › Sicherheit, Auth-Audit 2026-11-20),
    ohne Token; kein Link zu den Benachrichtigungs-Einstellungen (Pflichtmitteilung)."""
    items = [{"kind": "security.password_changed", "by_admin": False, "at": datetime(2026, 11, 14, 20, 5, tzinfo=timezone.utc)}]
    mail = _render(group="account.security", items=items)
    assert "Passwort geändert" in mail.html and "14.11.2026 21:05" in mail.html
    links = set(re.findall(r'href="([^"]+)"', mail.html))
    assert all(link.endswith("/?profile=security") for link in links), links
    assert "profile=notifications" not in mail.html and "#token" not in mail.html
    assert "lassen sich nicht abschalten" in mail.html


def test_test_mail_uses_the_frame_without_tenant():
    mail = render_test(lang="de", base_url="https://app.example.com")
    assert "Versand funktioniert" in mail.html and "Test-E-Mail" in mail.html and "über hocX" not in mail.html


def test_every_locale_renders_without_missing_keys():
    from app.core.locale_config_generated import LOCALES

    for lang in LOCALES:
        for group, items in (
            ("todo.new", _todo_items()),
            ("fine.issued", [{"type": "todo", "task": "X", "due": date(2026, 11, 13), "rule_name": "R", "tariff_name": "T", "amount": Decimal("15"),
                              "currency": "CHF", "issued_on": date(2026, 11, 14), "open_total": Decimal("35")}]),
            ("fine.upcoming", [{"task": "X", "due": date(2026, 11, 17), "days_left": 3, "steps": [(date(2026, 11, 18), Decimal("10")), (date(2026, 11, 25), Decimal("15"))],
                                "currency": "CHF", "rule_name": "R", "fixed": False, "source": None}]),
        ):
            mail = _render(lang=lang, group=group, items=items)
            assert "email." not in mail.html and "email." not in mail.subject, (lang, group)


# ── Bussen-Mails über den echten Ablauf ──────────────────────────────


@pytest.fixture
def sent():
    mails: list = []
    email_transport.override_transport(lambda config, email: mails.append(email))
    yield mails
    email_transport.override_transport(None)


def _enable_email(db):
    row = NotificationSettingsService().get_row(db)
    row.email_enabled = True
    row.smtp_host = "smtp.example.com"
    row.email_from_address = "noreply@example.com"
    row.email_link_base_url = "https://app.example.com"
    db.flush()


def _login(person, email: str):
    import secrets

    from app.core.security import hash_password

    person.email = email
    person.password_hash = hash_password(secrets.token_urlsafe(16))
    person.login_enabled = True


def _deliver_now(db):
    for row in db.scalars(select(Notification).where(Notification.status == "pending")):
        row.deliver_after = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.flush()


def test_frozen_todo_fine_sends_fine_issued_with_open_total(db, setup, sent):
    s = setup
    _login(s["ben"], "ben@example.com")
    _rule(db, s)
    todo = _todo(db, s, days_late=4, people=("ben",))
    _complete(db, todo, on=TODAY - timedelta(days=2))
    rows = db.scalars(select(Notification).where(Notification.kind == "fine.issued")).all()
    # _complete friert zweimal ein (Erledigen, dann Neuberechnung mit Datum): die erste Busse ist
    # danach gelöscht, ihre Meldung fällt beim Versand als überholt weg
    assert {row.recipient_id for row in rows} == {s["ben"].id}
    _enable_email(db)
    _deliver_now(db)
    dispatch.run(db)
    fine_mails = [mail for mail in sent if "Busse" in mail.subject]
    assert len(fine_mails) == 1
    mail = fine_mails[0]
    # Ben, Tarif Vollverdiener: 10 + 2 × 5 = 20
    assert "Neue Busse über CHF 20.00" in mail.subject
    assert "Pendenz zu spät: Material bringen" in mail.text and "Total offene Bussen" in mail.text
    assert "https://app.example.com/fines" in mail.text


def test_upcoming_fine_replaces_the_normal_reminder(db, setup):
    s = setup
    _login(s["anna"], "anna@example.com")
    _login(s["ben"], "ben@example.com")
    _rule(db, s, tags=("material",))
    fined = _todo(db, s, days_late=-3, people=("anna",), tags=("Material",))
    plain = _todo(db, s, days_late=-3, people=("ben",))
    now = datetime.combine(TODAY, datetime.min.time()).replace(hour=8, tzinfo=todo_notifications.TZ)
    counts = todo_notifications.scan_reminders(db, now=now)
    kinds = {(row.subject_id, row.kind) for row in db.scalars(select(Notification))}
    assert (fined.id, "fine.upcoming") in kinds and (fined.id, "todo.due_soon") not in kinds
    assert (plain.id, "todo.due_soon") in kinds
    assert counts["fine_upcoming"] == 1


def test_upcoming_fine_mail_shows_the_steps(db, setup, sent):
    s = setup
    _login(s["anna"], "anna@example.com")
    _rule(db, s, interval=7)
    todo = _todo(db, s, days_late=-3, people=("anna",))
    now = datetime.combine(TODAY, datetime.min.time()).replace(hour=8, tzinfo=todo_notifications.TZ)
    todo_notifications.scan_reminders(db, now=now)
    _enable_email(db)
    _deliver_now(db)
    dispatch.run(db)
    mail = next(mail for mail in sent if "Busse droht" in mail.subject)
    due = todo.due_date
    # Anna (Standardtarif Lernende): 2, ab 7 Tagen 3, ab 14 Tagen 4
    assert f"ab {(due + timedelta(days=1)).strftime('%d.%m.%Y')}: CHF 2.00" in mail.text
    assert f"ab {(due + timedelta(days=7)).strftime('%d.%m.%Y')}: CHF 3.00" in mail.text
    assert "steigt" in mail.text and "Regel «Pendenzen»" in mail.text


def test_attendance_fines_are_announced_when_the_protocol_closes(db, setup):
    s = setup
    template = make_template(db, s["tenant"].id)
    protocol = make_protocol(db, s["tenant"].id, template.id, status="durchgeführt")
    fine = make_fine(db, protocol.id, s["account"].id, amount=5.0, participant_name_snapshot="Ben")
    fine.participant_id = s["ben"].id
    db.flush()
    assert db.scalars(select(Notification).where(Notification.kind == "fine.issued")).all() == []
    ProtocolService().update_protocol(db, protocol.id, ProtocolUpdate(status="abgeschlossen"), notify_todos=True)
    rows = db.scalars(select(Notification).where(Notification.kind == "fine.issued")).all()
    assert [(row.recipient_id, row.payload["type"]) for row in rows] == [(s["ben"].id, "attendance")]
