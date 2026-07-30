from datetime import datetime

from pydantic import BaseModel, Field


class SongbookCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)


class SongbookUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)


class SongbookSummary(BaseModel):
    id: int
    tenant_id: int
    title: str
    description: str | None
    created_at: datetime
    updated_at: datetime
    song_count: int = 0


class SongRead(BaseModel):
    id: int
    songbook_id: int
    title: str
    artist: str
    album: str | None
    duration_seconds: int | None
    lyrics: str
    source_name: str | None
    source_id: str | None
    sort_index: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SongbookRead(SongbookSummary):
    songs: list[SongRead] = Field(default_factory=list)


class LyricsSearchResult(BaseModel):
    source_id: str
    title: str
    artist: str
    album: str | None = None
    duration_seconds: int | None = None
    lyrics: str = ""
    instrumental: bool = False


class SongCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    artist: str = Field(min_length=1, max_length=300)
    album: str | None = Field(default=None, max_length=300)
    duration_seconds: int | None = Field(default=None, ge=0)
    lyrics: str = ""
    source_name: str | None = Field(default=None, max_length=100)
    source_id: str | None = Field(default=None, max_length=200)


class SongUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    artist: str | None = Field(default=None, min_length=1, max_length=300)
    album: str | None = Field(default=None, max_length=300)
    lyrics: str | None = None
    sort_index: int | None = Field(default=None, ge=0)
