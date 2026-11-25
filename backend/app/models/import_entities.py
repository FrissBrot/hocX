"""Datei-Import (Migration 0230_cloud_import, services/cloud_import).

import_job: ein Import-Vorgang (Quelle ZIP oder Ordner-Upload, Regeln, Status, Lease).
import_item: eine Quelldatei mit Regel-Ergebnis und Ablaufstatus. Beide mit tenant_id + RLS.
Der Detailbericht (import_item) bleibt, solange mindestens eine importierte Datei existiert
(User-Entscheid E-12, Aufräumen in services/cloud_import/worker.py).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, CheckConstraint, Date, DateTime, ForeignKey, ForeignKeyConstraint, Index, Integer, SmallInteger, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

IMPORT_JOB_STATUSES = (
    "draft", "listing", "ready", "queued", "running", "needs_reauth", "cancel_requested", "cancelled", "done", "failed",
)
# Höchstens ein Auftrag je Mandant in diesen Zuständen (Partial Unique Index, E-5; 0281 ergänzt
# listing/needs_reauth)
IMPORT_JOB_ACTIVE_STATUSES = ("draft", "listing", "ready", "queued", "running", "needs_reauth", "cancel_requested")
# Quellen (0281): ZIP/Ordner aus P0, API-Anbieter aus services/cloud_import/providers
IMPORT_SOURCES = ("zip", "folder", "microsoft", "google_drive", "google_photos", "dropbox", "webdav")
IMPORT_PROVIDERS = ("microsoft", "google_drive", "google_photos", "dropbox", "webdav")
IMPORT_CONNECTION_STATUSES = ("active", "needs_reauth")
IMPORT_JOB_TERMINAL_STATUSES = ("cancelled", "done", "failed")
IMPORT_ITEM_STATUSES = ("listed", "queued", "staged", "imported", "duplicate", "skipped", "failed", "cancelled")


class ImportJob(Base):
    __tablename__ = "import_job"
    __table_args__ = (
        CheckConstraint(f"status IN {IMPORT_JOB_STATUSES}", name="ck_import_job_status"),
        CheckConstraint(f"source IN {IMPORT_SOURCES}", name="ck_import_job_source"),
        ForeignKeyConstraint(
            ["tenant_id", "connection_id"], ["import_connection.tenant_id", "import_connection.id"],
            ondelete="SET NULL (connection_id)", name="fk_import_job_connection",
        ),
        CheckConstraint("type_filter IN ('all', 'images', 'documents')", name="ck_import_job_type_filter"),
        Index("idx_import_job_tenant", "tenant_id", text("created_at DESC")),
        Index("idx_import_job_status_lease", "status", "lease_until"),
        UniqueConstraint("tenant_id", "id", name="uq_import_job_tenant_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()"))
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False)
    requested_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app_user.id", ondelete="SET NULL"))
    source: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'draft'"))
    type_filter: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'all'"))
    include_gps: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"), default=True)
    folder_tags: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"), default=False)
    # Album-Aktionen der Regeln wirken nur, wenn eingeschaltet (User-Entscheid: Standard aus)
    albums_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"), default=False)
    takeout: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"), default=False)
    rules: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"), default=list)
    # Gestagte ZIP-Archive: [{"path": <relativ zu storage_root>, "size": int}] (Name nie als Pfad)
    archives: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"), default=list)
    # Beim Import angelegte Alben: {"<Name>": "<album uuid>"}
    album_map: Mapped[dict[str, str]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"), default=dict)
    # Für den Bericht: {"<Name>": {"reused": bool, "candidates": int}} (bestehendes Album wiederverwendet?)
    album_report: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"), default=dict)
    total_items: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), default=0)
    total_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"), default=0)
    # Kuratierter Fehlercode (nie Ausnahme-Text)
    error: Mapped[str | None] = mapped_column(Text)
    lease_owner: Mapped[str | None] = mapped_column(Text)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    served_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_progress_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # --- API-Quellen (0281) ---
    # Verbindung zum Cloud-Konto (FK im selben Mandanten, SET NULL beim Löschen der Tokens)
    connection_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    # Gewählte Wurzeln: [{"ref": <Anbieter-Referenz>}] (Namen holt der Worker beim Anbieter)
    selection: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"), default=list)
    # Wiederaufnehmbarer Stand des Auflistens (Ordner-Warteschlange, Seiten-Cursor)
    listing_state: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"), default=dict)
    # Drosselung des Anbieters (429/503 + Retry-After): Auftrag erst danach wieder bedienen
    not_before: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Seit wann der Auftrag auf eine neue Anmeldung wartet (needs_reauth, nach 7 Tagen failed)
    reauth_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ImportConnection(Base):
    """Verbindung einer Person zu einem Cloud-Konto (Migration 0281). Tokens nur verschlüsselt
    (services/cloud_import/token_crypto.py); die Zeile wird bei Auftragsende bzw. nach
    ``purge_after`` gelöscht - dann gibt es keine Tokens mehr."""

    __tablename__ = "import_connection"
    __table_args__ = (
        CheckConstraint(f"provider IN {IMPORT_PROVIDERS}", name="ck_import_connection_provider"),
        CheckConstraint(f"status IN {IMPORT_CONNECTION_STATUSES}", name="ck_import_connection_status"),
        UniqueConstraint("tenant_id", "id", name="uq_import_connection_tenant_id"),
        Index("idx_import_connection_user", "tenant_id", "user_id"),
        Index("idx_import_connection_purge", "purge_after"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()"))
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'active'"), default="active")
    # Nur zur Anzeige («Verbunden als …») und Fehlerhilfe (Entra-Tenant für den Admin-Consent)
    account_label: Mapped[str | None] = mapped_column(Text)
    account_kind: Mapped[str | None] = mapped_column(Text)
    account_tenant_id: Mapped[str | None] = mapped_column(Text)
    # Stabile Kennung des Kontos beim Anbieter: «gleiches Konto» beim erneuten Anmelden
    account_subject: Mapped[str | None] = mapped_column(Text)
    granted_scopes: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"), default="")
    access_token_encrypted: Mapped[str | None] = mapped_column(Text)
    refresh_token_encrypted: Mapped[str | None] = mapped_column(Text)
    access_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    purge_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ImportItem(Base):
    __tablename__ = "import_item"
    __table_args__ = (
        CheckConstraint(f"status IN {IMPORT_ITEM_STATUSES}", name="ck_import_item_status"),
        CheckConstraint("kind IN ('image', 'document', 'other')", name="ck_import_item_kind"),
        UniqueConstraint("job_id", "path", name="uq_import_item_job_path"),
        ForeignKeyConstraint(["tenant_id", "job_id"], ["import_job.tenant_id", "import_job.id"], ondelete="CASCADE", name="fk_import_item_job"),
        Index("idx_import_item_job_status", "job_id", "status", "id"),
        Index("idx_import_item_tenant", "tenant_id"),
        Index("idx_import_item_stored_file", "stored_file_id", postgresql_where=text("stored_file_id IS NOT NULL")),
        Index("idx_import_item_existing_file", "existing_file_id", postgresql_where=text("existing_file_id IS NOT NULL")),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False)
    # FK (tenant_id, job_id) -> import_job (Migration 0230, fk_import_item_job): Eintrag und Auftrag
    # liegen immer im selben Mandanten
    job_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"), default=0)
    modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archive_index: Mapped[int | None] = mapped_column(SmallInteger)
    entry_index: Mapped[int | None] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    # Grund aus dem Auflisten (zu gross, Format, Takeout-Metadaten …), sonst NULL
    listing_code: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'listed'"))
    result_code: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"), default=list)
    estimated_date: Mapped[date | None] = mapped_column(Date)
    # Herkunft von estimated_date: "takeout" (Metadaten-JSON) oder "rule"
    date_source: Mapped[str | None] = mapped_column(Text)
    # Aufnahmedatum aus der Takeout-Metadaten-JSON (beim Auflisten gelesen)
    hint_date: Mapped[date | None] = mapped_column(Date)
    albums: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"), default=list)
    matched_rules: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"), default=list)
    conflict: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"), default=False)
    group_key: Mapped[str | None] = mapped_column(Text)
    staged_path: Mapped[str | None] = mapped_column(Text)
    stored_file_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("stored_file.id", ondelete="SET NULL"))
    # Duplikat: vorhandene Datei, die ergänzt wurde (zählt nicht für die Aufbewahrung des Berichts)
    existing_file_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("stored_file.id", ondelete="SET NULL"))
    attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("0"), default=0)
    # --- API-Quellen (0281) ---
    provider_item_id: Mapped[str | None] = mapped_column(Text)
    provider_drive_id: Mapped[str | None] = mapped_column(Text)
    # Hash des Anbieters (quickXorHash/md5, nur Wiederaufnahme/Hinweis - Duplikate erkennt die Pipeline)
    provider_hash: Mapped[str | None] = mapped_column(Text)
    provider_mime: Mapped[str | None] = mapped_column(Text)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
