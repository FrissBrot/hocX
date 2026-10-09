import uuid
from datetime import date

from pydantic import BaseModel, Field


class PhotoPositionIn(BaseModel):
    file_id: uuid.UUID
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    taken_on: date


class PhotoMatchRequest(BaseModel):
    photos: list[PhotoPositionIn] = Field(default_factory=list, max_length=20000)


class TourRef(BaseModel):
    id: uuid.UUID
    title: str


class PhotoMatch(BaseModel):
    file_id: uuid.UUID
    tour_id: uuid.UUID


class PhotoMatchResponse(BaseModel):
    tours: list[TourRef]
    matches: list[PhotoMatch]
