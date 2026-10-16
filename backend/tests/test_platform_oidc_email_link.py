"""Audit MAIN-SEC-005: Plattform-SSO verknüpft Admin-Konten per E-Mail nur bei
email_verified=true."""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.core.security import hash_password
from app.models.entities import PlatformAdmin
from app.services.platform_oidc_service import PlatformOidcService

_CFG = SimpleNamespace(issuer_url="https://idp.example.com")


def _admin(db, email: str) -> PlatformAdmin:
    admin = PlatformAdmin(email=email, password_hash=hash_password("pw-123456789"), display_name="Ops")
    db.add(admin)
    db.flush()
    return admin


@pytest.mark.parametrize("email_verified", [None, False, "false"])
def test_unverified_email_does_not_link_admin(db, email_verified):
    admin = _admin(db, "ops-unverified@example.com")
    claims = {"sub": "attacker", "email": admin.email}
    if email_verified is not None:
        claims["email_verified"] = email_verified

    with pytest.raises(HTTPException) as exc:
        PlatformOidcService()._find_or_link_admin(db, _CFG, claims)

    assert exc.value.status_code == 403
    db.refresh(admin)
    assert admin.oidc_subject is None


@pytest.mark.parametrize("email_verified", [True, "true"])
def test_verified_email_links_existing_admin(db, email_verified):
    admin = _admin(db, "ops-verified@example.com")

    linked = PlatformOidcService()._find_or_link_admin(
        db, _CFG, {"sub": "idp-sub-1", "email": admin.email, "email_verified": email_verified}
    )

    assert linked.id == admin.id
    assert admin.oidc_subject == "idp-sub-1"
    assert admin.oidc_issuer == _CFG.issuer_url
