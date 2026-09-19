from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

StorageCategoryKey = Literal["photos", "files", "protocols", "other"]


class StorageCategoryUsage(BaseModel):
    key: StorageCategoryKey
    label: str
    bytes: int


class StorageUsageRead(BaseModel):
    total_bytes: int
    quota_bytes: int | None
    categories: list[StorageCategoryUsage]
