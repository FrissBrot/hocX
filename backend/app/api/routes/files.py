from typing import Literal

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from fastapi import APIRouter, Depends, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from app.core.db import get_db
from app.core.config import settings
from app.core.security import CurrentUser, get_current_user, require_reader, require_writer
from app.models import ProtocolElementBlock, ProtocolImage
from app.schemas.files import FileOverviewItem, FileOverviewSource, StoredFileMetadata, StoredFileTagsUpdate
from app.schemas.protocol import ProtocolImageRead
from app.services.access_service import AccessService
from app.services.file_service import FileService, _safe_storage_path

router = APIRouter()
service = FileService()
access_service = AccessService()


@router.get("/files", response_model=list[FileOverviewItem])
def list_files(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=60, ge=1, le=200),
    source: FileOverviewSource | None = Query(default=None),
    only_images: bool = Query(default=False),
    search: str | None = Query(default=None),
    tags: list[str] | None = Query(default=None),
    sort_by: Literal["created_at", "original_name", "file_size_bytes"] = Query(default="created_at"),
    sort_dir: Literal["asc", "desc"] = Query(default="desc"),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Alle vom Mandanten hochgeladenen Dateien (Protokoll-Bilder, Word-Import-Quelldokumente,
    Abgabebox-Uploads) fuer die "Dateien"-Uebersichtsseite. Gleiche Rolle wie "Abgaben"
    (require_writer): dies ist eine mandantenweite Aggregatsicht ueber alle Protokolle
    hinweg, nicht scopebar auf die feingranulare Pro-Protokoll-Leserechte-Pruefung von
    ensure_can_read_stored_file."""
    require_writer(user)
    if user.current_tenant_id is None:
        raise HTTPException(status_code=400, detail="No active tenant")
    return service.list_tenant_files(
        db,
        user.current_tenant_id,
        skip=skip,
        limit=limit,
        source=source,
        only_images=only_images,
        search=search,
        tags=tags,
        sort_by=sort_by,
        sort_dir=sort_dir,
    )


@router.get("/files/tags", response_model=list[str])
def list_file_tags(
    query: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Autocomplete-Quelle fuer den Tag-Filter/-Editor auf der "Dateien"-Seite - jeder Tag,
    der aktuell auf irgendeiner Datei des Mandanten liegt, inklusive der automatischen
    Herkunfts-Tags (siehe FileOverviewItem.origin_tag)."""
    require_writer(user)
    if user.current_tenant_id is None:
        raise HTTPException(status_code=400, detail="No active tenant")
    return service.list_distinct_tags(db, user.current_tenant_id, query=query, limit=limit)


@router.get("/protocol-element-blocks/{protocol_element_block_id}/images", response_model=list[ProtocolImageRead])
def list_images(
    protocol_element_block_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_reader(user)
    access_service.ensure_can_read_protocol_block(db, user, protocol_element_block_id)
    return service.list_protocol_images(db, protocol_element_block_id)


@router.post("/protocol-element-blocks/{protocol_element_block_id}/images", response_model=ProtocolImageRead)
async def upload_image(
    protocol_element_block_id: int,
    file: UploadFile,
    title: str | None = Form(default=None),
    caption: str | None = Form(default=None),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    access_service.ensure_can_read_protocol_block(db, user, protocol_element_block_id)
    protocol_element_block = db.get(ProtocolElementBlock, protocol_element_block_id)
    if protocol_element_block is None:
        raise HTTPException(status_code=404, detail="Protocol element block not found")
    try:
        return await service.save_protocol_image(
            db,
            protocol_element_block=protocol_element_block,
            file=file,
            title=title,
            caption=caption,
            created_by=user.user_id,
        )
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Image could not be uploaded") from exc


@router.delete("/protocol-images/{image_id}", response_model=dict[str, str])
def delete_image(
    image_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    protocol_image = db.get(ProtocolImage, image_id)
    if protocol_image is None:
        raise HTTPException(status_code=404, detail="Image not found")
    access_service.ensure_can_read_protocol_block(db, user, protocol_image.protocol_element_block_id)
    try:
        deleted = service.delete_protocol_image(db, image_id)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Image could not be deleted") from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Image not found")
    return {"message": "Image deleted"}


@router.get("/stored-files/{stored_file_id}/content")
def get_stored_file_content(
    stored_file_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_reader(user)
    access_service.ensure_can_read_stored_file(db, user, stored_file_id)
    stored_file = service.get_stored_file(db, stored_file_id)
    if stored_file is None:
        raise HTTPException(status_code=404, detail="Stored file not found")
    if stored_file.scan_status == "infected":
        raise HTTPException(status_code=403, detail="Datei wurde von der Virenprüfung als infiziert erkannt und ist gesperrt")
    if stored_file.scan_status == "pending":
        raise HTTPException(status_code=425, detail="Datei wird noch auf Schadsoftware geprüft, bitte in Kürze erneut versuchen")
    file_path = _safe_storage_path(settings.storage_root, stored_file.storage_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File missing on filesystem")
    # SECURITY: set nosniff so a browser never MIME-sniffs the content and renders it
    # inline against our wishes, mirroring submission_assignments.get_submission_file_content.
    return FileResponse(
        path=file_path,
        media_type=stored_file.mime_type,
        filename=stored_file.original_name,
        content_disposition_type="inline" if stored_file.mime_type == "application/pdf" else "attachment",
        headers={"X-Content-Type-Options": "nosniff"},
    )


@router.patch("/stored-files/{stored_file_id}/tags", response_model=list[str])
def update_stored_file_tags(
    stored_file_id: int,
    payload: StoredFileTagsUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    access_service.ensure_can_read_stored_file(db, user, stored_file_id)
    stored_file = service.get_stored_file(db, stored_file_id)
    if stored_file is None:
        raise HTTPException(status_code=404, detail="Stored file not found")
    return service.update_stored_file_tags(db, stored_file, payload.tags)


@router.get("/stored-files/{stored_file_id}/metadata", response_model=StoredFileMetadata)
def get_stored_file_metadata(
    stored_file_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_reader(user)
    access_service.ensure_can_read_stored_file(db, user, stored_file_id)
    stored_file = service.get_stored_file(db, stored_file_id)
    if stored_file is None or user.current_tenant_id is None:
        raise HTTPException(status_code=404, detail="Stored file not found")
    metadata = service.get_stored_file_metadata(db, stored_file, settings.storage_root, user.current_tenant_id)
    if metadata is None:
        raise HTTPException(status_code=404, detail="Keine Metadaten verfügbar")
    return metadata


@router.get("/stored-files/{stored_file_id}/thumbnail")
def get_stored_file_thumbnail(
    stored_file_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Small JPEG preview for the "Dateien" grid, so scrolling it stays fluid instead of every
    tile pulling in a full-size original - same access rules as get_stored_file_content."""
    require_reader(user)
    access_service.ensure_can_read_stored_file(db, user, stored_file_id)
    stored_file = service.get_stored_file(db, stored_file_id)
    if stored_file is None:
        raise HTTPException(status_code=404, detail="Stored file not found")
    if stored_file.scan_status == "infected":
        raise HTTPException(status_code=403, detail="Datei wurde von der Virenprüfung als infiziert erkannt und ist gesperrt")
    if stored_file.scan_status == "pending":
        raise HTTPException(status_code=425, detail="Datei wird noch auf Schadsoftware geprüft, bitte in Kürze erneut versuchen")
    thumbnail_path = service.ensure_thumbnail(db, stored_file, settings.storage_root)
    if thumbnail_path is None:
        raise HTTPException(status_code=404, detail="Keine Vorschau verfügbar")
    return FileResponse(
        path=thumbnail_path,
        media_type="image/jpeg",
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=86400"},
    )
