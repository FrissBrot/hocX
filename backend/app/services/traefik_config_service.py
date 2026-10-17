from __future__ import annotations

import os
import secrets

import yaml
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import TenantDomain, TenantFeature

_DYNAMIC_FILE_NAME = "tenant-domains.yml"


def tenant_ids_with_custom_domain_feature(db: Session):
    """Subquery of tenant_ids that currently have `custom_domain` booked.

    Every place that decides whether an already-`active` TenantDomain row should still be
    treated as live (Traefik routing here, the health-check loop, the login bridge) filters
    through this - `require_feature` only gates *creating*/*verifying* a domain, so without this
    a feature revoke (manual downgrade or a tenant import/restore that never assigns the
    feature) would leave an already-provisioned domain served indefinitely
    (security-audit FEAT-01/FEAT-02)."""
    return select(TenantFeature.tenant_id).where(TenantFeature.feature_code == "custom_domain")


# Welches Feature ein Domain-Zweck braucht. Die Prüf-Domain ('verify') ist bewusst ein eigenes
# Feature, unabhängig von 'custom_domain' (eigenständig im Admin buchbar).
FEATURE_BY_PURPOSE = {"app": "custom_domain", "abgabebox": "custom_domain", "verify": "verify_domain"}


def tenant_ids_with_feature(feature_code: str):
    return select(TenantFeature.tenant_id).where(TenantFeature.feature_code == feature_code)


def domain_feature_booked():
    """Bedingung auf TenantDomain: der Mandant hat das Feature, das der Zweck der Domain braucht.

    Gleiche Rolle wie tenant_ids_with_custom_domain_feature (FEAT-01/FEAT-02), aber für alle
    Zwecke - eine Prüf-Domain bleibt ohne 'verify_domain' unbedient, auch wenn 'custom_domain'
    gebucht ist, und umgekehrt."""
    return or_(
        *(
            and_(TenantDomain.purpose == purpose, TenantDomain.tenant_id.in_(tenant_ids_with_feature(code)))
            for purpose, code in FEATURE_BY_PURPOSE.items()
        )
    )


def target_host_for_purpose(purpose: str) -> str | None:
    """Wohin der CNAME einer Mandanten-Domain zeigen muss. Die Prüfseite gehört zur Abgabebox."""
    return settings.traefik_domain if purpose == "app" else settings.traefik_abgabebox_domain


def _app_routers(domain: str, domain_id: int) -> dict:
    base = f"tenant-app-{domain_id}"
    return {
        f"{base}-frontend": {
            "rule": f"Host(`{domain}`)",
            "entryPoints": ["websecure"],
            "service": f"{settings.router_prefix}-frontend@docker",
            "priority": 10,
            # Gleichzeitige Requests pro IP begrenzen wie auf der Hauptdomain (MAIN-OPS-013).
            "middlewares": [f"{settings.traefik_middleware_prefix}web-inflight@docker"],
            "tls": {"certResolver": "letsencrypt"},
        },
        f"{base}-backend": {
            "rule": f"Host(`{domain}`) && (PathPrefix(`/api`) || PathPrefix(`/docs`) || PathPrefix(`/openapi.json`))",
            "entryPoints": ["websecure"],
            "service": f"{settings.router_prefix}-backend@docker",
            "priority": 100,
            "middlewares": [f"{settings.traefik_middleware_prefix}api-inflight@docker"],
            "tls": {"certResolver": "letsencrypt"},
        },
        f"{base}-auth": {
            # Narrowly scoped to just the login POST (see docker-compose.yml's hocx-auth router
            # for why) - not all of /api/auth, which also carries /session and /tenant-by-domain
            # polled on every page load.
            "rule": f"Host(`{domain}`) && Path(`/api/auth/login`) && Method(`POST`)",
            "entryPoints": ["websecure"],
            "service": f"{settings.router_prefix}-auth@docker",
            "priority": 200,
            "middlewares": [f"{settings.traefik_middleware_prefix}auth-ratelimit@docker"],
            "tls": {"certResolver": "letsencrypt"},
        },
        f"{base}-gallery-upload": {
            "rule": f"Host(`{domain}`) && Path(`/api/files/gallery-uploads`) && Method(`POST`)",
            "entryPoints": ["websecure"],
            "service": f"{settings.router_prefix}-gallery-upload@docker",
            "priority": 200,
            "middlewares": [f"{settings.traefik_middleware_prefix}{name}@docker" for name in ("gallery-upload-inflight",)],
            "tls": {"certResolver": "letsencrypt"},
        },
        f"{base}-word-import": {
            # Same rate-limit/body-size protection as docker-compose.yml's hocx-word-import
            # router, but for a tenant's own custom domain - see routes/word_import.py.
            "rule": f"Host(`{domain}`) && PathPrefix(`/api/tools/word-import`) && Method(`POST`)",
            "entryPoints": ["websecure"],
            "service": f"{settings.router_prefix}-word-import@docker",
            "priority": 200,
            "middlewares": [f"{settings.traefik_middleware_prefix}word-import-ratelimit@docker", f"{settings.traefik_middleware_prefix}word-import-body-limit@docker"],
            "tls": {"certResolver": "letsencrypt"},
        },
    }


def _abgabebox_routers(domain: str, domain_id: int) -> dict:
    base = f"tenant-abgabebox-{domain_id}"
    return {
        f"{base}-frontend": {
            "rule": f"Host(`{domain}`)",
            "entryPoints": ["websecure"],
            "service": f"{settings.router_prefix}-abgabebox-frontend@docker",
            "priority": 10,
            "middlewares": [f"{settings.traefik_middleware_prefix}web-inflight@docker"],
            "tls": {"certResolver": "letsencrypt"},
        },
        f"{base}-backend": {
            "rule": f"Host(`{domain}`) && PathPrefix(`/api`)",
            "entryPoints": ["websecure"],
            "service": f"{settings.router_prefix}-abgabebox-backend@docker",
            "priority": 100,
            "middlewares": [f"{settings.traefik_middleware_prefix}api-inflight@docker"],
            "tls": {"certResolver": "letsencrypt"},
        },
        f"{base}-upload": {
            "rule": f"Host(`{domain}`) && PathPrefix(`/api/public`) && Method(`POST`)",
            "entryPoints": ["websecure"],
            "service": f"{settings.router_prefix}-abgabebox-backend@docker",
            "priority": 200,
            "middlewares": [f"{settings.traefik_middleware_prefix}{name}@docker" for name in ("abgabebox-upload-ratelimit", "abgabebox-upload-inflight", "abgabebox-upload-body-limit")],
            "tls": {"certResolver": "letsencrypt"},
        },
        f"{base}-verify": {
            # Echtheitsprüfung: vor dem Upload-Router (Priorität 300 > 200), eigenes Rate-Limit
            # und 4 KiB Body-Limit - gleiche Middlewares wie docker-compose.yml.
            "rule": f"Host(`{domain}`) && Path(`/api/public/verify`) && Method(`POST`)",
            "entryPoints": ["websecure"],
            "service": f"{settings.router_prefix}-abgabebox-backend@docker",
            "priority": 300,
            "middlewares": [f"{settings.traefik_middleware_prefix}{name}@docker" for name in ("abgabebox-verify-ratelimit", "abgabebox-verify-body-limit")],
            "tls": {"certResolver": "letsencrypt"},
        },
        f"{base}-public-get": {
            # Same rate-limit as docker-compose.yml's abgabebox-public-get router, but for
            # a tenant's own custom domain - protects the unauthenticated listing/detail
            # GET endpoints from unbounded enumeration.
            "rule": f"Host(`{domain}`) && PathPrefix(`/api/public`) && Method(`GET`)",
            "entryPoints": ["websecure"],
            "service": f"{settings.router_prefix}-abgabebox-backend@docker",
            "priority": 200,
            "middlewares": [
                f"{settings.traefik_middleware_prefix}abgabebox-public-ratelimit@docker",
                f"{settings.traefik_middleware_prefix}api-inflight@docker",
            ],
            "tls": {"certResolver": "letsencrypt"},
        },
    }


_VERIFY_ROOT_REDIRECT = "tenant-verify-root-redirect"


def _verify_routers(domain: str, domain_id: int) -> dict:
    """Prüf-Domain eines Mandanten (z. B. verify.verein.ch): nur die Prüfseite der Abgabebox, ihre
    Assets, der Prüf-Endpoint und der Wartungsstatus. Abgabe-Links und alle übrigen Abgabebox-Routen bleiben
    auf dieser Domain unerreichbar (kein passender Router -> 404 von Traefik)."""
    base = f"tenant-verify-{domain_id}"
    tls = {"certResolver": "letsencrypt"}
    frontend_service = f"{settings.router_prefix}-abgabebox-frontend@docker"
    return {
        f"{base}-root": {
            # Startseite der Domain ist die Prüfseite
            "rule": f"Host(`{domain}`) && Path(`/`)",
            "entryPoints": ["websecure"],
            "service": frontend_service,
            "priority": 20,
            "middlewares": [f"{_VERIFY_ROOT_REDIRECT}@file"],
            "tls": tls,
        },
        f"{base}-frontend": {
            "rule": (
                f"Host(`{domain}`) && (PathPrefix(`/verify`) || PathPrefix(`/_next`) "
                "|| Path(`/favicon.ico`))"
            ),
            "entryPoints": ["websecure"],
            "service": frontend_service,
            "priority": 10,
            "middlewares": [f"{settings.traefik_middleware_prefix}web-inflight@docker"],
            "tls": tls,
        },
        f"{base}-check": {
            # gleiche Middlewares wie der Prüf-Router der Abgabebox-Domain (docker-compose.yml)
            "rule": f"Host(`{domain}`) && Path(`/api/public/verify`) && Method(`POST`)",
            "entryPoints": ["websecure"],
            "service": f"{settings.router_prefix}-abgabebox-backend@docker",
            "priority": 300,
            "middlewares": [f"{settings.traefik_middleware_prefix}{name}@docker" for name in ("abgabebox-verify-ratelimit", "abgabebox-verify-body-limit")],
            "tls": tls,
        },
        f"{base}-maintenance": {
            # Wartungshinweis der Seite (components/maintenance-banner.tsx)
            "rule": f"Host(`{domain}`) && Path(`/api/public/maintenance-status`) && Method(`GET`)",
            "entryPoints": ["websecure"],
            "service": f"{settings.router_prefix}-abgabebox-backend@docker",
            "priority": 300,
            "middlewares": [
                f"{settings.traefik_middleware_prefix}abgabebox-public-ratelimit@docker",
                f"{settings.traefik_middleware_prefix}api-inflight@docker",
            ],
            "tls": tls,
        },
    }


def regenerate(db: Session) -> None:
    """Rewrites the Traefik file-provider config from the active tenant_domain rows.

    Routers reference the already-running docker-provider services (hocx-frontend@docker etc.)
    so no new containers are started per tenant. Called after every domain create/verify/delete
    and once at backend startup to correct any drift.
    """
    rows = (
        db.execute(
            select(TenantDomain).where(
                TenantDomain.status == "active",
                domain_feature_booked(),
            )
        )
        .scalars()
        .all()
    )

    routers: dict = {}
    has_verify = False
    for row in rows:
        if row.purpose == "app":
            routers.update(_app_routers(row.domain, row.id))
        elif row.purpose == "abgabebox":
            routers.update(_abgabebox_routers(row.domain, row.id))
        elif row.purpose == "verify":
            routers.update(_verify_routers(row.domain, row.id))
            has_verify = True

    # Traefik's file provider errors on an explicit-but-empty `http.routers: {}` (or `http: {}`)
    # map ("routers cannot be a standalone element") - an empty document is the only form it
    # accepts cleanly when there is nothing to route yet.
    config: dict = {"http": {"routers": routers}} if routers else {}
    if has_verify:
        config["http"]["middlewares"] = {
            _VERIFY_ROOT_REDIRECT: {"redirectRegex": {"regex": r"^https://([^/]+)/?$", "replacement": "https://${1}/verify"}}
        }

    target_dir = settings.traefik_dynamic_config_dir
    os.makedirs(target_dir, exist_ok=True)
    final_path = os.path.join(target_dir, _DYNAMIC_FILE_NAME)
    # Unique per call (pid + random suffix) - multiple uvicorn workers run this at startup
    # concurrently, and a shared fixed tmp filename lets one worker's os.replace() race ahead
    # of another's, leaving the second with a FileNotFoundError on an already-renamed-away file.
    tmp_path = f"{final_path}.{os.getpid()}.{secrets.token_hex(4)}.tmp"
    with open(tmp_path, "w") as fh:
        yaml.safe_dump(config, fh, sort_keys=False)
    # deploy.sh hardens this directory to 0660/group-5001-only (traefik reads it via
    # group_add, no one else may) - open()'s default mode is umask-dependent (typically
    # 0644, world-readable) and would silently re-break that on every regenerate() call,
    # failing the next deploy's permission check ("... muss fuer die Container-Gruppe 5001
    # vorbereitet werden").
    os.chmod(tmp_path, 0o660)
    os.replace(tmp_path, final_path)
