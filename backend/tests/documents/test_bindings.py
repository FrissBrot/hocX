"""Datenbindungen: Registry, Typen, Formatierung, Beispielmodus und Rechte."""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from app.documents import bindings
from app.documents.bindings import BindingEnvironment, BindingResolver, UnknownBindingError, format_value
from app.documents.context import BuildContext, DocumentPermissionError
from app.documents.layout import FormatSpec
from app.documents.strings import strings_for
from tests.factories import make_current_user

STRINGS = strings_for("de")


def test_registry_paths_are_valid_binding_patterns():
    import re

    from app.documents.layout import BINDING_PATTERN

    for path, definition in bindings.REGISTRY.items():
        assert re.fullmatch(BINDING_PATTERN, path), path
        if definition.type == "list":
            assert definition.item_fields, path


def test_item_paths_need_a_list_scope():
    with pytest.raises(UnknownBindingError):
        bindings.validate_path("item.name")
    scope = bindings.lookup("protocol.participants")
    assert bindings.validate_path("item.name", scope=scope)[0] == "text"
    with pytest.raises(UnknownBindingError):
        bindings.validate_path("item.gibts_nicht", scope=scope)
    assert bindings.validate_path("brand.images.signet")[0] == "image"
    with pytest.raises(UnknownBindingError):
        bindings.lookup("protocol.passwort")


@pytest.mark.parametrize(
    ("value", "value_type", "fmt", "expected"),
    [
        (date(2026, 3, 5), "date", {}, "05.03.2026"),
        (date(2026, 3, 5), "date", {"date": "long"}, "5. März 2026"),
        ("2026-03-05", "date", {"date": "weekday"}, "Do, 05.03.2026"),
        (date(2026, 3, 5), "date", {"date": "month_year"}, "März 2026"),
        (date(2026, 3, 5), "date", {"date": "year"}, "2026"),
        (1234.5, "amount", {}, "1'234.50"),
        (12345, "number", {}, "12'345"),
        (2.25, "number", {"number": "decimal"}, "2.2"),
        (0.857, "percent", {}, "86%"),
        (True, "bool", {}, "Ja"),
        ("text", "text", {"transform": "upper", "prefix": "« ", "suffix": " »"}, "« TEXT »"),
        (None, "text", {"prefix": "x"}, ""),
        ([1, 2, 3], "list", {}, "3"),
    ],
)
def test_format_value(value, value_type, fmt, expected):
    assert format_value(value, value_type, FormatSpec(**fmt), STRINGS) == expected


def test_sample_mode_uses_translated_sample_texts():
    resolver = BindingResolver(None, BindingEnvironment(), strings=strings_for("fr"), mode="sample")
    assert resolver.resolve("protocol.title") == strings_for("fr")["sample.protocolTitle"]
    participants = resolver.resolve("protocol.participants")
    assert participants[0]["name"] == strings_for("fr")["sample.person1"]
    assert resolver.resolve("item.name", participants[0]) == participants[0]["name"]
    assert resolver.resolve("organization.name") == strings_for("fr")["sample.organization"]


def test_environment_values_win_over_samples():
    env = BindingEnvironment(document={"title": "Echt"}, organization={"name": "Verein"}, brand={"toc": True, "logo": "assets/brand-1.png"})
    resolver = BindingResolver(None, env, strings=STRINGS, mode="sample")
    assert resolver.resolve("document.title") == "Echt"
    assert resolver.resolve("organization.name") == "Verein"
    assert resolver.resolve("brand.toc") is True and resolver.resolve("brand.logo") == "assets/brand-1.png"


def test_data_mode_enforces_rights_of_exporting_user():
    reader = make_current_user(1, role="reader")
    ctx = BuildContext(db=SimpleNamespace(), tenant_id=1, language="de", user=reader)
    resolver = BindingResolver(ctx, BindingEnvironment(), strings=STRINGS)
    with pytest.raises(DocumentPermissionError):
        resolver.resolve("members.active")
    no_finance = make_current_user(1, role="admin", features=frozenset())
    resolver = BindingResolver(BuildContext(db=SimpleNamespace(), tenant_id=1, language="de", user=no_finance), BindingEnvironment(), strings=STRINGS)
    with pytest.raises(DocumentPermissionError):
        resolver.resolve("finance.total_balance")


def test_protocol_bindings_without_protocol_are_empty():
    ctx = BuildContext(db=SimpleNamespace(), tenant_id=1, language="de", user=make_current_user(1, role="admin"))
    resolver = BindingResolver(ctx, BindingEnvironment(), strings=STRINGS)
    assert resolver.resolve("protocol.title") is None
    assert resolver.resolve("protocol.participants") is None


def test_catalog_payload_lists_every_binding():
    payload = bindings.catalog_payload()
    assert {item["path"] for item in payload} == set(bindings.REGISTRY)
    assert next(item for item in payload if item["path"] == "finance.accounts")["access"] == "finance"


def test_new_todos_count_counts_every_todo_of_this_protocol(monkeypatch):
    """Neue Pendenzen: alle in diesem Protokoll erfassten, auch erledigte; offene Liste unverändert."""
    from app.documents import repository
    from app.documents.providers import people as people_provider
    from app.documents.providers import protocol as protocol_provider
    from app.documents.providers import todos as todo_provider

    def todo(protocol_id: int, status: str) -> SimpleNamespace:
        return SimpleNamespace(protocol_id=protocol_id, todo_status_code=status, resolved_due_date=None, assigned_participant_name=None)

    rows = [todo(7, "open"), todo(7, "done"), todo(7, "in_progress"), todo(8, "open")]
    monkeypatch.setattr(todo_provider, "list_tenant_todo_rows", lambda ctx: rows)
    monkeypatch.setattr(todo_provider, "task_text", lambda row: "")
    monkeypatch.setattr(todo_provider, "protocol_label", lambda row: "")
    monkeypatch.setattr(protocol_provider, "element_blocks", lambda *args, **kwargs: [])
    monkeypatch.setattr(protocol_provider, "protocol_status_code", lambda protocol: "held")
    monkeypatch.setattr(people_provider, "protocol_attendance_configs", lambda ctx, protocol: [])
    monkeypatch.setattr(repository, "list_protocol_elements", lambda db, protocol_id: [])
    protocol = SimpleNamespace(id=7, template_id=1, event_id=None, title="P", protocol_number="2026-03", protocol_date=date(2026, 3, 12))
    ctx = BuildContext(db=SimpleNamespace(get=lambda model, ident: None), tenant_id=1, language="de", protocol=protocol)
    resolver = BindingResolver(ctx, BindingEnvironment(), strings=STRINGS)
    assert resolver.resolve("protocol.new_todos_count") == 3
    assert len(resolver.resolve("protocol.open_todos")) == 2
