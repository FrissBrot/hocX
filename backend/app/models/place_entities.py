"""Foto-Standorte (Migration 0260_photo_places, services/photo_places.py, services/geo_places.py).

geo_place: globale Ortsdaten (GeoNames, swisstopo swissNAMES3D) - kein Mandantendatum, für die
Laufzeitrolle nur lesbar; geschrieben nur über hocx_geo_import_apply.
photo_location: Ort je Foto (tenant_id per Trigger aus stored_file, RLS). GPS-Zeilen schreibt nur
die Datenbank (hocx_photo_location_refresh), manuelle die Anwendung (photo_places.assign).
place_change_batch/_item: Rückgängig für «Ort setzen/entfernen».
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, ForeignKeyConstraint, Integer, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class GeoPlace(Base):
    __tablename__ = "geo_place"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    place_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    name_fold: Mapped[str] = mapped_column(Text, nullable=False)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    country_code: Mapped[str | None] = mapped_column(Text)
    admin1_code: Mapped[str | None] = mapped_column(Text)
    admin1_name: Mapped[str | None] = mapped_column(Text)
    population: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    elevation_m: Mapped[int | None] = mapped_column(Integer)
    importance: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    search_names: Mapped[str] = mapped_column(Text, nullable=False)


class PhotoLocation(Base):
    __tablename__ = "photo_location"

    stored_file_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("stored_file.id", ondelete="CASCADE"), primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    place_key: Mapped[str | None] = mapped_column(Text)
    place_name: Mapped[str | None] = mapped_column(Text)
    place_kind: Mapped[str | None] = mapped_column(Text)
    place_distance_m: Mapped[int | None] = mapped_column(Integer)
    locality_key: Mapped[str | None] = mapped_column(Text)
    locality_name: Mapped[str | None] = mapped_column(Text)
    locality_kind: Mapped[str | None] = mapped_column(Text)
    locality_distance_m: Mapped[int | None] = mapped_column(Integer)
    admin1_code: Mapped[str | None] = mapped_column(Text)
    admin1_name: Mapped[str | None] = mapped_column(Text)
    country_code: Mapped[str | None] = mapped_column(Text)
    search_text: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    geo_generation: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    set_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app_user.id", ondelete="SET NULL"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))


class PlaceChangeBatch(Base):
    __tablename__ = "place_change_batch"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()"))
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False)
    created_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app_user.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    mode: Mapped[str] = mapped_column(Text, nullable=False)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"), default=dict)
    upload_job_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    updated_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), default=0)
    undone_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    undone_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app_user.id", ondelete="SET NULL"))


class PlaceChangeItem(Base):
    __tablename__ = "place_change_item"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "batch_id"], ["place_change_batch.tenant_id", "place_change_batch.id"], ondelete="CASCADE",
            name="fk_place_change_item_batch",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    batch_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False)
    stored_file_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("stored_file.id", ondelete="CASCADE"), nullable=False)
    prev_place_key: Mapped[str | None] = mapped_column(Text)
    new_place_key: Mapped[str | None] = mapped_column(Text)
