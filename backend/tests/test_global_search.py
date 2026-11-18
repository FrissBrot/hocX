"""Globale Suche (routes/search.py): nur eigener Mandant, nur Gruppen mit Berechtigung,
Umlaute/Akzente egal, Platzhalter aus der Eingabe sind Text."""
from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from app.api.routes import search as route
from app.schemas.files import FileOverviewItem
from app.schemas.search import GlobalSearchQuery
from tests.factories import make_current_user, make_element_definition, make_participant, make_tenant


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch):
    monkeypatch.setattr(route, "enforce_rate_limit", lambda *args, **kwargs: None)


@pytest.fixture
def tenants(db):
    own = make_tenant(db, "Eigener Verein")
    other = make_tenant(db, "Fremder Verein")
    make_participant(db, own.id, "Jürg Müller")
    make_participant(db, own.id, "Anna Muster")
    make_participant(db, own.id, "100% Sicher")
    make_participant(db, other.id, "Jürg Fremd")
    db.flush()
    return own, other


def _names(result) -> list[str]:
    return [person.name for person in result.people]


def test_people_only_from_own_tenant_and_accent_insensitive(db, tenants, monkeypatch):
    own, _other = tenants
    monkeypatch.setattr(route, "search_files", lambda *args, **kwargs: [])
    admin = make_current_user(own.id, role="admin")
    assert _names(route.global_search(GlobalSearchQuery.model_construct(q="jurg"), db=db, user=admin)) == ["Jürg Müller"]
    assert _names(route.global_search(GlobalSearchQuery.model_construct(q="MÜLLER"), db=db, user=admin)) == ["Jürg Müller"]
    assert _names(route.global_search(GlobalSearchQuery.model_construct(q="mu"), db=db, user=admin)) == ["Anna Muster", "Jürg Müller"]


def test_like_wildcards_in_query_are_plain_text(db, tenants, monkeypatch):
    own, _other = tenants
    monkeypatch.setattr(route, "search_files", lambda *args, **kwargs: [])
    admin = make_current_user(own.id, role="admin")
    assert _names(route.global_search(GlobalSearchQuery.model_construct(q="0%"), db=db, user=admin)) == ["100% Sicher"]
    assert _names(route.global_search(GlobalSearchQuery.model_construct(q="__"), db=db, user=admin)) == []


def test_groups_follow_permissions(db, tenants, monkeypatch):
    own, _other = tenants
    calls: list[int] = []

    def fake_files(db_, tenant_id, query, limit=5, **_kinds):
        calls.append(tenant_id)
        return []

    monkeypatch.setattr(route, "search_files", fake_files)
    only_files = make_current_user(own.id, permissions=frozenset({"files.read"}))
    result = route.global_search(GlobalSearchQuery.model_construct(q="jurg"), db=db, user=only_files)
    assert result.people == [] and calls == [own.id]

    only_people = make_current_user(own.id, permissions=frozenset({"participants.read"}))
    calls.clear()
    assert _names(route.global_search(GlobalSearchQuery.model_construct(q="jurg"), db=db, user=only_people)) == ["Jürg Müller"]
    assert calls == []

    reader = make_current_user(own.id, role="reader")
    with pytest.raises(HTTPException) as exc:
        route.global_search(GlobalSearchQuery.model_construct(q="jurg"), db=db, user=reader)
    assert exc.value.status_code == 403


def test_files_use_tenant_scoped_file_list(db, tenants, monkeypatch):
    own, _other = tenants
    seen: list[dict] = []

    def fake_list(self, db_, tenant_id, **kwargs):
        seen.append({"tenant_id": tenant_id, **kwargs})
        if not kwargs.get("only_images"):
            return [FileOverviewItem.model_construct(id=uuid.uuid4(), original_name="Statuten.pdf", is_image=False, origin_tag="Dokumente", ref_label="")]
        return []

    monkeypatch.setattr(route.FileService, "list_tenant_files", fake_list)
    admin = make_current_user(own.id, role="admin")
    result = route.global_search(GlobalSearchQuery.model_construct(q="statuten"), db=db, user=admin)
    assert [file.name for file in result.files] == ["Statuten.pdf"]
    assert {call["tenant_id"] for call in seen} == {own.id}
    assert all(call["search"] == "statuten" and call["limit"] == route.GROUP_LIMIT for call in seen)


def test_whitespace_only_query_returns_nothing(db, tenants):
    own, _other = tenants
    admin = make_current_user(own.id, role="admin")
    result = route.global_search(GlobalSearchQuery.model_construct(q="  "), db=db, user=admin)
    assert result.people == [] and result.files == []


def test_elements_and_blocks_only_library_of_own_tenant(db, tenants, monkeypatch):
    """Elemente und Blöcke (Ctrl+K): nur Bibliothek des eigenen Mandanten, nur aktive,
    Umlaute egal, nur mit templates.edit."""
    own, other = tenants
    monkeypatch.setattr(route, "search_files", lambda *args, **kwargs: [])
    library = make_element_definition(db, own.id, "Ämtliplan", [
        {"id": 1, "title": "Küchenämtli", "block_title": None},
        {"id": 2, "title": "", "block_title": "Abwasch Küche"},
        {"id": "kaputt", "title": "Küche ohne Zahl"},
    ])
    single = make_element_definition(db, own.id, "Küche Einzelstück", [{"id": 1, "title": "Küche einzeln"}])
    single.is_library = False
    inactive = make_element_definition(db, own.id, "Küche alt", [{"id": 1, "title": "Küche alt"}])
    inactive.is_active = False
    make_element_definition(db, other.id, "Küche fremd", [{"id": 1, "title": "Küche fremd"}])
    no_blocks = make_element_definition(db, own.id, "Kuchenliste", [])
    no_blocks.configuration_json = {"blocks": "kein Array"}
    db.flush()

    writer = make_current_user(own.id, permissions=frozenset({"templates.edit"}))
    result = route.global_search(GlobalSearchQuery.model_construct(q="kuche"), db=db, user=writer)
    assert [element.title for element in result.elements] == ["Kuchenliste"]
    assert [(block.element_id, block.block_id, block.title) for block in result.blocks] == [
        (library.public_id, 1, "Küchenämtli"),
        (library.public_id, 2, "Abwasch Küche"),
    ]
    assert result.people == []

    result = route.global_search(GlobalSearchQuery.model_construct(q="amtli"), db=db, user=writer)
    assert [element.title for element in result.elements] == ["Ämtliplan"]

    people_only = make_current_user(own.id, permissions=frozenset({"participants.read"}))
    result = route.global_search(GlobalSearchQuery.model_construct(q="kuche"), db=db, user=people_only)
    assert result.elements == [] and result.blocks == []
