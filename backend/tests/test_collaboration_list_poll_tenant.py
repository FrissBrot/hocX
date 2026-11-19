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

    list_ids = ws._referenced_list_ids(protocol.id, tenant_a.id)

    assert list_ids == {own.id}


def test_ws_helper_sessions_are_bound_to_the_tenant_under_rls(db, shared):
    """Review 2026-11-19: Die Hilfssessions des Sockets (Listen-Poll, public_id-Übersetzung)
    laufen mit bind_tenant_scope - unter RLS (Rolle hocx_app) liefern sie fremde Listen und Konten
    auch dann nicht, wenn eine fremde interne ID hineingerät."""
    from app.core.tenant_scope import bound_tenant_id
    from tests.factories import make_app_user
    from tests.test_tenant_rls import as_app

    tenant_a = make_tenant(db, "Tenant A")
    tenant_b = make_tenant(db, "Tenant B")
    own = make_list_definition(db, tenant_a.id)
    foreign = make_list_definition(db, tenant_b.id)
    own_user = make_app_user(db, email="ws-own@example.com", tenant_id=tenant_a.id)
    foreign_user = make_app_user(db, email="ws-foreign@example.com", tenant_id=tenant_b.id)
    template = make_template(db, tenant_a.id)
    protocol = make_protocol(db, tenant_a.id, template.id)
    element = make_protocol_element(db, protocol.id)
    make_protocol_element_block(db, element.id, configuration_snapshot_json={"linked_list_id": own.id})

    # IDs vorher festhalten: as_app verwirft den Objektzustand, fremde Zeilen sind danach unsichtbar
    own_id, foreign_id, own_user_id, foreign_user_id = own.id, foreign.id, own_user.id, foreign_user.id
    protocol_id, tenant_a_id = protocol.id, tenant_a.id

    with as_app(db, None):
        assert set(ws._list_content_versions({own_id, foreign_id}, tenant_a_id)) == {own_id}
        assert set(ws._public_list_id_map({own_id, foreign_id}, tenant_a_id)) == {own_id}
        assert set(ws._public_user_id_map({own_user_id, foreign_user_id}, tenant_a_id)) == {own_user_id}
        assert ws._referenced_list_ids(protocol_id, tenant_a_id) == {own_id}
        assert bound_tenant_id(db) == tenant_a_id
