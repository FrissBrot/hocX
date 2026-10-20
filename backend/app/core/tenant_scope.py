"""Mandanten-Kontext für die Row-Level-Security der Datenbank (Migration 0132_tenant_rls).

Eine angemeldete Mandanten-Anfrage bindet ihre Session an den Mandanten des Kontos
(`get_optional_current_user` in security.py, collaboration_ws.py). Ab dann setzt jede Transaktion
der Session `app.tenant_id` transaktionslokal, und PostgreSQL liefert und ändert nur noch Zeilen
dieses Mandanten - auch dann, wenn einer Abfrage im Code der tenant_id-Filter fehlt.

`set_config(..., true)` gilt nur bis zum Ende der Transaktion. Nach einem Commit setzt der
`after_begin`-Hook den Wert in der nächsten Transaktion neu, und eine an den Pool zurückgegebene
Verbindung trägt nie den Mandanten der vorherigen Anfrage weiter.

Sessions ohne gebundenen Mandanten (Plattform-Admin, Hintergrundjobs, Worker, Anmeldung,
öffentliche Links) bleiben unbeschränkt; sie arbeiten bewusst mandantenübergreifend.

RLS ist ein zweites Sicherheitsnetz, keine Grenze gegen SQL-Injection (die Anwendung darf die
Einstellung selbst setzen). Die Prüfungen im Code (public_id_service, AccessService) bleiben
massgeblich.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import event, text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

TENANT_SCOPE_KEY = "rls_tenant_id"
_SET_SCOPE = text("SELECT set_config('app.tenant_id', :tenant_id, true)")


def _apply(connection: Connection, tenant_id: int | None) -> None:
    connection.execute(_SET_SCOPE, {"tenant_id": "" if tenant_id is None else str(tenant_id)})


def bind_tenant_scope(db: Session, tenant_id: int | None) -> None:
    """Bindet die Session an `tenant_id` (None: unbeschränkt). Wirkt sofort auf eine bereits
    laufende Transaktion und über den after_begin-Hook auf alle folgenden."""
    if tenant_id is None:
        db.info.pop(TENANT_SCOPE_KEY, None)
    else:
        db.info[TENANT_SCOPE_KEY] = tenant_id
    if db.in_transaction():
        _apply(db.connection(), tenant_id)


def bound_tenant_id(db: Session) -> int | None:
    return db.info.get(TENANT_SCOPE_KEY)


@contextmanager
def tenant_scope_suspended(db: Session) -> Iterator[None]:
    """Hebt die Bindung für eine bewusst mandantenübergreifende Systemprüfung kurz auf, z. B. die
    plattformweite Eindeutigkeit einer Login-E-Mail. Nur für Prüfungen, deren Ergebnis keine
    fremden Daten an den Aufrufer zurückgibt."""
    tenant_id = bound_tenant_id(db)
    if tenant_id is None:
        yield
        return
    bind_tenant_scope(db, None)
    try:
        yield
    finally:
        bind_tenant_scope(db, tenant_id)


@event.listens_for(Session, "after_begin")
def _scope_new_transaction(session: Session, transaction, connection: Connection) -> None:
    tenant_id = session.info.get(TENANT_SCOPE_KEY)
    if tenant_id is not None:
        _apply(connection, tenant_id)
