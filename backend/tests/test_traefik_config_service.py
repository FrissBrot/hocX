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
from tests.factories import make_tenant


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
    _make_domain(db, tenant.id, "perms.example.com", purpose="app", status="active")

    monkeypatch.setattr(traefik_config_service.settings, "traefik_dynamic_config_dir", str(tmp_path))
    traefik_config_service.regenerate(db)

    mode = os.stat(tmp_path / "tenant-domains.yml").st_mode & 0o777
    assert mode == 0o660


def test_regenerate_ignores_pending_domains(db, monkeypatch, tmp_path):
    tenant = make_tenant(db, "Pending Domain Verein")
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
    malicious = "evil.example.com\nfake-key: fake-value"
    domain_row = _make_domain(db, tenant.id, malicious, purpose="app", status="active")

    config = _regenerate_into_tmp(monkeypatch, tmp_path, db)

    routers = config["http"]["routers"]
    frontend_key = f"tenant-app-{domain_row.id}-frontend"
    assert routers[frontend_key]["rule"] == f"Host(`{malicious}`)"
    # No stray "fake-key" ever appears as a real top-level router or config key.
    assert "fake-key" not in config
    assert "fake-key" not in config.get("http", {})
