"""Link-Kontext für die Row-Level-Security der Abgabebox (Migration 0133_abgabebox_rls).

Die Rolle hocx_abgabebox sieht in der Datenbank nur Zeilen des Mandanten, dem der gesetzte
Upload-Link gehört; ohne Link gar nichts. Gesetzt wird das geheime Token selbst (nicht die
Mandanten-ID), damit auch ein übernommener Dienst ohne gültiges Token keinen anderen Mandanten
erreicht - die Datenbank leitet den Mandanten daraus ab (hocx_rls_abgabebox_tenant).

`set_config(..., true)` gilt nur bis zum Ende der Transaktion; der after_begin-Hook setzt das
Token nach jedem Commit (routes/public.py::_log committet mehrfach) in der nächsten Transaktion
neu, und eine Verbindung im Pool trägt nie das Token einer früheren Anfrage weiter.
"""

from __future__ import annotations

from sqlalchemy import event, text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

LINK_SCOPE_KEY = "abgabebox_link_token"
_SET_SCOPE = text("SELECT set_config('app.abgabebox_link', :token, true)")


def _apply(connection: Connection, token: str | None) -> None:
    connection.execute(_SET_SCOPE, {"token": token or ""})


def bind_link_scope(db: Session, token: str) -> None:
    """Bindet die Session an den Upload-Link `token`, sofort und für alle folgenden Transaktionen."""
    db.info[LINK_SCOPE_KEY] = token
    _apply(db.connection(), token)


@event.listens_for(Session, "after_begin")
def _scope_new_transaction(session: Session, transaction, connection: Connection) -> None:
    token = session.info.get(LINK_SCOPE_KEY)
    if token:
        _apply(connection, token)
