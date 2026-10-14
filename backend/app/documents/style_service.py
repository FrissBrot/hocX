"""Hausstile und ihre Assets (Schriften, Logo, Fussbild).

Ein Hausstil ist ein Basis-Stil aus dem Repo (modern/classic/compact) plus validierte Tokens
(style_tokens.DocumentStyleTokens). Hochgeladen werden nur Schriften und Rasterbilder; jede
Datei wird auf Viren geprüft, dekodiert und erst dann gespeichert. Template-Code gibt es nicht.
"""
from __future__ import annotations

import hashlib
import io
import uuid
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app import scanner
from app.core.config import settings
from app.documents.context import AssetCollector
from app.documents.model import ResolvedStyle
from app.documents.style_tokens import FONT_FAMILIES, STYLE_KEYS, DocumentStyleTokens, default_tokens
from app.models import DocumentStyle, DocumentStyleAsset
from app.services.file_service import MAX_UPLOAD_BYTES, _safe_storage_path

ASSET_DIR = "document_style_assets"
IMAGE_TYPES = {"PNG": ("image/png", ".png"), "JPEG": ("image/jpeg", ".jpg"), "WEBP": ("image/webp", ".webp")}
FONT_SUFFIXES = {".ttf": "font/ttf", ".otf": "font/otf"}
MAX_IMAGE_PIXELS = 6000


class StyleValidationError(ValueError):
    """Kuratierter Fehler (Detail ist ein Text-Schlüssel des Namespace documents)."""


# ── Stile ───────────────────────────────────────────────────────────────────


def parse_tokens(raw: dict | None) -> DocumentStyleTokens:
    return DocumentStyleTokens.model_validate(raw or {})


def list_styles(db: Session, tenant_id: int) -> list[DocumentStyle]:
    return list(db.scalars(select(DocumentStyle).where(DocumentStyle.tenant_id == tenant_id).order_by(DocumentStyle.is_default.desc(), DocumentStyle.name.asc())))


def get_style(db: Session, tenant_id: int, public_id: uuid.UUID) -> DocumentStyle | None:
    return db.scalar(select(DocumentStyle).where(DocumentStyle.tenant_id == tenant_id, DocumentStyle.public_id == public_id))


def default_style(db: Session, tenant_id: int) -> DocumentStyle | None:
    return db.scalar(select(DocumentStyle).where(DocumentStyle.tenant_id == tenant_id, DocumentStyle.is_default.is_(True)))


def _check_asset_refs(db: Session, tenant_id: int, tokens: DocumentStyleTokens) -> None:
    """Asset-Referenzen in Tokens müssen zum Mandanten und zur richtigen Art gehören."""
    expected = {tokens.logo_asset_id: "image", tokens.footer_image_asset_id: "image"}
    for font_id in tokens.custom_fonts.ids():
        expected[font_id] = "font"
    for asset_id, kind in expected.items():
        if asset_id is None:
            continue
        asset = db.scalar(select(DocumentStyleAsset).where(DocumentStyleAsset.public_id == asset_id, DocumentStyleAsset.tenant_id == tenant_id))
        if asset is None or asset.kind != kind:
            raise StyleValidationError("apiError.assetNotFound")
    if tokens.font == "custom" and tokens.custom_fonts.regular is None:
        raise StyleValidationError("apiError.customFontMissing")


def _set_default(db: Session, tenant_id: int, style_id: int) -> None:
    db.execute(update(DocumentStyle).where(DocumentStyle.tenant_id == tenant_id, DocumentStyle.id != style_id).values(is_default=False))


def create_style(db: Session, tenant_id: int, *, name: str, style_key: str, tokens: DocumentStyleTokens | None, is_default: bool = False) -> DocumentStyle:
    if style_key not in STYLE_KEYS:
        raise StyleValidationError("apiError.unknownStyle")
    tokens = tokens or default_tokens(style_key)
    _check_asset_refs(db, tenant_id, tokens)
    if default_style(db, tenant_id) is None:
        is_default = True
    style = DocumentStyle(tenant_id=tenant_id, name=name.strip() or style_key, style_key=style_key, tokens_json=tokens.model_dump(mode="json"), is_default=False, version=1)
    db.add(style)
    db.flush()
    if is_default:
        _set_default(db, tenant_id, style.id)
        db.flush()
        style.is_default = True
    db.flush()
    return style


def update_style(db: Session, style: DocumentStyle, *, name: str | None = None, style_key: str | None = None, tokens: DocumentStyleTokens | None = None, is_default: bool | None = None) -> DocumentStyle:
    changed = False
    if name is not None and name.strip() and name.strip() != style.name:
        style.name = name.strip()
    if style_key is not None and style_key != style.style_key:
        if style_key not in STYLE_KEYS:
            raise StyleValidationError("apiError.unknownStyle")
        style.style_key = style_key
        changed = True
    if tokens is not None:
        _check_asset_refs(db, style.tenant_id, tokens)
        dumped = tokens.model_dump(mode="json")
        if dumped != style.tokens_json:
            style.tokens_json = dumped
            changed = True
    if is_default:
        _set_default(db, style.tenant_id, style.id)
        db.flush()
        style.is_default = True
    if changed:
        style.version += 1
    db.flush()
    return style


def delete_style(db: Session, style: DocumentStyle) -> None:
    was_default = style.is_default
    tenant_id = style.tenant_id
    db.delete(style)
    db.flush()
    if was_default:
        replacement = db.scalar(select(DocumentStyle).where(DocumentStyle.tenant_id == tenant_id).order_by(DocumentStyle.id.asc()))
        if replacement is not None:
            replacement.is_default = True
            db.flush()


def ensure_default_style(db: Session, tenant_id: int) -> DocumentStyle:
    """Jeder Mandant hat mindestens einen Hausstil (Standard «Modern»)."""
    existing = default_style(db, tenant_id)
    if existing is not None:
        return existing
    any_style = db.scalar(select(DocumentStyle).where(DocumentStyle.tenant_id == tenant_id).order_by(DocumentStyle.id.asc()))
    if any_style is not None:
        any_style.is_default = True
        db.flush()
        return any_style
    return create_style(db, tenant_id, name="Standard", style_key="modern", tokens=None, is_default=True)


# ── Assets ──────────────────────────────────────────────────────────────────


def list_assets(db: Session, tenant_id: int) -> list[DocumentStyleAsset]:
    return list(db.scalars(select(DocumentStyleAsset).where(DocumentStyleAsset.tenant_id == tenant_id).order_by(DocumentStyleAsset.created_at.desc())))


def get_asset(db: Session, tenant_id: int, public_id: uuid.UUID) -> DocumentStyleAsset | None:
    return db.scalar(select(DocumentStyleAsset).where(DocumentStyleAsset.tenant_id == tenant_id, DocumentStyleAsset.public_id == public_id))


def asset_in_use(db: Session, asset: DocumentStyleAsset) -> bool:
    for style in list_styles(db, asset.tenant_id):
        try:
            tokens = parse_tokens(style.tokens_json)
        except ValueError:
            continue
        if asset.public_id in tokens.asset_ids():
            return True
    return False


def font_family_of(content: bytes) -> str:
    from fontTools.ttLib import TTFont

    font = TTFont(io.BytesIO(content), lazy=True, fontNumber=0)
    try:
        name_table = font["name"]
        family = name_table.getDebugName(16) or name_table.getDebugName(1)
        if not family or not font.getBestCmap():
            raise StyleValidationError("apiError.invalidFont")
        return str(family).strip()
    finally:
        font.close()


def _validated_image(content: bytes) -> tuple[str, str]:
    from PIL import Image

    try:
        with Image.open(io.BytesIO(content)) as image:
            image.verify()
        with Image.open(io.BytesIO(content)) as image:
            if image.format not in IMAGE_TYPES or max(image.size) > MAX_IMAGE_PIXELS:
                raise StyleValidationError("apiError.invalidImage")
            return IMAGE_TYPES[image.format]
    except StyleValidationError:
        raise
    except Exception as exc:  # noqa: BLE001 - jede Pillow-Ausnahme heisst «kein gültiges Bild»
        raise StyleValidationError("apiError.invalidImage") from exc


async def create_asset(db: Session, tenant_id: int, *, kind: str, filename: str, content: bytes, user_id: int | None) -> DocumentStyleAsset:
    if kind not in ("image", "font"):
        raise StyleValidationError("apiError.invalidKind")
    if len(content) > MAX_UPLOAD_BYTES:
        raise StyleValidationError("apiError.tooLarge")
    font_family = None
    if kind == "image":
        mime_type, suffix = _validated_image(content)
    else:
        suffix = Path(filename or "").suffix.lower()
        if suffix not in FONT_SUFFIXES:
            raise StyleValidationError("apiError.invalidFont")
        mime_type = FONT_SUFFIXES[suffix]
        try:
            font_family = font_family_of(content)
        except StyleValidationError:
            raise
        except Exception as exc:  # noqa: BLE001 - jede fontTools-Ausnahme heisst «keine gültige Schrift»
            raise StyleValidationError("apiError.invalidFont") from exc
    status = (await scanner.scan_many([content], host=settings.clamav_host, port=settings.clamav_port))[0]
    if status == "infected":
        raise StyleValidationError("apiError.infected")
    if status == "error":
        raise StyleValidationError("apiError.scanFailed")
    relative = Path(ASSET_DIR) / f"tenant-{tenant_id}" / f"{uuid.uuid4().hex}{suffix}"
    target = _safe_storage_path(settings.storage_root, str(relative))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    asset = DocumentStyleAsset(
        tenant_id=tenant_id,
        kind=kind,
        name=Path(filename or "").stem or kind,
        original_name=filename,
        mime_type=mime_type,
        storage_path=str(relative),
        file_size_bytes=len(content),
        checksum_sha256=hashlib.sha256(content).hexdigest(),
        font_family=font_family,
        created_by=user_id,
    )
    db.add(asset)
    try:
        db.flush()
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return asset


def delete_asset(db: Session, asset: DocumentStyleAsset) -> None:
    if asset_in_use(db, asset):
        raise StyleValidationError("apiError.assetInUse")
    path = _safe_storage_path(settings.storage_root, asset.storage_path)
    db.delete(asset)
    db.flush()
    path.unlink(missing_ok=True)


def read_asset(asset: DocumentStyleAsset) -> bytes | None:
    try:
        path = _safe_storage_path(settings.storage_root, asset.storage_path)
    except Exception:  # noqa: BLE001
        return None
    return path.read_bytes() if path.exists() else None


# ── Auflösung für den Compile ───────────────────────────────────────────────


def resolve(db: Session, tenant_id: int, style: DocumentStyle | None) -> tuple[ResolvedStyle, DocumentStyleTokens, dict[str, bytes], dict[str, bytes]]:
    """Hausstil → ResolvedStyle (Pfade im Compile-Root), Tokens, Schriftdateien und Bilder.
    Stilbilder liegen unter assets/style-*, getrennt von den Inhaltsbildern (Inhalts-Hash)."""
    assets = AssetCollector(prefix="style")
    style_key = style.style_key if style is not None else "modern"
    try:
        tokens = parse_tokens(style.tokens_json) if style is not None else default_tokens(style_key)
    except ValueError:
        tokens = default_tokens(style_key)

    def image(asset_id) -> str | None:
        if asset_id is None:
            return None
        asset = get_asset(db, tenant_id, asset_id)
        content = read_asset(asset) if asset is not None and asset.kind == "image" else None
        if content is None:
            return None
        ref = assets.add_image(content, key=f"style:{asset.public_id}")
        return None if ref.missing else ref.path

    fonts: dict[str, bytes] = {}
    families: list[str] = []
    if tokens.font == "custom":
        for asset_id in tokens.custom_fonts.ids():
            asset = get_asset(db, tenant_id, asset_id)
            content = read_asset(asset) if asset is not None and asset.kind == "font" else None
            if content is None:
                continue
            fonts[f"{asset.public_id.hex}{Path(asset.storage_path).suffix or '.ttf'}"] = content
            if asset.font_family and asset.font_family not in families:
                families.append(asset.font_family)
    elif tokens.font in FONT_FAMILIES:
        families.append(FONT_FAMILIES[tokens.font])

    resolved = ResolvedStyle(
        key=style_key,
        version=(style.version or 1) if style is not None else 1,
        primary_color=tokens.primary_color,
        secondary_color=tokens.secondary_color,
        fonts=families[:4],
        base_size=tokens.base_size,
        line_spacing=tokens.line_spacing,
        margins=tokens.margins,
        header=tokens.header,
        footer=tokens.footer,
        logo=image(tokens.logo_asset_id),
        footer_image=image(tokens.footer_image_asset_id),
        sender=tokens.sender,
        sender_color=tokens.sender_color,
        place=tokens.place,
    )
    return resolved, tokens, fonts, assets.files
