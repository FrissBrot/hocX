"""Tests for the import wizard's "remember last selected template" preference
(tenant.last_word_import_template_id + GET/PUT /tools/word-import/last-template)."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api.routes.word_import import get_last_word_import_template, set_last_word_import_template
from app.schemas.word_import import WordImportLastTemplate

from tests.factories import make_current_user, make_template, make_tenant


def test_get_last_template_defaults_to_none(db):
    tenant = make_tenant(db)
    user = make_current_user(tenant.id)

    result = get_last_word_import_template(db=db, user=user)

    assert result.template_id is None


def test_set_and_get_roundtrip(db):
    tenant = make_tenant(db)
    template = make_template(db, tenant.id)
    user = make_current_user(tenant.id)

    set_result = set_last_word_import_template(WordImportLastTemplate(template_id=template.id), db=db, user=user)
    assert set_result.template_id == template.id

    get_result = get_last_word_import_template(db=db, user=user)
    assert get_result.template_id == template.id


def test_set_rejects_template_from_other_tenant(db):
    tenant = make_tenant(db)
    other_tenant = make_tenant(db)
    other_template = make_template(db, other_tenant.id)
    user = make_current_user(tenant.id)

    with pytest.raises(HTTPException) as exc_info:
        set_last_word_import_template(WordImportLastTemplate(template_id=other_template.id), db=db, user=user)
    assert exc_info.value.status_code == 400


def test_set_none_clears_preference(db):
    tenant = make_tenant(db)
    template = make_template(db, tenant.id)
    user = make_current_user(tenant.id)
    set_last_word_import_template(WordImportLastTemplate(template_id=template.id), db=db, user=user)

    result = set_last_word_import_template(WordImportLastTemplate(template_id=None), db=db, user=user)

    assert result.template_id is None
    assert get_last_word_import_template(db=db, user=user).template_id is None
