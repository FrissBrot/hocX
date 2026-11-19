"""Nebenläufigkeit: Abgleich der Abgabe-Pendenzen nach Terminänderungen.

Jedes Anlegen/Ändern eines Termins gleicht alle Abgaben des Mandanten ab
(submission_service.sync_todos_for_event → sync_todos_if_tracked). Ändern zwei Personen
gleichzeitig Termine, legen beide Abgleiche dieselbe Pendenz an: der zweite scheiterte am
Unique-Index uix_protocol_todo_submission_element, rollte den Abgleich zurück und meldete einen
«unerwarteten Fehler» ins Fehlerprotokoll. Erwartet: der zweite wartet auf den ersten.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from app.core.db import engine
from app.models.entities import ProtocolTodo, SubmissionAssignment, SystemErrorLog, Tenant
from app.schemas.submission import SubmissionAssignmentCreate, SubmissionLinkCreate
from app.services.submission_link_service import SubmissionLinkService
from app.services.submission_service import SubmissionService
from tests.factories import make_event, make_participant, make_tenant

service = SubmissionService()


def _wait_until_blocked(timeout: float = 10.0) -> bool:
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


def test_parallel_submission_todo_syncs_do_not_collide():
    with Session(engine) as setup:
        tenant = make_tenant(setup, "Abgabe parallel")
        anna = make_participant(setup, tenant.id, display_name="Anna Muster")
        event = make_event(setup, tenant.id, title="Badetag")
        event.tag = "lager"
        event.spezial1_ids = [anna.id]
        setup.flush()
        link = SubmissionLinkService().create_link(setup, SubmissionLinkCreate(name="Leiter"), tenant_id=tenant.id)
        created = service.create_assignment(
            setup,
            SubmissionAssignmentCreate(
                title="Berichte", public_slug="berichte-parallel", source_type="events", tag_filter="lager",
                link_ids=[link.id], responsible_participant_source="spezial1_ids",
            ),
            tenant_id=tenant.id,
        )
        setup.commit()
        tenant_id = tenant.id
        assignment_id = setup.scalar(select(SubmissionAssignment.id).where(SubmissionAssignment.public_id == created.id))
        # create_assignment gleicht schon ab: die Pendenz entfernen, damit beide Abgleiche sie anlegen wollen
        setup.execute(delete(ProtocolTodo).where(ProtocolTodo.submission_assignment_id == assignment_id))
        setup.commit()

    def second_request() -> bool:
        with Session(engine) as db:
            return service.sync_todos_if_tracked(db, db.get(SubmissionAssignment, assignment_id))

    try:
        with Session(engine) as first, ThreadPoolExecutor(1) as pool:
            # Erster Request: Abgleich hat die Pendenz angelegt, Transaktion noch offen.
            first_assignment = first.get(SubmissionAssignment, assignment_id)
            original_commit = first.commit
            first.commit = first.flush  # Commit am Ende von sync_submission_todos zurückhalten
            service.sync_submission_todos(first, first_assignment)
            first.commit = original_commit
            future = pool.submit(second_request)
            assert _wait_until_blocked(), "zweiter Abgleich wartet nicht auf den ersten"
            first.commit()
            ok = future.result(timeout=30)

        with Session(engine) as check:
            todos = check.scalar(select(func.count()).select_from(ProtocolTodo).where(ProtocolTodo.submission_assignment_id == assignment_id))
            errors = check.scalar(select(func.count()).select_from(SystemErrorLog).where(SystemErrorLog.tenant_id == tenant_id))
        assert ok is True, "zweiter gleichzeitiger Abgleich scheitert"
        assert errors == 0
        assert todos == 1
    finally:
        with Session(engine) as cleanup:
            cleanup.execute(delete(SystemErrorLog).where(SystemErrorLog.tenant_id == tenant_id))
            cleanup.execute(delete(ProtocolTodo).where(ProtocolTodo.tenant_id == tenant_id))
            cleanup.execute(delete(Tenant).where(Tenant.id == tenant_id))
            cleanup.commit()
