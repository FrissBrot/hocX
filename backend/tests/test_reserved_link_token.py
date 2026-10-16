"""«verify» ist die Route der Prüfseite in der Abgabebox und darf nie ein Abgabe-Link-Token sein:
weder beim Erzeugen noch beim Import, und die DB lehnt es per CHECK ab."""
from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import SubmissionLink
from app.services import submission_link_service
from app.services.tenant_import_service import TenantImportService
from tests.factories import make_tenant


def test_generate_token_never_returns_a_reserved_value(monkeypatch):
    values = iter(["verify", "VERIFY", "a" * 32])
    monkeypatch.setattr(submission_link_service.secrets, "token_urlsafe", lambda _: next(values))
    assert submission_link_service.generate_token() == "a" * 32


def test_import_replaces_a_reserved_token(db):
    service = TenantImportService()
    service.db = db
    service.warnings = []
    token = service._claim_token(SubmissionLink, "Verify", lambda: "b" * 32, "Abgabebox-Link 'Standard'")
    assert token == "b" * 32
    assert any("reserviert" in warning for warning in service.warnings)


def test_database_rejects_the_reserved_token(db):
    tenant = make_tenant(db, "Tokenverein")
    savepoint = db.begin_nested()
    db.add(SubmissionLink(tenant_id=tenant.id, name="Prüfung", token="verify"))
    with pytest.raises(IntegrityError, match="ck_submission_link_token_reserved"):
        db.flush()
    savepoint.rollback()
