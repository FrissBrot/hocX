"""Assets des Document Studio: Bilder (Logo, Briefkopf, Hintergrund, Wasserzeichen, Grafiken)
und Schriften, mandantengebunden.

Hochgeladen werden nur Rasterbilder (PNG, JPEG, WebP) und Schriften (TTF, OTF), kein Code und
kein SVG. Jede Datei wird auf Viren geprüft (ClamAV), dekodiert und erst dann gespeichert.
Referenzen aus Brand-Profilen und Vorlagen (``public_id``) werden immer mit dem Mandanten des
Exports aufgelöst: eine fremde ID ergibt «nicht gefunden», nie fremde Daten.
"""
from __future__ import annotations

import hashlib
import io
import uuid
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app import scanner
from app.core.config import settings
from app.core.storage import MAIN, InvalidObjectKey, ObjectNotFound, get_object_store, validate_key
from app.models import DocumentAsset
from app.services.file_service import MAX_UPLOAD_BYTES

ASSET_DIR = "document_assets"
IMAGE_TYPES = {"PNG": ("image/png", ".png"), "JPEG": ("image/jpeg", ".jpg"), "WEBP": ("image/webp", ".webp")}
FONT_SUFFIXES = {".ttf": "font/ttf", ".otf": "font/otf"}
MAX_IMAGE_PIXELS = 6000
IMAGE_CATEGORIES = ("logo", "letterhead", "background", "watermark", "graphic", "image")


class AssetValidationError(ValueError):
    """Kuratierter Fehler (Detail ist ein Text-Schlüssel aus documentPdf ``apiError.*``)."""


def list_assets(db: Session, tenant_id: int, *, kind: str | None = None) -> list[DocumentAsset]:
    statement = select(DocumentAsset).where(DocumentAsset.tenant_id == tenant_id)
    if kind:
        statement = statement.where(DocumentAsset.kind == kind)
    return list(db.scalars(statement.order_by(DocumentAsset.created_at.desc(), DocumentAsset.id.desc())))


def get_asset(db: Session, tenant_id: int, public_id: uuid.UUID | str | None) -> DocumentAsset | None:
    if public_id is None:
        return None
    try:
        value = public_id if isinstance(public_id, uuid.UUID) else uuid.UUID(str(public_id))
    except ValueError:
        return None
    return db.scalar(select(DocumentAsset).where(DocumentAsset.tenant_id == tenant_id, DocumentAsset.public_id == value))


def assets_by_ids(db: Session, tenant_id: int, ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, DocumentAsset]:
    wanted = {value for value in ids if value is not None}
    if not wanted:
        return {}
    rows = db.scalars(select(DocumentAsset).where(DocumentAsset.tenant_id == tenant_id, DocumentAsset.public_id.in_(wanted)))
    return {row.public_id: row for row in rows}


def read_asset(asset: DocumentAsset) -> bytes | None:
    """Inhalt aus dem Objektspeicher (Namespace «main», Key = storage_path); fehlt das Objekt
    oder ist der Key ungültig, gilt das Asset als fehlend."""
    try:
        return get_object_store().get_bytes(MAIN, asset.storage_path)
    except (ObjectNotFound, InvalidObjectKey):
        return None


def font_family_of(content: bytes) -> str:
    from fontTools.ttLib import TTFont

    font = TTFont(io.BytesIO(content), lazy=True, fontNumber=0)
    try:
        name_table = font["name"]
        family = name_table.getDebugName(16) or name_table.getDebugName(1)
        if not family or not font.getBestCmap():
            raise AssetValidationError("apiError.invalidFont")
        return str(family).strip()
    finally:
        font.close()


def _validated_image(content: bytes) -> tuple[str, str, int, int]:
    from PIL import Image

    try:
        with Image.open(io.BytesIO(content)) as image:
            image.verify()
        with Image.open(io.BytesIO(content)) as image:
            if image.format not in IMAGE_TYPES or max(image.size) > MAX_IMAGE_PIXELS:
                raise AssetValidationError("apiError.invalidImage")
            mime, suffix = IMAGE_TYPES[image.format]
            return mime, suffix, image.width, image.height
    except AssetValidationError:
        raise
    except Exception as exc:  # noqa: BLE001 - jede Pillow-Ausnahme heisst «kein gültiges Bild»
        raise AssetValidationError("apiError.invalidImage") from exc


async def create_asset(  # loop-ok: nur im Worker-Thread (core/offload.run_coroutine_in_thread bzw. Galerie-Ingest)
    db: Session,
    tenant_id: int,
    *,
    kind: str,
    filename: str,
    content: bytes,
    user_id: int | None,
    category: str | None = None,
    name: str | None = None,
) -> DocumentAsset:
    if kind not in ("image", "font"):
        raise AssetValidationError("apiError.invalidKind")
    if len(content) > MAX_UPLOAD_BYTES:
        raise AssetValidationError("apiError.tooLarge")
    font_family = None
    width = height = None
    if kind == "image":
        mime_type, suffix, width, height = _validated_image(content)
        category = category if category in IMAGE_CATEGORIES else "image"
    else:
        suffix = Path(filename or "").suffix.lower()
        if suffix not in FONT_SUFFIXES:
            raise AssetValidationError("apiError.invalidFont")
        mime_type = FONT_SUFFIXES[suffix]
        try:
            font_family = font_family_of(content)
        except AssetValidationError:
            raise
        except Exception as exc:  # noqa: BLE001 - jede fontTools-Ausnahme heisst «keine gültige Schrift»
            raise AssetValidationError("apiError.invalidFont") from exc
        category = "font"
    status = (await scanner.scan_many([content], host=settings.clamav_host, port=settings.clamav_port))[0]
    if status == "infected":
        raise AssetValidationError("apiError.infected")
    if status == "error":
        raise AssetValidationError("apiError.scanFailed")
    key = validate_key(f"{ASSET_DIR}/tenant-{tenant_id}/{uuid.uuid4().hex}{suffix}")
    store = get_object_store()
    store.put_bytes(db, MAIN, key, content, content_type=mime_type)
    asset = DocumentAsset(
        tenant_id=tenant_id,
        kind=kind,
        category=category,
        name=(name or "").strip()[:120] or Path(filename or "").stem or kind,
        original_name=filename,
        mime_type=mime_type,
        storage_path=key,
        file_size_bytes=len(content),
        checksum_sha256=hashlib.sha256(content).hexdigest(),
        width_px=width,
        height_px=height,
        font_family=font_family,
        created_by=user_id,
    )
    db.add(asset)
    try:
        db.flush()
    except Exception:
        # Registrierung rollt mit der Transaktion zurück; das Objekt selbst entfernen.
        store.discard_unregistered(MAIN, key)
        raise
    return asset


def asset_references(db: Session, asset: DocumentAsset) -> list[dict[str, Any]]:
    """Wo ein Asset verwendet wird (Brand-Profile, Vorlagen-Entwürfe und -Veröffentlichungen,
    Komponenten). Ein verwendetes Asset kann nicht gelöscht werden: veröffentlichte Revisionen
    und historische Exporte müssen reproduzierbar bleiben."""
    from app.models import DocumentBrand, DocumentBrandRevision, DocumentComponent, DocumentTemplate, DocumentTemplateRevision

    needle = str(asset.public_id)
    references: list[dict[str, Any]] = []
    brand_rows = db.execute(
        select(DocumentBrand.public_id, DocumentBrand.name)
        .join(DocumentBrandRevision, DocumentBrandRevision.brand_id == DocumentBrand.id)
        .where(DocumentBrand.tenant_id == asset.tenant_id, DocumentBrandRevision.tokens_json.cast(_text_type()).contains(needle))
        .distinct()
    ).all()
    references += [{"kind": "brand", "id": str(row.public_id), "name": row.name} for row in brand_rows]
    template_rows = db.execute(
        select(DocumentTemplate.public_id, DocumentTemplate.name)
        .join(DocumentTemplateRevision, DocumentTemplateRevision.template_id == DocumentTemplate.id)
        .where(DocumentTemplate.tenant_id == asset.tenant_id, DocumentTemplateRevision.content_json.cast(_text_type()).contains(needle))
        .distinct()
    ).all()
    references += [{"kind": "template", "id": str(row.public_id), "name": row.name} for row in template_rows]
    component_rows = db.execute(
        select(DocumentComponent.public_id, DocumentComponent.name).where(
            DocumentComponent.tenant_id == asset.tenant_id, DocumentComponent.node_json.cast(_text_type()).contains(needle)
        )
    ).all()
    references += [{"kind": "component", "id": str(row.public_id), "name": row.name} for row in component_rows]
    return references


def _text_type():
    from sqlalchemy import Text

    return Text()


def delete_asset(db: Session, asset: DocumentAsset) -> None:
    if asset_references(db, asset):
        raise AssetValidationError("apiError.assetInUse")
    storage_path = asset.storage_path
    db.delete(asset)
    db.flush()
    # Tombstone in derselben Transaktion; physisch löscht der Job storage_purge nach dem Commit.
    try:
        get_object_store().delete(db, MAIN, storage_path)
    except InvalidObjectKey:
        pass


def rename_asset(asset: DocumentAsset, *, name: str | None = None, category: str | None = None) -> DocumentAsset:
    if name is not None and name.strip():
        asset.name = name.strip()[:120]
    if category is not None and asset.kind == "image" and category in IMAGE_CATEGORIES:
        asset.category = category
    return asset


def asset_usage(db: Session, tenant_id: int, assets: list[DocumentAsset], *, include_drafts: bool = True) -> dict[int, list[str]]:
    """Asset → Namen der aktiven Brand-Profile und Vorlagen, die es im aktuellen Stand nutzen
    (gültige Brand-Revision, veröffentlichte Revision bzw. Entwurf, Komponenten). Für die
    Anzeige «In …»; ob ein Asset gelöscht werden darf, prüft ``asset_references`` über alle
    Revisionen. ``include_drafts=False``: nur veröffentlichte Stände (wer keine Entwürfe sieht)."""
    from app.models import DocumentBrand, DocumentBrandRevision, DocumentComponent, DocumentTemplate, DocumentTemplateRevision

    if not assets:
        return {}
    text_type = _text_type()
    sources: list[tuple[str, str]] = []
    sources += db.execute(
        select(DocumentBrand.name, DocumentBrandRevision.tokens_json.cast(text_type))
        .join(DocumentBrandRevision, (DocumentBrandRevision.brand_id == DocumentBrand.id) & (DocumentBrandRevision.revision == DocumentBrand.current_revision))
        .where(DocumentBrand.tenant_id == tenant_id, DocumentBrand.archived_at.is_(None))
    ).all()
    sources += db.execute(
        select(DocumentTemplate.name, DocumentTemplateRevision.content_json.cast(text_type))
        .join(DocumentTemplateRevision, DocumentTemplateRevision.template_id == DocumentTemplate.id)
        .where(
            DocumentTemplate.tenant_id == tenant_id,
            DocumentTemplate.status == "active",
            or_(DocumentTemplateRevision.id == DocumentTemplate.published_revision_id, *([DocumentTemplateRevision.status == "draft"] if include_drafts else [])),
        )
    ).all()
    sources += db.execute(
        select(DocumentComponent.name, DocumentComponent.node_json.cast(text_type)).where(DocumentComponent.tenant_id == tenant_id)
    ).all()
    usage: dict[int, list[str]] = {}
    for asset in assets:
        needle = str(asset.public_id)
        names = [name for name, payload in sources if payload and needle in payload]
        usage[asset.id] = list(dict.fromkeys(names))
    return usage


def duplicate_groups(assets: list[DocumentAsset]) -> dict[int, tuple[int, str]]:
    """Asset → (Anzahl gleicher Dateien, Gruppenschlüssel) für Dateien mit gleicher Prüfsumme und
    Art im Verein, nur wenn es mehr als eine gibt."""
    groups: dict[tuple[str, str], list[DocumentAsset]] = {}
    for asset in assets:
        if asset.checksum_sha256:
            groups.setdefault((asset.kind, asset.checksum_sha256), []).append(asset)
    return {
        asset.id: (len(items), f"{kind}:{checksum[:16]}")
        for (kind, checksum), items in groups.items()
        if len(items) > 1
        for asset in items
    }


def merge_duplicates(db: Session, tenant_id: int) -> int:
    """Gleiche Dateien zusammenführen: je Gruppe bleibt die verwendete bzw. älteste Datei, nicht
    verwendete Kopien werden gelöscht. Verwendete Kopien bleiben (Revisionen und Exporte müssen
    reproduzierbar bleiben). Gibt die Anzahl entfernter Dateien zurück. Kein Commit."""
    assets = list_assets(db, tenant_id)
    groups: dict[tuple[str, str], list[DocumentAsset]] = {}
    for asset in assets:
        if asset.checksum_sha256:
            groups.setdefault((asset.kind, asset.checksum_sha256), []).append(asset)
    removed = 0
    for items in groups.values():
        if len(items) < 2:
            continue
        referenced = {asset.id for asset in items if asset_references(db, asset)}
        ordered = sorted(items, key=lambda asset: (asset.id not in referenced, asset.created_at, asset.id))
        for asset in ordered[1:]:
            if asset.id in referenced:
                continue
            delete_asset(db, asset)
            removed += 1
    return removed
