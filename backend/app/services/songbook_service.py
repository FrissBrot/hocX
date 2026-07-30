import json
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Songbook, SongbookSong
from app.schemas.songbook import LyricsSearchResult, SongCreate, SongbookCreate, SongbookUpdate, SongUpdate


class LyricsProviderError(RuntimeError):
    pass


class SongbookService:
    lyrics_api_url = "https://lrclib.net/api/search"

    def list_songbooks(self, db: Session, tenant_id: int) -> list[tuple[Songbook, int]]:
        statement = (
            select(Songbook, func.count(SongbookSong.id))
            .outerjoin(SongbookSong)
            .where(Songbook.tenant_id == tenant_id)
            .group_by(Songbook.id)
            .order_by(Songbook.updated_at.desc(), Songbook.id.desc())
        )
        return [(book, int(count)) for book, count in db.execute(statement)]

    def get_songbook(self, db: Session, songbook_id: int, tenant_id: int) -> Songbook | None:
        return db.scalar(select(Songbook).where(Songbook.id == songbook_id, Songbook.tenant_id == tenant_id))

    def create_songbook(
        self, db: Session, payload: SongbookCreate, tenant_id: int, created_by: int | None
    ) -> Songbook:
        book = Songbook(
            tenant_id=tenant_id,
            title=payload.title.strip(),
            description=payload.description.strip() if payload.description else None,
            created_by=created_by,
        )
        db.add(book)
        db.commit()
        db.refresh(book)
        return book

    def update_songbook(self, db: Session, book: Songbook, payload: SongbookUpdate) -> Songbook:
        for key, value in payload.model_dump(exclude_unset=True).items():
            setattr(book, key, value.strip() if isinstance(value, str) else value)
        book.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(book)
        return book

    def delete_songbook(self, db: Session, book: Songbook) -> None:
        db.delete(book)
        db.commit()

    def add_song(self, db: Session, book: Songbook, payload: SongCreate) -> SongbookSong:
        next_index = max((song.sort_index for song in book.songs), default=-1) + 1
        song = SongbookSong(songbook_id=book.id, sort_index=next_index, **payload.model_dump())
        book.updated_at = datetime.now(timezone.utc)
        db.add(song)
        db.commit()
        db.refresh(song)
        return song

    def get_song(self, db: Session, song_id: int, tenant_id: int) -> SongbookSong | None:
        return db.scalar(
            select(SongbookSong)
            .join(Songbook)
            .where(SongbookSong.id == song_id, Songbook.tenant_id == tenant_id)
        )

    def update_song(self, db: Session, song: SongbookSong, payload: SongUpdate) -> SongbookSong:
        for key, value in payload.model_dump(exclude_unset=True).items():
            setattr(song, key, value.strip() if isinstance(value, str) else value)
        book = db.get(Songbook, song.songbook_id)
        if book:
            book.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(song)
        return song

    def delete_song(self, db: Session, song: SongbookSong) -> None:
        book = db.get(Songbook, song.songbook_id)
        db.delete(song)
        if book:
            book.updated_at = datetime.now(timezone.utc)
        db.commit()

    def search_lyrics(self, query: str, limit: int = 10) -> list[LyricsSearchResult]:
        request = Request(
            f"{self.lyrics_api_url}?{urlencode({'q': query})}",
            headers={"User-Agent": "hocX/0.1 (songbook lyrics search)"},
        )
        try:
            with urlopen(request, timeout=8) as response:
                payload = json.load(response)
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise LyricsProviderError("Liedtextsuche ist derzeit nicht erreichbar") from exc

        return [
            LyricsSearchResult(
                source_id=str(item.get("id", "")),
                title=item.get("trackName") or "Unbekannter Titel",
                artist=item.get("artistName") or "Unbekannter Interpret",
                album=item.get("albumName"),
                duration_seconds=round(item["duration"]) if item.get("duration") is not None else None,
                lyrics=item.get("plainLyrics") or "",
                instrumental=bool(item.get("instrumental", False)),
            )
            for item in payload[:limit]
        ]
