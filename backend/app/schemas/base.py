"""Shared base for *Read schemas backed by a model with a public_id column (see
app/models/entities.py and alembic migrations 0065-0068).

PublicIdModel sources the schema's `id` field from the ORM object's `public_id`
automatically. Subclasses that also expose an internal FK int as a field (e.g.
`template_id` on ProtocolRead) declare `_fk_models`, mapping each such field name to
its target model class; those fields get resolved to the related row's public_id using
the same DB session the source ORM object is already attached to
(sqlalchemy.orm.object_session) - verified against a live FastAPI/uvicorn request cycle,
including the common `return some_orm_object` pattern under `response_model=...Read`
that most routers already use (no context-passing or per-router changes needed).

Direct construction (`SomeRead(id=..., ...)`, used by tests and by schemas nesting
another schema manually) is unaffected - the before-validator only fires for an object
that actually has a `public_id` attribute, i.e. a real ORM row.

FK resolution is one query per *distinct* internal id per request (SQLAlchemy's Session
identity map dedupes repeats), not literally one query per list row - acceptable for
this project's scale. If a specific list endpoint's FK fan-out ever becomes a hot spot,
batch-prefetch with app.services.public_id_service.resolve_public_ids() there instead of
changing this base class.

`_fk_list_models` is the same idea for a field holding a JSONB array of internal ids
(e.g. Event.organizer_ids) - each id in the list is translated, via one batched query
per field (public_id_service.resolve_public_ids), not one query per list element.
"""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, model_validator
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import object_session

from app.services import public_id_service


class PublicIdModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    _fk_models: ClassVar[dict[str, type]] = {}
    _fk_list_models: ClassVar[dict[str, type]] = {}

    @model_validator(mode="before")
    @classmethod
    def _translate_public_ids(cls, data: Any) -> Any:
        if not hasattr(data, "public_id"):
            return data
        values = {column.key: getattr(data, column.key) for column in sa_inspect(data).mapper.columns}
        values["id"] = values.pop("public_id")
        db = object_session(data) if (cls._fk_models or cls._fk_list_models) else None
        for field, model in cls._fk_models.items():
            internal_id = values.get(field)
            values[field] = public_id_service.resolve_public_id(db, model, internal_id) if internal_id is not None else None
        for field, model in cls._fk_list_models.items():
            internal_ids = values.get(field)
            if not internal_ids:
                continue
            mapping = public_id_service.resolve_public_ids(db, model, internal_ids)
            values[field] = [mapping[i] for i in internal_ids if i in mapping]
        return values
