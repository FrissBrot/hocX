from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

StorageCategoryKey = Literal["protocol_image", "word_import", "submission_upload", "gallery_upload", "export", "other"]


class StorageCategoryUsage(BaseModel):
    key: StorageCategoryKey
    label: str
    bytes: int


class StorageUsageRead(BaseModel):
    total_bytes: int
    quota_bytes: int | None
    categories: list[StorageCategoryUsage]
