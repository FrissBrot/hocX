"""Nebenläufigkeit: Organisation umbenennen, während der Plattform-Admin sie bestätigt.

Eine Namensänderung hebt die Bestätigung auf (``handle_rename``) - bestätigt wird genau der
geprüfte Name. Die Umbenennung (``TenantService.update``) lädt den Mandanten aber am Anfang und
prüft die Bestätigung erst nach dem Logo-Upload (Virenscan, Sekunden) am geladenen, inzwischen
veralteten Stand. Bestätigt der Plattform-Admin in diesem Fenster den alten Namen, sieht
``handle_rename`` «nicht bestätigt» und hebt nichts auf; das Festschreiben setzt dann nur den
neuen Namen. Ergebnis: Prüfseite und Exporte zeigen «bestätigte Organisation» mit einem Namen, den
niemand geprüft hat. Erwartet: Die Bestätigung wird aufgehoben.

Ohne ``db``-Fixture: zwei echte, festgeschriebene Transaktionen.
"""
from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.db import engine
from app.models import IdentityVerificationRequest, Tenant
from app.models.entities import PlatformAdmin
from app.services import identity_verification_service as verification
from tests.factories import make_tenant


def _session() -> Session:
    return Session(bind=engine.connect(), autoflush=False, future=True)


def _close(session: Session) -> None:
    connection = session.connection()
    session.close()
    connection.close()


@pytest.fixture
def ids():
    session = _session()
    try:
        tenant = make_tenant(session, "Musikverein Geprüft")
        admin = PlatformAdmin(email="ops-race@hocx.example", display_name="Ops", password_hash="x", role="owner")
        session.add(admin)
        session.flush()
        session.add(IdentityVerificationRequest(tenant_id=tenant.id, tenant_name=tenant.name, requested_by=None))
        session.commit()
        values = (tenant.id, admin.id)
    finally:
        _close(session)
    yield values
    with engine.connect() as connection:
        # Festgeschriebene Audit-Einträge entfernen: andere Tests zählen Aktionen global
        connection.execute(text("DELETE FROM audit_log WHERE tenant_id = :tid OR actor_email = 'ops-race@hocx.example'"), {"tid": values[0]})
        connection.execute(text("DELETE FROM tenant WHERE id = :tid"), {"tid": values[0]})
        connection.execute(text("DELETE FROM platform_admin WHERE id = :aid"), {"aid": values[1]})
        connection.commit()


def test_rename_loaded_before_approval_revokes_it(ids):
    tenant_id, admin_id = ids
    renamer = _session()
    try:
        # Umbenennung: Mandant geladen, neuer Name gesetzt, Logo-Upload läuft noch
        tenant = renamer.get(Tenant, tenant_id)
        old_name = tenant.name
        tenant.name = "Ganz Anderer Verein"

        # Plattform-Admin bestätigt in diesem Fenster den geprüften (alten) Namen
        admin = _session()
        try:
            verification.approve(admin, admin.get(Tenant, tenant_id), admin_id=admin_id, admin_email="ops-race@hocx.example", note=None)
            admin.commit()
        finally:
            _close(admin)

        verification.handle_rename(renamer, tenant, old_name, actor_email="vorstand@hocx.example")
        renamer.add(tenant)
        renamer.commit()
    finally:
        _close(renamer)

    with Session(engine) as check:
        saved = check.get(Tenant, tenant_id)
        assert saved.name == "Ganz Anderer Verein"
        assert saved.identity_verified_at is None, "neuer, ungeprüfter Name gilt als bestätigt"
        assert saved.identity_verification_revoked_reason == verification.REVOKED_NAME_CHANGED


def test_approval_waiting_for_a_rename_does_not_confirm_the_new_name(ids):
    """Security-Review 1.5.2, umgekehrte Reihenfolge: die Umbenennung hat geflusht (Zeile gesperrt,
    Antrag zurückgezogen), der Plattform-Admin bestätigt gleichzeitig. «Bestätigen» wartet auf die
    Sperre und sieht danach den neuen Namen - mit dem geprüften Namen als Erwartung lehnt es ab."""
    import threading

    from app.services.identity_verification_service import VerificationStateError

    tenant_id, admin_id = ids
    renamer = _session()
    outcome: dict = {}
    try:
        tenant = renamer.get(Tenant, tenant_id)
        old_name = tenant.name
        tenant.name = "Umbenannt Während Prüfung"
        verification.handle_rename(renamer, tenant, old_name, actor_email="vorstand@hocx.example")

        def approve():
            admin = _session()
            try:
                verification.approve(admin, admin.get(Tenant, tenant_id), admin_id=admin_id, admin_email="ops-race@hocx.example",
                                     note=None, expected_name=old_name)
                admin.commit()
                outcome["result"] = "approved"
            except VerificationStateError as exc:
                admin.rollback()
                outcome["result"] = str(exc)
            finally:
                _close(admin)

        worker = threading.Thread(target=approve)
        worker.start()
        worker.join(timeout=2)
        assert worker.is_alive(), "Bestätigen wartet nicht auf die Umbenennung"
        renamer.add(tenant)
        renamer.commit()
        worker.join(timeout=30)
    finally:
        _close(renamer)

    assert outcome.get("result") == "apiError.verificationNameChanged"
    with Session(engine) as check:
        saved = check.get(Tenant, tenant_id)
        assert saved.name == "Umbenannt Während Prüfung"
        assert saved.identity_verified_at is None
