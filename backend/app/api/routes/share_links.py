"""Verwaltung von Freigabe-Links (authentifiziert, mandantenweit) - die oeffentliche
Download-Seite selbst liegt in public_share.py."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.permissions import P
from app.core.features_generated import F
from app.core.security import CurrentUser, get_current_user, require_any_permission, require_feature, require_permission
from app.models.entities import PhotoAlbum, PhotoAlbumItem, ShareLink, ShareLinkFile, StoredFile
from app.schemas.files import ShareLinkCreate, ShareLinkRead
from app.services.access_service import AccessService, protocol_file_clause
from app.services import context_visibility_service, photo_album_share_service, share_link_service
from app.services.audit_service import AuditService
from app.services.file_service import BLOCKED_SCAN_STATUSES, FileService
from app.services.photo_metadata_privacy import MetadataPolicy

router = APIRouter()
service = FileService()
audit = AuditService()
access_service = AccessService()


def _audit(db: Session, user: CurrentUser, action: str, link: ShareLink, **details) -> None:
    """Öffentliche Links nachvollziehbar (Plan «Berechtigungen», Phase 8). share_link.id ist eine
    UUID - steht in den Details, entity_id bleibt leer."""
    audit.log(db, action=action, actor=user, entity_type="share_link",
              details={"kind": "share_album" if link.album_id is not None else "share_files", "link_id": str(link.id), "name": link.name, **details})


def _read(link: ShareLink, *, album_name: str | None, file_count: int, created_by_name: str | None) -> ShareLinkRead:
    return ShareLinkRead(
        id=link.id,
        name=link.name,
        url=f"/share/{link.token}",
        album_name=album_name,
        file_count=file_count,
        created_at=link.created_at,
        created_by_name=created_by_name,
        expires_at=link.expires_at,
        revoked_at=link.revoked_at,
        status=share_link_service.status_for(link),
        share_location=link.share_location,
        share_capture_date=link.share_capture_date,
        share_camera=link.share_camera,
    )


def _is_creator(user: CurrentUser, link: ShareLink) -> bool:
    """Eigener Link: die Leseprüfung je Datei entfällt (der Ersteller kennt die URL ohnehin). Die
    Trennung nach Dateiart (photos.read/files.read, share_link_service.may_see) gilt aber auch für
    ihn - wer files.read verliert, sieht keine Dokument-Links mehr (Security-Review Phase 3)."""
    return link.created_by is not None and link.created_by == user.user_id


def _may_read_link_files(db: Session, user: CurrentUser, link: ShareLink, readable: dict[int, bool] | None = None) -> bool:
    """Datei-Link: jede Datei darin muss das Konto selbst lesen dürfen wie im Einzelabruf
    (Protokollbilder/-exporte nur aus lesbaren Protokollen, Nachtlauf 2026-11-22) - die Token-URL
    öffnet sie ohne Anmeldung. Album-Links folgen dem Album (bewusste Weitergabe, add_album_items).
    Den eigenen Link sieht und widerruft der Ersteller immer (er kennt die URL ohnehin), auch wenn
    er das Leserecht inzwischen verloren hat. ``readable``: Zwischenspeicher je Datei für Listen."""
    if link.album_id is not None or _is_creator(user, link):
        return True
    cache = readable if readable is not None else {}
    internal_ids = db.scalars(
        select(StoredFile.id)
        .join(ShareLinkFile, ShareLinkFile.file_id == StoredFile.public_id)
        .where(ShareLinkFile.share_link_id == link.id, StoredFile.tenant_id == link.tenant_id)
    ).all()
    for internal_id in internal_ids:
        if internal_id not in cache:
            try:
                access_service.ensure_can_read_stored_file(db, user, internal_id, allow_context_grant=False)
                cache[internal_id] = True
            except HTTPException:
                cache[internal_id] = False
        if not cache[internal_id]:
            return False
    return True


def _album_holds_unreadable_photos(db: Session, user: CurrentUser, album: PhotoAlbum) -> bool:
    """Liegen im Album Fotos des eigenen Vereins, die das Konto selbst nicht öffnen dürfte (1.5.2,
    Verdacht 1)? Entwurfsbilder ohne Leserecht auf den Entwurf, Abgabe-Fotos ausserhalb der
    Reichweite «nur zugewiesene». Der Album-Link gäbe sie ohne Anmeldung weiter. Eine Abfrage
    für das ganze Album (nicht je Foto); Fotos eines Partners folgen dessen Album-Freigabe.
    Gezählt werden alle Einträge, auch noch nicht freigegebene - sie erscheinen nach der Freigabe."""
    conditions = []
    scope = access_service.protocol_read_scope(db, user)
    if scope is not None:
        conditions.append(~protocol_file_clause(StoredFile.id, scope))
    readable_assignments = context_visibility_service.readable_assignment_ids(db, user)
    if readable_assignments is not None:
        conditions.append(~context_visibility_service.abgabe_scope_clause(StoredFile.id, readable_assignments))
    if not conditions:
        return False
    hidden = db.scalar(
        select(func.count())
        .select_from(PhotoAlbumItem)
        .join(StoredFile, StoredFile.public_id == PhotoAlbumItem.file_id)
        .where(PhotoAlbumItem.album_id == album.id, StoredFile.tenant_id == user.current_tenant_id, or_(*conditions))
    )
    return bool(hidden)


MAX_LINK_FILES = 200


@router.post("/share-links", response_model=ShareLinkRead, status_code=201)
def create_share_link(payload: ShareLinkCreate, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    # Öffentlich teilen (Plan «Berechtigungen», Phase 3) - und nur, was man selbst sehen darf
    require_permission(user, P.SHARING_PUBLIC)
    require_any_permission(user, P.FILES_READ, P.PHOTOS_READ)
    require_feature(user, F.PHOTO_SHARING, write=True)
    if user.current_tenant_id is None:
        raise HTTPException(status_code=400, detail="No active tenant")
    name = (payload.name or "").strip()
    if len(name) > 120:
        raise HTTPException(status_code=422, detail="Name darf höchstens 120 Zeichen lang sein")
    has_files = bool(payload.file_ids)
    has_album = payload.album_id is not None
    if has_files == has_album:
        raise HTTPException(status_code=422, detail="Bitte entweder Dateien oder ein Album auswählen (genau eines).")
    metadata = MetadataPolicy(location=payload.share_location, capture_date=payload.share_capture_date, camera=payload.share_camera)

    if has_album:
        require_permission(user, P.PHOTOS_READ)
        album = photo_album_share_service.get_accessible_album(db, payload.album_id, user.current_tenant_id)
        if album is None:
            raise HTTPException(status_code=404, detail="Album nicht gefunden")
        if album.submission_assignment_id is not None and album.tenant_id == user.current_tenant_id:
            # Abgabe-Album eines Auftrags ausserhalb der eigenen Reichweite: wie in der Albenliste
            # gar nicht sichtbar (list_albums_with_stats), also wie unbekannt (1.5.2, Verdacht 1)
            readable_assignments = context_visibility_service.readable_assignment_ids(db, user)
            if readable_assignments is not None and album.submission_assignment_id not in readable_assignments:
                raise HTTPException(status_code=404, detail="Album nicht gefunden")
        if _album_holds_unreadable_photos(db, user, album):
            # Nur Rollenrechte wie beim Datei-Link: der Link zeigt das ganze Album ohne Anmeldung.
            raise HTTPException(
                status_code=403,
                detail="Das Album enthält Fotos, die du selbst nicht öffnen darfst. Teilen kann es nur, wer alle Fotos sehen darf.",
            )
        if not photo_album_share_service.may_create_public_link(db, album, user.current_tenant_id):
            # SEC-002: der Besitzer hat öffentliche Links für diesen Partner abgeschaltet.
            raise HTTPException(status_code=403, detail="Der Besitzer dieses Albums erlaubt keine öffentlichen Links.")
        link = share_link_service.create_for_album(
            db, tenant_id=user.current_tenant_id, name=name or album.name[:120], album=album, expires_at=payload.expires_at, created_by=user.user_id, metadata=metadata
        )
        _audit(db, user, "public_link.created", link, expires_at=link.expires_at.isoformat() if link.expires_at else None)
        return _read(link, album_name=album.name, file_count=len(share_link_service.file_ids_for_link(db, link)), created_by_name=user.display_name)

    ids = list(dict.fromkeys(payload.file_ids or []))
    # Obergrenze vor der Suche prüfen: sonst schnitt limit=200 ab und die Meldung lautete
    # fälschlich «nicht gefunden» (Audit Dateien/Fotos).
    if len(ids) > MAX_LINK_FILES:
        raise HTTPException(status_code=422, detail=f"Ein Link kann höchstens {MAX_LINK_FILES} Dateien enthalten.")
    found = service.list_tenant_files(
        db, user.current_tenant_id, file_ids=ids, limit=MAX_LINK_FILES,
        readable_assignment_ids=context_visibility_service.readable_assignment_ids(db, user),
    )
    if {item.id for item in found} != set(ids):
        raise HTTPException(status_code=404, detail="Mindestens eine Datei wurde nicht gefunden")
    # Je Datei nur, was man selbst sehen darf: Bilder mit photos.read, Dokumente mit files.read
    if any(item.mime_type and item.mime_type.startswith("image/") for item in found):
        require_permission(user, P.PHOTOS_READ)
    if any(not (item.mime_type and item.mime_type.startswith("image/")) for item in found):
        require_permission(user, P.FILES_READ)
    # Leserecht je Datei wie im Einzelabruf (Protokollbilder/-exporte nur aus lesbaren Protokollen,
    # Nachtlauf 2026-11-22): der Link gibt die Datei ohne Anmeldung weiter, also nur Rollenrechte
    # wie beim Album (add_album_items). Nicht lesbare wie unbekannte melden (kein Existenz-Orakel).
    internal_ids = db.scalars(
        select(StoredFile.id).where(StoredFile.tenant_id == user.current_tenant_id, StoredFile.public_id.in_(ids))
    ).all()
    for internal_id in internal_ids:
        try:
            access_service.ensure_can_read_stored_file(db, user, internal_id, allow_context_grant=False)
        except HTTPException:
            raise HTTPException(status_code=404, detail="Mindestens eine Datei wurde nicht gefunden") from None
    if any(item.scan_status in BLOCKED_SCAN_STATUSES for item in found):
        # Gesperrte Dateien zeigt die öffentliche Seite nie - nicht erst aufnehmen und mitzählen.
        raise HTTPException(status_code=422, detail="Gesperrte Dateien (Virenprüfung) können nicht geteilt werden.")
    if not name:
        # Ohne Namen: eine Datei heisst wie sie selbst, mehrere werden gezählt
        name = (found[0].original_name or "Datei")[:120] if len(found) == 1 else f"{len(found)} Dateien"
    try:
        link = share_link_service.create_for_files(
            db, tenant_id=user.current_tenant_id, name=name, file_ids=ids, expires_at=payload.expires_at, created_by=user.user_id, metadata=metadata
        )
    except share_link_service.ShareLinkError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    _audit(db, user, "public_link.created", link, file_count=len(ids), expires_at=link.expires_at.isoformat() if link.expires_at else None)
    return _read(link, album_name=None, file_count=len(ids), created_by_name=user.display_name)


@router.get("/share-links", response_model=list[ShareLinkRead])
def list_share_links(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    require_permission(user, P.SHARING_PUBLIC)
    if user.current_tenant_id is None:
        raise HTTPException(status_code=400, detail="No active tenant")
    rows = share_link_service.list_for_tenant(db, user.current_tenant_id)
    kinds = share_link_service.content_kinds(db, [row.link for row in rows])
    # Nur Links, deren Inhalt man selbst sehen darf (die Token-URL öffnet ihn ohne Anmeldung);
    # Leseprüfung je Datei nur einmal, auch wenn sie in mehreren Links steckt
    readable: dict[int, bool] = {}
    return [
        _read(row.link, album_name=row.album_name, file_count=row.file_count, created_by_name=row.created_by_name)
        for row in rows
        if share_link_service.may_see(user.can, kinds.get(row.link.id, set())) and _may_read_link_files(db, user, row.link, readable)
    ]


@router.delete("/share-links/{share_link_id}", status_code=204)
def revoke_share_link(share_link_id: uuid.UUID, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    require_permission(user, P.SHARING_PUBLIC)
    if user.current_tenant_id is None:
        raise HTTPException(status_code=400, detail="No active tenant")
    link = db.get(ShareLink, share_link_id)
    if (
        link is None
        or not share_link_service.can_manage(db, link, user.current_tenant_id)
        or not share_link_service.may_see(user.can, share_link_service.content_kinds(db, [link]).get(link.id, set()))
        or not _may_read_link_files(db, user, link)
    ):
        raise HTTPException(status_code=404, detail="Link nicht gefunden")
    share_link_service.revoke(db, link)
    _audit(db, user, "public_link.revoked", link)
