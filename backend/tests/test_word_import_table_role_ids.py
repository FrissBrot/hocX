"""Public table overrides must be decoded on both analysis endpoints."""
import asyncio
import io
import json
import uuid
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException, UploadFile

from app.api.routes import word_import as routes
from app.models import ListDefinition
from app.schemas.word_import import TablePreview, WordImportAnalysis, WordImportDocumentReanalyzeRequest


@pytest.mark.parametrize("endpoint", ["analyze", "reanalyze"])
def test_analysis_decodes_list_uuid(monkeypatch, endpoint):
    public_id = uuid.UUID("01a067ae-27a5-7e49-986a-5606a4cdda10")
    db = object()
    user = SimpleNamespace(current_tenant_id=7)
    override = {0: {"role": "list", "list_definition_id": str(public_id), "list_grouping_strategy": "fill_down"}}
    resolver = Mock(return_value={public_id: 42})
    monkeypatch.setattr(routes.public_id_service, "resolve_internal_ids", resolver)
    monkeypatch.setattr(routes, "require_writer", lambda user: None)
    monkeypatch.setattr(routes, "_encode_analysis", lambda db, analysis: analysis)

    def analyze(db, **kwargs):
        role = kwargs["table_role_overrides"][0]
        assert role["list_grouping_strategy"] == "fill_down"
        return WordImportAnalysis(tables=[TablePreview(index=0, **role)])

    if endpoint == "analyze":
        monkeypatch.setattr(routes, "_resolve_template_id", lambda *args: 1)
        monkeypatch.setattr(routes.service, "analyze", analyze)
        result = asyncio.run(routes.analyze_word_import(
            file=UploadFile(filename="test.docx", file=io.BytesIO(b"document")),
            template_id=uuid.uuid4(), protocol_date_hint=None,
            table_roles_json=json.dumps(override), db=db, user=user,
        ))
    else:
        monkeypatch.setattr(routes, "_resolve_document_id", lambda *args: 1)
        monkeypatch.setattr(routes.queue_service, "get_document", lambda *args, **kwargs: object())
        monkeypatch.setattr(routes.queue_service, "reanalyze", analyze)
        result = routes.reanalyze_word_import_document(
            document_id=uuid.uuid4(), payload=WordImportDocumentReanalyzeRequest(table_roles=override),
            db=db, user=user,
        )
    assert result.tables[0].list_definition_id == 42
    resolver.assert_called_once_with(db, ListDefinition, [public_id], tenant_id=7)
    assert override[0]["list_definition_id"] == str(public_id)


@pytest.mark.parametrize("value", [None, [], {"0": None}, {"0": {"list_definition_id": "invalid"}}, {"0": {"list_definition_id": 42}}])
def test_invalid_table_roles_return_bad_request(value):
    with pytest.raises(HTTPException) as exc:
        routes._decode_table_roles(None, 7, value)
    assert exc.value.status_code == 400


def test_missing_or_foreign_list_is_rejected(monkeypatch):
    monkeypatch.setattr(routes.public_id_service, "resolve_internal_ids", Mock(return_value={}))
    with pytest.raises(HTTPException) as exc:
        routes._decode_table_roles(None, 7, {0: {"role": "list", "list_definition_id": str(uuid.uuid4())}})
    assert exc.value.status_code == 400
    assert exc.value.detail == "Liste nicht gefunden"


def test_non_list_overrides_are_preserved():
    roles = {0: {"role": "attendance"}, 1: {"role": "matrix", "matrix_key": "block-1", "list_definition_id": None}}
    assert routes._decode_table_roles(None, 7, roles) == roles
