"""Regression tests for traefik_config_service (previously zero coverage) - generates the
Traefik dynamic file-provider config (tenant-domains.yml) straight from tenant_domain rows.
Audit flagged this as injection-relevant: `domain` is user-supplied (a tenant admin types it
in when registering a custom domain) and gets interpolated directly into a Traefik routing
rule string (`Host(`{domain}`)`). Since the whole document is built as a Python dict and only
serialized to YAML at the very end via yaml.safe_dump, a malicious domain value can't break out
of the YAML structure or inject new routers/keys - it can at most end up as a syntactically odd
but still single, contained string value. These tests pin exactly that: the output is always
valid YAML with the expected router shape, and no domain string (however adversarial) produces
extra top-level keys, extra routers, or invalid YAML.

IMPORTANT: settings.traefik_dynamic_config_dir (`app/core/config.py`) is, in the real running
stack, bind-mounted straight into the live Traefik container (docker-compose.yml ->
./infra/traefik/dynamic:/app/traefik_dynamic) and already contains real production routing for
at least one real tenant custom domain. Every test here MUST monkeypatch that path to an
isolated tmp directory before calling regenerate() - never let a test run against the real
path, which would rewrite live production routing.
"""
from __future__ import annotations

import os

import yaml

from app.models import TenantDomain
from app.services import traefik_config_service
from app.services.admin_tenant_service import AdminTenantService
from tests.factories import grant_tenant_feature, make_tenant


def _make_domain(db, tenant_id: int, domain: str, purpose: str = "app", status: str = "active") -> TenantDomain:
    row = TenantDomain(
        tenant_id=tenant_id,
        purpose=purpose,
        domain=domain,
        verification_token="tok-" + os.urandom(4).hex(),
        status=status,
    )
    db.add(row)
    db.flush()
    return row


def _regenerate_into_tmp(monkeypatch, tmp_path, db) -> dict:
    monkeypatch.setattr(traefik_config_service.settings, "traefik_dynamic_config_dir", str(tmp_path))
    traefik_config_service.regenerate(db)
    path = tmp_path / "tenant-domains.yml"
    with open(path, "r") as fh:
        return yaml.safe_load(fh) or {}


def test_regenerate_writes_valid_config_for_active_app_domain(db, monkeypatch, tmp_path):
    tenant = make_tenant(db, "Traefik Test Verein")
    grant_tenant_feature(db, tenant.id)
    domain_row = _make_domain(db, tenant.id, "verein.example.com", purpose="app", status="active")

    config = _regenerate_into_tmp(monkeypatch, tmp_path, db)

    routers = config["http"]["routers"]
    frontend_key = f"tenant-app-{domain_row.id}-frontend"
    assert frontend_key in routers
    assert routers[frontend_key]["rule"] == "Host(`verein.example.com`)"
    assert routers[frontend_key]["service"] == "hocx-frontend@docker"


def test_regenerate_writes_file_group_readable_not_world_readable(db, monkeypatch, tmp_path):
    """deploy.sh hardens infra/traefik/dynamic to mode 0660/group-5001-only before every
    deploy and refuses to proceed otherwise ("... muss fuer die Container-Gruppe 5001
    vorbereitet werden"). open()'s default mode is umask-dependent (typically 0644,
    world-readable) - without an explicit chmod, every regenerate() call would silently
    re-break that hardening and fail the next deploy's permission check."""
    tenant = make_tenant(db, "Permissions Test Verein")
    grant_tenant_feature(db, tenant.id)
    _make_domain(db, tenant.id, "perms.example.com", purpose="app", status="active")

    monkeypatch.setattr(traefik_config_service.settings, "traefik_dynamic_config_dir", str(tmp_path))
    traefik_config_service.regenerate(db)

    mode = os.stat(tmp_path / "tenant-domains.yml").st_mode & 0o777
    assert mode == 0o660


def test_regenerate_ignores_pending_domains(db, monkeypatch, tmp_path):
    tenant = make_tenant(db, "Pending Domain Verein")
    grant_tenant_feature(db, tenant.id)
    _make_domain(db, tenant.id, "pending.example.com", purpose="app", status="pending")

    config = _regenerate_into_tmp(monkeypatch, tmp_path, db)

    routers = (config.get("http") or {}).get("routers") or {}
    assert not any("pending.example.com" in str(r) for r in routers.values())


def test_regenerate_with_no_active_domains_writes_empty_document(db, monkeypatch, tmp_path):
    """Traefik's file provider errors on an explicit-but-empty `http.routers: {}` map, so when
    there is nothing to route, regenerate() must write an entirely empty YAML document (`{}` /
    None) rather than `{"http": {"routers": {}}}`. Any pre-existing active tenant_domain rows
    (there are real ones in this shared dev DB) are hidden for the duration of this test by
    flipping them to 'pending' within the test's own rolled-back transaction."""
    db.execute(
        TenantDomain.__table__.update().where(TenantDomain.status == "active").values(status="pending")
    )

    config = _regenerate_into_tmp(monkeypatch, tmp_path, db)

    assert not config


def test_regenerate_abgabebox_purpose_produces_abgabebox_routers(db, monkeypatch, tmp_path):
    tenant = make_tenant(db, "Abgabebox Verein")
    grant_tenant_feature(db, tenant.id)
    domain_row = _make_domain(db, tenant.id, "box.example.com", purpose="abgabebox", status="active")

    config = _regenerate_into_tmp(monkeypatch, tmp_path, db)

    routers = config["http"]["routers"]
    frontend_key = f"tenant-abgabebox-{domain_row.id}-frontend"
    assert routers[frontend_key]["rule"] == "Host(`box.example.com`)"
    assert routers[frontend_key]["service"] == "hocx-abgabebox-frontend@docker"


def test_regenerate_malicious_domain_string_stays_a_single_contained_value(db, monkeypatch, tmp_path):
    """A domain value crafted to look like it could break out of the YAML/rule structure
    (backticks matching Traefik's Host() quoting, embedded newlines, YAML-special characters)
    must still round-trip as a single opaque string - never additional YAML keys, never a
    second router, never invalid YAML that fails to parse."""
    tenant = make_tenant(db, "Injection Test Verein")
    grant_tenant_feature(db, tenant.id)
    malicious = "evil.example.com`) || Host(`attacker.example.com"
    domain_row = _make_domain(db, tenant.id, malicious, purpose="app", status="active")

    config = _regenerate_into_tmp(monkeypatch, tmp_path, db)

    routers = config["http"]["routers"]
    frontend_key = f"tenant-app-{domain_row.id}-frontend"
    assert frontend_key in routers
    # Exactly the routers this one active domain should produce - no extras injected.
    assert {name for name in routers if name.startswith(f"tenant-app-{domain_row.id}-")} == {
        frontend_key,
        f"tenant-app-{domain_row.id}-backend",
        f"tenant-app-{domain_row.id}-auth",
        f"tenant-app-{domain_row.id}-word-import",
        f"tenant-app-{domain_row.id}-gallery-upload",
    }
    # The malicious string is preserved verbatim as one opaque value inside the rule -
    # it did not fragment into separate YAML structure.
    assert routers[frontend_key]["rule"] == f"Host(`{malicious}`)"


def test_regenerate_newline_in_domain_does_not_produce_extra_yaml_keys(db, monkeypatch, tmp_path):
    """A domain containing an embedded newline is the classic YAML-injection vector (a naive
    f-string dump could let it terminate the current mapping entry and start a new top-level
    key). yaml.safe_dump must block-quote/escape it so the parsed structure still contains
    exactly one router set for this domain."""
    tenant = make_tenant(db, "Newline Verein")
    grant_tenant_feature(db, tenant.id)
    malicious = "evil.example.com\nfake-key: fake-value"
    domain_row = _make_domain(db, tenant.id, malicious, purpose="app", status="active")

    config = _regenerate_into_tmp(monkeypatch, tmp_path, db)

    routers = config["http"]["routers"]
    frontend_key = f"tenant-app-{domain_row.id}-frontend"
    assert routers[frontend_key]["rule"] == f"Host(`{malicious}`)"
    # No stray "fake-key" ever appears as a real top-level router or config key.
    assert "fake-key" not in config
    assert "fake-key" not in config.get("http", {})


def test_regenerate_excludes_active_domain_whose_tenant_lost_the_feature(db, monkeypatch, tmp_path):
    """security-audit FEAT-01: require_feature("custom_domain") only gates create_domain/
    verify_domain - once a domain is 'active', regenerate() used to serve it forever, even
    after the feature was revoked (manual downgrade, or a tenant import that never assigns the
    feature at all, see FEAT-02). No `grant_tenant_feature` call here on purpose."""
    tenant = make_tenant(db, "Downgraded Verein")
    _make_domain(db, tenant.id, "downgraded.example.com", purpose="app", status="active")

    config = _regenerate_into_tmp(monkeypatch, tmp_path, db)

    routers = (config.get("http") or {}).get("routers") or {}
    assert not any("downgraded.example.com" in str(r) for r in routers.values())


def test_regenerate_reincludes_domain_once_feature_is_granted(db, monkeypatch, tmp_path):
    tenant = make_tenant(db, "Regranted Verein")
    domain_row = _make_domain(db, tenant.id, "regranted.example.com", purpose="app", status="active")

    before = _regenerate_into_tmp(monkeypatch, tmp_path, db)
    assert not any("regranted.example.com" in str(r) for r in (before.get("http") or {}).get("routers", {}).values())

    grant_tenant_feature(db, tenant.id)
    after = _regenerate_into_tmp(monkeypatch, tmp_path, db)
    routers = after["http"]["routers"]
    assert routers[f"tenant-app-{domain_row.id}-frontend"]["rule"] == "Host(`regranted.example.com`)"


def test_revoking_custom_domain_feature_immediately_drops_the_domain_from_traefik_config(db, monkeypatch, tmp_path):
    """security-audit FEAT-01: regenerate() only runs at startup and after domain
    create/verify/delete - without AdminTenantService.update_tenant_features() also triggering
    it, a revoked feature would leave the domain routed until one of those unrelated events
    happens to fire next."""
    tenant = make_tenant(db, "Live Downgrade Verein")
    grant_tenant_feature(db, tenant.id)
    _make_domain(db, tenant.id, "live-downgrade.example.com", purpose="app", status="active")
    monkeypatch.setattr(traefik_config_service.settings, "traefik_dynamic_config_dir", str(tmp_path))

    # Sanity check: the domain is actually being served before the revoke.
    traefik_config_service.regenerate(db)
    before_path = tmp_path / "tenant-domains.yml"
    with open(before_path) as fh:
        before = yaml.safe_load(fh) or {}
    assert any("live-downgrade.example.com" in str(r) for r in (before.get("http") or {}).get("routers", {}).values())

    AdminTenantService().update_tenant_features(db, tenant.id, [], admin_id=1)

    with open(before_path) as fh:
        after = yaml.safe_load(fh) or {}
    routers = (after.get("http") or {}).get("routers") or {}
    assert not any("live-downgrade.example.com" in str(r) for r in routers.values())


def test_custom_domains_use_release_upload_middlewares_and_prefix(monkeypatch):
    monkeypatch.setattr(traefik_config_service.settings, 'router_prefix', 'release-test')
    monkeypatch.setattr(traefik_config_service.settings, 'traefik_middleware_prefix', 'release-test-')
    gallery = traefik_config_service._app_routers('photos.example.com', 1)['tenant-app-1-gallery-upload']
    box = traefik_config_service._abgabebox_routers('box.example.com', 2)['tenant-abgabebox-2-upload']
    assert gallery['service'] == 'release-test-gallery-upload@docker'
    assert gallery['middlewares'] == ['release-test-gallery-upload-inflight@docker']
    assert box['service'] == 'release-test-abgabebox-backend@docker'
    assert 'release-test-abgabebox-upload-body-limit@docker' in box['middlewares']
