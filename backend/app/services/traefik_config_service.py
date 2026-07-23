from __future__ import annotations

import os
import secrets

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import TenantDomain

_DYNAMIC_FILE_NAME = "tenant-domains.yml"


def _app_routers(domain: str, domain_id: int) -> dict:
    base = f"tenant-app-{domain_id}"
    return {
        f"{base}-frontend": {
            "rule": f"Host(`{domain}`)",
            "entryPoints": ["websecure"],
            "service": "hocx-frontend@docker",
            "priority": 10,
            "tls": {"certResolver": "letsencrypt"},
        },
        f"{base}-backend": {
            "rule": f"Host(`{domain}`) && (PathPrefix(`/api`) || PathPrefix(`/docs`) || PathPrefix(`/openapi.json`))",
            "entryPoints": ["websecure"],
            "service": "hocx-backend@docker",
            "priority": 100,
            "tls": {"certResolver": "letsencrypt"},
        },
        f"{base}-auth": {
            # Narrowly scoped to just the login POST (see docker-compose.yml's hocx-auth router
            # for why) - not all of /api/auth, which also carries /session and /tenant-by-domain
            # polled on every page load.
            "rule": f"Host(`{domain}`) && Path(`/api/auth/login`) && Method(`POST`)",
            "entryPoints": ["websecure"],
            "service": "hocx-auth@docker",
            "priority": 200,
            "middlewares": ["auth-ratelimit@docker"],
            "tls": {"certResolver": "letsencrypt"},
        },
    }


def _abgabebox_routers(domain: str, domain_id: int) -> dict:
    base = f"tenant-abgabebox-{domain_id}"
    return {
        f"{base}-frontend": {
            "rule": f"Host(`{domain}`)",
            "entryPoints": ["websecure"],
            "service": "abgabebox-frontend@docker",
            "priority": 10,
            "tls": {"certResolver": "letsencrypt"},
        },
        f"{base}-backend": {
            "rule": f"Host(`{domain}`) && PathPrefix(`/api`)",
            "entryPoints": ["websecure"],
            "service": "abgabebox-backend@docker",
            "priority": 100,
            "tls": {"certResolver": "letsencrypt"},
        },
        f"{base}-upload": {
            "rule": f"Host(`{domain}`) && PathPrefix(`/api/public`) && Method(`POST`)",
            "entryPoints": ["websecure"],
            "service": "abgabebox-backend@docker",
            "priority": 200,
            "middlewares": ["abgabebox-upload-ratelimit@docker"],
            "tls": {"certResolver": "letsencrypt"},
        },
    }


def regenerate(db: Session) -> None:
    """Rewrites the Traefik file-provider config from the active tenant_domain rows.

    Routers reference the already-running docker-provider services (hocx-frontend@docker etc.)
    so no new containers are started per tenant. Called after every domain create/verify/delete
    and once at backend startup to correct any drift.
    """
    rows = db.execute(select(TenantDomain).where(TenantDomain.status == "active")).scalars().all()

    routers: dict = {}
    for row in rows:
        if row.purpose == "app":
            routers.update(_app_routers(row.domain, row.id))
        elif row.purpose == "abgabebox":
            routers.update(_abgabebox_routers(row.domain, row.id))

    # Traefik's file provider errors on an explicit-but-empty `http.routers: {}` (or `http: {}`)
    # map ("routers cannot be a standalone element") - an empty document is the only form it
    # accepts cleanly when there is nothing to route yet.
    config = {"http": {"routers": routers}} if routers else {}

    target_dir = settings.traefik_dynamic_config_dir
    os.makedirs(target_dir, exist_ok=True)
    final_path = os.path.join(target_dir, _DYNAMIC_FILE_NAME)
    # Unique per call (pid + random suffix) - multiple uvicorn workers run this at startup
    # concurrently, and a shared fixed tmp filename lets one worker's os.replace() race ahead
    # of another's, leaving the second with a FileNotFoundError on an already-renamed-away file.
    tmp_path = f"{final_path}.{os.getpid()}.{secrets.token_hex(4)}.tmp"
    with open(tmp_path, "w") as fh:
        yaml.safe_dump(config, fh, sort_keys=False)
    os.replace(tmp_path, final_path)
