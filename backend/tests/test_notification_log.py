"""Versandprotokoll im Admin-Portal: mandantenübergreifend, filterbar, ohne Mailinhalt."""
from datetime import UTC, datetime

from app.models import Notification
from app.notifications.log import list_log
from tests.factories import make_app_user, make_tenant


def _notification(db, user, *, kind="todo.assigned", status="sent", payload=None, skip_reason=None):
    row = Notification(
        tenant_id=user.tenant_id, recipient_id=user.id, kind=kind, group_key="todo.new", payload=payload or {},
        status=status, skip_reason=skip_reason, sent_at=datetime.now(UTC) if status == "sent" else None,
    )
    db.add(row)
    db.flush()
    return row


def test_log_lists_mails_of_all_tenants_with_filters(db):
    alpha = make_tenant(db, "Alpha Team")
    beta = make_tenant(db, "Beta Gruppe")
    anna = make_app_user(db, "anna.log@example.com", tenant_id=alpha.id, first_name="Anna", last_name="Log")
    ben = make_app_user(db, "ben.log@example.com", tenant_id=beta.id, first_name="Ben", last_name="Log")
    sent = _notification(db, anna)
    skipped = _notification(db, ben, status="skipped", skip_reason="recipient_left")
    changed = _notification(db, ben, kind="security.email_changed", payload={"old_email": "alt@example.com"})

    page = list_log(db, search="log@example.com", limit=50)
    ids = {item.id for item in page.items}
    assert {sent.public_id, skipped.public_id} <= ids
    entry = next(item for item in page.items if item.id == skipped.public_id)
    assert (entry.tenant_name, entry.status, entry.skip_reason) == ("Beta Gruppe", "skipped", "recipient_left")

    only_skipped = list_log(db, status="skipped", search="Beta Gruppe")
    assert [item.id for item in only_skipped.items] == [skipped.public_id] and only_skipped.total == 1

    # Hinweis «E-Mail geändert» ging an die alte Adresse - so steht es auch im Protokoll
    by_tenant = list_log(db, search="Beta Gruppe")
    assert next(item for item in by_tenant.items if item.id == changed.public_id).recipient_email == "alt@example.com"
    assert not hasattr(entry, "payload")
