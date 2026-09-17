from copy import deepcopy
from pathlib import Path
import uuid

import pytest
from fastapi import HTTPException

from app.api.routes.word_import import _encode_analysis
from app.models import DocumentTemplate, DocumentTemplatePart
from app.schemas.document_template import DocumentTemplateCreate, DocumentTemplateUpdate
from app.schemas.word_import import WordImportAnalysis, WordImportTextMapping, WordImportFormFieldValue
from app.services.document_template_service import DocumentTemplateService
from app.services.document_template_config_ids import translate_part_ids
from app.services.snapshot_reference_ids import snapshot_reference_ids
from tests.factories import make_tenant, make_list_definition, make_finance_account


def test_document_template_part_references_round_trip_and_materialize(db, tmp_path, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "storage_root", str(tmp_path))
    tenant = make_tenant(db)
    source = tmp_path / "custom.tex"
    source.write_text("% custom preamble")
    part = DocumentTemplatePart(tenant_id=tenant.id, code="custom", name="Custom", part_type="preamble", storage_path=str(source))
    db.add(part)
    db.flush()
    public_id = str(part.public_id)
    config = {"slots": {"preamble": public_id}, "theme": {"font_parts": {"font_regular": public_id}},
              "title_assets": {"header_image_part_id": public_id, "footer_image_part_id": None}}
    original = deepcopy(config)
    decoded = translate_part_ids(db, config, tenant_id=tenant.id, decode=True)
    assert decoded["theme"]["font_parts"]["font_regular"] == part.id
    assert decoded["title_assets"]["header_image_part_id"] == part.id
    assert translate_part_ids(db, decoded, tenant_id=tenant.id, decode=False) == original
    assert config == original

    service = DocumentTemplateService()
    payload = {"slots": {"preamble": public_id}}
    result = service.create_document_template(db, DocumentTemplateCreate(name="Custom", configuration_json=payload), tenant_id=tenant.id)
    assert result.configuration_json == payload
    assert (Path(result.filesystem_path) / "preamble.tex").read_text() == "% custom preamble"
    from app.services.public_id_service import get_by_public_id
    stored = get_by_public_id(db, DocumentTemplate, result.id, tenant_id=tenant.id)
    assert stored.configuration_json == {"slots": {"preamble": part.id}}
    updated = service.update_document_template(db, stored.id, DocumentTemplateUpdate(configuration_json=result.configuration_json))
    assert updated.configuration_json == payload
    assert service.get_document_template(db, stored.id).configuration_json == payload
    assert service.list_document_templates(db, tenant.id)[0].configuration_json == payload


def test_document_template_rejects_foreign_and_invalid_parts(db):
    tenant = make_tenant(db)
    other = make_tenant(db)
    part = DocumentTemplatePart(tenant_id=other.id, code="foreign", name="Foreign", part_type="preamble", storage_path="/tmp/foreign.tex")
    db.add(part)
    db.flush()
    for value in (str(part.public_id), str(uuid.uuid4()), "invalid", part.id):
        with pytest.raises(HTTPException) as exc:
            translate_part_ids(db, {"slots": {"preamble": value}}, tenant_id=tenant.id, decode=True)
        assert exc.value.status_code == 400


def test_snapshot_public_references_preserve_internal_config_and_scope(db):
    tenant = make_tenant(db)
    other = make_tenant(db)
    lists = [make_list_definition(db, tenant.id, name=str(i)) for i in range(3)]
    foreign = make_list_definition(db, other.id)
    account = make_finance_account(db, tenant.id)
    config = {"linked_list_id": lists[0].id, "auto_source": {"list_id": lists[1].id},
              "rows": [{"linked_list_id": lists[2].id}, {"row_config": {"linked_list_id": foreign.id}}],
              "finance_account_id": account.id}
    original = deepcopy(config)
    result = snapshot_reference_ids(db, config, tenant.id)
    assert result == {"lists": {str(item.id): str(item.public_id) for item in lists},
                      "finance_accounts": {str(account.id): str(account.public_id)}}
    assert config == original

    from tests.factories import make_template, make_protocol, make_protocol_element, make_protocol_element_block
    from app.services.protocol_element_service import ProtocolElementService
    from app.api.routes.protocol_elements import _block_to_read
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id)
    element = make_protocol_element(db, protocol.id)
    block = make_protocol_element_block(db, element.id, config)
    response = ProtocolElementService().list_protocol_elements(db, protocol.id)[0].blocks[0]
    assert response.model_dump(mode="json")["public_reference_ids"] == result
    assert _block_to_read(db, block).model_dump(mode="json")["public_reference_ids"] == result
    assert block.configuration_snapshot_json == original


def test_word_import_form_target_keys_use_public_element_ids(monkeypatch):
    from app.api.routes import word_import as routes
    from app.models import TemplateElement
    public_id = uuid.uuid4()
    def resolve(db, model, ids):
        if model is TemplateElement:
            assert ids == [42]
            return {42: public_id}
        return {}
    monkeypatch.setattr(routes.public_id_service, "resolve_public_ids", resolve)
    analysis = WordImportAnalysis(text_mappings=[WordImportTextMapping(
        extracted_heading="Form", extracted_text="Value",
        form_fields_by_target={"42:10": [WordImportFormFieldValue(row_id="1", label="Name", row_type="text", raw_value="Value")]},
    )])
    encoded = _encode_analysis(None, analysis)
    fields = encoded.text_mappings[0].form_fields_by_target[f"{public_id}:10"]
    assert fields[0].raw_value == "Value"
    assert "42:10" in analysis.text_mappings[0].form_fields_by_target
