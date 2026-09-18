from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    SmallInteger,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))


class UpdatedAtMixin:
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))


class Tenant(Base, TimestampMixin):
    __tablename__ = "tenant"
    __table_args__ = (Index("idx_tenant_last_word_import_template", "last_word_import_template_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, unique=True, server_default=text("uuidv7()")
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    profile_image_path: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))
    tag_config_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"), default=dict)
    public_slug: Mapped[str | None] = mapped_column(Text, unique=True)
    # Vorlage, die im Import-Assistenten zuletzt ausgewählt wurde - wird beim nächsten
    # Öffnen der Seite wieder vorausgewählt. SET NULL statt CASCADE, damit das Löschen
    # einer Vorlage nicht versehentlich den Tenant mitreisst; die UI fällt dann einfach
    # auf die erste aktive Vorlage zurück.
    last_word_import_template_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("template.id", ondelete="SET NULL")
    )
    # NULL = kein Limit gesetzt (Standard fuer alle bestehenden Mandanten). Vom Adminportal aus
    # gesetzt (siehe AdminTenantStorageQuotaUpdate), gegen StorageService.breakdown_for_tenant
    # geprueft.
    storage_quota_bytes: Mapped[int | None] = mapped_column(BigInteger)


class PlatformOidcConfig(Base, TimestampMixin, UpdatedAtMixin):
    """Single global SSO provider config for the platform-admin panel only - tenants/customers
    have no OIDC option at all (see security audit 2026-07-26 for why the old per-tenant
    tenant_oidc_config was removed). There is always at most one meaningful row; the service
    layer enforces that, not the schema."""

    __tablename__ = "platform_oidc_config"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, unique=True, server_default=text("uuidv7()")
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("FALSE"))
    issuer_url: Mapped[str] = mapped_column(Text, nullable=False)
    client_id: Mapped[str] = mapped_column(Text, nullable=False)
    client_secret: Mapped[str] = mapped_column(Text, nullable=False)
    scopes: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'openid email profile'"))


class TenantDomain(Base, TimestampMixin):
    __tablename__ = "tenant_domain"
    __table_args__ = (
        UniqueConstraint("tenant_id", "purpose", name="uq_tenant_domain_tenant_purpose"),
        UniqueConstraint("domain", name="uq_tenant_domain_domain"),
        CheckConstraint("purpose IN ('app', 'abgabebox')", name="ck_tenant_domain_purpose"),
        CheckConstraint("status IN ('pending', 'active')", name="ck_tenant_domain_status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, unique=True, server_default=text("uuidv7()")
    )
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False)
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    domain: Mapped[str] = mapped_column(Text, nullable=False)
    verification_token: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'pending'"))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_healthy: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Role(Base):
    __tablename__ = "role"

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    code: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text)


class AppUser(Base, TimestampMixin, UpdatedAtMixin):
    __tablename__ = "app_user"
    __table_args__ = (
        UniqueConstraint("email", name="uq_app_user_email"),
        CheckConstraint(
            "preferred_mfa_factor_type IN ('totp', 'webauthn')",
            name="ck_app_user_preferred_mfa_factor_type",
        ),
        Index("idx_app_user_default_tenant", "default_tenant_id"),
        Index("idx_app_user_email", "email"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, unique=True, server_default=text("uuidv7()")
    )
    default_tenant_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("tenant.id", ondelete="SET NULL"))
    first_name: Mapped[str] = mapped_column(Text, nullable=False)
    last_name: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, Computed("display_name", persisted=True))
    email: Mapped[str] = mapped_column(Text, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    preferred_language: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'de'"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("TRUE"))
    session_revoke_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    preferred_mfa_factor_type: Mapped[str | None] = mapped_column(Text)
    external_identity_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"), default=dict)


class UserMfaFactor(Base, TimestampMixin, UpdatedAtMixin):
    __tablename__ = "user_mfa_factor"
    __table_args__ = (
        Index("idx_user_mfa_factor_user", "user_id", "factor_type"),
        # Platform-admin MFA factors (audit finding, 2026-08-27 - platform admins, the
        # highest-privilege tier, had no MFA option at all): this table is reused rather than
        # adding a parallel one, since the TOTP-storage shape (secret_encrypted,
        # totp_last_counter, label, ...) is identical regardless of which principal owns the
        # factor. user_id is now nullable and platform_admin_id was added alongside it; the
        # check constraint enforces exactly one owner per row.
        Index("idx_user_mfa_factor_platform_admin", "platform_admin_id", "factor_type"),
        UniqueConstraint("webauthn_credential_id", name="uq_user_mfa_factor_webauthn_credential_id"),
        CheckConstraint("factor_type IN ('totp', 'webauthn')", name="ck_user_mfa_factor_type"),
        CheckConstraint(
            "(user_id IS NOT NULL AND platform_admin_id IS NULL) OR "
            "(user_id IS NULL AND platform_admin_id IS NOT NULL)",
            name="ck_user_mfa_factor_single_owner",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, unique=True, server_default=text("uuidv7()")
    )
    user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app_user.id", ondelete="CASCADE"))
    platform_admin_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("platform_admin.id", ondelete="CASCADE")
    )
    factor_type: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    secret_encrypted: Mapped[str | None] = mapped_column(Text)
    totp_last_counter: Mapped[int | None] = mapped_column(BigInteger)
    webauthn_credential_id: Mapped[str | None] = mapped_column(Text)
    webauthn_public_key_pem: Mapped[str | None] = mapped_column(Text)
    webauthn_sign_count: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    webauthn_aaguid: Mapped[str | None] = mapped_column(Text)
    webauthn_rp_id: Mapped[str | None] = mapped_column(Text)
    webauthn_transports_json: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb"), default=list
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PlatformAdmin(Base, TimestampMixin, UpdatedAtMixin):
    """Betreiber-Account fürs zentrale Admin-Panel. Komplett getrennt vom Kunden-`AppUser`-System."""

    __tablename__ = "platform_admin"
    __table_args__ = (
        UniqueConstraint("email", name="uq_platform_admin_email"),
        UniqueConstraint("oidc_issuer", "oidc_subject", name="uq_platform_admin_oidc"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, unique=True, server_default=text("uuidv7()")
    )
    email: Mapped[str] = mapped_column(Text, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("TRUE"))
    session_revoke_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    oidc_subject: Mapped[str | None] = mapped_column(Text)
    oidc_issuer: Mapped[str | None] = mapped_column(Text)
    # 'owner' = full read/write access, 'support' = read-only across the whole admin panel
    # (no create/update/delete on tenants, users, admins, domains, OIDC config, ...).
    role: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'owner'"))


class UserRole(Base):
    __tablename__ = "user_role"
    __table_args__ = (
        PrimaryKeyConstraint("user_id", "role_id", name="pk_user_role"),
        Index("idx_user_role_role", "role_id"),
    )

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    role_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("role.id", ondelete="RESTRICT"), nullable=False)


class UserTenantRole(Base, TimestampMixin, UpdatedAtMixin):
    __tablename__ = "user_tenant_role"
    __table_args__ = (
        PrimaryKeyConstraint("user_id", "tenant_id", name="pk_user_tenant_role"),
        Index("idx_user_tenant_role_tenant", "tenant_id", "role_id"),
        Index("idx_user_tenant_role_role", "role_id", "is_active"),
    )

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False)
    role_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("role.id", ondelete="RESTRICT"), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("TRUE"))


class GroupEntity(Base, TimestampMixin, UpdatedAtMixin):
    __tablename__ = "group_entity"
    __table_args__ = (Index("idx_group_entity_tenant_active", "tenant_id", "is_active"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, unique=True, server_default=text("uuidv7()")
    )
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("TRUE"))
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_until: Mapped[date | None] = mapped_column(Date)


class Leader(Base, TimestampMixin, UpdatedAtMixin):
    __tablename__ = "leader"
    __table_args__ = (Index("idx_leader_tenant_active", "tenant_id", "is_active"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, unique=True, server_default=text("uuidv7()")
    )
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("TRUE"))
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_until: Mapped[date | None] = mapped_column(Date)


class Participant(Base, TimestampMixin, UpdatedAtMixin):
    __tablename__ = "participant"
    __table_args__ = (
        Index("idx_participant_tenant_active", "tenant_id", "is_active"),
        Index("idx_participant_app_user_id", "app_user_id"),
        UniqueConstraint("tenant_id", "display_name", name="uq_participant_tenant_display_name"),
        UniqueConstraint("tenant_id", "app_user_id", name="uq_participant_tenant_app_user"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, unique=True, server_default=text("uuidv7()")
    )
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False)
    app_user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app_user.id", ondelete="SET NULL"))
    first_name: Mapped[str | None] = mapped_column(Text)
    last_name: Mapped[str | None] = mapped_column(Text)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("TRUE"))
    joined_at: Mapped[date | None] = mapped_column(Date)
    left_at: Mapped[date | None] = mapped_column(Date)


class EventCategory(Base):
    __tablename__ = "event_category"

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    code: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text)


class Event(Base, TimestampMixin, UpdatedAtMixin):
    __tablename__ = "event"
    __table_args__ = (
        Index("idx_event_tenant_date", "tenant_id", "event_date"),
        Index("idx_event_tenant_category", "tenant_id", "event_category_id"),
        Index("idx_event_category_id", "event_category_id"),
        Index("idx_event_group_id", "group_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, unique=True, server_default=text("uuidv7()")
    )
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False)
    event_date: Mapped[date] = mapped_column(Date, nullable=False)
    event_end_date: Mapped[date | None] = mapped_column(Date)
    event_category_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("event_category.id", ondelete="RESTRICT"), nullable=False)
    tag: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    participant_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    is_cancelled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    is_session_marker: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    group_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("group_entity.id", ondelete="SET NULL"))
    organizer_ids: Mapped[list[int] | None] = mapped_column(JSONB)
    leadership_ids: Mapped[list[int] | None] = mapped_column(JSONB)
    participant_ids: Mapped[list[int] | None] = mapped_column(JSONB)
    spezial1_ids: Mapped[list[int] | None] = mapped_column(JSONB)
    spezial2_ids: Mapped[list[int] | None] = mapped_column(JSONB)
    spezial3_ids: Mapped[list[int] | None] = mapped_column(JSONB)
    location: Mapped[str | None] = mapped_column(Text)
    spezial_text1: Mapped[str | None] = mapped_column(Text)
    spezial_text2: Mapped[str | None] = mapped_column(Text)
    spezial_text3: Mapped[str | None] = mapped_column(Text)
    cycle_assignments: Mapped[list[EventCycle]] = relationship(
        "EventCycle",
        primaryjoin="Event.id == EventCycle.event_id",
        foreign_keys="EventCycle.event_id",
        lazy="selectin",
        cascade="all, delete-orphan",
    )


class CycleConfig(Base, TimestampMixin, UpdatedAtMixin):
    __tablename__ = "cycle_config"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, unique=True, server_default=text("uuidv7()")
    )
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    reset_month: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("12"))
    reset_day: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("31"))
    name_pattern: Mapped[str | None] = mapped_column(Text)


class TableSnapshot(Base, TimestampMixin):
    """One row per (tenant, cycle_config, cycle_year, table_name): a frozen JSONB copy
    of that table's rows (scoped to the tenant) as of the cycle boundary. Only ever
    created by the daily cycle_snapshot_loop (see TableSnapshotService.create_snapshot)
    - there is no manual/on-demand trigger, this is a historical-record feature, not a
    backup tool. See app/services/table_snapshot_config.py for which tables are covered.
    snapshot_json rows keep their original internal id/FK values verbatim (no
    remapping), so a future feature can reference a specific historical row by
    (table_name, cycle_config_id, cycle_year, row id) without any schema change here."""

    __tablename__ = "table_snapshot"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "cycle_config_id", "cycle_year", "table_name",
            name="uq_table_snapshot_tenant_cycle_table",
        ),
        Index("idx_table_snapshot_tenant_cycle", "tenant_id", "cycle_config_id", "cycle_year"),
        Index("idx_table_snapshot_json_gin", "snapshot_json", postgresql_using="gin"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, unique=True, server_default=text("uuidv7()")
    )
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False)
    cycle_config_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("cycle_config.id", ondelete="CASCADE"), nullable=False)
    cycle_year: Mapped[int] = mapped_column(Integer, nullable=False)
    table_name: Mapped[str] = mapped_column(Text, nullable=False)
    snapshot_json: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"), default=list)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    # Set the first time a guarded historical-edit write lands on this snapshot (see
    # table_snapshots API routes) - the UI uses this to permanently flag "diese
    # historische Ansicht wurde nachträglich bearbeitet" even after the fact.
    is_edited: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"), default=False)
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    edited_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app_user.id", ondelete="SET NULL"))


class WordImportProfile(Base, TimestampMixin, UpdatedAtMixin):
    __tablename__ = "word_import_profile"
    __table_args__ = (
        UniqueConstraint("tenant_id", "template_id", name="uq_word_import_profile_tenant_template"),
        Index("idx_word_import_profile_tenant", "tenant_id"),
        Index("idx_word_import_profile_template", "template_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, unique=True, server_default=text("uuidv7()")
    )
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False)
    template_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("template.id", ondelete="SET NULL"))
    mapping_config_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"), default=dict)


class WordImportSuggestionOutcome(Base, TimestampMixin):
    """Append-only log of one row per resolved matching decision at
    WordImportService.commit() time (event/participant/table-role/list-entry/matrix-
    column match) - never mutated after insert. Used to compute per-tenant accept-rate
    quality stats (see WordImportQualityService) and, from that data, adaptive
    per-tenant score thresholds (see word_import_thresholds.adaptive_threshold)."""

    __tablename__ = "word_import_suggestion_outcome"
    __table_args__ = (
        Index("idx_word_import_suggestion_outcome_lookup", "tenant_id", "template_id", "signal_type"),
        Index("idx_word_import_suggestion_outcome_template", "template_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, unique=True, server_default=text("uuidv7()")
    )
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False)
    template_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("template.id", ondelete="SET NULL"))
    signal_type: Mapped[str] = mapped_column(Text, nullable=False)
    suggested_score: Mapped[float] = mapped_column(Float, nullable=False)
    was_accepted: Mapped[bool] = mapped_column(Boolean, nullable=False)


class WordImportDocument(Base, TimestampMixin, UpdatedAtMixin):
    __tablename__ = "word_import_document"
    __table_args__ = (
        CheckConstraint("status IN ('eingelesen', 'importiert')", name="ck_word_import_document_status"),
        Index("idx_word_import_document_tenant_template_status", "tenant_id", "template_id", "status"),
        Index("idx_word_import_document_protocol", "protocol_id"),
        Index("idx_word_import_document_created_by", "created_by"),
        Index("idx_word_import_document_imported_by", "imported_by"),
        Index("idx_word_import_document_stored_file", "stored_file_id"),
        Index("idx_word_import_document_template", "template_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, unique=True, server_default=text("uuidv7()")
    )
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False)
    template_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("template.id", ondelete="RESTRICT"), nullable=False)
    stored_file_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("stored_file.id", ondelete="RESTRICT"), nullable=False)
    original_filename: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    protocol_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'eingelesen'"))
    # Cached WordImportAnalysis output, so the review step can be reopened later without
    # re-reading/re-parsing the stored file - refreshed on manual reanalyze and whenever a
    # sibling document in the same tenant+template queue gets committed (see
    # WordImportQueueService._refresh_pending_siblings).
    analysis_snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"), default=dict)
    # Reviewer's in-progress edits on top of analysis_snapshot_json (candidate links,
    # approve toggles, corrected values) - opaque to the backend, shape owned entirely by
    # the frontend wizard. Reset to {} whenever analysis_snapshot_json is regenerated (see
    # WordImportQueueService._reanalyze_document), since row indices/candidates it refers
    # to no longer match.
    review_draft_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"), default=dict)
    protocol_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("protocol.id", ondelete="SET NULL"))
    created_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app_user.id", ondelete="SET NULL"))
    imported_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app_user.id", ondelete="SET NULL"))
    imported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EventCycle(Base):
    __tablename__ = "event_cycle"
    __table_args__ = (
        PrimaryKeyConstraint("event_id", "cycle_config_id", "cycle_year", name="pk_event_cycle"),
        Index("idx_event_cycle_event", "event_id"),
        Index("idx_event_cycle_config_year", "cycle_config_id", "cycle_year"),
    )

    event_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("event.id", ondelete="CASCADE"), nullable=False)
    cycle_config_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("cycle_config.id", ondelete="CASCADE"), nullable=False)
    cycle_year: Mapped[int] = mapped_column(SmallInteger, nullable=False)


class ListDefinition(Base, TimestampMixin, UpdatedAtMixin):
    __tablename__ = "list_definition"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_list_definition_tenant_name"),
        CheckConstraint(
            "column_one_value_type IN ('text', 'participant', 'participants', 'event')",
            name="ck_list_definition_column_one_type",
        ),
        CheckConstraint(
            "column_two_value_type IN ('text', 'participant', 'participants', 'event')",
            name="ck_list_definition_column_two_type",
        ),
        Index("idx_list_definition_tenant_active", "tenant_id", "is_active"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, unique=True, server_default=text("uuidv7()")
    )
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    column_one_title: Mapped[str] = mapped_column(Text, nullable=False)
    column_one_value_type: Mapped[str] = mapped_column(Text, nullable=False)
    column_two_title: Mapped[str] = mapped_column(Text, nullable=False)
    column_two_value_type: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("TRUE"))
    # Bumped on any entry create/update/delete, or a column title/type change - lets protocol
    # blocks that snapshot this list's data cheaply detect "has anything relevant changed"
    # without reconciling independent per-row updated_at timestamps (entries don't cascade
    # to bump this table's updated_at, and deletes don't touch it at all).
    content_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))


class ListEntry(Base, TimestampMixin, UpdatedAtMixin):
    __tablename__ = "list_entry"
    __table_args__ = (
        Index("idx_list_entry_definition_sort", "list_definition_id", "sort_index"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, unique=True, server_default=text("uuidv7()")
    )
    list_definition_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("list_definition.id", ondelete="CASCADE"), nullable=False
    )
    sort_index: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    column_one_value_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb"), default=dict
    )
    column_two_value_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb"), default=dict
    )


class DocumentTemplate(Base, TimestampMixin, UpdatedAtMixin):
    __tablename__ = "document_template"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", "version", name="uq_document_template_tenant_code_version"),
        CheckConstraint("version >= 1", name="ck_document_template_version_positive"),
        Index("idx_document_template_tenant_code_version", "tenant_id", "code", "version"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, unique=True, server_default=text("uuidv7()")
    )
    tenant_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"))
    code: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    filesystem_path: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("TRUE"))
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("FALSE"))
    configuration_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"), default=dict)


class DocumentTemplatePart(Base, TimestampMixin, UpdatedAtMixin):
    __tablename__ = "document_template_part"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", "version", name="uq_document_template_part_tenant_code_version"),
        CheckConstraint("version >= 1", name="ck_document_template_part_version_positive"),
        Index("idx_document_template_part_tenant_type", "tenant_id", "part_type"),
        Index("idx_document_template_part_active", "tenant_id", "is_active"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, unique=True, server_default=text("uuidv7()")
    )
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    part_type: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("TRUE"))


class ElementType(Base):
    __tablename__ = "element_type"

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    code: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text)


class RenderType(Base):
    __tablename__ = "render_type"

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    code: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text)


class Template(Base, TimestampMixin, UpdatedAtMixin):
    __tablename__ = "template"
    __table_args__ = (
        CheckConstraint("version >= 1", name="ck_template_version_positive"),
        CheckConstraint("status IN ('active', 'archived')", name="ck_template_status"),
        Index("idx_template_tenant", "tenant_id"),
        Index("idx_template_status", "status"),
        Index("idx_template_document_template", "document_template_id"),
        Index("idx_template_created_by", "created_by"),
        Index("idx_template_cycle_config", "cycle_config_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, unique=True, server_default=text("uuidv7()")
    )
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False)
    document_template_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("document_template.id", ondelete="RESTRICT"))
    next_event_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("event.id", ondelete="SET NULL"))
    last_event_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("event.id", ondelete="SET NULL"))
    todo_due_event_tag: Mapped[str | None] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    protocol_number_pattern: Mapped[str | None] = mapped_column(Text)
    title_pattern: Mapped[str | None] = mapped_column(Text)
    auto_create_next_protocol: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("FALSE"))
    cycle_config_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("cycle_config.id", ondelete="SET NULL"))
    cycle_config: Mapped[CycleConfig | None] = relationship("CycleConfig", foreign_keys="Template.cycle_config_id", lazy="selectin")
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'active'"))
    created_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app_user.id", ondelete="SET NULL"))


class TemplateParticipant(Base, TimestampMixin):
    __tablename__ = "template_participant"
    __table_args__ = (
        PrimaryKeyConstraint("template_id", "participant_id", name="pk_template_participant"),
        Index("idx_template_participant_template", "template_id"),
        Index("idx_template_participant_participant", "participant_id"),
    )

    template_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("template.id", ondelete="CASCADE"), nullable=False)
    participant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("participant.id", ondelete="CASCADE"), nullable=False)
    exclude_from_attendance: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("FALSE"))


class UserTemplateAccess(Base, TimestampMixin):
    __tablename__ = "user_template_access"
    __table_args__ = (
        PrimaryKeyConstraint("user_id", "template_id", name="pk_user_template_access"),
        Index("idx_user_template_access_tenant_user", "tenant_id", "user_id"),
        Index("idx_user_template_access_template", "template_id"),
    )

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False)
    template_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("template.id", ondelete="CASCADE"), nullable=False)


class UserProtocolAccess(Base, TimestampMixin):
    __tablename__ = "user_protocol_access"
    __table_args__ = (
        PrimaryKeyConstraint("user_id", "protocol_id", name="pk_user_protocol_access"),
        Index("idx_user_protocol_access_tenant_user", "tenant_id", "user_id"),
        Index("idx_user_protocol_access_protocol", "protocol_id"),
    )

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False)
    protocol_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("protocol.id", ondelete="CASCADE"), nullable=False)


class ElementDefinition(Base, TimestampMixin, UpdatedAtMixin):
    __tablename__ = "element_definition"
    __table_args__ = (
        Index("idx_element_definition_tenant", "tenant_id"),
        Index("idx_element_definition_type", "element_type_id"),
        Index("idx_element_definition_render_type", "render_type_id"),
        Index("idx_element_definition_configuration_gin", "configuration_json", postgresql_using="gin"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, unique=True, server_default=text("uuidv7()")
    )
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False)
    element_type_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("element_type.id", ondelete="RESTRICT"), nullable=False)
    render_type_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("render_type.id", ondelete="RESTRICT"), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    display_title: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    is_editable: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("TRUE"))
    allows_multiple_values: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("FALSE"))
    export_visible: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("TRUE"))
    latex_template: Mapped[str | None] = mapped_column(Text)
    configuration_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"), default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("TRUE"))


class TemplateElement(Base, TimestampMixin):
    __tablename__ = "template_element"
    __table_args__ = (
        UniqueConstraint("template_id", "sort_index", name="uq_template_element_template_sort"),
        Index("idx_template_element_template_sort", "template_id", "sort_index"),
        Index("idx_template_element_configuration_gin", "configuration_json", postgresql_using="gin"),
        Index("idx_template_element_element_definition", "element_definition_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, unique=True, server_default=text("uuidv7()")
    )
    template_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("template.id", ondelete="CASCADE"), nullable=False)
    element_definition_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("element_definition.id", ondelete="RESTRICT"), nullable=False)
    sort_index: Mapped[int] = mapped_column(Integer, nullable=False)
    section_name: Mapped[str] = mapped_column(Text, nullable=False)
    section_order: Mapped[int | None] = mapped_column(Integer)
    is_required: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("FALSE"))
    is_visible: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("TRUE"))
    export_visible: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("TRUE"))
    configuration_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"), default=dict)


class TemplateElementBlock(Base, TimestampMixin):
    __tablename__ = "template_element_block"
    __table_args__ = (
        UniqueConstraint("template_element_id", "sort_index", name="uq_template_element_block_sort"),
        Index("idx_template_element_block_sort", "template_element_id", "sort_index"),
        Index("idx_template_element_block_configuration_gin", "configuration_override_json", postgresql_using="gin"),
        Index("idx_template_element_block_element_definition", "element_definition_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, unique=True, server_default=text("uuidv7()")
    )
    template_element_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("template_element.id", ondelete="CASCADE"), nullable=False)
    element_definition_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("element_definition.id", ondelete="RESTRICT"), nullable=False)
    sort_index: Mapped[int] = mapped_column(Integer, nullable=False)
    render_order: Mapped[int | None] = mapped_column(Integer)
    block_title: Mapped[str | None] = mapped_column(Text)
    is_required: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("FALSE"))
    is_visible: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("TRUE"))
    export_visible: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("TRUE"))
    configuration_override_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"), default=dict)


Index("idx_template_element_block_render", TemplateElementBlock.template_element_id, text("COALESCE(render_order, sort_index)"))


class Protocol(Base, TimestampMixin, UpdatedAtMixin):
    __tablename__ = "protocol"
    __table_args__ = (
        UniqueConstraint("tenant_id", "protocol_number", name="uq_protocol_tenant_number"),
        CheckConstraint("status IN ('geplant', 'vorbereitet', 'durchgeführt', 'abgeschlossen')", name="ck_protocol_status"),
        Index("idx_protocol_tenant_date", "tenant_id", "protocol_date"),
        Index("idx_protocol_template", "template_id"),
        Index("idx_protocol_event", "event_id"),
        Index("idx_protocol_status", "status"),
        Index("idx_protocol_document_template", "document_template_id", "document_template_version"),
        Index("idx_protocol_created_by", "created_by"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, unique=True, server_default=text("uuidv7()")
    )
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False)
    template_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("template.id", ondelete="RESTRICT"), nullable=False)
    template_version: Mapped[int] = mapped_column(Integer, nullable=False)
    document_template_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("document_template.id", ondelete="RESTRICT"))
    document_template_version: Mapped[int | None] = mapped_column(Integer)
    document_template_path_snapshot: Mapped[str | None] = mapped_column(Text)
    protocol_number: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    protocol_date: Mapped[date] = mapped_column(Date, nullable=False)
    event_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("event.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'geplant'"))
    version_major: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), default=0)
    version_minor: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), default=0)
    version_final_minor: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), default=0)
    session_notes: Mapped[str | None] = mapped_column(Text)
    track_changes_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"), default=True)
    created_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app_user.id", ondelete="SET NULL"))


class ProtocolElement(Base, TimestampMixin):
    __tablename__ = "protocol_element"
    __table_args__ = (
        UniqueConstraint("protocol_id", "sort_index", name="uq_protocol_element_protocol_sort"),
        Index("idx_protocol_element_protocol_sort", "protocol_id", "sort_index"),
        Index("idx_protocol_element_template_element", "template_element_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, unique=True, server_default=text("uuidv7()")
    )
    protocol_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("protocol.id", ondelete="CASCADE"), nullable=False)
    template_element_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("template_element.id", ondelete="SET NULL"))
    sort_index: Mapped[int] = mapped_column(Integer, nullable=False)
    section_name_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    section_order_snapshot: Mapped[int | None] = mapped_column(Integer)
    is_required_snapshot: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("FALSE"))
    is_visible_snapshot: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("TRUE"))
    export_visible_snapshot: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("TRUE"))
    element_title_snapshot: Mapped[str | None] = mapped_column(Text)
    responsible_assignments_snapshot: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    responsible_name_display_mode: Mapped[str | None] = mapped_column(Text)


class ProtocolElementBlock(Base, TimestampMixin):
    __tablename__ = "protocol_element_block"
    __table_args__ = (
        UniqueConstraint("protocol_element_id", "sort_index", name="uq_protocol_element_block_sort"),
        Index("idx_protocol_element_block_sort", "protocol_element_id", "sort_index"),
        Index("idx_protocol_element_block_type", "element_type_id"),
        Index("idx_protocol_element_block_configuration_gin", "configuration_snapshot_json", postgresql_using="gin"),
        Index("idx_protocol_element_block_element_definition", "element_definition_id"),
        Index("idx_protocol_element_block_render_type", "render_type_id"),
        Index("idx_protocol_element_block_template_element_block", "template_element_block_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, unique=True, server_default=text("uuidv7()")
    )
    protocol_element_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("protocol_element.id", ondelete="CASCADE"), nullable=False)
    template_element_block_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("template_element_block.id", ondelete="SET NULL"))
    element_definition_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("element_definition.id", ondelete="SET NULL"))
    element_type_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("element_type.id", ondelete="RESTRICT"), nullable=False)
    render_type_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("render_type.id", ondelete="RESTRICT"), nullable=False)
    title_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    display_title_snapshot: Mapped[str | None] = mapped_column(Text)
    description_snapshot: Mapped[str | None] = mapped_column(Text)
    block_title_snapshot: Mapped[str | None] = mapped_column(Text)
    is_editable_snapshot: Mapped[bool] = mapped_column(Boolean, nullable=False)
    allows_multiple_values_snapshot: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("FALSE"))
    sort_index: Mapped[int] = mapped_column(Integer, nullable=False)
    render_order: Mapped[int | None] = mapped_column(Integer)
    is_required_snapshot: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("FALSE"))
    is_visible_snapshot: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("TRUE"))
    export_visible_snapshot: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("TRUE"))
    latex_template_snapshot: Mapped[str | None] = mapped_column(Text)
    configuration_snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"), default=dict)


Index("idx_protocol_element_block_render", ProtocolElementBlock.protocol_element_id, text("COALESCE(render_order, sort_index)"))


class StoredFile(Base, TimestampMixin):
    __tablename__ = "stored_file"
    __table_args__ = (
        Index("idx_stored_file_tenant", "tenant_id"),
        Index("idx_stored_file_tags_gin", "tags", postgresql_using="gin"),
        Index("idx_stored_file_created_by", "created_by"),
        Index(
            "idx_stored_file_scan_status_pending",
            "scan_status",
            postgresql_where=text("scan_status <> 'clean'"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, unique=True, server_default=text("uuidv7()")
    )
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False)
    original_name: Mapped[str] = mapped_column(Text, nullable=False)
    mime_type: Mapped[str | None] = mapped_column(Text)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    latex_path: Mapped[str | None] = mapped_column(Text)
    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    checksum_sha256: Mapped[str | None] = mapped_column(Text)
    perceptual_hash: Mapped[str | None] = mapped_column(Text)
    # Laplacian-variance sharpness and clipped-histogram exposure estimates (see
    # photo_quality.py) - relative ranking signals for the photo-culling "beste Bilder
    # vorschlagen" feature, not an absolute/universal quality bar. None for non-image
    # files and images PIL couldn't decode.
    sharpness_score: Mapped[float | None] = mapped_column(Float)
    exposure_score: Mapped[float | None] = mapped_column(Float)
    # Set by FileService.backfill_missing_quality_scores once it has attempted this file,
    # regardless of whether that attempt could actually produce scores - a file missing
    # from disk (or PIL-undecodable) otherwise left both scores NULL forever, so the same
    # row kept matching that method's "still missing a score" query on every tick,
    # indefinitely (audit fix, 2026-09-17). Same pattern as face_analyzed_at below.
    quality_analyzed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Phase 3 (photo_analysis_job/photo-analysis-worker) - sharpness/exposure of the best
    # detected face region, not the whole image. None if no face was detected, the file
    # isn't an image, or it hasn't been analyzed yet.
    face_quality_score: Mapped[float | None] = mapped_column(Float)
    # Set by the worker once it has processed the file, regardless of whether a face was
    # found - face_quality_score alone can't express "analyzed, no face" vs. "not analyzed
    # yet" since both leave that column NULL.
    face_analyzed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    thumbnail_path: Mapped[str | None] = mapped_column(Text)
    # Original pixel dimensions, captured alongside thumbnail generation (see
    # _generate_thumbnail_bytes/ensure_thumbnail in file_service.py) so the Fotos gallery's
    # masonry grid can reserve each tile's correct aspect-ratio box before the image itself
    # has loaded, instead of the layout jumping as each thumbnail comes in. None for
    # non-images, files PIL couldn't decode, and files uploaded before this column existed
    # whose thumbnail was never regenerated since.
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    scan_status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'clean'"))
    # User-assigned tags for the "Dateien" overview page's filter/editor - separate from the
    # auto-derived "origin tag" (which protocol/word-import/submission this file came from,
    # see StoredFileRepository.list_tenant_files), which is computed on read rather than
    # stored here so it always reflects the current protocol number / assignment title.
    tags: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"), default=list)
    created_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app_user.id", ondelete="SET NULL"))


class ProtocolText(Base, TimestampMixin, UpdatedAtMixin):
    __tablename__ = "protocol_text"
    __table_args__ = (Index("idx_protocol_text_protocol_element_block", "protocol_element_block_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, unique=True, server_default=text("uuidv7()")
    )
    protocol_element_block_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("protocol_element_block.id", ondelete="CASCADE"), nullable=False, unique=True)
    content: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    tracked_baseline_content: Mapped[str | None] = mapped_column(Text)
    tracked_dirty: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"), default=False)


class ProtocolDisplaySnapshot(Base, TimestampMixin):
    __tablename__ = "protocol_display_snapshot"
    __table_args__ = (
        Index("idx_protocol_display_snapshot_protocol_element_block", "protocol_element_block_id"),
        Index("idx_protocol_display_snapshot_json_gin", "snapshot_json", postgresql_using="gin"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, unique=True, server_default=text("uuidv7()")
    )
    protocol_element_block_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("protocol_element_block.id", ondelete="CASCADE"), nullable=False, unique=True)
    source_type: Mapped[str | None] = mapped_column(Text)
    source_id: Mapped[str | None] = mapped_column(Text)
    compiled_text: Mapped[str | None] = mapped_column(Text)
    snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"), default=dict)


class TodoStatus(Base):
    __tablename__ = "todo_status"

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    code: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text)


class ProtocolTodo(Base, TimestampMixin, UpdatedAtMixin):
    __tablename__ = "protocol_todo"
    __table_args__ = (
        UniqueConstraint("protocol_element_block_id", "sort_index", name="uq_protocol_todo_block_sort"),
        Index("idx_protocol_todo_protocol_element_block", "protocol_element_block_id"),
        Index("idx_protocol_todo_status_due_date", "todo_status_id", "due_date"),
        Index("idx_protocol_todo_assigned_user", "assigned_user_id"),
        Index("idx_protocol_todo_assigned_participant", "assigned_participant_id"),
        Index("idx_protocol_todo_closed_in_protocol", "closed_in_protocol_id"),
        Index("idx_protocol_todo_created_by", "created_by"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, unique=True, server_default=text("uuidv7()")
    )
    tenant_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"))
    protocol_element_block_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("protocol_element_block.id", ondelete="CASCADE"))
    sort_index: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    task: Mapped[str] = mapped_column(Text, nullable=False)
    assigned_user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app_user.id", ondelete="SET NULL"))
    assigned_participant_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("participant.id", ondelete="SET NULL"))
    todo_status_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("todo_status.id", ondelete="RESTRICT"), nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date)
    due_event_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("event.id", ondelete="SET NULL"))
    due_marker: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reference_link: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"), default=list)
    created_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app_user.id", ondelete="SET NULL"))
    closed_in_protocol_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("protocol.id", ondelete="SET NULL"))
    submission_assignment_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("submission_assignment.id", ondelete="CASCADE"))
    element_ref: Mapped[str | None] = mapped_column(Text)
    tracked_change: Mapped[str | None] = mapped_column(Text)
    tracked_change_before_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    pending_delete: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"), default=False)


class ProtocolImage(Base, TimestampMixin):
    __tablename__ = "protocol_image"
    __table_args__ = (
        UniqueConstraint("protocol_element_block_id", "sort_index", name="uq_protocol_image_block_sort"),
        Index("idx_protocol_image_protocol_element_block", "protocol_element_block_id"),
        Index("idx_protocol_image_stored_file", "stored_file_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, unique=True, server_default=text("uuidv7()")
    )
    protocol_element_block_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("protocol_element_block.id", ondelete="CASCADE"), nullable=False)
    stored_file_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("stored_file.id", ondelete="RESTRICT"), nullable=False)
    sort_index: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    title: Mapped[str | None] = mapped_column(Text)
    caption: Mapped[str | None] = mapped_column(Text)


class GalleryImage(Base, TimestampMixin):
    """Marks a StoredFile as having been uploaded directly through the "Dateien"/"Fotos"
    gallery upload window - not tied to a protocol block, word-import document, or
    submission upload, the three other origins in StoredFileRepository._files_overview_branches.
    Exists as its own join table (rather than a boolean/enum column on StoredFile) purely to
    follow that same "one join table per origin" convention the other three branches use."""
    __tablename__ = "gallery_image"
    __table_args__ = (
        Index("idx_gallery_image_tenant", "tenant_id"),
        Index("idx_gallery_image_event", "event_id"),
        Index("idx_gallery_image_stored_file", "stored_file_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False)
    stored_file_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("stored_file.id", ondelete="RESTRICT"), nullable=False)
    # The Termin the uploader optionally targeted in GalleryUploadModal, kept around (it
    # used to be discarded once the file landed in that Termin's auto-album) so the Fotos
    # page's date-grouped headers can show which Termin/Zyklus a given date belongs to.
    event_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("event.id", ondelete="SET NULL"))
    created_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app_user.id", ondelete="SET NULL"))


class ProtocolExportCache(Base, TimestampMixin):
    __tablename__ = "protocol_export_cache"
    __table_args__ = (
        CheckConstraint("export_format IN ('latex', 'pdf')", name="ck_protocol_export_cache_format"),
        Index("idx_protocol_export_cache_protocol", "protocol_id", "export_format"),
        Index("idx_protocol_export_cache_generated_file", "generated_file_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, unique=True, server_default=text("uuidv7()")
    )
    protocol_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("protocol.id", ondelete="CASCADE"), nullable=False)
    export_format: Mapped[str] = mapped_column(Text, nullable=False)
    latex_source: Mapped[str | None] = mapped_column(Text)
    generated_file_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("stored_file.id", ondelete="SET NULL"))
    generator_version: Mapped[str | None] = mapped_column(Text)


# ── Finance ───────────────────────────────────────────────────────────────────

class FinanceAccount(Base, TimestampMixin, UpdatedAtMixin):
    __tablename__ = "finance_account"
    __table_args__ = (
        Index("idx_finance_account_tenant", "tenant_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, unique=True, server_default=text("uuidv7()")
    )
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    currency_label: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'CHF'"))
    description: Mapped[str | None] = mapped_column(Text)


class FinanceTransaction(Base, TimestampMixin):
    __tablename__ = "finance_transaction"
    __table_args__ = (
        Index("idx_finance_transaction_account", "account_id", "transaction_date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, unique=True, server_default=text("uuidv7()")
    )
    account_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("finance_account.id", ondelete="CASCADE"), nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(15, 2), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    transaction_date: Mapped[date] = mapped_column(Date, nullable=False)
    protocol_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("protocol.id", ondelete="SET NULL"))


class UserProtocolScroll(Base):
    __tablename__ = "user_protocol_scroll"
    __table_args__ = (
        PrimaryKeyConstraint("user_id", "protocol_id"),
        Index("idx_user_protocol_scroll_protocol", "protocol_id"),
    )

    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    protocol_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("protocol.id", ondelete="CASCADE"), nullable=False)
    last_element_id: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))


class AttendanceFine(Base, TimestampMixin):
    __tablename__ = "attendance_fine"
    __table_args__ = (
        Index("idx_attendance_fine_protocol", "protocol_id"),
        Index("idx_attendance_fine_participant", "participant_id"),
        Index("idx_attendance_fine_account", "account_id"),
        Index("idx_attendance_fine_collected_by", "collected_by_user_id"),
        Index("idx_attendance_fine_collected_transaction", "collected_transaction_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, unique=True, server_default=text("uuidv7()")
    )
    protocol_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("protocol.id", ondelete="CASCADE"), nullable=False)
    participant_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("participant.id", ondelete="SET NULL"))
    participant_name_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    fine_type: Mapped[str] = mapped_column(Text, nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(15, 2), nullable=False)
    account_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("finance_account.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'pending'"))
    collected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    collected_transaction_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("finance_transaction.id", ondelete="SET NULL"))
    closed_in_protocol_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("protocol.id", ondelete="SET NULL"))
    collected_by_user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app_user.id", ondelete="SET NULL"))


class SubmissionAssignment(Base, TimestampMixin, UpdatedAtMixin):
    """Konfiguration einer Abgabe (Upload-Box), gekoppelt an Termine (per Tag-Filter + Offset) oder eine Liste (+ Stichtag)."""

    __tablename__ = "submission_assignment"
    __table_args__ = (
        UniqueConstraint("tenant_id", "public_slug", name="uq_submission_assignment_tenant_slug"),
        CheckConstraint("source_type IN ('events', 'list')", name="ck_submission_assignment_source_type"),
        CheckConstraint(
            # Tage vor/nach Termin bzw. Stichtag sind bewusst optional (siehe Migration
            # 0056_submission_flexible_window): NULL = kein Zeitfenster, die Abgabe bleibt offen,
            # bis sie manuell geschlossen wird (SubmissionUpload.status = 'closed').
            "(source_type = 'events' AND tag_filter IS NOT NULL "
            "AND list_definition_id IS NULL AND deadline IS NULL) OR "
            "(source_type = 'list' AND list_definition_id IS NOT NULL "
            "AND tag_filter IS NULL AND offset_days_before IS NULL AND offset_days_after IS NULL)",
            name="ck_submission_assignment_source_fields",
        ),
        CheckConstraint("offset_days_before IS NULL OR offset_days_before >= 0", name="ck_submission_assignment_offset_before"),
        CheckConstraint("offset_days_after IS NULL OR offset_days_after >= 0", name="ck_submission_assignment_offset_after"),
        CheckConstraint("max_files_per_element IS NULL OR max_files_per_element >= 1", name="ck_submission_assignment_max_files"),
        CheckConstraint("max_file_size_mb >= 1", name="ck_submission_assignment_max_size"),
        CheckConstraint("sort_order IN ('alphabetical', 'date', 'proximity')", name="ck_submission_assignment_sort_order"),
        Index("idx_submission_assignment_tenant_active", "tenant_id", "is_active"),
        Index("idx_submission_assignment_list_definition", "list_definition_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, unique=True, server_default=text("uuidv7()")
    )
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    public_slug: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    tag_filter: Mapped[str | None] = mapped_column(Text)
    offset_days_before: Mapped[int | None] = mapped_column(Integer)
    offset_days_after: Mapped[int | None] = mapped_column(Integer)
    list_definition_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("list_definition.id", ondelete="RESTRICT"))
    deadline: Mapped[date | None] = mapped_column(Date)
    allowed_file_types: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"), default=list)
    max_files_per_element: Mapped[int | None] = mapped_column(Integer, server_default=text("5"))
    max_file_size_mb: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("20"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("TRUE"))
    sort_order: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'date'"))
    responsible_participant_source: Mapped[str | None] = mapped_column(Text)


class SubmissionUpload(Base, TimestampMixin):
    """Append-only Log der Abgabe-Ereignisse (Erstabgabe/Reopen/erneute Abgabe) je Element.

    Bewusst append-only statt mutierbar: die restricted Postgres-Rolle des separaten
    abgabebox-backend-Service darf auf dieser Tabelle nur INSERT (kein UPDATE/DELETE),
    damit ein kompromittierter öffentlicher Prozess frühere Abgaben nicht verändern kann.
    Der aktuelle Zustand eines Elements ist der Status der Zeile mit der höchsten id
    je (assignment_id, event_id|list_entry_id).
    """

    __tablename__ = "submission_upload"
    __table_args__ = (
        CheckConstraint(
            "(event_id IS NOT NULL AND list_entry_id IS NULL) OR (event_id IS NULL AND list_entry_id IS NOT NULL)",
            name="ck_submission_upload_exactly_one_target",
        ),
        # 'reopened' bleibt in der CHECK-Liste fuer historische Zeilen aus vor der 2026-08-17
        # Umstellung auf kumulative Uploads (siehe submission_service.py) - der Service erzeugt
        # diesen Wert nicht mehr neu, behandelt ihn aber weiterhin gleichwertig zu 'submitted'.
        CheckConstraint("status IN ('submitted', 'reopened', 'closed')", name="ck_submission_upload_status"),
        Index("idx_submission_upload_assignment_event", "assignment_id", "event_id"),
        Index("idx_submission_upload_assignment_list_entry", "assignment_id", "list_entry_id"),
        Index("idx_submission_upload_event", "event_id"),
        Index("idx_submission_upload_list_entry", "list_entry_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, unique=True, server_default=text("uuidv7()")
    )
    assignment_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("submission_assignment.id", ondelete="CASCADE"), nullable=False)
    event_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("event.id", ondelete="CASCADE"))
    list_entry_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("list_entry.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(Text, nullable=False)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SubmissionUploadFile(Base, TimestampMixin):
    __tablename__ = "submission_upload_file"
    __table_args__ = (
        UniqueConstraint("upload_id", "sort_index", name="uq_submission_upload_file_sort"),
        Index("idx_submission_upload_file_upload", "upload_id"),
        Index("idx_submission_upload_file_stored_file", "stored_file_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, unique=True, server_default=text("uuidv7()")
    )
    upload_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("submission_upload.id", ondelete="CASCADE"), nullable=False)
    stored_file_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("stored_file.id", ondelete="RESTRICT"), nullable=False)
    sort_index: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    delete_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Set by photo_album_service.sync_submission_uploads once this file has been folded
    # into its target album(s) - NULL means "not yet synced" (or synced before this column
    # existed, in which case the next tick treats it as new; harmless, add_items is
    # idempotent). Bounds that periodic sweep to new-since-last-tick rows instead of
    # re-scanning every clean image submission ever uploaded on every tick, forever.
    album_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SubmissionUploadLog(Base):
    __tablename__ = "submission_upload_log"
    __table_args__ = (
        Index("idx_upload_log_assignment_element", "assignment_id", "element_ref"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, unique=True, server_default=text("uuidv7()")
    )
    assignment_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("submission_assignment.id", ondelete="CASCADE"), nullable=False)
    element_ref: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))


class SystemErrorLog(Base):
    """App-wide captured backend errors - visible only in the platform-admin panel, never
    surfaced to a customer/public request (see the global exception handlers in
    backend/app/main.py and abgabebox-backend/app/main.py, and app/core/error_log.py)."""

    __tablename__ = "system_error_log"
    __table_args__ = (
        CheckConstraint("source IN ('backend', 'abgabebox-backend')", name="ck_system_error_log_source"),
        Index("idx_system_error_log_created", "created_at"),
        Index("idx_system_error_log_tenant", "tenant_id", "created_at"),
        Index("idx_system_error_log_type", "error_type", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, unique=True, server_default=text("uuidv7()")
    )
    source: Mapped[str] = mapped_column(Text, nullable=False)
    tenant_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("tenant.id", ondelete="SET NULL"))
    actor_email: Mapped[str | None] = mapped_column(Text)
    request_method: Mapped[str | None] = mapped_column(Text)
    request_path: Mapped[str | None] = mapped_column(Text)
    status_code: Mapped[int | None] = mapped_column(Integer)
    error_type: Mapped[str] = mapped_column(Text, nullable=False)
    error_message: Mapped[str] = mapped_column(Text, nullable=False)
    traceback: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))


class PhotoAlbum(Base, TimestampMixin):
    """`kind` distinguishes an admin-created album ("manual") from the three auto-generated
    kinds this table also holds (see photo_album_service.py): one per Zyklus+Periode
    ("cycle"), one per Abgabe ("submission"), one per Abgabe-Element ("submission_element").
    Exactly one of (cycle_config_id, cycle_year) / submission_assignment_id (+ optionally
    submission_element_ref) is set, matching `kind` - see migration 0068's
    ck_photo_album_kind_fields, enforced in Postgres rather than just in Python since
    get_or_create_*_album()'s uniqueness guarantee (the partial unique indexes from that
    same migration) depends on it."""

    __tablename__ = "photo_album"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'manual'"))
    cycle_config_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("cycle_config.id", ondelete="CASCADE"))
    cycle_year: Mapped[int | None] = mapped_column(SmallInteger)
    submission_assignment_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("submission_assignment.id", ondelete="CASCADE"))
    # "event-<public_id>" / "entry-<public_id>", same format as SubmissionUploadLog.element_ref
    # (see submission_service.py's _element_ref) - only set when kind == "submission_element".
    submission_element_ref: Mapped[str | None] = mapped_column(Text)


class PhotoAlbumItem(Base):
    __tablename__ = "photo_album_item"

    album_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("photo_album.id", ondelete="CASCADE"), primary_key=True)
    # Overview IDs cover both StoredFile and SubmissionUploadFile.
    file_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    # Current resolved best-of ("Stern") state - auto-recomputed (see
    # photo_album_service.recompute_best_of) except where best_override pins it.
    is_best: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("FALSE"), default=False)
    # A user's manual "immer im Best-of" / "nie im Best-of" pick, surviving future
    # recomputes. NULL = automatically managed (the common case).
    best_override: Mapped[str | None] = mapped_column(Text)


class PhotoAnalysisJob(Base, TimestampMixin):
    """Phase 3 of the photo-culling feature: a batch of stored_file rows queued for the
    separate photo-analysis-worker container to score (currently: face_quality_score).
    Written/read here by the backend (hocx_app); the worker itself connects as the
    separate, minimally-privileged hocx_photo_worker role (see migration 0067) and only
    ever transitions status/started_at/finished_at/error on a row it already sees."""

    __tablename__ = "photo_analysis_job"
    __table_args__ = (
        Index("idx_photo_analysis_job_tenant", "tenant_id"),
        Index("idx_photo_analysis_job_status_created", "status", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()"))
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'queued'"))
    stored_file_ids: Mapped[list[int]] = mapped_column(JSONB, nullable=False)
    requested_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app_user.id", ondelete="SET NULL"))
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GalleryUploadJob(Base, TimestampMixin):
    """Backs the "Bilder hochladen" gallery upload window's async ingestion (see
    app/main.py's gallery_upload_ingest_loop and FileService.process_pending_gallery_upload_jobs) -
    the upload request only stages the raw file(s) to disk and creates this row; scanning,
    ZIP extraction, thumbnailing and StoredFile/GalleryImage creation all happen later, off
    the request's event loop, so a multi-GB ZIP doesn't have to be buffered or fully
    processed before the upload dialog can close. Stays inside hocx_app (unlike
    PhotoAnalysisJob, no separate worker/role - this reuses the backend's own ClamAV
    connectivity and DB access)."""

    __tablename__ = "gallery_upload_job"
    __table_args__ = (Index("idx_gallery_upload_job_tenant_status", "tenant_id", "status"),)

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()"))
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'queued'"))
    # Storage-relative paths of the raw upload(s) staged by the request handler - see
    # FileService.stage_gallery_upload.
    staged_paths: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    tags: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    # At most one of these three targets is ever set - mirrors upload_gallery_images' own
    # mutual-exclusion check.
    upload_event_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("event.id", ondelete="SET NULL"))
    upload_assignment_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("submission_assignment.id", ondelete="SET NULL")
    )
    upload_element_ref: Mapped[str | None] = mapped_column(Text)
    # Resolved once, at request time, from upload_assignment_id + upload_element_ref (see
    # upload_gallery_images) - saves the ingest loop from re-resolving it via
    # submission_service on every job it processes.
    upload_element_label: Mapped[str | None] = mapped_column(Text)
    upload_cycle_config_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("cycle_config.id", ondelete="SET NULL"))
    requested_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app_user.id", ondelete="SET NULL"))
    # Unknown until a ZIP is opened and its matching entries counted; known immediately for
    # a batch of individually-selected images.
    total_files: Mapped[int | None] = mapped_column(Integer)
    processed_files: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    # StoredFile.public_id values (as str, not the internal bigint PhotoAnalysisJob.
    # stored_file_ids uses) - this job's whole purpose downstream is building the
    # FileOverviewItem list a job-detail response returns, which needs public ids anyway
    # (see FileService.list_tenant_files' file_ids param).
    imported_file_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    # Per-file problems (too large, unsupported format, infected, corrupt ZIP entry, ...) -
    # same partial-success shape the old synchronous route's GalleryUploadResult had.
    errors: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    # Fatal/unexpected exception text, distinct from the per-file `errors` above.
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
