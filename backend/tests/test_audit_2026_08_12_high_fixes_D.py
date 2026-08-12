"""Regression test for audit finding H10 (2026-08-12, agent D): PDF export's
_render_protocol_body() looped over every protocol element calling
resolve_display_section_title() (the single-item variant, several db.get() calls each) even
though a batch variant, resolve_display_section_titles_batch() (three IN(...) queries total,
already used correctly by ProtocolElementService.list_protocol_elements), existed for exactly
this purpose. For protocols with many elements this multiplied DB roundtrips unnecessarily.

Fix (backend/app/services/export_service.py, around line 611-614): resolve all elements'
titles with one resolve_display_section_titles_batch() call up front, then look each one up
by element.id inside the loop - mirroring protocol_element_service.py's calling convention.

This test verifies two things:
1. Correctness: a protocol mixing a plain (non-live) section title with a live-resolved,
   responsible-participant-bearing title still renders the exact same titles as before.
2. The N+1 is actually gone: resolve_display_section_titles_batch() is called exactly once
   (not once per element), and the single-item resolve_display_section_title() is never
   called at all during the export.
"""
from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from unittest.mock import patch

import app.services.export_service as export_service_module
import app.services.responsible_label_service as responsible_label_service_module
from app.services.export_service import ExportService
from tests.factories import (
    make_participant,
    make_protocol,
    make_protocol_element,
    make_protocol_element_block,
    make_protocol_text,
    make_template,
    make_tenant,
)


def _make_empty_template_dir() -> str:
    """Minimal, self-contained document-template directory (no fontspec/custom fonts) - same
    approach as test_export_service.py's helper, kept local here to avoid cross-test-file
    coupling."""
    template_dir = tempfile.mkdtemp(prefix="hocx-test-template-h10-")
    styles_dir = Path(template_dir) / "styles"
    styles_dir.mkdir(parents=True, exist_ok=True)
    (styles_dir / "theme.tex").write_text(
        "\\usepackage{xcolor}\n\\definecolor{hocxSecondary}{rgb}{0.4,0.4,0.4}\n",
        encoding="utf-8",
    )
    return template_dir


def _protocol_with_template_dir(db, protocol_number: str) -> tuple:
    tenant = make_tenant(db, "H10 Batch Title Verein")
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id, protocol_number=protocol_number)
    protocol.document_template_path_snapshot = _make_empty_template_dir()
    db.add(protocol)
    db.flush()
    return tenant, template, protocol


def test_export_latex_batch_resolves_titles_correctly_and_avoids_per_element_lookups(db):
    tenant, template, protocol = _protocol_with_template_dir(db, "H10-1")

    participant_a = make_participant(db, tenant.id, display_name="Anna Muster")
    participant_b = make_participant(db, tenant.id, display_name="Bruno Beispiel")

    # Element 1: plain section title, not finalized/live-resolvable -> falls back to
    # section_name_snapshot as-is.
    element_plain = make_protocol_element(db, protocol.id, sort_index=0, section_name="Traktandum 1")
    text_block_plain = make_protocol_element_block(db, element_plain.id, configuration_snapshot_json={}, sort_index=0, element_type_code="text")
    make_protocol_text(db, text_block_plain.id, content="Ein Text.")

    # Element 2: live-resolved responsible title via a direct participant_id assignment
    # (no list_entry/list_definition needed to exercise the live path).
    element_live_single = make_protocol_element(db, protocol.id, sort_index=1, section_name="STALE - should not appear")
    element_live_single.element_title_snapshot = "Traktandum 2"
    element_live_single.responsible_assignments_snapshot = [{"participant_id": participant_a.id}]
    element_live_single.responsible_name_display_mode = "display_name"
    db.add(element_live_single)
    make_protocol_element_block(db, element_live_single.id, configuration_snapshot_json={}, sort_index=0, element_type_code="text")

    # Element 3: live-resolved title with two responsible participants.
    element_live_multi = make_protocol_element(db, protocol.id, sort_index=2, section_name="STALE 2 - should not appear")
    element_live_multi.element_title_snapshot = "Traktandum 3"
    element_live_multi.responsible_assignments_snapshot = [
        {"participant_id": participant_a.id},
        {"participant_id": participant_b.id},
    ]
    element_live_multi.responsible_name_display_mode = "display_name"
    db.add(element_live_multi)
    make_protocol_element_block(db, element_live_multi.id, configuration_snapshot_json={}, sort_index=0, element_type_code="text")

    db.flush()

    service = ExportService()

    real_batch_fn = responsible_label_service_module.resolve_display_section_titles_batch
    with patch.object(
        export_service_module, "resolve_display_section_titles_batch", wraps=real_batch_fn
    ) as batch_spy, patch.object(
        responsible_label_service_module, "resolve_display_section_title"
    ) as single_item_spy:
        _protocol, _export_dir, _latex_source, body_content = service._build_export_context(db, protocol.id)

    # Correctness: all three titles resolved as expected.
    assert "Traktandum 1" in body_content
    assert "Traktandum 2 (Anna Muster)" in body_content
    assert "Traktandum 3 (Anna Muster, Bruno Beispiel)" in body_content
    assert "STALE" not in body_content

    # Performance: exactly one batch call for the whole export, and the single-item
    # resolver (the N+1 culprit) is never invoked at all.
    assert batch_spy.call_count == 1
    single_item_spy.assert_not_called()


def test_export_pdf_end_to_end_still_produces_a_real_pdf_with_batch_titles(db):
    """Full export_pdf() path (not just _build_export_context) still works after switching
    to the batch resolver - guards against a wiring mistake breaking the real export
    entrypoint."""
    tenant, template, protocol = _protocol_with_template_dir(db, "H10-2")
    participant = make_participant(db, tenant.id, display_name="Anna Muster")

    element = make_protocol_element(db, protocol.id, sort_index=0, section_name="STALE - should not appear")
    element.element_title_snapshot = "Traktandum"
    element.responsible_assignments_snapshot = [{"participant_id": participant.id}]
    element.responsible_name_display_mode = "display_name"
    db.add(element)
    db.flush()

    text_block = make_protocol_element_block(db, element.id, configuration_snapshot_json={}, sort_index=0, element_type_code="text")
    make_protocol_text(db, text_block.id, content="Ein Beschluss.")

    service = ExportService()
    result = asyncio.run(service.export_pdf(db, protocol.id))

    assert result.status == "generated"
    assert result.export_format == "pdf"
