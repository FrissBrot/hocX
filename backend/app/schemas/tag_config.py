from __future__ import annotations

import re

from pydantic import BaseModel, Field, RootModel, field_validator

_HEX_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")
_MAX_TAG_NAME_LENGTH = 200
_MAX_TAGS_PER_PATCH = 500


class TagConfigEntry(BaseModel):
    model_config = {"extra": "forbid"}

    color: str | None = Field(default=None)

    @field_validator("color")
    @classmethod
    def _validate_color(cls, value: str | None) -> str | None:
        if value is not None and not _HEX_COLOR.match(value):
            raise ValueError("color must be a #RRGGBB hex string")
        return value


class TagConfigPatch(RootModel[dict[str, TagConfigEntry]]):
    """PATCH /tag-config payload: a partial map of tag name -> {color}. An empty entry
    ({}) is how the frontend clears a tag's config (e.g. when renaming - see
    frontend/lib/hooks/use-tag-config.ts renameTag)."""

    @field_validator("root")
    @classmethod
    def _validate_shape(cls, value: dict[str, TagConfigEntry]) -> dict[str, TagConfigEntry]:
        if len(value) > _MAX_TAGS_PER_PATCH:
            raise ValueError(f"Cannot patch more than {_MAX_TAGS_PER_PATCH} tags at once")
        for tag_name in value:
            if not tag_name or len(tag_name) > _MAX_TAG_NAME_LENGTH:
                raise ValueError(f"Tag name must be 1-{_MAX_TAG_NAME_LENGTH} characters")
        return value
