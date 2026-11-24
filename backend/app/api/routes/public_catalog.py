"""Oeffentlicher (unauthentifizierter) Preiskatalog fuer die Landing Page auf der Hauptdomain.
Liefert nur buchbare Plaene - Aenderungen im Adminportal (Preise, Limits, Features,
"Beliebteste Wahl") erscheinen damit ohne Deployment auf der Website. Kein IP-Rate-Limit: der
Abruf kommt serverseitig vom Frontend (eine IP fuer alle Besucher) und ist ein reiner,
kleiner Katalog-Read ohne Enumerations-Risiko. Dasselbe gilt fuer die Kundenliste: nur Namen
(und Logo-URLs) von Mandanten, die im Adminportal ausdruecklich fuer die Website freigegeben wurden.

Die Logos selbst laedt der Browser des Besuchers: diese Route hat deshalb ein IP-Rate-Limit
(gesamt und strenger fuer Fehlversuche) und liefert nur Logos gelisteter Mandanten."""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.core.client_ip import rate_limit_source
from app.core.db import get_db
from app.core.rate_limit import enforce_rate_limit
from app.schemas.public_catalog import PublicCustomerRead, PublicPlanComparisonRead, PublicPlanRead
from app.services import website_customer_logo_service
from app.services.admin_tenant_service import AdminTenantService

router = APIRouter()
service = AdminTenantService()


@router.get("/public/plans", response_model=list[PublicPlanRead])
def list_public_plans(db: Session = Depends(get_db)):
    return service.list_public_plans(db)


@router.get("/public/plan-comparison", response_model=PublicPlanComparisonRead)
def get_public_plan_comparison(db: Session = Depends(get_db)):
    """Abos und Features für die Vergleichstabelle der Website (gleiche Regeln wie /public/plans)."""
    return service.public_plan_comparison(db)


@router.get("/public/customers", response_model=list[PublicCustomerRead])
def list_public_customers(db: Session = Depends(get_db)):
    return service.list_public_customers(db)


# Ein Seitenaufruf laedt alle Logos der Kundenleiste; Fehlversuche (Raten von Kennungen) strenger.
CUSTOMER_LOGO_LIMIT_PER_MINUTE = 300
CUSTOMER_LOGO_MISS_LIMIT_PER_MINUTE = 30
# Die URL wechselt mit jedem neuen Logo; eine Stunde begrenzt, wie lange ein entlisteter Mandant
# in Browser- und Proxy-Caches sichtbar bleibt (danach genügt meist ein 304).
CUSTOMER_LOGO_CACHE_CONTROL = "public, max-age=3600"
_LOGO_KEY = re.compile(website_customer_logo_service.LOGO_KEY_PATTERN)
_LOGO_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "default-src 'none'; sandbox",
    "Cross-Origin-Resource-Policy": "same-site",
}


def _etag_matches(header: str | None, etag: str) -> bool:
    if not header:
        return False
    candidates = [part.strip().removeprefix("W/") for part in header.split(",")]
    return "*" in candidates or etag in candidates


@router.get("/public/customers/logos/{key}.png")
def get_public_customer_logo(key: str, request: Request, db: Session = Depends(get_db)):
    """Logo eines auf der Website gelisteten Mandanten als neu gerendertes PNG. Unbekannte,
    fehlerhafte und nicht (mehr) gelistete Kennungen ergeben dieselbe 404 - kein Orakel."""
    ip = rate_limit_source(request)
    enforce_rate_limit(f"public-customer-logo:{ip}", limit=CUSTOMER_LOGO_LIMIT_PER_MINUTE, period_seconds=60, fail_open=True)
    logo = website_customer_logo_service.find_listed_logo(db, key) if _LOGO_KEY.fullmatch(key) else None
    if logo is None:
        enforce_rate_limit(f"public-customer-logo:miss:{ip}", limit=CUSTOMER_LOGO_MISS_LIMIT_PER_MINUTE, period_seconds=60, fail_open=True)
        raise HTTPException(status_code=404, detail="Not found")
    # Kennung enthaelt den Speicherschluessel des Logos: gleiche Kennung = gleicher Inhalt
    etag = f'"{key}"'
    headers = {**_LOGO_HEADERS, "Cache-Control": CUSTOMER_LOGO_CACHE_CONTROL, "ETag": etag}
    if _etag_matches(request.headers.get("if-none-match"), etag):
        return Response(status_code=304, headers=headers)
    return Response(content=logo.content, media_type="image/png", headers=headers)
