"""Brand Studio: Brand-Profile mit unveränderlichen Revisionen und ihre Auflösung für den Compile.

Snapshot-Strategie: Jede gespeicherte Änderung der Tokens erzeugt eine neue
``document_brand_revision`` (unveränderlich); ``document_brand.current_revision`` zeigt auf die
gültige. Entwürfe von Vorlagen sehen immer die aktuelle Revision, veröffentlichte Revisionen
folgen ihr (``brand_mode=follow``) oder halten die Revision beim Veröffentlichen fest
(``pinned``). Jeder Export speichert die verwendete Brand-Revision - ältere PDFs bleiben so
nachvollziehbar und reproduzierbar, auch wenn das Profil später geändert wird.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.documents import assets as asset_service
from app.documents.brand import BUILTIN_FONTS, FALLBACK_FONTS, BrandTokens, parse_tokens, preset_tokens, resolve_appearance
from app.documents.context import AssetCollector
from app.documents.hashing import json_hash
from app.documents.locking import lock_row
from app.models import DocumentBrand, DocumentBrandRevision, DocumentExport, DocumentTemplate, DocumentTemplateAssignment, DocumentTemplateRevision, Tenant


class BrandConflictError(Exception):
    """Das Profil wurde inzwischen von jemand anderem geändert (optimistische Sperre)."""

    def __init__(self, current_lock_version: int) -> None:
        super().__init__("conflict")
        self.current_lock_version = current_lock_version


class BrandValidationError(ValueError):
    """Kuratierter Fehler (Text-Schlüssel aus documentPdf ``apiError.*``)."""


# ── Lesen ────────────────────────────────────────────────────────────────────


def list_brands(db: Session, tenant_id: int, *, include_archived: bool = False) -> list[DocumentBrand]:
    statement = select(DocumentBrand).where(DocumentBrand.tenant_id == tenant_id)
    if not include_archived:
        statement = statement.where(DocumentBrand.archived_at.is_(None))
    return list(db.scalars(statement.order_by(DocumentBrand.is_default.desc(), DocumentBrand.name.asc())))


def get_brand(db: Session, tenant_id: int, public_id: uuid.UUID | None) -> DocumentBrand | None:
    if public_id is None:
        return None
    return db.scalar(select(DocumentBrand).where(DocumentBrand.tenant_id == tenant_id, DocumentBrand.public_id == public_id))


def default_brand(db: Session, tenant_id: int) -> DocumentBrand | None:
    return db.scalar(select(DocumentBrand).where(DocumentBrand.tenant_id == tenant_id, DocumentBrand.is_default.is_(True)))


def current_revision(db: Session, brand: DocumentBrand) -> DocumentBrandRevision | None:
    return db.scalar(
        select(DocumentBrandRevision).where(DocumentBrandRevision.brand_id == brand.id, DocumentBrandRevision.revision == brand.current_revision)
    )


def list_revisions(db: Session, brand: DocumentBrand, limit: int = 50) -> list[DocumentBrandRevision]:
    return list(
        db.scalars(
            select(DocumentBrandRevision).where(DocumentBrandRevision.brand_id == brand.id).order_by(DocumentBrandRevision.revision.desc()).limit(limit)
        )
    )


def get_revision(db: Session, tenant_id: int, revision_id: int | None) -> DocumentBrandRevision | None:
    """Revision nur, wenn sie zu einem Profil des Mandanten gehört."""
    if revision_id is None:
        return None
    revision = db.get(DocumentBrandRevision, revision_id)
    if revision is None:
        return None
    brand = db.get(DocumentBrand, revision.brand_id)
    return revision if brand is not None and brand.tenant_id == tenant_id else None


def tokens_of(revision: DocumentBrandRevision | None) -> BrandTokens:
    if revision is None:
        return BrandTokens()
    try:
        return parse_tokens(revision.tokens_json)
    except ValueError:
        # Gespeicherte Revision passt nicht mehr zum Schema: Standardwerte statt Abbruch
        return BrandTokens()


# ── Schreiben ────────────────────────────────────────────────────────────────


def _check_asset_refs(db: Session, tenant_id: int, tokens: BrandTokens) -> None:
    ids = tokens.asset_ids()
    found = asset_service.assets_by_ids(db, tenant_id, ids)
    for asset_id in ids:
        asset = found.get(asset_id)
        if asset is None:
            raise BrandValidationError("apiError.assetNotFound")
    for asset_id in tokens.typography.body.asset_ids + tokens.typography.heading.asset_ids:
        if found[asset_id].kind != "font":
            raise BrandValidationError("apiError.invalidFont")
    for asset_id in tokens.assets.ids():
        if found[asset_id].kind != "image":
            raise BrandValidationError("apiError.invalidImage")


def _add_revision(db: Session, brand: DocumentBrand, tokens: BrandTokens, *, user_id: int | None, note: str | None = None) -> DocumentBrandRevision:
    data = tokens.model_dump(mode="json")
    next_revision = (db.scalar(select(func.max(DocumentBrandRevision.revision)).where(DocumentBrandRevision.brand_id == brand.id)) or 0) + 1
    revision = DocumentBrandRevision(brand_id=brand.id, revision=next_revision, tokens_json=data, tokens_hash=json_hash(data), note=note, created_by=user_id)
    db.add(revision)
    db.flush()
    brand.current_revision = next_revision
    return revision


def _set_default(db: Session, tenant_id: int, brand: DocumentBrand) -> None:
    # Alle Profile des Mandanten sperren: zwei parallele Standardwechsel verletzten sonst
    # uq_document_brand_default (HTTP 500)
    db.execute(select(DocumentBrand.id).where(DocumentBrand.tenant_id == tenant_id).order_by(DocumentBrand.id).with_for_update())
    db.execute(update(DocumentBrand).where(DocumentBrand.tenant_id == tenant_id, DocumentBrand.id != brand.id).values(is_default=False))
    db.flush()
    brand.is_default = True


def create_brand(
    db: Session,
    tenant_id: int,
    *,
    name: str,
    tokens: BrandTokens | None = None,
    preset: str | None = None,
    description: str | None = None,
    is_default: bool = False,
    user_id: int | None = None,
) -> DocumentBrand:
    tokens = tokens or (preset_tokens(preset) if preset else BrandTokens())
    _check_asset_refs(db, tenant_id, tokens)
    brand = DocumentBrand(tenant_id=tenant_id, name=name.strip()[:120] or "Brand", description=description, is_default=False, current_revision=1, created_by=user_id, updated_by=user_id)
    db.add(brand)
    db.flush()
    _add_revision(db, brand, tokens, user_id=user_id)
    if is_default or default_brand(db, tenant_id) is None:
        _set_default(db, tenant_id, brand)
    db.flush()
    return brand


def update_brand(
    db: Session,
    brand: DocumentBrand,
    *,
    expected_lock_version: int | None,
    name: str | None = None,
    description: str | None = None,
    tokens: BrandTokens | None = None,
    is_default: bool | None = None,
    note: str | None = None,
    user_id: int | None = None,
) -> DocumentBrand:
    lock_row(db, brand)
    if expected_lock_version is not None and expected_lock_version != brand.lock_version:
        raise BrandConflictError(brand.lock_version)
    if name is not None and name.strip():
        brand.name = name.strip()[:120]
    if description is not None:
        brand.description = description.strip()[:600] or None
    if tokens is not None:
        _check_asset_refs(db, brand.tenant_id, tokens)
        current = current_revision(db, brand)
        if current is None or current.tokens_hash != json_hash(tokens.model_dump(mode="json")):
            _add_revision(db, brand, tokens, user_id=user_id, note=note)
    if is_default:
        if brand.archived_at is not None:
            raise BrandValidationError("apiError.brandArchived")
        _set_default(db, brand.tenant_id, brand)
    brand.lock_version += 1
    brand.updated_by = user_id
    db.flush()
    return brand


def restore_revision(db: Session, brand: DocumentBrand, revision: DocumentBrandRevision, *, user_id: int | None) -> DocumentBrand:
    """Älteren Stand als neue Revision übernehmen (die Historie bleibt unverändert)."""
    lock_row(db, brand)
    tokens = tokens_of(revision)
    _check_asset_refs(db, brand.tenant_id, tokens)
    _add_revision(db, brand, tokens, user_id=user_id, note=f"restore:{revision.revision}")
    brand.lock_version += 1
    brand.updated_by = user_id
    db.flush()
    return brand


def duplicate_brand(db: Session, brand: DocumentBrand, *, name: str, user_id: int | None) -> DocumentBrand:
    return create_brand(db, brand.tenant_id, name=name, tokens=tokens_of(current_revision(db, brand)), description=brand.description, user_id=user_id)


def archive_brand(db: Session, brand: DocumentBrand, *, archived: bool) -> DocumentBrand:
    from datetime import UTC, datetime

    lock_row(db, brand)
    if archived and brand.is_default:
        raise BrandValidationError("apiError.defaultBrand")
    brand.archived_at = datetime.now(UTC) if archived else None
    brand.lock_version += 1
    db.flush()
    return brand


def delete_brand(db: Session, brand: DocumentBrand) -> None:
    """Nur unbenutzte Profile: Exporte, Vorlagen, Zuweisungen oder Revisionen, die eine
    Brand-Revision festhalten (``brand_mode=pinned``), behalten ihre Referenz - dafür gibt es
    «Archivieren». Ohne die Prüfung der festgehaltenen Revisionen setzte der FK (ON DELETE
    SET NULL) das Pinning still zurück."""
    if brand.is_default:
        raise BrandValidationError("apiError.defaultBrand")
    revision_ids = select(DocumentBrandRevision.id).where(DocumentBrandRevision.brand_id == brand.id)
    used = (
        db.scalar(select(func.count(DocumentExport.id)).where(DocumentExport.brand_revision_id.in_(revision_ids)))
        or db.scalar(select(func.count(DocumentTemplate.id)).where(DocumentTemplate.brand_id == brand.id))
        or db.scalar(select(func.count(DocumentTemplateAssignment.id)).where(DocumentTemplateAssignment.brand_id == brand.id))
        or db.scalar(select(func.count(DocumentTemplateRevision.id)).where(DocumentTemplateRevision.brand_revision_id.in_(revision_ids)))
    )
    if used:
        raise BrandValidationError("apiError.brandInUse")
    db.delete(brand)
    db.flush()


def ensure_default_brand(db: Session, tenant_id: int) -> DocumentBrand:
    brand = default_brand(db, tenant_id)
    if brand is not None:
        return brand
    # Erster Aufruf (auch aus GET-Endpunkten): Mandantenzeile sperren und erneut prüfen, sonst
    # legen zwei parallele Anfragen je ein Standardprofil an (uq_document_brand_default -> 500)
    db.execute(select(Tenant.id).where(Tenant.id == tenant_id).with_for_update())
    brand = default_brand(db, tenant_id)
    if brand is not None:
        return brand
    existing = db.scalar(select(DocumentBrand).where(DocumentBrand.tenant_id == tenant_id, DocumentBrand.archived_at.is_(None)).order_by(DocumentBrand.id.asc()))
    if existing is not None:
        _set_default(db, tenant_id, existing)
        db.flush()
        return existing
    tenant = db.get(Tenant, tenant_id)
    return create_brand(db, tenant_id, name=tenant.name if tenant is not None else "Brand", tokens=BrandTokens(), is_default=True)


# ── Auflösung für den Compile ───────────────────────────────────────────────

_WEIGHTS = {"regular": 400, "medium": 500, "bold": 700}


@dataclass
class ResolvedBrand:
    tokens: BrandTokens
    brand_id: int | None = None
    revision_id: int | None = None
    files: dict[str, bytes] = field(default_factory=dict)
    fonts: dict[str, bytes] = field(default_factory=dict)
    # Bildpfade im Compile-Root und Schalter für Bindungen (brand.*)
    env: dict[str, Any] = field(default_factory=dict)
    organization: dict[str, Any] = field(default_factory=dict)
    typst: dict[str, Any] = field(default_factory=dict)
    asset_checksums: dict[str, str] = field(default_factory=dict)
    families: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def resolve_brand(db: Session, tenant_id: int, revision: DocumentBrandRevision | None, *, tokens: BrandTokens | None = None) -> ResolvedBrand:
    """Brand-Revision (oder ungespeicherte Tokens der Live-Vorschau) → Werte für Compiler und
    Typst. Bilder liegen unter assets/brand-*, getrennt von Inhaltsbildern (Inhalts-Hash)."""
    tokens = tokens if tokens is not None else tokens_of(revision)
    resolved = ResolvedBrand(tokens=tokens, brand_id=revision.brand_id if revision is not None else None, revision_id=revision.id if revision is not None else None)
    collector = AssetCollector(prefix="brand")
    found = asset_service.assets_by_ids(db, tenant_id, tokens.asset_ids())

    def image(asset_id: uuid.UUID | None) -> str | None:
        if asset_id is None:
            return None
        asset = found.get(asset_id)
        content = asset_service.read_asset(asset) if asset is not None and asset.kind == "image" else None
        if content is None:
            resolved.warnings.append(f"asset:{asset_id}")
            return None
        resolved.asset_checksums[str(asset.public_id)] = asset.checksum_sha256 or ""
        ref = collector.add_image(content, key=f"brand:{asset.public_id}")
        return None if ref.missing else ref.path

    def families(choice) -> list[str]:
        names: list[str] = []
        for asset_id in choice.asset_ids:
            asset = found.get(asset_id)
            content = asset_service.read_asset(asset) if asset is not None and asset.kind == "font" else None
            if content is None:
                resolved.warnings.append(f"font:{asset_id}")
                continue
            resolved.fonts[f"{asset.public_id.hex}{Path(asset.storage_path).suffix or '.ttf'}"] = content
            resolved.asset_checksums[str(asset.public_id)] = asset.checksum_sha256 or ""
            if asset.font_family and asset.font_family not in names:
                names.append(asset.font_family)
        if choice.builtin:
            names.append(BUILTIN_FONTS[choice.builtin])
        for fallback in tokens.typography.fallbacks:
            names.append(BUILTIN_FONTS[fallback])
        if not names:
            names.append(BUILTIN_FONTS["inter"])
        return list(dict.fromkeys(names + list(FALLBACK_FONTS)))

    body_fonts = families(tokens.typography.body)
    heading_fonts = families(tokens.typography.heading)
    resolved.families = list(dict.fromkeys(body_fonts + heading_fonts))

    assets = tokens.assets
    paths = {
        "logo": image(assets.logo),
        "logo_alt": image(assets.logo_alt),
        "letterhead": image(assets.letterhead),
        "background": image(assets.background),
        "watermark": image(assets.watermark),
        "footer_image": image(assets.footer_image),
    }
    images = {item.key: image(item.asset_id) for item in assets.images}
    resolved.files = collector.files

    layout = tokens.layout
    hf = layout.header_footer
    resolved.env = {
        **paths,
        "images": images,
        "footer_text": hf.footer_text,
        "header_show_logo": hf.header_show_logo and paths["logo"] is not None,
        "header_show_title": hf.header_show_title,
        "header_show_date": hf.header_show_date,
        "header_line": hf.header_line,
        "footer_show_number": hf.footer_show_number,
        "footer_show_pages": hf.footer_show_pages,
        "footer_line": hf.footer_line,
        "title_page": layout.title_page,
        "toc": layout.toc,
        "show_metadata": layout.show_metadata,
        "watermark_draft": layout.watermark_draft,
        "verify_show_url": tokens.verify.show_url,
        "verify_show_id": tokens.verify.show_id,
        "verify_show_qr": tokens.verify.show_qr,
    }
    tenant = db.get(Tenant, tenant_id)
    organization = tokens.organization
    resolved.organization = {
        "name": organization.name or (tenant.name if tenant is not None else ""),
        "address": organization.address,
        "contact": organization.contact,
        "website": organization.website,
        "place": organization.place,
    }
    colors = tokens.colors.model_dump(mode="json", exclude={"custom"})
    typography = tokens.typography
    resolved.typst = {
        "colors": {key: str(value).upper() for key, value in colors.items()},
        "custom_colors": {item.key: item.value.upper() for item in tokens.colors.custom},
        "fonts": {"body": body_fonts, "heading": heading_fonts},
        "typography": {
            "base_size": typography.base_size,
            "size_title": typography.size_title,
            "size_subtitle": typography.size_subtitle,
            "size_h1": typography.size_h1,
            "size_h2": typography.size_h2,
            "size_h3": typography.size_h3,
            "size_small": typography.size_small,
            "weight_body": _WEIGHTS[typography.weight_body],
            "weight_heading": _WEIGHTS[typography.weight_heading],
            "line_height": typography.line_height,
            "letter_spacing_heading": typography.letter_spacing_heading,
            "heading_transform": typography.heading_transform,
        },
        "layout": {
            "paragraph_gap": layout.paragraph_gap,
            "section_gap": layout.section_gap,
            "heading_style": layout.heading_style,
            "table_style": layout.table_style,
            "border_width": layout.border_width,
            "radius": layout.radius,
        },
        "appearance": resolve_appearance(tokens),
    }
    return resolved
