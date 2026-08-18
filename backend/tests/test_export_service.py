"""Regression tests for ExportService (PDF/LaTeX rendering of a protocol) - previously zero
test coverage despite being 2100+ lines and the single most user-visible feature in hocX
(every protocol eventually gets exported). Not aiming for exhaustive line coverage of every
block type - just: a typical protocol renders to a real, non-trivial PDF without raising,
the attendance-block present/late/excused/absent counting is correct, and an empty protocol
degrades gracefully instead of crashing.

Uses a minimal, self-contained fake document-template directory (no fontspec/custom fonts)
rather than depending on any tenant's real, materialized document template - keeps this
independent of production data and fast (plain pdflatex, no xelatex needed).
"""
from __future__ import annotations

import asyncio
import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import select

from app.core.config import settings
from app.models.entities import StoredFile, TodoStatus
from app.services.export_service import ExportService
from tests.factories import (
    make_participant,
    make_protocol,
    make_protocol_element,
    make_protocol_element_block,
    make_protocol_text,
    make_protocol_todo,
    make_template,
    make_tenant,
)


def _make_empty_template_dir() -> str:
    """A minimal, self-contained document-template directory: no fontspec/custom fonts (so
    plain pdflatex, not xelatex, is used - see ExportService._resolve_compiler), just enough
    of a theme.tex to define \\hocxSecondary, which the attendance block (element_type_id 9)
    unconditionally references via \\color{hocxSecondary}. Every other optional .tex partial
    (preamble/macros/header_footer/title_page/toc) is legitimately allowed to be absent -
    ExportService._read_optional() treats a missing file as ""."""
    template_dir = tempfile.mkdtemp(prefix="hocx-test-template-")
    styles_dir = Path(template_dir) / "styles"
    styles_dir.mkdir(parents=True, exist_ok=True)
    (styles_dir / "theme.tex").write_text(
        "\\usepackage{xcolor}\n\\definecolor{hocxSecondary}{rgb}{0.4,0.4,0.4}\n",
        encoding="utf-8",
    )
    return template_dir


def _protocol_with_template_dir(db, *, template_dir: str | None = None) -> tuple:
    tenant = make_tenant(db, "Export Test Verein")
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id, protocol_number="EXP-1")
    protocol.document_template_path_snapshot = template_dir or _make_empty_template_dir()
    db.add(protocol)
    db.flush()
    return tenant, template, protocol


def _read_generated_file_bytes(db, generated_file_id: int) -> bytes:
    stored_file = db.get(StoredFile, generated_file_id)
    assert stored_file is not None
    path = Path(settings.storage_root) / stored_file.storage_path
    return path.read_bytes()


# --- typical protocol: text + attendance + bullet list, full PDF compile ----------------


def test_export_pdf_typical_protocol_produces_a_real_pdf(db):
    tenant, template, protocol = _protocol_with_template_dir(db)
    participant = make_participant(db, tenant.id, display_name="Anna Muster")

    element = make_protocol_element(db, protocol.id, sort_index=0, section_name="Traktandum 1")

    text_block = make_protocol_element_block(db, element.id, configuration_snapshot_json={}, sort_index=0, element_type_code="text")
    make_protocol_text(db, text_block.id, content="Dies ist ein **wichtiger** Beschluss.")

    attendance_block = make_protocol_element_block(
        db, element.id, sort_index=1, element_type_code="attendance",
        configuration_snapshot_json={
            "attendance_entries": [
                {"participant_id": participant.id, "status": "present"},
                {"participant_name": "Bruno Beispiel", "status": "late"},
                {"participant_name": "Clara Muster", "status": "excused"},
                {"participant_name": "Dario Test", "status": "absent"},
            ]
        },
    )

    bullet_block = make_protocol_element_block(
        db, element.id, sort_index=2, element_type_code="bullet_list",
        configuration_snapshot_json={"bullet_items": ["Erster Punkt", "Zweiter Punkt"]},
    )
    assert attendance_block.id and bullet_block.id  # keep references alive/used

    service = ExportService()
    result = asyncio.run(service.export_pdf(db, protocol.id))

    assert result.status == "generated"
    assert result.export_format == "pdf"
    pdf_bytes = _read_generated_file_bytes(db, result.generated_file_id)
    assert pdf_bytes.startswith(b"%PDF")
    # A one-page protocol with real content compiles to well over a trivial/empty size.
    assert len(pdf_bytes) > 2000


def test_export_latex_attendance_counts_all_four_buckets_correctly(db):
    """Exercises the present/late/excused/absent counting at the heart of the attendance
    block (export_service.py, _default_block_content element_type_id == 9) via the same
    body-rendering path export_latex/export_pdf use, without paying for a full pdflatex
    compile - _build_export_context builds the LaTeX body content but doesn't invoke
    pdflatex itself."""
    tenant, template, protocol = _protocol_with_template_dir(db)
    element = make_protocol_element(db, protocol.id, sort_index=0, section_name="Anwesenheit")
    make_protocol_element_block(
        db, element.id, sort_index=0, element_type_code="attendance",
        configuration_snapshot_json={
            "attendance_entries": [
                {"participant_name": "A", "status": "present"},
                {"participant_name": "B", "status": "present"},
                {"participant_name": "C", "status": "late"},
                {"participant_name": "D", "status": "excused"},
                {"participant_name": "E", "status": "absent"},
                {"participant_name": "F", "status": "absent"},
            ]
        },
    )

    service = ExportService()
    _protocol, _export_dir, _latex_source, body_content = service._build_export_context(db, protocol.id)

    assert "2 Anwesend" in body_content
    assert "1 Verspaetet" in body_content
    assert "1 Entschuldigt" in body_content
    assert "2 Unentschuldigt" in body_content


# --- edge case: empty protocol (no elements at all) --------------------------------------


def test_export_pdf_of_empty_protocol_does_not_crash(db):
    tenant, template, protocol = _protocol_with_template_dir(db)
    # No protocol_element / block / text at all - the protocol body is entirely empty.

    service = ExportService()
    result = asyncio.run(service.export_pdf(db, protocol.id))

    assert result.status == "generated"
    pdf_bytes = _read_generated_file_bytes(db, result.generated_file_id)
    assert pdf_bytes.startswith(b"%PDF")


def test_export_pdf_raises_for_unknown_protocol(db):
    import pytest

    service = ExportService()
    with pytest.raises(ValueError, match="Protocol not found"):
        asyncio.run(service.export_pdf(db, 999_999_999))


def test_export_pdf_raises_when_document_template_snapshot_missing(db):
    """A protocol whose document_template_path_snapshot points at a directory that no
    longer exists on disk (e.g. cleaned up / never materialized) must fail with a clear
    error instead of a confusing filesystem exception deep inside shutil.copytree."""
    import pytest

    tenant, template, protocol = _protocol_with_template_dir(db, template_dir="/no/such/directory/at/all")

    service = ExportService()
    with pytest.raises(ValueError, match="Document template snapshot path not found"):
        asyncio.run(service.export_pdf(db, protocol.id))


def test_export_global_todo_markdown_formats_grouped_whatsapp_view(db):
    tenant = make_tenant(db, "Markdown Export Verein")
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id, protocol_number="P-42")
    protocol.title = "Lagerplanung"
    db.add(protocol)

    element = make_protocol_element(db, protocol.id, section_name="Todos")
    todo_block = make_protocol_element_block(db, element.id, configuration_snapshot_json={}, element_type_code="todo")
    anna = make_participant(db, tenant.id, display_name="Anna Muster")
    make_participant(db, tenant.id, display_name="Bruno Beispiel")

    todo_included = make_protocol_todo(db, todo_block.id, task="Material einkaufen")
    todo_included.assigned_participant_id = anna.id
    todo_included.due_date = datetime(2026, 1, 3).date()
    todo_included.tags = ["Camp", "Kueche"]

    todo_filtered_out = make_protocol_todo(db, todo_block.id, task="Bus anfragen", sort_index=1)
    todo_filtered_out.assigned_participant_id = anna.id
    todo_filtered_out.due_date = datetime(2026, 1, 10).date()
    db.add_all([todo_included, todo_filtered_out])
    db.flush()

    service = ExportService()
    markdown = service.export_global_todo_markdown(
        db,
        tenant.id,
        "open",
        group_by_person=True,
        until_date="2026-01-05",
        date_summary="Bis nächster Hock",
    )

    assert "*Offene Todos*" in markdown
    assert "Ansicht: Nach Person gruppiert" in markdown
    assert "Zeitraum: Bis nächster Hock (05.01.2026)" in markdown
    assert "*Anna Muster (1)*" in markdown
    assert "1. Material einkaufen" in markdown
    assert "Fällig: 03.01.2026" in markdown
    assert "Protokoll: P-42 · Lagerplanung" in markdown
    assert "Tags: Camp, Kueche" in markdown
    assert "Bus anfragen" not in markdown


def test_export_global_todo_markdown_marks_completed_items_in_all_view(db):
    tenant = make_tenant(db, "Markdown Status Verein")
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id, protocol_number="P-9")
    element = make_protocol_element(db, protocol.id, section_name="Todos")
    todo_block = make_protocol_element_block(db, element.id, configuration_snapshot_json={}, element_type_code="todo")

    open_todo = make_protocol_todo(db, todo_block.id, task="Offene Aufgabe")
    done_todo = make_protocol_todo(db, todo_block.id, task="Erledigte Aufgabe", sort_index=1)
    done_status_id = db.scalar(select(TodoStatus.id).where(TodoStatus.code == "done"))
    done_todo.todo_status_id = done_status_id
    db.add_all([open_todo, done_todo])
    db.flush()

    service = ExportService()
    markdown = service.export_global_todo_markdown(db, tenant.id, "all")

    assert "*Todo-Übersicht*" in markdown
    assert "Offen: 1 | Erledigt: 1 | Abgebrochen: 0" in markdown
    assert "1. Offene Aufgabe [Offen]" in markdown
    assert "2. ~Erledigte Aufgabe~ [Erledigt]" in markdown


# --- M17: EXPORT_ROOT/generated needs a retention sweep (no cleanup job previously) ---------


def test_m17_cleanup_old_generated_exports_deletes_only_files_past_retention(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "export_root", str(tmp_path))
    generated_dir = tmp_path / "generated"
    generated_dir.mkdir()

    old_file = generated_dir / "old-export.pdf"
    old_file.write_bytes(b"%PDF-old")
    recent_file = generated_dir / "recent-export.pdf"
    recent_file.write_bytes(b"%PDF-recent")

    old_timestamp = (datetime.now() - timedelta(days=31)).timestamp()
    os.utime(old_file, (old_timestamp, old_timestamp))

    service = ExportService()
    result = service.cleanup_old_generated_exports()

    assert result == {"deleted": 1}
    assert not old_file.exists()
    assert recent_file.exists()


def test_m17_cleanup_old_generated_exports_respects_custom_retention(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "export_root", str(tmp_path))
    generated_dir = tmp_path / "generated"
    generated_dir.mkdir()

    file_path = generated_dir / "export.pdf"
    file_path.write_bytes(b"%PDF")
    ten_days_ago = (datetime.now() - timedelta(days=10)).timestamp()
    os.utime(file_path, (ten_days_ago, ten_days_ago))

    service = ExportService()

    assert service.cleanup_old_generated_exports(retention_days=30) == {"deleted": 0}
    assert file_path.exists()

    assert service.cleanup_old_generated_exports(retention_days=5) == {"deleted": 1}
    assert not file_path.exists()


def test_m17_cleanup_old_generated_exports_missing_dir_is_a_noop(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "export_root", str(tmp_path / "does-not-exist"))

    service = ExportService()

    assert service.cleanup_old_generated_exports() == {"deleted": 0}
