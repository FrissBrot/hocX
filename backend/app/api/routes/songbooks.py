from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import CurrentUser, get_current_user, require_writer
from app.schemas.songbook import (
    LyricsSearchResult,
    SongCreate,
    SongRead,
    SongbookCreate,
    SongbookRead,
    SongbookSummary,
    SongbookUpdate,
    SongUpdate,
)
from app.services.songbook_service import LyricsProviderError, SongbookService

router = APIRouter()
service = SongbookService()


def _summary(book, song_count: int | None = None) -> SongbookSummary:
    return SongbookSummary(
        id=book.id,
        tenant_id=book.tenant_id,
        title=book.title,
        description=book.description,
        created_at=book.created_at,
        updated_at=book.updated_at,
        song_count=len(book.songs) if song_count is None else song_count,
    )


@router.get("/songbooks", response_model=list[SongbookSummary])
def list_songbooks(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    require_writer(user)
    return [_summary(book, count) for book, count in service.list_songbooks(db, user.current_tenant_id)]


@router.post("/songbooks", response_model=SongbookSummary, status_code=status.HTTP_201_CREATED)
def create_songbook(
    payload: SongbookCreate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    try:
        return _summary(service.create_songbook(db, payload, user.current_tenant_id, user.user_id), 0)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Liederbuch konnte nicht erstellt werden") from exc


@router.get("/songbooks/{songbook_id}", response_model=SongbookRead)
def get_songbook(
    songbook_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    book = service.get_songbook(db, songbook_id, user.current_tenant_id)
    if book is None:
        raise HTTPException(status_code=404, detail="Liederbuch nicht gefunden")
    return SongbookRead(**_summary(book).model_dump(), songs=book.songs)


@router.patch("/songbooks/{songbook_id}", response_model=SongbookSummary)
def patch_songbook(
    songbook_id: int,
    payload: SongbookUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    book = service.get_songbook(db, songbook_id, user.current_tenant_id)
    if book is None:
        raise HTTPException(status_code=404, detail="Liederbuch nicht gefunden")
    try:
        return _summary(service.update_songbook(db, book, payload))
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Liederbuch konnte nicht gespeichert werden") from exc


@router.delete("/songbooks/{songbook_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_songbook(
    songbook_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    book = service.get_songbook(db, songbook_id, user.current_tenant_id)
    if book is None:
        raise HTTPException(status_code=404, detail="Liederbuch nicht gefunden")
    service.delete_songbook(db, book)


@router.get("/lyrics/search", response_model=list[LyricsSearchResult])
def search_lyrics(
    q: str = Query(min_length=2, max_length=200),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    try:
        return service.search_lyrics(q.strip())
    except LyricsProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/songbooks/{songbook_id}/songs", response_model=SongRead, status_code=status.HTTP_201_CREATED)
def add_song(
    songbook_id: int,
    payload: SongCreate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    book = service.get_songbook(db, songbook_id, user.current_tenant_id)
    if book is None:
        raise HTTPException(status_code=404, detail="Liederbuch nicht gefunden")
    try:
        return service.add_song(db, book, payload)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Lied konnte nicht hinzugefuegt werden") from exc


@router.patch("/songbook-songs/{song_id}", response_model=SongRead)
def patch_song(
    song_id: int,
    payload: SongUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    song = service.get_song(db, song_id, user.current_tenant_id)
    if song is None:
        raise HTTPException(status_code=404, detail="Lied nicht gefunden")
    return service.update_song(db, song, payload)


@router.delete("/songbook-songs/{song_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_song(
    song_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    song = service.get_song(db, song_id, user.current_tenant_id)
    if song is None:
        raise HTTPException(status_code=404, detail="Lied nicht gefunden")
    service.delete_song(db, song)
