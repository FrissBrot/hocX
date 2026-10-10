from __future__ import annotations

from pydantic import BaseModel


class PublicPlanFeature(BaseModel):
    code: str
    name: str


class PublicCustomerRead(BaseModel):
    """Kunde fuer "Im Einsatz bei" - bewusst nur der Name, keine IDs/Slugs."""

    name: str


class PublicPlanRead(BaseModel):
    """Preiskarte der oeffentlichen Website. Bewusst ohne interne Felder (tenant_count,
    sort_order, is_bookable) - nur, was auf der Landing Page sichtbar ist."""

    code: str
    name: str
    description: str | None = None
    # Rappen, nicht Franken (wie im Admin-Katalog).
    price_monthly_rp: int | None = None
    price_yearly_rp: int | None = None
    # None = unbegrenzt.
    included_user_limit: int | None = None
    included_storage_bytes: int | None = None
    is_featured: bool = False
    features: list[PublicPlanFeature] = []
