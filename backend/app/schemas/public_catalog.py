from __future__ import annotations

from pydantic import BaseModel


class PublicPlanFeature(BaseModel):
    code: str
    name: str


class PublicCustomerLogo(BaseModel):
    """Logo eines gelisteten Kunden: relative URL mit nicht erratbarer Kennung (kein Mandanten-ID,
    kein Speicherpfad) und die Pixelmasse des ausgelieferten PNG (für width/height im <img>)."""

    url: str
    width: int
    height: int


class PublicCustomerRead(BaseModel):
    """Kunde fuer "Im Einsatz bei" - Name und (falls vorhanden) Logo, keine IDs/Slugs."""

    name: str
    logo: PublicCustomerLogo | None = None


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


class PublicFeatureRead(BaseModel):
    """Zeile der Funktionsvergleichs-Tabelle auf der Website: buchbares Feature aus dem
    Katalog (Name/Beschreibung wie im Adminportal gepflegt)."""

    code: str
    name: str
    description: str | None = None
    # Produktmodul aus permissions/features.json (Gruppierung der Tabelle); "other" für
    # Features, die nur in der Datenbank stehen
    module: str
    # Einzeln zubuchbar zu diesem Monatspreis (Rappen); None = nur über ein Abo
    standalone_price_monthly_rp: int | None = None


class PublicPlanComparisonRead(BaseModel):
    """Abos und Features für die Vergleichstabelle der Website, bei jedem Abruf aus der DB."""

    plans: list[PublicPlanRead]
    features: list[PublicFeatureRead]
