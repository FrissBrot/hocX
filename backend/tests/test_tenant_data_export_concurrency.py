"""Nebenläufigkeit beim Anfordern des Vereins-Gesamtexports.

request_export prüft «läuft schon einer?» und legt dann einen Auftrag an. Zwei gleichzeitige
Anfragen (Doppelklick, zwei Tabs, zwei Admins) sahen beide «keiner aktiv» und legten beide einen
Auftrag an: der Worker baute den vollständigen Export (alle Personendaten, ggf. alle Dateien)
zweimal, die Sperre «Es läuft bereits ein Gesamtexport» griff nicht.
Erwartet: die zweite Anfrage wartet auf die erste und wird dann mit ExportInProgress abgewiesen.
"""

from __future__ import annotations

import secrets
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from app.core.db import engine
from app.models import Tenant, TenantDataExport
from app.models.entities import AppUser
from app.services.data_export import tenant as tenant_export
from tests.factories import make_app_user, make_tenant


def _wait_until_blocked(timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    with engine.connect() as probe:
        while time.monotonic() < deadline:
            if probe.scalar(text("SELECT count(*) FROM pg_locks WHERE NOT granted")):
                return True
            probe.rollback()  # neuer Schnappschuss je Probe
            time.sleep(0.05)
    return False


def test_parallel_export_requests_create_only_one_job():
    with Session(engine) as setup:
        tenant = make_tenant(setup, "Gesamtexport parallel")
        admin = make_app_user(setup, email=f"{uuid.uuid4().hex[:8]}@example.com", tenant_id=tenant.id, role_code="admin")
        setup.commit()
        tenant_id, user_id = tenant.id, admin.id

    def request(db: Session) -> TenantDataExport:
        return tenant_export.request_export(
            db, tenant_id=tenant_id, user_id=user_id, password=secrets.token_urlsafe(16), include_files=False, language="de",
        )

    def second_request():
        with Session(engine) as db:
            try:
                job = request(db)
                db.commit()
                return job.id
            except Exception as exc:  # Befund festhalten
                db.rollback()
                return type(exc).__name__

    pool = ThreadPoolExecutor(1)
    first = Session(engine)
    try:
        request(first)  # erste Anfrage: Auftrag geschrieben, Commit noch nicht durch
        future = pool.submit(second_request)
        blocked = _wait_until_blocked(timeout=3.0)
        first.commit()
        second = future.result(timeout=30)
    finally:
        first.rollback()
        first.close()
        pool.shutdown(wait=True)

    try:
        with Session(engine) as check:
            jobs = check.scalars(select(TenantDataExport).where(TenantDataExport.tenant_id == tenant_id)).all()
        assert len(jobs) == 1, f"{len(jobs)} gleichzeitige Gesamtexport-Aufträge angelegt"
        assert blocked, "zweite Anfrage wartet nicht auf die erste"
        assert second == "ExportInProgress"
    finally:
        with Session(engine) as cleanup:
            cleanup.execute(delete(TenantDataExport).where(TenantDataExport.tenant_id == tenant_id))
            cleanup.execute(delete(AppUser).where(AppUser.id == user_id))
            cleanup.execute(delete(Tenant).where(Tenant.id == tenant_id))
            cleanup.commit()
