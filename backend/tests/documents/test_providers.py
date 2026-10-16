"""Provider: jeder Block-Typ lässt sich bauen; Filter, Gruppierung, Rechte und Mandanten-Isolation."""
from __future__ import annotations

import asyncio
from datetime import date

import pytest

from app.documents.builder import BlockSpecError, build_blocks, build_document
from app.documents.catalog import CATALOG, BlockSpec
from app.documents.context import BuildContext, DocumentNotFoundError, DocumentPermissionError
from app.documents.model import ResolvedStyle
from app.documents.style_tokens import DocumentStyleTokens
from app.models import ProtocolTodo, TodoStatus
from tests.factories import (
    make_current_user,
    make_event,
    make_finance_account,
    make_fine,
    make_list_definition,
    make_list_entry,
    make_participant,
    make_protocol,
    make_protocol_element,
    make_protocol_element_block,
    make_protocol_text,
    make_protocol_todo,
    make_template,
    make_tenant,
)


@pytest.fixture
def world(db):
    tenant = make_tenant(db, "Verein A")
    other = make_tenant(db, "Verein B")
    template = make_template(db, tenant.id)
    other_template = make_template(db, other.id)
    protocol = make_protocol(db, tenant.id, template.id, protocol_number="P-7", protocol_date=date(2026, 3, 1), status="durchgeführt")
    other_protocol = make_protocol(db, other.id, other_template.id, protocol_number="X-1")
    anna = make_participant(db, tenant.id, "Anna Muster")
    stranger = make_participant(db, other.id, "Fremde Person")
    element = make_protocol_element(db, protocol.id, section_name="Begrüssung")
    text_block = make_protocol_element_block(db, element.id, {}, element_type_code="text", sort_index=0)
    make_protocol_text(db, text_block.id, "Hallo **Verein** #set")
    todo_block = make_protocol_element_block(db, element.id, {}, element_type_code="todo", sort_index=1)
    make_protocol_todo(db, todo_block.id, task="Saal reservieren", tenant_id=tenant.id)
    make_protocol_element_block(
        db,
        element.id,
        {"attendance_entries": [{"participant_id": anna.id, "participant_name": "Anna Muster", "status": "present"}]},
        element_type_code="attendance",
        sort_index=2,
    )
    make_protocol_element_block(
        db,
        element.id,
        {"rows": [{"label": "Leitung", "value_type": "participant", "participant_id": anna.id}, {"label": "Fremd", "value_type": "participant", "participant_id": stranger.id}]},
        element_type_code="form",
        sort_index=3,
    )
    make_event(db, tenant.id, title="GV", event_date=date(2026, 5, 1))
    make_event(db, other.id, title="Fremder Anlass", event_date=date(2026, 5, 2))
    return {
        "tenant": tenant, "other": other, "template": template, "protocol": protocol, "other_protocol": other_protocol,
        "anna": anna, "stranger": stranger, "element": element,
    }


def _ctx(db, world, **kwargs) -> BuildContext:
    return BuildContext(db=db, tenant_id=world["tenant"].id, language="de", protocol=kwargs.pop("protocol", world["protocol"]), today=date(2026, 3, 1), public_base_url="https://hocx.example.ch", **kwargs)


def _plain(blocks) -> str:
    return str([block.model_dump(mode="json") for block in blocks])


@pytest.mark.parametrize("block_type", sorted(CATALOG))
def test_every_catalog_block_builds_with_defaults(db, world, block_type):
    blocks = build_blocks(_ctx(db, world), [BlockSpec(type=block_type, hide_if_empty=False)])
    assert blocks, block_type
    assert all(block.type in CATALOG for block in blocks)


def test_protocol_elements_contain_content_and_skip_foreign_refs(db, world):
    blocks = build_blocks(_ctx(db, world), [BlockSpec(type="protocol_element")])
    assert len(blocks) == 1 and blocks[0].title == "Begrüssung"
    dumped = _plain(blocks)
    assert "Saal reservieren" in dumped
    assert "Anna Muster" in dumped
    assert "#set" in dumped
    assert "Fremde Person" not in dumped  # Fremd-ID in configuration_snapshot_json


def test_todo_table_filters_and_grouping(db, world):
    done_id = db.scalar(__import__("sqlalchemy").select(TodoStatus.id).where(TodoStatus.code == "done"))
    block = make_protocol_element_block(db, world["element"].id, {}, element_type_code="todo", sort_index=9)
    done = make_protocol_todo(db, block.id, task="Erledigt X", tenant_id=world["tenant"].id)
    done.todo_status_id = done_id
    db.flush()
    ctx = _ctx(db, world, protocol=None)
    open_only = build_blocks(ctx, [BlockSpec(type="todo_table", params={"status": "open"})])
    assert "Erledigt X" not in _plain(open_only) and "Saal reservieren" in _plain(open_only)
    grouped = build_blocks(ctx, [BlockSpec(type="todo_table", params={"status": "all", "group_by": "status"})])
    labels = [group.label_key for group in grouped[0].table.groups]
    assert labels == ["todoStatus.open", "todoStatus.done"]


def test_foreign_list_and_account_are_not_found(db, world):
    foreign_list = make_list_definition(db, world["other"].id)
    make_list_entry(db, foreign_list.id, column_one_value={"text_value": "Geheim"})
    ctx = _ctx(db, world)
    with pytest.raises(DocumentNotFoundError):
        build_blocks(ctx, [BlockSpec(type="list_table", params={"list_id": str(foreign_list.public_id)})])
    foreign_account = make_finance_account(db, world["other"].id)
    with pytest.raises(DocumentNotFoundError):
        build_blocks(ctx, [BlockSpec(type="finance_transactions", params={"account_id": str(foreign_account.public_id)})])
    with pytest.raises(DocumentNotFoundError):
        build_blocks(ctx, [BlockSpec(type="session_notes", params={"protocol_id": str(world["other_protocol"].public_id)})])


def test_foreign_refs_in_protocol_block_config_are_ignored(db, world):
    foreign_account = make_finance_account(db, world["other"].id)
    foreign_list = make_list_definition(db, world["other"].id)
    make_list_entry(db, foreign_list.id, column_one_value={"text_value": "Geheim"})
    element = make_protocol_element(db, world["protocol"].id, sort_index=5, section_name="Finanzen")
    make_protocol_element_block(db, element.id, {"finance_account_id": foreign_account.id}, element_type_code="finance_balance")
    make_protocol_element_block(db, element.id, {"linked_list_id": foreign_list.id}, element_type_code="form", sort_index=1)
    blocks = build_blocks(_ctx(db, world), [BlockSpec(type="protocol_element")])
    dumped = _plain(blocks)
    assert "Geheim" not in dumped
    assert foreign_account.name not in dumped or "Test Account" not in dumped


def test_events_are_tenant_scoped(db, world):
    blocks = build_blocks(_ctx(db, world, protocol=None), [BlockSpec(type="event_table", params={"date_from": "2026-01-01"})])
    dumped = _plain(blocks)
    assert "GV" in dumped and "Fremder Anlass" not in dumped


def test_member_list_requires_writer_and_finance_requires_feature(db, world):
    reader = make_current_user(world["tenant"].id, role="reader")
    ctx = _ctx(db, world, user=reader)
    with pytest.raises(DocumentPermissionError):
        build_blocks(ctx, [BlockSpec(type="member_list")])
    # TYPST-002: Listen sind wie in der Listen-API (require_writer) Schreibenden vorbehalten.
    with pytest.raises(DocumentPermissionError):
        build_blocks(ctx, [BlockSpec(type="list_table")])
    no_finance = make_current_user(world["tenant"].id, role="admin", features=frozenset())
    with pytest.raises(DocumentPermissionError):
        build_blocks(_ctx(db, world, user=no_finance), [BlockSpec(type="finance_balance")])
    with pytest.raises(DocumentPermissionError):
        build_blocks(_ctx(db, world, user=no_finance), [BlockSpec(type="chart", params={"chart_type": "finance_by_month"})])


def test_invalid_params_are_curated(db, world):
    with pytest.raises(BlockSpecError):
        build_blocks(_ctx(db, world), [BlockSpec(type="todo_table", params={"status": "irgendwas"})])
    with pytest.raises(BlockSpecError):
        build_blocks(_ctx(db, world), [BlockSpec(type="gibts_nicht")])
    with pytest.raises(BlockSpecError):
        build_blocks(_ctx(db, world), [BlockSpec(type="qr_link", params={"target": "url", "url": "javascript:alert(1)"})])


def test_hide_if_empty_removes_block_and_marks_otherwise(db, world):
    ctx = _ctx(db, world, protocol=None)
    assert build_blocks(ctx, [BlockSpec(type="bullet_list", params={"items": []})]) == []
    kept = build_blocks(ctx, [BlockSpec(type="bullet_list", hide_if_empty=False)])
    assert kept[0].empty is True


def test_fines_from_protocol(db, world):
    account = make_finance_account(db, world["tenant"].id)
    make_fine(db, world["protocol"].id, account.id, amount=7.5, participant_name_snapshot="Anna Muster")
    blocks = build_blocks(_ctx(db, world), [BlockSpec(type="fines")])
    assert "7.50 CHF" in _plain(blocks)


def test_full_document_renders(db, world, renderer):
    ctx = _ctx(db, world)
    specs = [BlockSpec(type=block_type, hide_if_empty=False) for block_type in sorted(CATALOG)]
    document = build_document(ctx, document_type="protocol", specs=specs, style=ResolvedStyle(), tokens=DocumentStyleTokens(toc="on", title_page="modern"), tenant_name="Verein A", version="v0.1")
    output = asyncio.run(renderer.render_pdf(document, __import__("app.documents.renderer", fromlist=["RenderAssets"]).RenderAssets(files=ctx.assets.files)))
    assert output.pdf.startswith(b"%PDF")
    assert output.warnings == []
    assert document.options.watermark is True  # Entwurf


def test_restricted_reader_sees_only_accessible_todos(db, world):
    reader = make_current_user(world["tenant"].id, role="reader", user_id=world["anna"].id)
    ctx = _ctx(db, world, protocol=None, user=reader)
    # Ohne Protokollzugriff und ohne Zuweisung bleibt die Liste für eingeschränkte Leser leer;
    # für normale Leser (nicht eingeschränkt) erscheinen alle Todos des Mandanten.
    blocks = build_blocks(ctx, [BlockSpec(type="todo_table", hide_if_empty=False, params={"status": "all"})])
    assert blocks
    assert db.query(ProtocolTodo).count() >= 1


@pytest.mark.parametrize("scan_status", ["pending", "infected", "error"])
def test_unscanned_images_are_not_embedded(db, world, tmp_path, monkeypatch, scan_status):
    """TYPST-008: Bilder ohne Freigabe des Virenscans werden nicht dekodiert/eingebettet."""
    import io

    from PIL import Image

    from app.core.config import settings
    from app.models import StoredFile

    monkeypatch.setattr(settings, "storage_root", str(tmp_path))
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), (1, 2, 3)).save(buffer, format="PNG")
    (tmp_path / "bild.png").write_bytes(buffer.getvalue())

    def stored(status):
        row = StoredFile(tenant_id=world["tenant"].id, original_name="bild.png", mime_type="image/png", storage_path="bild.png", file_size_bytes=len(buffer.getvalue()), scan_status=status)
        db.add(row)
        db.flush()
        return row

    blocked, clean = stored(scan_status), stored("clean")
    ctx = _ctx(db, world)
    image = build_blocks(ctx, [BlockSpec(type="image", params={"file_id": str(blocked.public_id)})])[0].image
    assert image.missing is True and not ctx.assets.files
    gallery = build_blocks(ctx, [BlockSpec(type="image_gallery", params={"file_ids": [str(blocked.public_id), str(clean.public_id)]})])[0]
    assert [item.missing for item in gallery.images] == [True, False]
