"""Antwortschemas, die das hocX-Backend fuer den Wanderplaner selbst erzeugt. Alle anderen
Wanderplaner-Schemas liegen im Service (wanderplaner-backend/app/schemas/hiking_tour.py) -
hocX reicht deren Antworten unveraendert durch."""

import uuid
from datetime import datetime

from pydantic import BaseModel


class PrintResponse(BaseModel):
    generated_file_id: uuid.UUID
    content_url: str
    sheet_count: int
    created_at: datetime
