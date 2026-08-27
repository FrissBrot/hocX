"""Regression tests for HOCH findings from the 2026-08-16 audit."""
import pytest

from app.models import Protocol
from tests.factories import (
    make_event,
    make_participant,
    make_protocol,
    make_tenant,
    make_template,
)
from tests.test_audit_2026_08_16_critical_fixes import _s2_make_document_template_with_dir


# --- S5: export_standalone_pdf/export_global_pdf accepted a foreign-tenant template_id ----


def test_export_standalone_pdf_rejects_document_template_from_foreign_tenant(db):
    import asyncio

    from app.services.export_service import ExportService

    tenant_a = make_tenant(db, "Tenant A (S5)")
    tenant_b = make_tenant(db, "Tenant B (S5)")
    protocol_a = make_protocol(db, tenant_a.id, make_template(db, tenant_a.id).id)
    doc_template_b = _s2_make_document_template_with_dir(db, tenant_b.id, code="s5-foreign")

    service = ExportService()
    with pytest.raises(ValueError, match="Template not found"):
        asyncio.run(service.export_standalone_pdf(db, protocol_a.id, doc_template_b.id, "todo-list"))


def test_export_global_pdf_rejects_document_template_from_foreign_tenant(db):
    import asyncio

    from app.services.export_service import ExportService

    tenant_a = make_tenant(db, "Tenant A (S5b)")
    tenant_b = make_tenant(db, "Tenant B (S5b)")
    doc_template_b = _s2_make_document_template_with_dir(db, tenant_b.id, code="s5b-foreign")

    service = ExportService()
    with pytest.raises(ValueError, match="Template not found"):
        asyncio.run(service.export_global_pdf(db, tenant_a.id, doc_template_b.id, "todos"))


# --- D2: renumbering cascade ignored cross-template n_cycle_all siblings ------------------


def test_renumber_later_siblings_bumps_cross_template_n_cycle_all_sibling(db):
    from datetime import date

    from app.services.protocol_service import ProtocolService

    tenant = make_tenant(db, "Tenant (D2)")
    template_a = make_template(db, tenant.id, name="Template A (D2)")
    template_a.protocol_number_pattern = "{n_cycle_all}"
    template_b = make_template(db, tenant.id, name="Template B (D2)")
    template_b.protocol_number_pattern = "{n_cycle_all}"
    db.flush()

    # Sibling in template B already claimed n_cycle_all=1 for a later date.
    sibling = make_protocol(db, tenant.id, template_b.id, protocol_date=date(2026, 6, 1))
    sibling.protocol_number = "1"
    sibling.status = "geplant"
    db.flush()

    service = ProtocolService()
    service._renumber_later_siblings(
        db, tenant_id=tenant.id, template=template_a, protocol_date=date(2026, 3, 1), reset_month=12, reset_day=31
    )

    db.flush()
    refreshed = db.get(Protocol, sibling.id)
    assert refreshed.protocol_number == "2", (
        "cross-template sibling using {n_cycle_all} must be bumped when an earlier-dated "
        "protocol is inserted into a different template in the same cycle"
    )


def test_renumber_later_siblings_ignores_cross_template_sibling_not_using_n_cycle_all(db):
    from datetime import date

    from app.services.protocol_service import ProtocolService

    tenant = make_tenant(db, "Tenant (D2b)")
    template_a = make_template(db, tenant.id, name="Template A (D2b)")
    template_a.protocol_number_pattern = "{n_cycle_all}"
    template_b = make_template(db, tenant.id, name="Template B (D2b)")
    template_b.protocol_number_pattern = "{n}"  # per-template only, not cross-template
    db.flush()

    sibling = make_protocol(db, tenant.id, template_b.id, protocol_date=date(2026, 6, 1))
    sibling.protocol_number = "1"
    sibling.status = "geplant"
    db.flush()

    service = ProtocolService()
    service._renumber_later_siblings(
        db, tenant_id=tenant.id, template=template_a, protocol_date=date(2026, 3, 1), reset_month=12, reset_day=31
    )

    db.flush()
    refreshed = db.get(Protocol, sibling.id)
    assert refreshed.protocol_number == "1", "a template not using {n_cycle_all} must be left untouched"


# --- D5/D6: standalone-todo participant/event assignment ---------------------------------


def test_update_todo_on_standalone_todo_accepts_own_tenant_participant(db):
    from app.services.protocol_todo_service import ProtocolTodoService
    from app.schemas.protocol import ProtocolTodoCreate, ProtocolTodoUpdate

    tenant = make_tenant(db, "Tenant (D5)")
    participant = make_participant(db, tenant.id, "Standalone Assignee")

    service = ProtocolTodoService()
    todo = service.create_standalone_todo(
        db, tenant.id, ProtocolTodoCreate(task="Standalone Task", todo_status_id=1)
    )
    db.flush()

    updated = service.update_todo(db, todo.id, ProtocolTodoUpdate(assigned_participant_id=participant.public_id))
    # update_todo returns the raw ORM entity (internal ints), not a public schema.
    assert updated.assigned_participant_id == participant.id


def test_update_todo_on_standalone_todo_rejects_foreign_tenant_participant(db):
    from app.services.protocol_todo_service import ProtocolTodoService
    from app.schemas.protocol import ProtocolTodoCreate, ProtocolTodoUpdate

    tenant_a = make_tenant(db, "Tenant A (D5b)")
    tenant_b = make_tenant(db, "Tenant B (D5b)")
    foreign_participant = make_participant(db, tenant_b.id, "Foreign Assignee")

    service = ProtocolTodoService()
    todo = service.create_standalone_todo(
        db, tenant_a.id, ProtocolTodoCreate(task="Standalone Task", todo_status_id=1)
    )
    db.flush()

    with pytest.raises(ValueError, match="not available"):
        service.update_todo(db, todo.id, ProtocolTodoUpdate(assigned_participant_id=foreign_participant.public_id))


def test_create_standalone_todo_rejects_foreign_tenant_participant(db):
    from app.services.protocol_todo_service import ProtocolTodoService
    from app.schemas.protocol import ProtocolTodoCreate

    tenant_a = make_tenant(db, "Tenant A (D6)")
    tenant_b = make_tenant(db, "Tenant B (D6)")
    foreign_participant = make_participant(db, tenant_b.id, "Foreign Assignee (D6)")

    service = ProtocolTodoService()
    with pytest.raises(ValueError, match="not available"):
        service.create_standalone_todo(
            db, tenant_a.id,
            ProtocolTodoCreate(task="Task", todo_status_id=1, assigned_participant_id=foreign_participant.public_id),
        )


def test_create_standalone_todo_rejects_foreign_tenant_event(db):
    from app.services.protocol_todo_service import ProtocolTodoService
    from app.schemas.protocol import ProtocolTodoCreate

    tenant_a = make_tenant(db, "Tenant A (D6b)")
    tenant_b = make_tenant(db, "Tenant B (D6b)")
    foreign_event = make_event(db, tenant_b.id, title="Foreign Event (D6b)")

    service = ProtocolTodoService()
    with pytest.raises(ValueError, match="not available"):
        service.create_standalone_todo(
            db, tenant_a.id,
            ProtocolTodoCreate(task="Task", todo_status_id=1, due_event_id=foreign_event.public_id),
        )


# --- D9: fines-by-participant grouped by name snapshot instead of participant_id ---------


def _make_fine(db, *, protocol_id, account_id, participant_id, name_snapshot, amount):
    from app.models import AttendanceFine

    fine = AttendanceFine(
        protocol_id=protocol_id,
        account_id=account_id,
        participant_id=participant_id,
        participant_name_snapshot=name_snapshot,
        fine_type="late",
        amount=amount,
    )
    db.add(fine)
    db.flush()
    return fine


def test_fetch_fines_by_participant_does_not_merge_different_participants_with_colliding_name_snapshot(db):
    # Participant.display_name has a per-tenant UNIQUE constraint, so two *currently active*
    # participants can never literally share a display_name - but participant_name_snapshot
    # is a frozen copy on each fine, so two *different* participants can still end up with
    # the same snapshot text (one was renamed after an old fine was created; a different,
    # unrelated participant happens to be named that today). Grouping by the snapshot text
    # (pre-fix behaviour) would wrongly merge these into one row.
    from decimal import Decimal

    from app.services.statistics_common import fetch_fines_by_participant
    from tests.factories import make_finance_account

    tenant = make_tenant(db, "Tenant (D9)")
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id)
    account = make_finance_account(db, tenant.id)
    renamed_participant = make_participant(db, tenant.id, "New Name After Rename")
    other_participant = make_participant(db, tenant.id, "Same Name")

    _make_fine(db, protocol_id=protocol.id, account_id=account.id, participant_id=renamed_participant.id, name_snapshot="Same Name", amount=Decimal("5.00"))
    _make_fine(db, protocol_id=protocol.id, account_id=account.id, participant_id=other_participant.id, name_snapshot="Same Name", amount=Decimal("3.00"))

    rows = fetch_fines_by_participant(db, tenant.id)
    amounts = {r.amount for r in rows if r.name in ("Same Name", "New Name After Rename")}
    assert amounts == {Decimal("5.00"), Decimal("3.00")}, (
        "two different participant_ids whose fine snapshots happen to share the same name "
        "text must not be merged into one row"
    )


def test_fetch_fines_by_participant_merges_renamed_participant_into_one_row(db):
    from decimal import Decimal

    from app.services.statistics_common import fetch_fines_by_participant
    from tests.factories import make_finance_account

    tenant = make_tenant(db, "Tenant (D9b)")
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id)
    account = make_finance_account(db, tenant.id)
    participant = make_participant(db, tenant.id, "Current Name")

    # Two fines with different frozen name snapshots (participant was renamed between them),
    # but the same participant_id.
    _make_fine(db, protocol_id=protocol.id, account_id=account.id, participant_id=participant.id, name_snapshot="Old Name", amount=Decimal("2.00"))
    _make_fine(db, protocol_id=protocol.id, account_id=account.id, participant_id=participant.id, name_snapshot="Current Name", amount=Decimal("4.00"))

    rows = fetch_fines_by_participant(db, tenant.id)
    matching = [r for r in rows if r.name == "Current Name"]
    assert len(matching) == 1, "a renamed participant's fines must be grouped into a single row"
    assert matching[0].amount == Decimal("6.00")
    assert matching[0].count == 2


# --- D11: concurrent double-commit of the same word-import queue document ----------------


def test_commit_document_rejects_a_document_already_marked_importiert(db):
    # Reproduces the outcome of D11's race (two near-simultaneous commit requests: the
    # first already flipped status to "importiert" before the second's guard check runs)
    # without needing two real concurrent transactions - the row-lock's job is exactly to
    # make the second request observe this already-"importiert" state instead of the stale
    # "eingelesen" one, which is what's asserted here. Sets status directly rather than
    # driving a real commit through WordImportService.commit()/create_from_template(): that
    # path uses `with db.begin_nested()`, whose bookkeeping doesn't survive a second use
    # within one test's savepoint-wrapped session (documented, pre-existing limitation, see
    # test_protocol_number_cycle_rank.py's module docstring) - orthogonal to what this test
    # needs to verify.
    from app.models import WordImportDocument
    from app.services.word_import_queue_service import WordImportQueueService
    from tests.test_word_import_e2e import _build_template, _commit_payload_from_analysis
    from tests.word_import_fixtures import default_spec, render_docx

    ctx = _build_template(db)
    queue_service = WordImportQueueService()
    raw_bytes = render_docx(default_spec())
    documents, _warnings = queue_service.ingest(
        db, tenant_id=ctx["tenant"].id, template_id=ctx["template"].id,
        created_by=None, files=[("test.docx", raw_bytes)],
    )
    document = documents[0]
    db.flush()
    analysis = queue_service.word_import_service.analyze(
        db, tenant_id=ctx["tenant"].id, template_id=ctx["template"].id,
        protocol_date_hint=None, raw_bytes=raw_bytes,
    )
    payload = _commit_payload_from_analysis(analysis, template_id=ctx["template"].id)

    # Simulates "another request already committed this document" instead of racing a real
    # second transaction.
    document.status = "importiert"
    db.flush()

    with pytest.raises(ValueError, match="bereits importiert"):
        queue_service.commit_document(db, document=document, tenant_id=ctx["tenant"].id, user_id=1, payload=payload)


def test_commit_document_claims_the_row_atomically_before_importing():
    # Static check that the fix's atomic claim (UPDATE ... WHERE status == "eingelesen",
    # committed in its own short transaction) is actually present and precedes the call
    # into word_import_service.commit() - the two-real-transactions race itself isn't
    # practically reproducible inside this suite's single-connection-per-test db fixture
    # (see the module-level note above), so this pins the concrete implementation instead.
    #
    # A plain SELECT ... FOR UPDATE held across the word_import_service.commit() call (the
    # previous fix attempt) does NOT actually close the race: that call performs several
    # internal db.commit()s of its own, each of which releases the lock long before this
    # method would have written status="importiert" - a near-simultaneous second commit
    # request can still read "eingelesen" in that window and also proceed (audit finding,
    # 2026-08-25). Flipping the status to "importiert" up front, in its own committed
    # transaction, closes that window instead of merely narrowing it.
    import inspect

    from app.services.word_import_queue_service import WordImportQueueService

    source = inspect.getsource(WordImportQueueService.commit_document)
    claim_pos = source.index('WordImportDocument.status == "eingelesen"')
    claim_commit_pos = source.index("db.commit()", claim_pos)
    import_call_pos = source.index("self.word_import_service.commit(")
    assert claim_pos < claim_commit_pos < import_call_pos, (
        "the eingelesen -> importiert claim must be committed in its own transaction "
        "before word_import_service.commit() runs, otherwise a concurrent request can "
        "still slip through the window opened by that call's own internal commits"
    )
