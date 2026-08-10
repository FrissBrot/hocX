"""Regression tests for a real bug found in Timo's actual "2. Hock vom 17.11.2025"
document: his Anwesenheit table has three separate status columns (header
['', 'Anwesend:', 'Entschuldigt:', 'Unentschuldigt:']) with a bare "X" marking the
right one per row - the marker cell itself never contains a status *word*. The
importer's status classification only ever looked at the marker's own text, so every
bare "X" fell through unclassified and every row silently defaulted to "present"
regardless of which column was actually marked (three real people - Dario von Moos,
Noé Gamma, Rafael Omlin - showed up as "Anwesend" despite being marked "Entschuldigt").

A second, independent bug surfaced while fixing the first: _classify_status checked
the EXCUSED keywords ("entschuldigt") before the ABSENT ones, and "unentschuldigt"
contains "entschuldigt" as a literal substring - so a "Unentschuldigt" column/marker
was misclassified as "excused" instead of "absent"."""
from datetime import date

from app.services import word_import_service as svc
from app.services.word_import_service import WordImportService

from tests.test_word_import_e2e import _build_template
from tests.word_import_fixtures import TableSpec, default_spec, render_docx


def test_classify_status_distinguishes_entschuldigt_from_unentschuldigt():
    assert svc._classify_status("Entschuldigt:") == "excused"
    assert svc._classify_status("Entschuldigt") == "excused"
    assert svc._classify_status("Unentschuldigt:") == "absent"
    assert svc._classify_status("Unentschuldigt") == "absent"
    assert svc._classify_status("Abwesend") == "absent"
    assert svc._classify_status("Verspätet") == "late"
    assert svc._classify_status("Anwesend:") is None
    assert svc._classify_status("X") is None
    assert svc._classify_status("") is None


def test_multi_column_x_marker_attendance_table_is_classified_by_column(db):
    """Reproduces the real document's exact table shape end to end through analyze()."""
    ctx = _build_template(db)
    tenant, template = ctx["tenant"], ctx["template"]
    spec = default_spec(protocol_date=date(2026, 11, 17))
    spec.attendance = TableSpec(
        heading="Anwesenheit",
        header_cells=["", "Anwesend:", "Entschuldigt:", "Unentschuldigt:"],
        rows=[
            ["Timo Weber", "X", "", ""],
            ["Nevio Muster", "", "X", ""],
            ["Sandro Keller", "", "", "X"],
        ],
    )
    raw_bytes = render_docx(spec)

    service = WordImportService()
    analysis = service.analyze(
        db, tenant_id=tenant.id, template_id=template.id, protocol_date_hint=None, raw_bytes=raw_bytes,
    )
    status_by_name = {m.raw_name: m.status for m in analysis.attendance_mappings if m.raw_name}
    assert status_by_name["Timo Weber"] == "present"
    assert status_by_name["Nevio Muster"] == "excused"
    assert status_by_name["Sandro Keller"] == "absent"


def test_single_status_column_shape_still_uses_marker_text(db):
    """The older shape (one free-text "Status" column whose cell literally says
    "entschuldigt") must keep working exactly as before - the new column-header-based
    classification only kicks in when a header actually carries a status keyword."""
    ctx = _build_template(db)
    tenant, template = ctx["tenant"], ctx["template"]
    spec = default_spec(protocol_date=date(2026, 11, 17))
    spec.attendance = TableSpec(
        heading="Anwesenheit",
        header_cells=["Name", "Status"],
        rows=[
            ["Timo Weber", ""],
            ["Nevio Muster", "entschuldigt"],
            ["Sandro Keller", "unentschuldigt"],
        ],
    )
    raw_bytes = render_docx(spec)

    service = WordImportService()
    analysis = service.analyze(
        db, tenant_id=tenant.id, template_id=template.id, protocol_date_hint=None, raw_bytes=raw_bytes,
    )
    status_by_name = {m.raw_name: m.status for m in analysis.attendance_mappings if m.raw_name}
    assert status_by_name["Timo Weber"] == "present"
    assert status_by_name["Nevio Muster"] == "excused"
    assert status_by_name["Sandro Keller"] == "absent"
