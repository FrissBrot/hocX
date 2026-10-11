"""JSON-Export/-Import des Preiskatalogs (Module/Features, Pläne, Speicherpakete) für das
Adminportal (/admin/plans).

Ablauf: Export herunterladen, von Hand anpassen, hochladen. Der Import läuft in zwei Schritten:
`preview` rechnet aus, was sich ändern würde (inkl. Fehlerliste), `apply` schreibt dieselben
Änderungen in einer einzigen Transaktion. Der `code` jedes Eintrags ist die feste ID, über die
Datei und Datenbank zusammengeführt werden - umbenennen lässt er sich per Import nicht.

Modi:
- Ergänzen (overwrite=False): Einträge der Datei werden angelegt bzw. aktualisiert, und zwar nur
  die Felder, die im Eintrag stehen. Was in der Datei fehlt, bleibt unverändert.
- Überschreiben (overwrite=True): jeder Eintrag ersetzt den bestehenden vollständig (fehlende
  Felder = Standardwert). Pläne/Speicherpakete, die in einer vorhandenen Liste fehlen, werden
  gelöscht - ausser sie sind noch Mandanten zugewiesen, dann werden sie nur auf nicht buchbar
  gesetzt (tenant_storage_package hängt per ON DELETE CASCADE am Paket, ein Löschen würde
  Mandanten still ihr Zusatzkontingent wegnehmen). Die Übersicht "Umbuchen" zeigt diese
  Mandanten. Fehlt eine ganze Liste (z.B. kein "storage_packages"), bleibt sie unangetastet.

Features (Module) sind im Code verdrahtet (Feature-Gating) und können per Import nur geändert,
nie angelegt oder gelöscht werden. Zuweisungen an Mandanten sind nicht Teil der Datei."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Callable

from pydantic import BaseModel, ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Feature, Plan, PlanFeature, StoragePackage, Tenant, TenantStoragePackage
from app.schemas.catalog_config import (
    CATALOG_SCHEMA_VERSION,
    CatalogFeatureEntry,
    CatalogFieldChange,
    CatalogImportChange,
    CatalogImportPreview,
    CatalogPlanEntry,
    CatalogStoragePackageEntry,
)
from app.services.admin_tenant_service import AdminTenantService

# Gleiche Umrechnung wie das Preiskatalog-Formular im Frontend (1 GB = 1024 MB).
BYTES_PER_GB = 1024**3

SECTION_KEYS = ("features", "plans", "storage_packages")
ENTITY_BY_SECTION = {"features": "feature", "plans": "plan", "storage_packages": "storage_package"}
SECTION_LABELS = {"features": "Modul", "plans": "Plan", "storage_packages": "Speicherpaket"}


class CatalogChangedError(ValueError):
    """Der Katalog wurde zwischen Vorschau und Import geändert."""


# --- Einheiten -----------------------------------------------------------------------------


def _rp_to_chf(rp: int | None) -> float | int | None:
    if rp is None:
        return None
    value = Decimal(rp) / 100
    return int(value) if value == value.to_integral_value() else float(value)


def _chf_to_rp(value: Decimal | None, _old: Any) -> int | None:
    if value is None:
        return None
    rp = value * 100
    if rp != rp.to_integral_value():
        raise ValueError("höchstens zwei Nachkommastellen (Rappen)")
    return int(rp)


def _bytes_to_gb(value: int | None) -> float | int | None:
    if value is None:
        return None
    gb = round(value / BYTES_PER_GB, 6)
    return int(gb) if gb == int(gb) else gb


def _gb_to_bytes(value: Decimal | None, old: Any) -> int | None:
    if value is None:
        return None
    # Der Export rundet auf 6 Nachkommastellen - steht derselbe Wert wieder in der Datei, bleiben
    # die exakten Bytes erhalten, statt durch die Rundung eine Scheinänderung zu erzeugen.
    if isinstance(old, int) and Decimal(str(_bytes_to_gb(old))) == value:
        return old
    return int((value * BYTES_PER_GB).to_integral_value(rounding=ROUND_HALF_UP))


def _text(value: str | None, _old: Any) -> str | None:
    return (value or "").strip() or None


def _same(value: Any, _old: Any) -> Any:
    return value


def _identity(value: Any) -> Any:
    return value


@dataclass(frozen=True)
class _Field:
    attr: str  # Spalte in der Datenbank
    key: str  # Feld in der JSON-Datei
    from_file: Callable[[Any, Any], Any] = _same
    to_file: Callable[[Any], Any] = _identity


FEATURE_FIELDS = (
    _Field("name", "name", _text),
    _Field("description", "description", _text),
    _Field("standalone_price_monthly_rp", "standalone_price_monthly_chf", _chf_to_rp, _rp_to_chf),
)
PLAN_FIELDS = (
    _Field("name", "name", _text),
    _Field("description", "description", _text),
    _Field("price_monthly_rp", "price_monthly_chf", _chf_to_rp, _rp_to_chf),
    _Field("price_yearly_rp", "price_yearly_chf", _chf_to_rp, _rp_to_chf),
    _Field("included_user_limit", "included_users"),
    _Field("included_storage_bytes", "included_storage_gb", _gb_to_bytes, _bytes_to_gb),
    _Field("feature_codes", "feature_codes", lambda value, _old: sorted(set(value))),
    _Field("is_bookable", "is_bookable"),
    _Field("is_featured", "is_featured"),
    _Field("sort_order", "sort_order"),
)
STORAGE_PACKAGE_FIELDS = (
    _Field("name", "name", _text),
    _Field("bytes", "storage_gb", _gb_to_bytes, _bytes_to_gb),
    _Field("price_monthly_rp", "price_monthly_chf", _chf_to_rp, _rp_to_chf),
    _Field("price_yearly_rp", "price_yearly_chf", _chf_to_rp, _rp_to_chf),
    _Field("is_bookable", "is_bookable"),
    _Field("sort_order", "sort_order"),
)
FIELDS_BY_SECTION: dict[str, tuple[_Field, ...]] = {
    "features": FEATURE_FIELDS,
    "plans": PLAN_FIELDS,
    "storage_packages": STORAGE_PACKAGE_FIELDS,
}
MODEL_BY_SECTION: dict[str, type[BaseModel]] = {
    "features": CatalogFeatureEntry,
    "plans": CatalogPlanEntry,
    "storage_packages": CatalogStoragePackageEntry,
}
# Pflichtfelder beim Anlegen und im Überschreiben-Modus (dann wird der Eintrag komplett ersetzt).
REQUIRED_KEYS = {"features": ("name",), "plans": ("name",), "storage_packages": ("name", "storage_gb")}


@dataclass
class _Op:
    section: str
    code: str
    action: str
    target: dict[str, Any] | None
    changes: list[CatalogFieldChange] = field(default_factory=list)
    tenant_count: int = 0
    name: str = ""


@dataclass
class _State:
    """Aktueller Katalog in Datenbank-Einheiten, pro Abschnitt code -> Spaltenwerte."""

    sections: dict[str, dict[str, dict[str, Any]]]
    tenant_counts: dict[str, dict[str, int]]

    def fingerprint(self) -> str:
        return hashlib.sha256(json.dumps(self.sections, sort_keys=True, default=str).encode()).hexdigest()


class CatalogConfigService:
    def __init__(self, tenant_service: AdminTenantService | None = None) -> None:
        self.tenant_service = tenant_service or AdminTenantService()

    # --- Lesen ---------------------------------------------------------------------------

    def _load_state(self, db: Session) -> _State:
        features = {
            f.code: {"name": f.name, "description": f.description, "standalone_price_monthly_rp": f.standalone_price_monthly_rp}
            for f in db.scalars(select(Feature).order_by(Feature.code.asc()))
        }
        feature_codes_by_plan: dict[str, list[str]] = {}
        for plan_code, feature_code in db.execute(
            select(PlanFeature.plan_code, PlanFeature.feature_code).order_by(PlanFeature.feature_code.asc())
        ).all():
            feature_codes_by_plan.setdefault(plan_code, []).append(feature_code)
        plans = {
            p.code: {
                "name": p.name,
                "description": p.description,
                "price_monthly_rp": p.price_monthly_rp,
                "price_yearly_rp": p.price_yearly_rp,
                "included_user_limit": p.included_user_limit,
                "included_storage_bytes": p.included_storage_bytes,
                "feature_codes": feature_codes_by_plan.get(p.code, []),
                "is_bookable": p.is_bookable,
                "is_featured": p.is_featured,
                "sort_order": p.sort_order,
            }
            for p in db.scalars(select(Plan).order_by(Plan.sort_order.asc(), Plan.price_yearly_rp.asc().nulls_first(), Plan.code.asc()))
        }
        packages = {
            p.code: {
                "name": p.name,
                "bytes": p.bytes,
                "price_monthly_rp": p.price_monthly_rp,
                "price_yearly_rp": p.price_yearly_rp,
                "is_bookable": p.is_bookable,
                "sort_order": p.sort_order,
            }
            for p in db.scalars(select(StoragePackage).order_by(StoragePackage.sort_order.asc(), StoragePackage.bytes.asc(), StoragePackage.code.asc()))
        }
        plan_counts = dict(
            db.execute(select(Tenant.plan_code, func.count(Tenant.id)).where(Tenant.plan_code.is_not(None)).group_by(Tenant.plan_code)).all()
        )
        package_counts = dict(
            db.execute(
                select(TenantStoragePackage.package_code, func.count(TenantStoragePackage.tenant_id)).group_by(TenantStoragePackage.package_code)
            ).all()
        )
        return _State(
            sections={"features": features, "plans": plans, "storage_packages": packages},
            tenant_counts={"features": {}, "plans": plan_counts, "storage_packages": package_counts},
        )

    def export_config(self, db: Session) -> dict[str, Any]:
        state = self._load_state(db)
        result: dict[str, Any] = {
            "_anleitung": self._guide(state),
            "schema_version": CATALOG_SCHEMA_VERSION,
            "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        for section in SECTION_KEYS:
            entries = []
            for code, values in state.sections[section].items():
                entry: dict[str, Any] = {"code": code}
                for spec in FIELDS_BY_SECTION[section]:
                    entry[spec.key] = spec.to_file(values[spec.attr])
                if section != "features":
                    entry["_mandanten"] = int(state.tenant_counts[section].get(code, 0))
                entries.append(entry)
            result[section] = entries
        return result

    # --- Vorschau ------------------------------------------------------------------------

    def preview(self, db: Session, config: dict[str, Any], *, overwrite: bool) -> CatalogImportPreview:
        state = self._load_state(db)
        ops, errors, unchanged = self._compute(state, config, overwrite=overwrite)
        return self._preview_model(state, ops, errors, unchanged, overwrite=overwrite)

    def _preview_model(
        self, state: _State, ops: list[_Op], errors: list[str], unchanged: int, *, overwrite: bool
    ) -> CatalogImportPreview:
        return CatalogImportPreview(
            overwrite=overwrite,
            changes=[
                CatalogImportChange(
                    entity=ENTITY_BY_SECTION[op.section],  # type: ignore[arg-type]
                    code=op.code,
                    name=op.name,
                    action=op.action,  # type: ignore[arg-type]
                    changes=op.changes,
                    tenant_count=op.tenant_count,
                )
                for op in ops
            ],
            errors=errors,
            unchanged_count=unchanged,
            base_fingerprint=state.fingerprint(),
        )

    def _compute(self, state: _State, config: Any, *, overwrite: bool) -> tuple[list[_Op], list[str], int]:
        errors: list[str] = []
        if not isinstance(config, dict):
            return [], ["Die Datei muss ein JSON-Objekt enthalten."], 0
        version = config.get("schema_version")
        if version != CATALOG_SCHEMA_VERSION:
            errors.append(f"schema_version muss {CATALOG_SCHEMA_VERSION} sein (gefunden: {json.dumps(version)}).")
        allowed_top = {"schema_version", "exported_at", *SECTION_KEYS}
        for key in config:
            if not key.startswith("_") and key not in allowed_top:
                errors.append(f"Unbekannter Abschnitt '{key}' (erlaubt: {', '.join(SECTION_KEYS)}).")
        if not any(section in config for section in SECTION_KEYS):
            errors.append("Die Datei enthält keinen der Abschnitte features, plans oder storage_packages.")

        # Erst alle Abschnitte einlesen, dann Querbezüge prüfen (feature_codes, is_featured).
        targets: dict[str, dict[str, dict[str, Any]]] = {}
        for section in SECTION_KEYS:
            if section not in config:
                continue
            targets[section] = self._parse_section(state, section, config[section], overwrite=overwrite, errors=errors)

        feature_codes = set(state.sections["features"])
        for code, target in targets.get("plans", {}).items():
            unknown = [c for c in target["feature_codes"] if c not in feature_codes]
            if unknown:
                errors.append(f"Plan '{code}': unbekannte feature_codes {', '.join(unknown)}.")

        ops: list[_Op] = []
        unchanged = 0
        for section in SECTION_KEYS:
            current = state.sections[section]
            section_targets = targets.get(section)
            final: dict[str, dict[str, Any]] = {code: dict(values) for code, values in current.items()}
            removed: dict[str, str] = {}
            if section_targets is not None:
                final.update(section_targets)
                if overwrite and section != "features":
                    for code in current:
                        if code in section_targets:
                            continue
                        if state.tenant_counts[section].get(code, 0) > 0:
                            final[code] = {**current[code], "is_bookable": False}
                            if section == "plans":
                                final[code]["is_featured"] = False
                            removed[code] = "deactivate"
                        else:
                            del final[code]
                            removed[code] = "delete"
            if section == "plans":
                self._resolve_featured(final, section_targets or {}, errors)

            for code in [*current, *[c for c in final if c not in current]]:
                count = int(state.tenant_counts[section].get(code, 0))
                if code not in final:
                    ops.append(_Op(section, code, "delete", None, tenant_count=count, name=current[code]["name"]))
                    continue
                changes = self._diff(section, current.get(code), final[code])
                if code not in current:
                    ops.append(_Op(section, code, "create", final[code], changes, count, final[code]["name"] or code))
                elif changes:
                    action = removed.get(code, "update")
                    ops.append(_Op(section, code, action, final[code], changes, count, final[code]["name"] or code))
                else:
                    unchanged += 1
        return ops, errors, unchanged

    def _parse_section(
        self, state: _State, section: str, raw: Any, *, overwrite: bool, errors: list[str]
    ) -> dict[str, dict[str, Any]]:
        label = SECTION_LABELS[section]
        if not isinstance(raw, list):
            errors.append(f"'{section}' muss eine Liste sein.")
            return {}
        current = state.sections[section]
        model = MODEL_BY_SECTION[section]
        targets: dict[str, dict[str, Any]] = {}
        for index, item in enumerate(raw):
            ref = f"{section}[{index}]"
            if not isinstance(item, dict):
                errors.append(f"{ref}: Eintrag muss ein Objekt sein.")
                continue
            if isinstance(item.get("code"), str):
                ref = f"{label} '{item['code']}'"
            data = {key: value for key, value in item.items() if not str(key).startswith("_")}
            try:
                entry = model.model_validate(data)
            except ValidationError as exc:
                for err in exc.errors():
                    loc = ".".join(str(part) for part in err["loc"]) or "Eintrag"
                    errors.append(f"{ref}: {loc}: {err['msg']}")
                continue
            code = entry.code
            if code in targets:
                errors.append(f"{ref}: code kommt mehrfach vor.")
                continue
            existing = current.get(code)
            if section == "features" and existing is None:
                errors.append(f"{ref}: unbekanntes Modul. Module können nur geändert, nicht angelegt werden.")
                continue

            full_replace = existing is None or overwrite
            set_keys = entry.model_fields_set - {"code"}
            target: dict[str, Any] = dict(existing) if existing is not None and not full_replace else {}
            for spec in FIELDS_BY_SECTION[section]:
                if not full_replace and spec.key not in set_keys:
                    continue
                old = existing.get(spec.attr) if existing is not None else None
                try:
                    target[spec.attr] = spec.from_file(getattr(entry, spec.key), old)
                except ValueError as exc:
                    errors.append(f"{ref}: {spec.key}: {exc}")
            attr_by_key = {spec.key: spec.attr for spec in FIELDS_BY_SECTION[section]}
            for key in REQUIRED_KEYS[section]:
                if target.get(attr_by_key[key]) is None and f"{ref}: {key}:" not in " ".join(errors):
                    errors.append(f"{ref}: {key} fehlt.")
            targets[code] = target
        return targets

    @staticmethod
    def _resolve_featured(final: dict[str, dict[str, Any]], file_targets: dict[str, dict[str, Any]], errors: list[str]) -> None:
        """Höchstens ein Plan ist "Beliebteste Wahl" (wie upsert_plan): markiert die Datei einen,
        verlieren alle anderen die Markierung."""
        featured_in_file = [code for code, target in file_targets.items() if target.get("is_featured")]
        if len(featured_in_file) > 1:
            errors.append(f"Nur ein Plan darf is_featured = true haben (gefunden: {', '.join(featured_in_file)}).")
            return
        keep = featured_in_file[0] if featured_in_file else next((c for c, v in final.items() if v.get("is_featured")), None)
        for code, values in final.items():
            if code != keep and values.get("is_featured"):
                final[code] = {**values, "is_featured": False}

    @staticmethod
    def _diff(section: str, old: dict[str, Any] | None, new: dict[str, Any]) -> list[CatalogFieldChange]:
        changes = []
        for spec in FIELDS_BY_SECTION[section]:
            old_value = old.get(spec.attr) if old is not None else None
            new_value = new.get(spec.attr)
            if old is not None and old_value == new_value:
                continue
            if old is None and new_value in (None, [], False, 0) and spec.attr not in ("is_bookable",):
                continue
            changes.append(
                CatalogFieldChange(
                    field=spec.key,
                    old=spec.to_file(old_value) if old is not None else None,
                    new=spec.to_file(new_value),
                )
            )
        return changes

    # --- Anwenden ------------------------------------------------------------------------

    def apply(
        self, db: Session, config: dict[str, Any], *, overwrite: bool, base_fingerprint: str | None = None
    ) -> CatalogImportPreview:
        state = self._load_state(db)
        if base_fingerprint and base_fingerprint != state.fingerprint():
            raise CatalogChangedError(
                "Der Preiskatalog wurde seit der Vorschau geändert. Bitte die Vorschau neu laden und erneut prüfen."
            )
        ops, errors, unchanged = self._compute(state, config, overwrite=overwrite)
        if errors:
            raise ValueError("Import nicht möglich:\n" + "\n".join(errors))

        quota_plans: set[str] = set()
        quota_packages: set[str] = set()
        for op in ops:
            if op.section == "features":
                self._apply_feature(db, op)
            elif op.section == "plans":
                if self._apply_plan(db, op, state.sections["plans"].get(op.code)):
                    quota_plans.add(op.code)
            elif self._apply_storage_package(db, op, state.sections["storage_packages"].get(op.code)):
                quota_packages.add(op.code)
        db.flush()

        # Kontingente der betroffenen Mandanten nachführen (Plan-Speicher oder Paketgrösse geändert).
        tenant_ids: set[int] = set()
        if quota_plans:
            tenant_ids.update(db.scalars(select(Tenant.id).where(Tenant.plan_code.in_(quota_plans))))
        if quota_packages:
            tenant_ids.update(
                db.scalars(select(TenantStoragePackage.tenant_id).where(TenantStoragePackage.package_code.in_(quota_packages)))
            )
        for tenant_id in sorted(tenant_ids):
            self.tenant_service.apply_effective_storage_quota(db, tenant_id)
        db.commit()
        return self._preview_model(state, ops, [], unchanged, overwrite=overwrite)

    @staticmethod
    def _apply_feature(db: Session, op: _Op) -> None:
        feature = db.get(Feature, op.code)
        assert feature is not None and op.target is not None
        for spec in FEATURE_FIELDS:
            setattr(feature, spec.attr, op.target[spec.attr])

    @staticmethod
    def _apply_plan(db: Session, op: _Op, old: dict[str, Any] | None) -> bool:
        """True, wenn sich das Speicherkontingent des Plans geändert hat."""
        if op.action == "delete":
            db.execute(PlanFeature.__table__.delete().where(PlanFeature.plan_code == op.code))
            db.delete(db.get(Plan, op.code))
            return False
        assert op.target is not None
        plan = db.get(Plan, op.code) or Plan(code=op.code)
        for spec in PLAN_FIELDS:
            if spec.attr != "feature_codes":
                setattr(plan, spec.attr, op.target[spec.attr])
        db.add(plan)
        db.flush()
        wanted = set(op.target["feature_codes"])
        current = set(db.scalars(select(PlanFeature.feature_code).where(PlanFeature.plan_code == op.code)))
        if current - wanted:
            db.execute(
                PlanFeature.__table__.delete().where(
                    PlanFeature.plan_code == op.code, PlanFeature.feature_code.in_(current - wanted)
                )
            )
        for feature_code in sorted(wanted - current):
            db.add(PlanFeature(plan_code=op.code, feature_code=feature_code))
        return old is not None and old["included_storage_bytes"] != op.target["included_storage_bytes"]

    @staticmethod
    def _apply_storage_package(db: Session, op: _Op, old: dict[str, Any] | None) -> bool:
        """True, wenn sich die Paketgrösse geändert hat."""
        if op.action == "delete":
            db.delete(db.get(StoragePackage, op.code))
            return False
        assert op.target is not None
        package = db.get(StoragePackage, op.code) or StoragePackage(code=op.code)
        for spec in STORAGE_PACKAGE_FIELDS:
            setattr(package, spec.attr, op.target[spec.attr])
        db.add(package)
        return old is not None and old["bytes"] != op.target["bytes"]

    # --- Anleitung -----------------------------------------------------------------------

    @staticmethod
    def _guide(state: _State) -> dict[str, Any]:
        return {
            "zweck": (
                "Diese Datei enthält den Preiskatalog von hocX: Module (features), Pläne/Abos (plans) und "
                "Speicher-Zusatzpakete (storage_packages). Sie kann bearbeitet und im Adminportal unter "
                "Preiskatalog > Konfiguration importieren wieder hochgeladen werden. Dieser Abschnitt "
                "(_anleitung) wird beim Import ignoriert und darf drin bleiben."
            ),
            "ablauf": [
                "1. Datei herunterladen (das ist diese Datei).",
                "2. Werte anpassen, Einträge hinzufügen oder entfernen.",
                "3. Im Adminportal hochladen und den Modus wählen (Ergänzen oder Überschreiben).",
                "4. Die Vorschau zeigt alle Änderungen (neu, geändert, gelöscht, nicht mehr buchbar) und Fehler. Erst mit 'Import anwenden' wird gespeichert.",
                "5. Gespeichert wird alles oder nichts: bei einem Fehler wird keine Änderung übernommen.",
            ],
            "id": (
                "Das Feld 'code' ist die feste ID jedes Eintrags und verbindet die Datei mit dem bestehenden Katalog. "
                "Erlaubt sind Kleinbuchstaben a-z, Ziffern und _. Ein bestehender code darf nicht geändert werden: "
                "ein geänderter code gilt als neuer Eintrag (und im Überschreiben-Modus wird der alte entfernt)."
            ),
            "modi": {
                "ergaenzen": (
                    "Schalter 'Überschreiben' aus. Einträge aus der Datei werden angelegt bzw. aktualisiert. "
                    "Innerhalb eines Eintrags werden nur die Felder geändert, die dort stehen - "
                    "{\"code\": \"standard\", \"price_yearly_chf\": 490} ändert nur den Jahrespreis. "
                    "Was in der Datei fehlt, bleibt unverändert. Ein neuer Eintrag braucht mindestens die Pflichtfelder."
                ),
                "ueberschreiben": (
                    "Schalter 'Überschreiben' an. Der Katalog wird durch die Datei ersetzt: jeder Eintrag wird "
                    "vollständig übernommen (fehlende Felder = Standardwert, siehe 'felder'). Pläne und "
                    "Speicherpakete, die in der Liste fehlen, werden gelöscht. Sind sie noch Mandanten "
                    "zugewiesen, werden sie stattdessen auf nicht buchbar gesetzt und erscheinen im "
                    "Preiskatalog unter 'Umbuchen'. Fehlt ein ganzer Abschnitt (z.B. kein 'storage_packages'), "
                    "bleibt dieser Teil unverändert; eine leere Liste [] entfernt alle Einträge des Abschnitts."
                ),
            },
            "regeln": [
                "Preise in CHF mit höchstens zwei Nachkommastellen, z.B. 29.9 oder 490. null = kein Preis.",
                "Speicher in GB (1 GB = 1024 MB), Dezimalwerte erlaubt, z.B. 2.5.",
                "Unbekannte Feldnamen sind ein Fehler (schützt vor Tippfehlern). Felder, die mit _ beginnen (z.B. _mandanten), sind nur Info und werden ignoriert.",
                "Module (features) können nur geändert werden; neue Module entstehen nur durch ein Software-Update. Im Überschreiben-Modus werden fehlende Module nicht gelöscht.",
                "Höchstens ein Plan darf is_featured = true haben. Wird einer markiert, verlieren alle anderen die Markierung.",
                "Welcher Mandant welchen Plan und welche Pakete hat, ist nicht Teil dieser Datei und wird nie geändert.",
                "Ändert sich der Speicher eines Plans oder die Grösse eines Pakets, wird das Speicherkontingent der betroffenen Mandanten neu berechnet (ausser bei manuell gesetztem Kontingent).",
            ],
            "felder": {
                "features": {
                    "code": "Pflicht. ID des Moduls, muss bereits existieren (siehe gueltige_feature_codes).",
                    "name": "Pflicht beim Überschreiben. Anzeigename.",
                    "description": "Text oder null.",
                    "standalone_price_monthly_chf": "Preis pro Monat, wenn das Modul einzeln zugebucht wird. null = nur über einen Plan erhältlich.",
                },
                "plans": {
                    "code": "Pflicht. ID des Plans.",
                    "name": "Pflicht bei neuen Plänen und beim Überschreiben.",
                    "description": "Text oder null.",
                    "price_monthly_chf": "Monatspreis oder null.",
                    "price_yearly_chf": "Jahrespreis oder null. Beide Preise null = individueller Preis pro Mandant.",
                    "included_users": "Anzahl inkludierter Benutzer (ganze Zahl) oder null = unbegrenzt.",
                    "included_storage_gb": "Inkludierter Speicher in GB oder null = unbegrenzt.",
                    "feature_codes": "Liste der enthaltenen Module, z.B. [\"finance\"]. Standard: [].",
                    "is_bookable": "true = bei neuen Mandanten und auf der Website wählbar, false = nur vom Admin zuweisbar. Standard: true.",
                    "is_featured": "true = auf der Website als 'Beliebteste Wahl' hervorgehoben. Standard: false.",
                    "sort_order": "Ganze Zahl für die Reihenfolge. Standard: 0.",
                },
                "storage_packages": {
                    "code": "Pflicht. ID des Pakets.",
                    "name": "Pflicht bei neuen Paketen und beim Überschreiben.",
                    "storage_gb": "Pflicht bei neuen Paketen und beim Überschreiben. Grösse in GB, grösser als 0.",
                    "price_monthly_chf": "Monatspreis oder null.",
                    "price_yearly_chf": "Jahrespreis oder null.",
                    "is_bookable": "true = kann Mandanten zugebucht werden, false = nicht mehr neu zubuchbar (bestehende Zuweisungen bleiben). Standard: true.",
                    "sort_order": "Ganze Zahl für die Reihenfolge. Standard: 0.",
                },
            },
            "gueltige_feature_codes": {code: values["name"] for code, values in state.sections["features"].items()},
            "beispiele": {
                "preis_aendern_ergaenzen": {"plans": [{"code": "standard", "price_yearly_chf": 490, "price_monthly_chf": 49}]},
                "neues_speicherpaket": {
                    "storage_packages": [{"code": "extra_50gb", "name": "50 GB Zusatzspeicher", "storage_gb": 50, "price_yearly_chf": 120}]
                },
                "plan_nicht_mehr_buchbar": {"plans": [{"code": "standard", "is_bookable": False}]},
                "modul_umbenennen": {"features": [{"code": "finance", "name": "Finanzen"}]},
            },
        }
