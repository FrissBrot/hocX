"""Regression test for the HIGH finding from the 2026-09-24 security audit of
feature/tenant-feature-gating-finance: the Abgabebox upload endpoint checked incoming uploads
only against settings.tenant_storage_quota_mb, a single global value for every tenant - a tenant
on a small plan (or with no storage packages) could accumulate storage via this public channel
far beyond what their plan+packages entitle them to, since the main backend's own quota
(Tenant.storage_quota_bytes, see upload_pipeline.py's _enforce_tenant_storage_quota) was never
consulted here.

routes/public.py's _effective_upload_quota_bytes() is what now combines the two: the tenant's own
quota always applies, capped by the global constant as an absolute ceiling for this public,
unauthenticated channel.
"""
from __future__ import annotations

from app.routes.public import _effective_upload_quota_bytes


def test_small_tenant_quota_is_enforced_even_though_global_cap_is_larger():
    """The bug: a tenant with a 10 MB plan quota must not be allowed to upload up to the global
    2048 MB constant via the public Abgabebox channel."""
    tenant_quota_bytes = 10 * 1024 * 1024
    global_cap_bytes = 2048 * 1024 * 1024

    effective = _effective_upload_quota_bytes(tenant_quota_bytes, global_cap_bytes)

    assert effective == tenant_quota_bytes


def test_global_cap_still_applies_as_ceiling_for_a_generous_tenant_quota():
    """A tenant quota larger than the global constant must not raise the effective limit past the
    global ceiling - defense-in-depth for this public, unauthenticated channel."""
    tenant_quota_bytes = 10 * 1024 * 1024 * 1024
    global_cap_bytes = 2048 * 1024 * 1024

    effective = _effective_upload_quota_bytes(tenant_quota_bytes, global_cap_bytes)

    assert effective == global_cap_bytes


def test_unlimited_tenant_quota_falls_back_to_global_cap():
    """Tenant.storage_quota_bytes is None when the main backend treats the tenant as unlimited
    (unlimited plan, no packages) - the global constant must still apply as a ceiling, not lift
    all limits on this public channel."""
    global_cap_bytes = 2048 * 1024 * 1024

    effective = _effective_upload_quota_bytes(None, global_cap_bytes)

    assert effective == global_cap_bytes
