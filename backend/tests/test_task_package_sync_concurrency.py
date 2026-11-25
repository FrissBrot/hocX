"""Nebenläufigkeit: Abgleich der Aufgabenpakete «pro Termin» nach Terminänderungen.

Nach jedem Anlegen/Ändern eines Termins (und nach dem CSV-Import) gleicht die Route die
Aufgabenpakete des Tags ab (sync_packages_after_change). Ändern zwei Personen gleichzeitig
Termine mit demselben Tag, laufen zwei Abgleiche parallel. Ohne Sperre legen beide dieselbe
Instanz an: der zweite scheitert am Unique-Index uq_protocol_todo_package_occurrence, sein
ganzer Abgleich wird zurückgerollt (Pendenzen weiterer neuer Termine fehlen bis zum Tagesjob)
und im Fehlerprotokoll steht ein «unerwarteter Fehler». Erwartet: der zweite Abgleich wartet
auf den ersten und sieht dessen Instanz.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date

from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from app.core.db import engine
from app.models import ProtocolTodo, TaskPackage, TaskPackageCycle, TaskPackageItem, Tenant
from app.services import task_package_service as packages
from tests.factories import make_cycle_config, make_event, make_tenant

TODAY = date(2026, 10, 12)  # Zyklus 01.08.2026-31.07.2027

# Kein Warten ohne Ende (wie test_submission_todo_sync_concurrency): scheitert ein Assert, solange
# `first` seine Sperren hält, bricht der zweite Abgleich nach lock_timeout ab, statt den
# ThreadPool und damit den ganzen Testlauf anzuhalten.
LOCK_TIMEOUT = "30s"


def _session() -> Session:
    session = Session(engine)
    session.execute(text("SELECT set_config('lock_timeout', :value, true)"), {"value": LOCK_TIMEOUT})  # nur diese Transaktion
    return session


def _wait_until_blocked(timeout: float = 10.0) -> bool:
    """Wartet, bis eine andere Verbindung auf eine Sperre wartet (Lock oder Unique-Index)."""
    deadline = time.monotonic() + timeout
    with engine.connect() as probe:
        while time.monotonic() < deadline:
            waiting = probe.scalar(
                text("SELECT count(*) FROM pg_stat_activity WHERE wait_event_type = 'Lock' AND datname = current_database()")
            )
            if waiting:
                return True
            time.sleep(0.05)
    return False


def test_parallel_event_tag_syncs_do_not_collide():
    with Session(engine) as setup:
        tenant = make_tenant(setup, "Pfadi parallel")
        cycle = make_cycle_config(setup, tenant.id, name="Scharjahr", reset_month=7, reset_day=31)
        package = TaskPackage(tenant_id=tenant.id, name="Lager")
        setup.add(package)
        setup.flush()
        item = TaskPackageItem(
            task_package_id=package.id,
            task="Lagerplatz reservieren",
            tags=[],
            responsible_json=[],
            recurrence_json={"type": "events", "event_tag": "Lager"},
            due_rule_json={"type": "offset", "offset_days": -14},
        )
        setup.add_all([item, TaskPackageCycle(task_package_id=package.id, cycle_config_id=cycle.id, start_cycle_year=2026)])
        event = make_event(setup, tenant.id, title="Pfingstlager", event_date=date(2027, 5, 15))
        event.tag = "Lager"
        setup.commit()
        tenant_id, package_id, item_id = tenant.id, package.id, item.id

    def second_request() -> str | None:
        with _session() as db:
            try:
                packages.sync_packages_for_event_tag(db, tenant_id=tenant_id, tag="Lager", today=TODAY)
            except Exception as exc:  # Befund festhalten statt den Thread sterben zu lassen
                db.rollback()
                return type(exc).__name__
        return None

    try:
        with _session() as first, ThreadPoolExecutor(1) as pool:
            # Erster Request: Abgleich läuft, Transaktion noch offen (wie während der Route).
            packages.sync_package(first, first.get(TaskPackage, package_id), today=TODAY, commit=False)
            first.flush()
            future = pool.submit(second_request)
            assert _wait_until_blocked(), "zweiter Abgleich wartet nicht auf den ersten"
            first.commit()
            error = future.result(timeout=30)

        assert error is None, f"zweiter gleichzeitiger Abgleich scheitert mit {error}"
        with Session(engine) as check:
            count = check.scalar(select(func.count()).select_from(ProtocolTodo).where(ProtocolTodo.task_package_item_id == item_id))
        assert count == 1
    finally:
        with Session(engine) as cleanup:
            cleanup.execute(delete(ProtocolTodo).where(ProtocolTodo.tenant_id == tenant_id))
            cleanup.execute(delete(Tenant).where(Tenant.id == tenant_id))
            cleanup.commit()
