"""Eingeschränkte Fassung: fehlen dem Exportierenden Rechte für einen Teil der Daten, steht an der
Stelle ein Platzhalter (nie stillschweigend weggelassen), und das PDF ist ein Entwurf ohne Version,
im Register als eingeschränkt gekennzeichnet und keine Version des Protokoll-Dokuments."""
from __future__ import annotations

import asyncio
from datetime import date

from sqlalchemy import select

from app.core.storage import MAIN, get_object_store
from app.documents import compiler, service
from app.documents.catalog import BlockSpec, FinesParams
from app.documents.context import BuildContext
from app.documents.providers import finance
from app.documents.service import DocumentRequest
from app.models import AttendanceFine, DocumentRegistry
from tests.documents.conftest import pdf_text
from tests.factories import (
    make_current_user,
    make_finance_account,
    make_participant,
    make_protocol,
    make_protocol_element,
    make_protocol_element_block,
    make_protocol_text,
    make_template,
    make_tenant,
)


def _fines_setup(db):
    tenant = make_tenant(db, "Bussenrechte")
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id, status="abgeschlossen")
    own = make_participant(db, tenant.id, "Eigene Person")
    other = make_participant(db, tenant.id, "Andere Person")
    account = make_finance_account(db, tenant.id)
    for person in (own, other):
        db.add(AttendanceFine(
            protocol_id=protocol.id, participant_id=person.id, participant_name_snapshot=person.display_name,
            fine_type="absent", amount=10, account_id=account.id, status="pending",
        ))
    db.flush()
    return tenant, own


def test_fines_of_others_become_a_visible_placeholder(db):
    tenant, own = _fines_setup(db)
    reader = make_current_user(tenant.id, role="reader", user_id=own.id)
    ctx = BuildContext(db=db, tenant_id=tenant.id, language="de", user=reader)
    [block] = finance.provide_fines(ctx, BlockSpec(type="fines"), FinesParams())
    assert block.table.row_count() == 1
    assert block.restricted and "(1)" in block.restricted and "Berechtigung" in block.restricted
    assert ctx.restrictions == ["finesHidden"]

    admin_ctx = BuildContext(db=db, tenant_id=tenant.id, language="de", user=make_current_user(tenant.id, role="admin", user_id=own.id))
    [full] = finance.provide_fines(admin_ctx, BlockSpec(type="fines"), FinesParams())
    assert full.table.row_count() == 2 and full.restricted is None and admin_ctx.restrictions == []


def test_run_component_attaches_notes_the_provider_did_not_set(db, monkeypatch):
    tenant = make_tenant(db, "Platzhalter")
    ctx = BuildContext(db=db, tenant_id=tenant.id, language="de")
    original = compiler.PROVIDERS["fines"]

    def forgetful(ctx, spec, params):
        blocks = original(ctx, spec, params)
        ctx.restriction_note("statisticsScope")
        return blocks

    monkeypatch.setitem(compiler.PROVIDERS, "fines", forgetful)
    [block] = compiler.run_component(ctx, BlockSpec(type="fines"))
    # Leer, aber mit Platzhalter: der Block bleibt und trägt den Hinweis
    assert block.empty and block.restricted and "Vorlagen" in block.restricted


def _protocol(db):
    tenant = make_tenant(db, "Eingeschränkt")
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id, protocol_number="E-1", protocol_date=date(2026, 5, 1), status="durchgeführt")
    block = make_protocol_element_block(db, make_protocol_element(db, protocol.id, section_name="Traktandum").id, {}, element_type_code="text")
    make_protocol_text(db, block.id, "Inhalt")
    return tenant, protocol


def test_restricted_export_is_an_unversioned_marked_draft(db, monkeypatch):
    tenant, protocol = _protocol(db)
    original = compiler.PROVIDERS["protocol_element"]

    def with_hidden_data(ctx, spec, params):
        ctx.restriction_note("todos")
        return original(ctx, spec, params)

    monkeypatch.setitem(compiler.PROVIDERS, "protocol_element", with_hidden_data)
    request = DocumentRequest(protocol_id=protocol.public_id, document_type="protocol")
    result = asyncio.run(service.render(db, None, tenant.id, request))
    export = result.export

    assert export.version_label is None and export.version_major is None
    assert (export.options_json or {}).get("restricted") == ["todos"]
    entry = db.scalar(select(DocumentRegistry).where(DocumentRegistry.public_id == export.public_id))
    assert entry.document_type == "protocol_restricted" and entry.status_code is None
    assert protocol.version_minor == 0  # zählt nicht als Protokollversion
    text = pdf_text(get_object_store().get_bytes(MAIN, result.stored_file.storage_path))
    assert "Eingeschränkte Fassung" in text

    # Eine eingeschränkte Fassung wird nie wiederverwendet
    again = asyncio.run(service.render(db, None, tenant.id, request)).export
    assert again.public_id != export.public_id
