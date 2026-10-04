"""Migration 0098: element_type-Codes auf die festen Frontend-ids (12-16) umbenennen."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import text

BACKEND_ROOT = Path(__file__).resolve().parents[1]
CANONICAL = {12: "finance_balance", 13: "finance_transactions", 14: "fine_list", 15: "chart", 16: "entry_exit"}
# Belegung einer frisch aus der 1.0.0-Baseline aufgesetzten Instanz (vor dieser Migration).
BASELINE_LAYOUT = {12: "entry_exit", 13: "finance_balance", 14: "finance_transactions", 15: "fine_list", 16: "chart"}


def _load_migration():
    spec = importlib.util.spec_from_file_location(
        "migration_0098", BACKEND_ROOT / "alembic/versions/0098_canonical_element_type_ids.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _set_layout(conn, layout: dict[int, str]) -> None:
    for element_type_id in layout:
        conn.execute(text("UPDATE element_type SET code = :tmp WHERE id = :id"), {"tmp": f"__x_{element_type_id}", "id": element_type_id})
    for element_type_id, code in layout.items():
        conn.execute(text("UPDATE element_type SET code = :code WHERE id = :id"), {"code": code, "id": element_type_id})


def _layout(conn) -> dict[int, str]:
    rows = conn.execute(text("SELECT id, code FROM element_type WHERE id BETWEEN 12 AND 16"))
    return {row.id: row.code for row in rows}


@pytest.fixture
def migration(db, monkeypatch):
    module = _load_migration()
    monkeypatch.setattr(module.op, "get_bind", lambda: db.connection(), raising=False)
    return module


def test_migration_relabels_baseline_layout_so_ids_keep_editor_meaning(db, migration):
    conn = db.connection()
    _set_layout(conn, BASELINE_LAYOUT)

    migration.upgrade()

    # id 12 war im Editor "Kontostand" - danach heisst sie auch so; Referenzen bleiben unveraendert.
    assert _layout(conn) == CANONICAL


def test_migration_is_noop_on_canonical_layout(db, migration):
    conn = db.connection()
    assert _layout(conn) == CANONICAL

    migration.upgrade()

    assert _layout(conn) == CANONICAL


def test_migration_inserts_missing_types_with_fixed_ids(db, migration):
    conn = db.connection()
    # Zustand direkt nach 0001 auf einer alten Baseline: nur entry_exit als id 12.
    conn.execute(text("UPDATE element_type SET code = '__gone_' || id WHERE id BETWEEN 13 AND 16"))
    conn.execute(text("UPDATE element_type SET code = 'entry_exit' WHERE id = 12"))
    conn.execute(text("DELETE FROM element_type WHERE id BETWEEN 13 AND 16"))

    migration.upgrade()

    assert _layout(conn) == CANONICAL
