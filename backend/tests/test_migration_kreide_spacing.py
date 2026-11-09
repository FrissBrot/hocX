"""Migration 0167: Brand-Profile im Design «Kreide» bekommen grössere Abstände (neue Revision);
bewusst geänderte Werte und andere Designs bleiben unverändert."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from app.documents import brand_service, examples
from app.documents.brand import BrandTokens
from app.documents.hashing import json_hash
from tests.factories import make_tenant

BACKEND_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def migration(db, monkeypatch):
    spec = importlib.util.spec_from_file_location("migration_0167", BACKEND_ROOT / "alembic/versions/0167_kreide_spacing.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.op, "get_bind", lambda: db.connection(), raising=False)
    return module


def _brand(db, tenant_id, name, *, base="kreide", line_height=1.35, paragraph_gap=2.5, section_gap=6.5):
    tokens = BrandTokens()
    tokens.appearance.base = base
    tokens.typography.line_height = line_height
    tokens.layout.paragraph_gap = paragraph_gap
    tokens.layout.section_gap = section_gap
    return brand_service.create_brand(db, tenant_id, name=name, tokens=tokens)


def test_kreide_brands_get_larger_spacing_and_custom_values_stay(db, migration):
    tenant = make_tenant(db, "Kreide-Abstand")
    old = _brand(db, tenant.id, "Kreide")
    partly = _brand(db, tenant.id, "Kreide eigen", section_gap=12)
    other = _brand(db, tenant.id, "Alpin", base="alpin")

    migration.upgrade()
    db.expire_all()

    revision = brand_service.current_revision(db, old)
    assert old.current_revision == 2
    assert revision.tokens_json["typography"]["line_height"] == 1.5
    assert revision.tokens_json["layout"]["paragraph_gap"] == 3
    assert revision.tokens_json["layout"]["section_gap"] == 10
    assert revision.tokens_hash == json_hash(revision.tokens_json)
    assert revision.note
    # Die bisherige Revision bleibt unverändert (Exporte halten sie fest)
    assert [item.tokens_json["layout"]["section_gap"] for item in brand_service.list_revisions(db, old)] == [10, 6.5]

    partly_tokens = brand_service.current_revision(db, partly).tokens_json
    assert partly_tokens["layout"]["section_gap"] == 12
    assert partly_tokens["typography"]["line_height"] == 1.5

    assert other.current_revision == 1


def test_kreide_example_uses_the_larger_spacing():
    kreide = next(item for item in examples.EXAMPLES if item.key == "kreide")
    tokens = examples.example_tokens(kreide)
    assert (tokens.typography.line_height, tokens.layout.paragraph_gap, tokens.layout.section_gap) == (1.5, 3, 10)
