"""Vollständiges Löschen bzw. Übernehmen gespeicherter Dateien (Datenschutz-Audit PRIV-003/004/016).

Eine Datei (``stored_file``) hängt an mehreren Stellen, die keinen gemeinsamen Fremdschlüssel haben:
Objekt im Objektspeicher, Vorschaubild im lokalen thumbnail_root, Dokumente samt erzeugter Dateien
(PDF, Text), Album-Einträge (``photo_album_item.file_id`` ohne FK), Freigabelink-Einträge
(``share_link_file.file_id`` ohne FK). Bisher räumte jeder Löschpfad davon nur einen Teil ab.

``FileEraser`` bündelt das:

- ``erase`` löscht eine Datei überall. Der Aufrufer committet; Vorschaubilder werden erst danach
  mit ``unlink_thumbnails`` entfernt (ein Rollback soll keine Vorschau ohne Datei hinterlassen).
- ``erase_if_unreferenced`` löscht nur Dateien, auf die nichts anderes mehr zeigt (z. B. ein
  Protokollbild, das auch in einem anderen Protokoll steckt).
- ``keep_in_gallery`` übernimmt eine Datei, deren Zusammenhang gelöscht wird (Protokoll,
  Abgabe), in die Galerie - mit Herkunfts-Tag. Abgabebox-Dateien werden dafür in den
  Haupt-Namespace verschoben, weil der Namespace allein an submission_upload_file hängt.
"""
from __future__ import annotations

import uuid
from collections.abc import Iterable
from pathlib import Path

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.objstore_client import new_object_key
from app.core.storage import ABGABEBOX, MAIN, get_object_store
from app.models.entities import (
    DocumentExport,
    GalleryImage,
    PhotoAlbum,
    PhotoAlbumItem,
    ProtocolImage,
    ProtocolTodoFile,
    ShareLinkFile,
    StoredFile,
    SubmissionUploadFile,
    WordImportDocument,
)
from app.services import document_service

# Zeilen, die eine Datei weiterhin brauchen: solange eine davon existiert, bleibt die Datei.
_REFERENCES = (
    ProtocolImage.stored_file_id,
    GalleryImage.stored_file_id,
    GalleryImage.live_video_stored_file_id,
    WordImportDocument.stored_file_id,
    SubmissionUploadFile.stored_file_id,
    ProtocolTodoFile.stored_file_id,
    DocumentExport.stored_file_id,
)


def is_referenced(db: Session, stored_file_id: int) -> bool:
    for column in _REFERENCES:
        if db.scalar(select(column).where(column == stored_file_id).limit(1)) is not None:
            return True
    return False


def _owned_thumbnail(stored_file: StoredFile) -> Path | None:
    # Nur die eigene Vorschau "<id>.jpg" (Audit MAIN-BE-005): eine übernommene gehört einer anderen Datei.
    if stored_file.thumbnail_path != f"{stored_file.id}.jpg":
        return None
    root = Path(settings.thumbnail_root).resolve()
    path = (root / stored_file.thumbnail_path).resolve()
    return path if path.is_relative_to(root) else None


class FileEraser:
    def __init__(self, file_service=None) -> None:
        self._thumbnails: list[Path] = []
        self._touched_albums: set = set()
        self._file_service = file_service

    def erase(self, db: Session, stored_file: StoredFile, *, namespace: str | None = None, extra_public_ids: Iterable[uuid.UUID] = ()) -> None:
        """Löscht die Datei samt allem, was ohne Fremdschlüssel an ihr hängt. ``extra_public_ids``:
        weitere IDs, unter denen sie in Alben/Links steht (Abgabebox: die public_id der
        Einreichungsdatei). ``namespace`` muss vor dem Löschen der Einreichungszeilen bestimmt werden."""
        if namespace is None:
            from app.services.stored_file_location import namespace_for_stored_file

            namespace = namespace_for_stored_file(db, stored_file)
        from app.services import photo_album_service  # spät: photo_album_service importiert submission_service

        public_ids = [stored_file.public_id, *extra_public_ids]
        document_service.release_original(db, stored_file.id)
        self._touched_albums |= photo_album_service.drop_items_for_files(db, public_ids)
        db.execute(delete(ShareLinkFile).where(ShareLinkFile.file_id.in_(public_ids)))
        thumbnail = _owned_thumbnail(stored_file)
        storage_key = stored_file.storage_path
        from app.services import erasure_journal

        erasure_journal.record(db, "stored_file", stored_file.public_id, tenant_id=stored_file.tenant_id)
        db.delete(stored_file)
        db.flush()
        get_object_store().delete(db, namespace, storage_key)
        if thumbnail is not None:
            self._thumbnails.append(thumbnail)

    def erase_if_unreferenced(self, db: Session, stored_file_ids: Iterable[int], *, namespace: str = MAIN) -> int:
        erased = 0
        for stored_file_id in dict.fromkeys(stored_file_ids):
            stored_file = db.get(StoredFile, stored_file_id)
            if stored_file is None or is_referenced(db, stored_file_id):
                continue
            self.erase(db, stored_file, namespace=namespace)
            erased += 1
        return erased

    def keep_in_gallery(
        self,
        db: Session,
        stored_file: StoredFile,
        *,
        tag: str,
        namespace: str = MAIN,
        extra_public_ids: Iterable[uuid.UUID] = (),
        created_by: int | None = None,
    ) -> None:
        """Übernimmt die Datei in die Galerie (Herkunfts-Tag), bevor ihr Zusammenhang gelöscht wird."""
        if namespace == ABGABEBOX:
            store = get_object_store()
            upload_prefix = Path(settings.upload_root).resolve().relative_to(Path(settings.storage_root).resolve()).as_posix()
            new_key = new_object_key(*[part for part in (upload_prefix, "kept") if part and part != "."], filename=stored_file.original_name)
            old_key = stored_file.storage_path
            with store.local_copy(ABGABEBOX, old_key, work_dir=Path(settings.storage_work_root)) as path:
                store.put_file(db, MAIN, new_key, path, content_type=stored_file.mime_type)
            stored_file.storage_path = new_key
            store.delete(db, ABGABEBOX, old_key)
        tags = list(stored_file.tags or [])
        if tag and tag not in tags:
            tags.append(tag)
        stored_file.tags = tags
        # Album-Einträge unter der Einreichungs-ID auf die Datei umbiegen (die Einreichung verschwindet).
        for public_id in extra_public_ids:
            db.execute(update(PhotoAlbumItem).where(PhotoAlbumItem.file_id == public_id).values(file_id=stored_file.public_id))
        if db.scalar(select(GalleryImage.id).where(GalleryImage.stored_file_id == stored_file.id)) is None:
            db.add(GalleryImage(tenant_id=stored_file.tenant_id, stored_file_id=stored_file.id, created_by=created_by))
        db.flush()

    def after_commit(self, db: Session) -> None:
        """Nach dem Commit: Vorschaubilder entfernen, «beste Bilder» betroffener Alben neu bestimmen."""
        for path in self._thumbnails:
            path.unlink(missing_ok=True)
        self._thumbnails.clear()
        if self._file_service is not None:
            from app.services import photo_album_service

            for album_id in self._touched_albums:
                album = db.get(PhotoAlbum, album_id)
                if album is not None:
                    photo_album_service.recompute_best_of(db, self._file_service, album)
        self._touched_albums.clear()
