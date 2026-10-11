"""JSON-Export/-Import des Preiskatalogs (Module, Pläne, Speicherpakete) im Adminportal, siehe
catalog_config_service. Die Datei arbeitet bewusst in CHF und GB statt in Rappen und Bytes, weil
sie von Hand bearbeitet wird; umgerechnet wird erst im Service."""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

CATALOG_SCHEMA_VERSION = 1

CODE_PATTERN = r"^[a-z0-9_]+$"


class _CatalogEntry(BaseModel):
    # Tippfehler in Feldnamen ("price_montly_chf") sollen auffallen statt still ignoriert zu
    # werden. Felder mit "_"-Präfix (Infos aus dem Export wie "_mandanten") entfernt der Service
    # vor der Validierung.
    model_config = ConfigDict(extra="forbid")

    code: str = Field(pattern=CODE_PATTERN)


class CatalogFeatureEntry(_CatalogEntry):
    name: str | None = Field(default=None, min_length=1)
    description: str | None = None
    standalone_price_monthly_chf: Decimal | None = Field(default=None, ge=0)


class CatalogPlanEntry(_CatalogEntry):
    name: str | None = Field(default=None, min_length=1)
    description: str | None = None
    price_monthly_chf: Decimal | None = Field(default=None, ge=0)
    price_yearly_chf: Decimal | None = Field(default=None, ge=0)
    included_users: int | None = Field(default=None, ge=0)
    included_storage_gb: Decimal | None = Field(default=None, ge=0)
    feature_codes: list[str] = []
    is_bookable: bool = True
    is_featured: bool = False
    sort_order: int = 0


class CatalogStoragePackageEntry(_CatalogEntry):
    name: str | None = Field(default=None, min_length=1)
    storage_gb: Decimal | None = Field(default=None, gt=0)
    price_monthly_chf: Decimal | None = Field(default=None, ge=0)
    price_yearly_chf: Decimal | None = Field(default=None, ge=0)
    is_bookable: bool = True
    sort_order: int = 0


class CatalogImportRequest(BaseModel):
    # Rohes JSON der hochgeladenen Datei - validiert wird eintragsweise im Service, damit alle
    # Fehler auf einmal und mit Plan-/Paket-Code gemeldet werden statt als einzelner 422.
    config: dict[str, Any]
    overwrite: bool = False
    # Fingerprint aus der Vorschau. Gesetzt = Import bricht ab, wenn sich der Katalog seither
    # geändert hat (z.B. ein zweiter Admin hat inzwischen einen Preis angepasst).
    base_fingerprint: str | None = None


class CatalogFieldChange(BaseModel):
    field: str
    old: Any = None
    new: Any = None


class CatalogImportChange(BaseModel):
    entity: Literal["feature", "plan", "storage_package"]
    code: str
    name: str
    # deactivate = fehlt im Überschreiben-Modus, ist aber noch Mandanten zugewiesen und wird
    # deshalb nur auf nicht buchbar gesetzt statt gelöscht.
    action: Literal["create", "update", "delete", "deactivate"]
    changes: list[CatalogFieldChange] = []
    tenant_count: int = 0


class CatalogImportPreview(BaseModel):
    overwrite: bool
    changes: list[CatalogImportChange]
    errors: list[str]
    unchanged_count: int
    base_fingerprint: str
