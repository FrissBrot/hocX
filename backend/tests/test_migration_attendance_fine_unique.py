"""Migration 0116 (MAIN-BE-016): doppelte Bussen werden zusammengeführt, die entfernten
Zeilen bleiben als Prüfkopie erhalten, danach verhindert ein Unique-Index neue Duplikate."""
from __future__ import annotations

import importlib.util
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.models import AttendanceFine
from tests.factories import make_finance_account, make_protocol, make_template, make_tenant

BACKEND_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def migration(db, monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "migration_0116", BACKEND_ROOT / "alembic/versions/0116_attendance_fine_unique.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.op, "execute", lambda sql: db.connection().execute(text(sql)), raising=False)
    # Zustand vor der Migration herstellen (die Test-DB ist bereits auf head).
    conn = db.connection()
    conn.execute(text("DROP INDEX uq_attendance_fine_participant"))
    conn.execute(text("DROP INDEX uq_attendance_fine_name"))
    conn.execute(text("DROP TABLE attendance_fine_merged_duplicate"))
    return module


def _fine(db, protocol_id, account_id, *, status="pending", participant_name="Anna", minutes=0, fine_type="late"):
    fine = AttendanceFine(
        protocol_id=protocol_id, account_id=account_id, amount=Decimal("5.00"), fine_type=fine_type,
        participant_name_snapshot=participant_name, status=status,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=minutes),
    )
    db.add(fine)
    db.flush()
    return fine.id


def test_duplicates_are_merged_keeping_the_strongest_status(db, migration):
    tenant = make_tenant(db, "Dedupe")
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id)
    account = make_finance_account(db, tenant.id)
    oldest_pending = _fine(db, protocol.id, account.id, minutes=0)
    collected = _fine(db, protocol.id, account.id, status="collected", minutes=5)
    newer_pending = _fine(db, protocol.id, account.id, minutes=10)
    other_type = _fine(db, protocol.id, account.id, fine_type="absent")
    other_person = _fine(db, protocol.id, account.id, participant_name="Ben")

    migration.upgrade()
    db.expire_all()

    remaining = set(db.execute(text("SELECT id FROM attendance_fine WHERE protocol_id = :p"), {"p": protocol.id}).scalars())
    assert remaining == {collected, other_type, other_person}
    merged = dict(db.execute(text("SELECT id, merged_into_id FROM attendance_fine_merged_duplicate")).all())
    assert merged == {oldest_pending: collected, newer_pending: collected}


def test_unique_index_rejects_new_duplicates_afterwards(db, migration):
    tenant = make_tenant(db, "Dedupe 2")
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id)
    account = make_finance_account(db, tenant.id)
    _fine(db, protocol.id, account.id)

    migration.upgrade()

    nested = db.begin_nested()
    with pytest.raises(IntegrityError):
        _fine(db, protocol.id, account.id, minutes=1)
    nested.rollback()
