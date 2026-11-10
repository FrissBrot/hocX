"""Audit MAIN-OPS-001: scripts/deploy.sh schrieb auf Prod HOCX_ENVIRONMENT='prod' (Host-Name)
statt 'production'. Das Backend sah sich damit nicht als Produktion: /docs und /openapi.json
waren offen, Demo-Daten- und Konfigurationssperren aus. 'prod' gilt jetzt als Alias, damit
bestehende Hosts nach dem Update korrekt als Produktion laufen."""
from __future__ import annotations

import pytest

from app.core.config import settings


@pytest.mark.parametrize("value", ["production", "prod", "PROD", " Production "])
def test_production_aliases_count_as_production(value):
    assert settings.model_copy(update={"environment": value}).is_production is True


@pytest.mark.parametrize("value", ["development", "dev", "test", "local", "staging"])
def test_other_environments_are_not_production(value):
    assert settings.model_copy(update={"environment": value}).is_production is False


def test_prod_alias_enforces_production_config_checks():
    # Die Produktionspruefungen (u. a. Secure-Cookies) muessen auch fuer den Alias greifen.
    insecure = settings.model_copy(
        update={
            "environment": "prod",
            "auth_secure_cookies": False,
            "auth_secret": "x" * 40,
            "admin_auth_secret": "y" * 40,
        }
    )
    with pytest.raises(SystemExit):
        insecure.validate_for_production()


def test_prod_alias_hides_local_dev_origins():
    assert settings.model_copy(update={"environment": "prod"}).local_dev_origins == ()
