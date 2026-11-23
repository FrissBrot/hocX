import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.auth_security.step_up import ADMIN, require_recent_auth
from app.core.config import settings
from app.core.db import get_db
from app.core.rate_limit import enforce_rate_limit
from app.core.permissions import P
from app.core.client_ip import rate_limit_source
from app.core.security import CurrentUser, get_current_user, get_optional_current_user, require_permission
from app.core.tenant_scope import tenant_scope_suspended
from app.models import Participant, Tenant, TenantDomain
from app.schemas.cashflow import TenantPortalCharges
from app.schemas.user import TenantDomainCreate, TenantDomainRead, TenantLookupRead, TenantRead, TenantSubscriptionRead, TenantUpdate
from app.services import public_id_service, tenant_trust_service
from app.services.tenant_service import (
    TenantService,
    build_tenant_profile_image_url,
    can_view_tenant_logo,
    tenant_logo_is_public,
    tenant_profile_image_media_type,
    tenant_profile_image_response,
)
from app.core.offload import run_coroutine_in_thread

router = APIRouter()
service = TenantService()


@router.get("/tenants", response_model=list[TenantRead])
def list_tenants(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    return service.list_tenants(db, user)


def _lookup_read(db: Session, tenant: Tenant, *, trusted: bool) -> TenantLookupRead:
    if not trusted:
        return TenantLookupRead(id=tenant.public_id, trusted=False)
    # Nur bei Trust und nur als Zahl: die Konten des anderen Mandanten sind per Row-Level-Security
    # sonst unsichtbar (app/core/tenant_scope.py).
    with tenant_scope_suspended(db):  # rls-ok: nur bei Trust und nur als Anzahl
        participant_count = db.scalar(
            select(func.count()).select_from(Participant).where(Participant.tenant_id == tenant.id, Participant.is_active.is_(True))
        )
    return TenantLookupRead(
        id=tenant.public_id,
        trusted=True,
        name=tenant.name,
        participant_count=participant_count or 0,
        profile_image_url=build_tenant_profile_image_url(tenant.public_id, tenant.profile_image_path),
    )


@router.get("/tenants/lookup", response_model=TenantLookupRead)
def lookup_tenant(public_id: uuid.UUID, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    """Loest einen ANDEREN Mandanten ueber seine public_id auf - eine bewusste, eng gefasste
    Ausnahme vom in public_id_service.py dokumentierten Grundsatz "public_id-Lookups immer auf
    den eigenen Mandanten scopen": der mandantenuebergreifende Lookup ist hier der Zweck
    (siehe photo_album_share_service.invite - Vorschau des Zielmandanten vor einer
    Album-Freigabe-Einladung). Ohne Trust (noch nie eine Freigabe angenommen, siehe
    tenant_trust_service) bestaetigt die Antwort nur, dass die ID existiert - kein Name, kein
    Profilbild. Nur mit files.manage (Album-Freigaben), damit nicht jeder authentifizierte Nutzer beliebige
    Mandanten-IDs durchprobieren kann."""
    require_permission(user, P.PHOTOS_MANAGE)
    if user.current_tenant_id is None:
        raise HTTPException(status_code=400, detail="No active tenant")
    tenant = public_id_service.get_by_public_id(db, Tenant, public_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Kein Mandant mit dieser ID gefunden")
    return _lookup_read(db, tenant, trusted=tenant_trust_service.is_trusted(db, user.current_tenant_id, tenant.id))


@router.get("/tenants/trusted", response_model=list[TenantLookupRead])
def search_trusted_tenants(
    search: str = Query(min_length=2, max_length=100),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Namenssuche - ausschliesslich unter Mandanten, mit denen bereits ein Trust besteht."""
    require_permission(user, P.PHOTOS_MANAGE)
    if user.current_tenant_id is None:
        raise HTTPException(status_code=400, detail="No active tenant")
    return [_lookup_read(db, tenant, trusted=True) for tenant in tenant_trust_service.search_trusted(db, user.current_tenant_id, search)]


@router.patch("/tenants/{tenant_id}", response_model=TenantRead)
async def patch_tenant(
    tenant_id: uuid.UUID,
    name: str | None = Form(default=None),
    profile_image: UploadFile | None = File(default=None),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    # Ganze Verarbeitung im Worker-Thread (Concurrency-Audit CONC-001): sie mischt synchrone
    # DB-Zugriffe mit awaits und blockierte sonst den Event-Loop des ganzen Workers.
    return await run_coroutine_in_thread(_patch_tenant_impl, tenant_id=tenant_id, name=name, profile_image=profile_image, db=db, user=user)


async def _patch_tenant_impl(  # loop-ok: nur über run_coroutine_in_thread (core/offload.py)
    tenant_id: uuid.UUID,
    name: str | None = Form(default=None),
    profile_image: UploadFile | None = File(default=None),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    internal_id = public_id_service.resolve_internal_id(db, Tenant, tenant_id)
    if internal_id is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    try:
        tenant = await service.update_tenant(
            db, internal_id, user, TenantUpdate(name=name), profile_image
        )
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Tenant could not be updated") from exc
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return tenant


@router.get("/tenants/{tenant_id}/subscription", response_model=TenantSubscriptionRead)
def get_tenant_subscription(
    tenant_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    internal_id = public_id_service.resolve_internal_id(db, Tenant, tenant_id)
    if internal_id is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    result = service.get_subscription(db, internal_id, user)
    if result is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return result


@router.get("/tenants/{tenant_id}/charges", response_model=TenantPortalCharges)
def get_tenant_charges(
    tenant_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    internal_id = public_id_service.resolve_internal_id(db, Tenant, tenant_id)
    if internal_id is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    result = service.get_charges(db, internal_id, user)
    if result is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return result


# Logos werden von der App-Shell auf jeder Seite geladen (Browser-Cache), Fehlversuche strenger.
TENANT_LOGO_LIMIT_PER_MINUTE = 300
TENANT_LOGO_MISS_LIMIT_PER_MINUTE = 30
TENANT_LOGO_MAX_AGE = 3600


@router.get("/tenants/{tenant_id}/profile-image")
def tenant_profile_image(
    tenant_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: CurrentUser | None = Depends(get_optional_current_user),
):
    """Vereinslogo. Ohne Anmeldung nur, wo es ohnehin öffentlich gezeigt wird (Login-Branding der
    eigenen App-Domain, Prüfseite mit freigegebener Identität, tenant_service.tenant_logo_is_public);
    angemeldet für den eigenen Mandanten und vertraute Partner. Alles andere - unbekannt, fremd,
    kein Logo, kein Rasterbild - ergibt dieselbe 404."""
    ip = rate_limit_source(request)
    enforce_rate_limit(f"tenant-logo:{ip}", limit=TENANT_LOGO_LIMIT_PER_MINUTE, period_seconds=60, fail_open=True)
    try:
        public_id = uuid.UUID(tenant_id)
    except ValueError:
        public_id = None
    tenant = (
        public_id_service.get_by_public_id(db, Tenant, public_id)  # nosemgrep: public-id-lookup-without-tenant -- mandantenübergreifend gewollt, Zugriff prüft can_view_tenant_logo
        if public_id is not None
        else None
    )
    key = tenant.profile_image_path if tenant is not None else None
    if (
        tenant is None
        or key is None
        or tenant_profile_image_media_type(key) is None  # Altbestand ohne Rasterendung (z. B. SVG) nie ausliefern
        or not can_view_tenant_logo(db, tenant, user)
    ):
        enforce_rate_limit(f"tenant-logo:miss:{ip}", limit=TENANT_LOGO_MISS_LIMIT_PER_MINUTE, period_seconds=60, fail_open=True)
        raise HTTPException(status_code=404, detail="Tenant profile image not found")
    if tenant_logo_is_public(db, tenant):
        cache = {"Cache-Control": f"public, max-age={TENANT_LOGO_MAX_AGE}"}
    else:
        # Nur für Angemeldete: nie in geteilten Caches ablegen
        cache = {"Cache-Control": f"private, max-age={TENANT_LOGO_MAX_AGE}", "Vary": "Cookie"}
    return tenant_profile_image_response(request, key, extra_headers=cache)


# Getrennte Stundenkontingente je Mandant für die Domain-Routen (Audit 08, 2026-11).
DOMAIN_CREATE_LIMIT_PER_HOUR = 5
DOMAIN_VERIFY_LIMIT_PER_HOUR = 20
DOMAIN_DELETE_LIMIT_PER_HOUR = 10


@router.get("/tenants/{tenant_id}/domains", response_model=list[TenantDomainRead])
def list_tenant_domains(
    tenant_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    internal_id = public_id_service.resolve_internal_id(db, Tenant, tenant_id)
    if internal_id is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return service.list_domains(db, internal_id, user)


@router.post("/tenants/{tenant_id}/domains", response_model=TenantDomainRead)
def create_tenant_domain(
    tenant_id: uuid.UUID,
    payload: TenantDomainCreate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    internal_id = public_id_service.resolve_internal_id(db, Tenant, tenant_id)  # nosemgrep: public-id-lookup-without-tenant -- require_manageable prüft direkt danach
    if internal_id is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    # Each create/verify/delete triggers a full Traefik dynamic-config rewrite + reload (and
    # verify can trigger a Let's-Encrypt certificate request) - cap how often a tenant can do
    # that instead of leaving it fully unbounded.
    # Erst Rechte, dann Kontingent (Audit MAIN-SEC-008): sonst verbrauchen Fremde mit
    # 403-Requests das Stundenkontingent des Mandanten.
    service.require_manageable(internal_id, user)
    # Eigene Domain = Sicherheitskonfiguration (Anmeldung über diese Domain, SEC-AUTH-010)
    require_recent_auth(user, kind=ADMIN, action="tenant.domain_create")
    enforce_rate_limit(f"tenant-domain-create:{internal_id}", limit=DOMAIN_CREATE_LIMIT_PER_HOUR, period_seconds=3600)
    return service.create_domain(db, internal_id, user, payload)


@router.post("/tenants/{tenant_id}/domains/{domain_id}/verify", response_model=TenantDomainRead)
def verify_tenant_domain(
    tenant_id: uuid.UUID,
    domain_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    tenant_internal_id = public_id_service.resolve_internal_id(db, Tenant, tenant_id)
    domain_internal_id = public_id_service.resolve_internal_id(db, TenantDomain, domain_id)
    if tenant_internal_id is None or domain_internal_id is None:
        raise HTTPException(status_code=404, detail="Tenant or domain not found")
    # Erst Rechte, dann Kontingent (Audit MAIN-SEC-008): sonst verbrauchen Fremde mit
    # 403-Requests das Stundenkontingent des Mandanten.
    service.require_manageable(tenant_internal_id, user)
    # Eigenes, grosszügigeres Kontingent (Audit 08, 2026-11): wer wiederholt «Jetzt prüfen»
    # klickt, solange das DNS noch nicht durch ist, darf sich nicht das Löschen sperren. Eine
    # erfolglose Prüfung schreibt Traefik nicht neu, kostet nur DNS-Abfragen.
    enforce_rate_limit(f"tenant-domain-verify:{tenant_internal_id}", limit=DOMAIN_VERIFY_LIMIT_PER_HOUR, period_seconds=3600)
    return service.verify_domain(db, tenant_internal_id, user, domain_internal_id)


@router.delete("/tenants/{tenant_id}/domains/{domain_id}", response_model=dict[str, str])
def delete_tenant_domain(
    tenant_id: uuid.UUID,
    domain_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    tenant_internal_id = public_id_service.resolve_internal_id(db, Tenant, tenant_id)
    domain_internal_id = public_id_service.resolve_internal_id(db, TenantDomain, domain_id)
    if tenant_internal_id is None or domain_internal_id is None:
        raise HTTPException(status_code=404, detail="Tenant or domain not found")
    # Erst Rechte, dann Kontingent (Audit MAIN-SEC-008): sonst verbrauchen Fremde mit
    # 403-Requests das Stundenkontingent des Mandanten.
    service.require_manageable(tenant_internal_id, user)
    require_recent_auth(user, kind=ADMIN, action="tenant.domain_delete")
    enforce_rate_limit(f"tenant-domain-delete:{tenant_internal_id}", limit=DOMAIN_DELETE_LIMIT_PER_HOUR, period_seconds=3600)
    service.delete_domain(db, tenant_internal_id, user, domain_internal_id)
    return {"message": "Domain removed"}
