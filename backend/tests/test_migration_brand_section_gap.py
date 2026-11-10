"""Migration 0159: Brand-Profile mit dem bisherigen Standard-Abschnittsabstand bekommen eine neue
Revision mit dem grösseren Wert; bewusst gesetzte Werte und alte Revisionen bleiben unverändert."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from app.documents import brand_service
from app.documents.brand import BrandTokens
from app.documents.hashing import json_hash
from tests.factories import make_tenant

BACKEND_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def migration(db, monkeypatch):
    spec = importlib.util.spec_from_file_location("migration_0159", BACKEND_ROOT / "alembic/versions/0159_brand_section_gap.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.op, "get_bind", lambda: db.connection(), raising=False)
    return module


def _brand(db, tenant_id, name, gap):
    tokens = BrandTokens()
    tokens.layout.section_gap = gap
    return brand_service.create_brand(db, tenant_id, name=name, tokens=tokens)


def test_old_default_gets_a_new_revision_and_custom_values_stay(db, migration):
    tenant = make_tenant(db, "Abstand")
    old_default = _brand(db, tenant.id, "Standard", 6)
    compact = _brand(db, tenant.id, "Kompakt", 4)
    custom = _brand(db, tenant.id, "Eigen", 7.5)

    migration.upgrade()
    db.expire_all()

    revision = brand_service.current_revision(db, old_default)
    assert old_default.current_revision == 2
    assert revision.tokens_json["layout"]["section_gap"] == 8
    assert revision.tokens_hash == json_hash(revision.tokens_json)
    assert revision.note
    # Die bisherige Revision bleibt unverändert (Exporte halten sie fest)
    assert [item.tokens_json["layout"]["section_gap"] for item in brand_service.list_revisions(db, old_default)] == [8, 6]

    assert brand_service.current_revision(db, compact).tokens_json["layout"]["section_gap"] == 5
    assert custom.current_revision == 1
    assert brand_service.current_revision(db, custom).tokens_json["layout"]["section_gap"] == 7.5


def test_new_brands_use_the_larger_gap():
    assert BrandTokens().layout.section_gap == 8
