from copy import deepcopy
import uuid


from app.api.routes.word_import import _encode_analysis
from app.schemas.word_import import WordImportAnalysis, WordImportTextMapping, WordImportFormFieldValue
from app.services.snapshot_reference_ids import snapshot_reference_ids
from tests.factories import make_tenant, make_list_definition, make_finance_account, make_event


def test_snapshot_public_references_preserve_internal_config_and_scope(db):
    tenant = make_tenant(db)
    other = make_tenant(db)
    lists = [make_list_definition(db, tenant.id, name=str(i)) for i in range(3)]
    foreign = make_list_definition(db, other.id)
    account = make_finance_account(db, tenant.id)
    event = make_event(db, tenant.id)
    config = {"repeat_source_type": "event", "repeat_source_id": event.id, "linked_list_id": lists[0].id, "auto_source": {"list_id": lists[1].id},
              "rows": [{"linked_list_id": lists[2].id}, {"row_config": {"linked_list_id": foreign.id}}],
              "finance_account_id": account.id}
    original = deepcopy(config)
    result = snapshot_reference_ids(db, config, tenant.id)
    assert result == {"lists": {str(item.id): str(item.public_id) for item in lists},
                      "finance_accounts": {str(account.id): str(account.public_id)},
                      "events": {str(event.id): str(event.public_id)}}
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
