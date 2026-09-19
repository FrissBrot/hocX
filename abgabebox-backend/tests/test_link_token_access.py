"""The public Abgabebox is reachable only via a random link token (submission_link.token) -
the tenant's public_slug is no longer an access credential. Everything here is DB-free, same
style as the rest of this suite (the grants themselves are verified against a real database in
backend/tests/test_submission_links.py):

- an unknown or malformed token is a plain 404 (malformed ones without touching the DB), and
  the "no such link" and "link exists but doesn't reach this Abgabe" cases are indistinguishable
- every lookup below the link is scoped to that link (tenant + link id are always passed on)
- the table definitions this service reads through mirror exactly the columns the restricted
  DB role was granted (id, tenant_id, token / assignment_id, link_id) - in particular no link
  name and no tenant table any more
- a captcha session token minted for one link cannot be replayed against another
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app import captcha, models, repository
from app.config import settings
from app.routes import public

VALID_TOKEN = "A" * 32


def test_malformed_token_is_rejected_without_a_db_lookup(monkeypatch):
    def _boom(*args, **kwargs):
        raise AssertionError("repository must not be queried for a malformed token")

    monkeypatch.setattr(repository, "get_link_by_token", _boom)

    for bad in ["", "abc", "acme", "a" * 200, "has space " + "a" * 30, "sl/ash" + "a" * 30, "ümlaut" + "a" * 30]:
        with pytest.raises(HTTPException) as exc_info:
            public._get_tenant_or_404(db=None, link_token=bad)
        assert exc_info.value.status_code == 404


def test_unknown_token_is_404(monkeypatch):
    monkeypatch.setattr(repository, "get_link_by_token", lambda db, *, token: None)

    with pytest.raises(HTTPException) as exc_info:
        public._get_tenant_or_404(db=None, link_token=VALID_TOKEN)

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Nicht gefunden"


def test_valid_token_resolves_to_the_links_tenant_and_link_id(monkeypatch):
    monkeypatch.setattr(repository, "get_link_by_token", lambda db, *, token: {"id": 7, "tenant_id": 42, "token": token})

    assert public._get_tenant_or_404(db=None, link_token=VALID_TOKEN) == {"id": 42, "link_id": 7}


def test_assignment_lookup_is_always_scoped_to_the_link(monkeypatch):
    seen: dict = {}

    def _fake(db, *, tenant_id, link_id, public_slug):
        seen.update(tenant_id=tenant_id, link_id=link_id, public_slug=public_slug)
        return None

    monkeypatch.setattr(repository, "get_assignment_by_slug", _fake)

    with pytest.raises(HTTPException) as exc_info:
        public._get_assignment_or_404(None, {"id": 42, "link_id": 7}, "fotos")

    assert exc_info.value.status_code == 404
    assert seen == {"tenant_id": 42, "link_id": 7, "public_slug": "fotos"}


def test_assignment_queries_only_return_abgaben_attached_to_the_link():
    for query_fn, kwargs in [
        (repository.list_active_assignments, {"tenant_id": 1, "link_id": 2}),
        (repository.get_assignment_by_slug, {"tenant_id": 1, "link_id": 2, "public_slug": "x"}),
    ]:
        captured = {}

        class _FakeDb:
            def execute(self, statement):
                captured["sql"] = str(statement.compile(compile_kwargs={"literal_binds": True}))

                class _Result:
                    def mappings(self):
                        class _M:
                            def first(self):
                                return None

                            def __iter__(self):
                                return iter([])

                        return _M()

                return _Result()

        query_fn(_FakeDb(), **kwargs)

        sql = captured["sql"]
        assert "submission_assignment_link" in sql
        assert "link_id = 2" in sql
        assert "tenant_id = 1" in sql


def test_token_lookup_selects_only_the_granted_columns():
    statement = select(models.submission_link_table).where(models.submission_link_table.c.token == "x")
    sql = str(statement.compile())

    assert {c.name for c in models.submission_link_table.c} == {"id", "tenant_id", "token"}
    assert "name" not in sql.split("FROM")[0]
    assert {c.name for c in models.submission_assignment_link_table.c} == {"assignment_id", "link_id"}


def test_public_slug_of_the_tenant_is_no_longer_read_at_all():
    assert not hasattr(models, "tenant_table")
    assert not hasattr(repository, "get_tenant_by_slug")


def test_captcha_session_token_is_bound_to_the_link(monkeypatch):
    monkeypatch.setattr(settings, "friendly_captcha_sitekey", "site-123")
    monkeypatch.setattr(settings, "friendly_captcha_api_key", "secret-456")
    monkeypatch.setattr(settings, "captcha_session_secret", "test-captcha-secret-0123456789")

    token = captcha.mint_captcha_session_token("A" * 32, "fotos", "event-1", client_ip="1.2.3.4")

    assert captcha.verify_captcha_session_token(token, "A" * 32, "fotos", "event-1", client_ip="1.2.3.4") is True
    assert captcha.verify_captcha_session_token(token, "B" * 32, "fotos", "event-1", client_ip="1.2.3.4") is False
    assert captcha.verify_captcha_session_token(token, "A" * 32, "other", "event-1", client_ip="1.2.3.4") is False
    assert captcha.verify_captcha_session_token(token, "A" * 32, "fotos", "event-1", client_ip="9.9.9.9") is False
