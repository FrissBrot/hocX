"""Nachtlauf 2026-11-19 (protokolle/mandantentrennung): Der Listen-Poll der Zusammenarbeit
(collaboration_ws: _referenced_list_ids, _list_content_versions, _public_list_id_map) läuft in
eigenen SessionLocal()-Sessions ohne Mandantenbindung, RLS greift dort also nicht. Die Listen-IDs
stammen aus configuration_snapshot_json, das ein Schreiber per Block-PATCH frei setzt. Ohne
Mandantenfilter meldete der Socket so «list_changed» mit public_id und content_version fremder
Listen - ein Beobachtungskanal auf Tabellen anderer Vereine."""

import pytest

from app.api.routes import collaboration_ws as ws
from tests.factories import (
    make_list_definition,
    make_protocol,
    make_protocol_element,
    make_protocol_element_block,
    make_template,
    make_tenant,
)


class _Shared:
    def __init__(self, db):
        self._db = db

    def __call__(self):
        return self

    def close(self):
        pass

    def __getattr__(self, name):
        return getattr(self._db, name)


@pytest.fixture
def shared(db, monkeypatch):
    monkeypatch.setattr(ws, "SessionLocal", _Shared(db))


def test_list_poll_ignores_lists_of_other_tenants(db, shared):
    tenant_a = make_tenant(db, "Tenant A")
    tenant_b = make_tenant(db, "Tenant B")
    own = make_list_definition(db, tenant_a.id)
    foreign = make_list_definition(db, tenant_b.id)
    foreign_row = make_list_definition(db, tenant_b.id, name="Fremde Zeilenliste")
    template = make_template(db, tenant_a.id)
    protocol = make_protocol(db, tenant_a.id, template.id)
    element = make_protocol_element(db, protocol.id)
    make_protocol_element_block(db, element.id, configuration_snapshot_json={"linked_list_id": own.id})
    make_protocol_element_block(db, element.id, configuration_snapshot_json={"linked_list_id": foreign.id}, sort_index=1)
    make_protocol_element_block(
        db, element.id,
        configuration_snapshot_json={"rows": [{"id": "r", "value_type": "list_entry", "linked_list_id": foreign_row.id}]},
        sort_index=2,
    )

    list_ids = ws._referenced_list_ids(protocol.id)

    assert list_ids == {own.id}
