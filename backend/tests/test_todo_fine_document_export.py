"""Busse im Pendenzen-Export (Document Studio, providers/todos.py): Spalte «Busse» mit laufender und
eingefrorener Busse, Sichtbarkeit wie im Pendenzen-Popup, WhatsApp-Text."""
from __future__ import annotations

from datetime import timedelta

from app.documents.catalog import BlockSpec, TodoTableParams
from app.documents.context import BuildContext
from app.documents.providers import todos
from tests.factories import make_current_user
from tests.test_todo_fines import FEATURES, TODAY, _complete, _rule, _todo, setup  # noqa: F401 (Fixture)


def _ctx(db, s, user=None) -> BuildContext:
    return BuildContext(db=db, tenant_id=s["tenant"].id, language="de", user=user or s["manager"], today=TODAY)


def _table(db, s, user=None, **params):
    spec = BlockSpec(type="todo_table", params={"status": "all", **params})
    block = todos.provide(_ctx(db, s, user), spec, TodoTableParams(status="all", **params))[0]
    return block.table


def _fine_by_task(table) -> dict[str, str]:
    keys = [column.key for column in table.columns]
    if "fine" not in keys:
        return {}
    task, fine = keys.index("task"), keys.index("fine")
    return {row.cells[task].v: row.cells[fine].v for group in table.groups for row in group.rows}


def test_fine_column_shows_running_and_frozen_fines(db, setup):
    s = setup
    _rule(db, s)
    running = _todo(db, s, days_late=3, people=("anna", "ben"))
    running.task = "Laufend"
    frozen = _todo(db, s, days_late=4, people=("ben",))
    frozen.task = "Erledigt"
    _complete(db, frozen, on=TODAY - timedelta(days=2))
    on_time = _todo(db, s, days_late=-2)
    on_time.task = "Noch nicht fällig"
    db.flush()

    fines = _fine_by_task(_table(db, s))
    # Anna 2 + 3×1, Ben 10 + 3×5 = 30; erledigt nach 2 Tagen Verspätung: Ben 10 + 2×5 = 20
    assert fines["Laufend"].startswith("30") and fines["Laufend"].endswith("CHF")
    assert fines["Erledigt"].startswith("20")
    assert fines["Noch nicht fällig"] == ""


def test_member_without_reports_personal_sees_only_own_amount(db, setup):
    s = setup
    _rule(db, s)
    todo = _todo(db, s, days_late=3, people=("anna", "ben"))
    todo.task = "Gemeinsam"
    only_anna = _todo(db, s, days_late=3, people=("anna",))
    only_anna.task = "Nur Anna"
    db.flush()
    member = make_current_user(s["tenant"].id, role="reader", user_id=s["ben"].id, features=FEATURES)

    fines = _fine_by_task(_table(db, s, member))
    assert fines["Gemeinsam"].startswith("25")
    assert fines["Nur Anna"] == ""


def test_no_fine_column_without_fines_or_when_switched_off(db, setup):
    s = setup
    _todo(db, s, days_late=3)  # keine Regel -> keine Busse
    assert "fine" not in [column.key for column in _table(db, s).columns]

    _rule(db, s)
    assert "fine" in [column.key for column in _table(db, s).columns]
    assert "fine" not in [column.key for column in _table(db, s, show_fines=False).columns]


def test_markdown_lists_fine_and_respects_excluded_column(db, setup):
    s = setup
    _rule(db, s)
    todo = _todo(db, s, days_late=3, people=("ben",))
    todo.task = "Material bringen"
    db.flush()
    ctx = _ctx(db, s)
    rows = todos.filter_rows(ctx, todos.list_tenant_todo_rows(ctx), TodoTableParams(status="all"))
    strings = {
        "col.status": "Status", "col.assignee": "Zuständig", "col.due": "Fällig", "col.protocol": "Protokoll",
        "col.tags": "Tags", "col.fine": "Busse", "col.count": "Anzahl", "label.asOf": "Stand {date}",
        "group.unassigned": "Ohne", "empty.todo_table": "Keine",
    }
    loaded = todos.load_todo_fines(ctx, rows)
    text = todos.markdown(rows, strings=strings, title="Pendenzen", group_by_person=False, show_status=False, today=TODAY, fines=loaded)
    assert "_Busse:_ 25" in text
    without = todos.markdown(
        rows, strings=strings, title="Pendenzen", group_by_person=False, show_status=False, today=TODAY, fines=loaded, exclude_columns={"Busse"}
    )
    assert "Busse" not in without
