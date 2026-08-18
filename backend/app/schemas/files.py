from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

FileOverviewSource = Literal["protocol_image", "word_import", "submission_upload"]


class FileOverviewItem(BaseModel):
    id: int
    original_name: str
    mime_type: str | None
    file_size_bytes: int | None
    created_at: datetime
    source: FileOverviewSource
    is_image: bool
    content_url: str
    thumbnail_url: str | None
    ref_label: str
    ref_date: date | None
    ref_href: str | None
