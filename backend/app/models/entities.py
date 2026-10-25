from __future__ import annotations

import uuid
from datetime import date, datetime, time
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Computed,
    Date,
    DateTime,
    FetchedValue,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    SmallInteger,
    Table,
    Text,
    Time,
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
    # NULL = kein Limit. Immer Plan + Zusatzpakete (AdminTenantService.
    # recompute_effective_storage_quota), seit 0136 ohne manuellen Override.
    storage_quota_bytes: Mapped[int | None] = mapped_column(BigInteger)
    # Preismodell (0085_plan_pricing): plan_code ist der aktuelle Vertrag, tenant_feature bleibt
    # aber die alleinige Quelle der Wahrheit fuers Enforcement - ein Plan-Wechsel im Adminportal
    # traegt seine plan_feature-Zeilen nur als Baseline in tenant_feature ein, entfernt aber keine
    # einzeln zugebuchten Zusatzmodule. NULL = kein Plan zugewiesen (sollte nach dem Backfill
    # praktisch nie vorkommen, siehe Migration).
    plan_code: Mapped[str | None] = mapped_column(Text, ForeignKey("plan.code", ondelete="SET NULL"))
    billing_cycle: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'monthly'"))
    # Ueberschreibt plan.included_user_limit, wenn gesetzt (analog zu storage_quota_bytes als
    # Override-Mechanismus). NULL = das Limit des Plans gilt.
    user_limit_override: Mapped[int | None] = mapped_column(Integer)
    # Abo-Konditionen aus dem Adminportal (0089_plan_catalog_details): Rabatt in Prozent auf Plan
    # + Zusatzmodule und eine nur intern sichtbare Notiz (z.B. "Vereinsrabatt bis 2027").
    discount_percent: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("0"))
    billing_note: Mapped[str | None] = mapped_column(Text)
    # Auf der oeffentlichen Website unter "Im Einsatz bei" gelistet (0104_tenant_show_on_website).
    show_on_website: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("FALSE"))
    # Standardsprache erzeugter Dokumente (Dokument-Engine), pro Export überschreibbar.
    # NULL = Standardsprache aus i18n/locales.json.
    document_language: Mapped[str | None] = mapped_column(Text)
    # Öffentliche Prüfseite (Abgabebox /verify): Name und Logo zeigen, auf neuere Versionen
    # hinweisen. Die Freigabelogik selbst steckt in der View document_verification_public.
    verify_show_identity: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("FALSE"), default=False)
    verify_show_newer_version: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("TRUE"), default=True)
    # Bussen und Anwesenheit je Person in der Statistik für alle Mitglieder sichtbar (0138). Standard
    # aus: Leser sehen dort nur ihre eigene Zeile, wie in der Bussenliste (Datenschutz-Audit PRIV-001).
    statistics_per_person_public: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("FALSE"), default=False)
    # Identität der Organisation durch einen Plattform-Admin bestätigt (Abzeichen auf der
    # Prüfseite). Eine Namensänderung hebt die Bestätigung auf (revoked_*).
    identity_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    identity_verified_by_admin_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("platform_admin.id", ondelete="SET NULL"))
    identity_verification_note: Mapped[str | None] = mapped_column(Text)
    identity_verification_revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    identity_verification_revoked_reason: Mapped[str | None] = mapped_column(Text)
    # Cashflow im Adminportal (0127_cashflow): ab diesem Datum entstehen Forderungen je
    # Abrechnungsperiode (NULL = Erstellungsdatum). billing_charged_until ist der Cursor der
    # Forderungserzeugung - bis hierhin sind alle Perioden abgerechnet (siehe cashflow_service).
    billing_start_date: Mapped[date | None] = mapped_column(Date)
    # Vertragsende für das Offboarding (0146, Check tenant_offboarding in system_health_service)
    contract_ends_on: Mapped[date | None] = mapped_column(Date)
    # Datenschutzhinweise des Vereins für die Abgabebox (0147, abgabebox_privacy_notice())
    privacy_notice_url: Mapped[str | None] = mapped_column(Text)
    billing_charged_until: Mapped[date | None] = mapped_column(Date)


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
        # Eindeutig nur unter aktiven Domains (Migration 0129, Security-Audit SEC-004): eine
        # unbestätigte (pending) Domain darf die Domain für andere Mandanten nicht blockieren.
        Index("uq_tenant_domain_active_domain", "domain", unique=True, postgresql_where=text("status = 'active'")),
        CheckConstraint("purpose IN ('app', 'abgabebox', 'verify')", name="ck_tenant_domain_purpose"),
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


class Feature(Base):
    """Katalog buchbarer Mandanten-Features (Feature-Gating), orthogonal zu Rollen: eine Rolle
    steuert, was ein Nutzer innerhalb seines Mandanten darf, `tenant_feature` steuert, ob ein
    Feature für den Mandanten überhaupt gebucht ist. Seed-Zeilen kommen aus der zugehörigen
    Migration, nicht aus baseline_lookup_data.sql (dieser Katalog existiert erst seit der
    Feature-Gating-Einführung, nach dem 0001-Baseline-Squash)."""

    __tablename__ = "feature"

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    # Rappen, nicht Franken (Rundungsfehler) - NULL, wenn das Feature nie einzeln zugebucht
    # werden kann, sondern nur gebuendelt ueber einen Plan verfuegbar ist.
    standalone_price_monthly_rp: Mapped[int | None] = mapped_column(Integer)


class Plan(Base):
    """Preiskatalog-Eintrag. Ein Plan bundlet Features (plan_feature) und Limits; die Zuweisung
    an einen Mandanten (Tenant.plan_code) traegt beim Wechsel nur eine Baseline in
    tenant_feature ein - siehe Kommentar an Tenant.plan_code."""

    __tablename__ = "plan"

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    price_monthly_rp: Mapped[int | None] = mapped_column(Integer)
    price_yearly_rp: Mapped[int | None] = mapped_column(Integer)
    # NULL = kein Limit (z.B. der 'legacy'-Plan fuer Bestandsmandanten oder ein Premium-Tarif).
    included_user_limit: Mapped[int | None] = mapped_column(Integer)
    included_storage_bytes: Mapped[int | None] = mapped_column(BigInteger)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    description: Mapped[str | None] = mapped_column(Text)
    # False = erscheint nicht bei "Neuer Mandant", kann aber einzelnen Mandanten zugewiesen
    # werden (z.B. 'legacy' fuer Bestandsmandanten).
    is_bookable: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("TRUE"))
    # Auf der oeffentlichen Website als "Beliebteste Wahl" hervorgehoben (0103_plan_is_featured).
    # Hoechstens ein Plan - upsert_plan setzt beim Markieren alle anderen zurueck.
    is_featured: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("FALSE"))
    # Priorität bei Überlast (0151_overload_priority): 0 niedrig, 1 normal, 2 hoch. Wird es knapp,
    # sehen neue Nutzer von Mandanten mit niedriger Priorität zuerst die Überlast-Seite
    # (app/core/db_admission.py).
    load_priority: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("1"), default=1)


class PlanFeature(Base):
    __tablename__ = "plan_feature"

    plan_code: Mapped[str] = mapped_column(Text, ForeignKey("plan.code", ondelete="CASCADE"), primary_key=True)
    feature_code: Mapped[str] = mapped_column(Text, ForeignKey("feature.code", ondelete="CASCADE"), primary_key=True)


class TenantFeature(Base, TimestampMixin):
    __tablename__ = "tenant_feature"
    __table_args__ = (
        UniqueConstraint("tenant_id", "feature_code", name="uq_tenant_feature_tenant_code"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, unique=True, server_default=text("uuidv7()")
    )
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False)
    feature_code: Mapped[str] = mapped_column(Text, ForeignKey("feature.code", ondelete="CASCADE"), nullable=False)
    enabled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))
    enabled_by_admin_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("platform_admin.id", ondelete="SET NULL"))


class StoragePackage(Base):
    """Zusatzpaket-Katalogeintrag (0087_storage_packages), analog zu Plan: ein fester Preis fuer
    ein festes Bytes-Kontingent, das ein Mandant zusaetzlich zum Plan zubuchen kann."""

    __tablename__ = "storage_package"

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    price_monthly_rp: Mapped[int | None] = mapped_column(Integer)
    price_yearly_rp: Mapped[int | None] = mapped_column(Integer)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    # False = kann keinem Mandanten mehr neu zugebucht werden, bestehende Zuweisungen bleiben
    # (0106_storage_package_is_bookable, gesetzt u.a. vom Katalog-Import im Überschreiben-Modus).
    is_bookable: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("TRUE"))


class TenantStoragePackage(Base):
    """Zuweisung eines Zusatzpakets an einen Mandanten inkl. Menge - geht in
    AdminTenantService.recompute_effective_storage_quota() ein, das Tenant.storage_quota_bytes
    neu berechnet (Plan-Kontingent + Summe dieser Zeilen)."""

    __tablename__ = "tenant_storage_package"
    __table_args__ = (
        UniqueConstraint("tenant_id", "package_code", name="uq_tenant_storage_package_tenant_code"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False)
    package_code: Mapped[str] = mapped_column(Text, ForeignKey("storage_package.code", ondelete="CASCADE"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))
    added_by_admin_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("platform_admin.id", ondelete="SET NULL"))


class Role(Base):
    __tablename__ = "role"

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    code: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text)


class Participant(Base, TimestampMixin, UpdatedAtMixin):
    __tablename__ = "app_user"
    __table_args__ = (
        Index("uq_app_user_login_email", "email", unique=True, postgresql_where=text("login_enabled")),
        CheckConstraint("NOT login_enabled OR (email IS NOT NULL AND email <> '' AND password_hash IS NOT NULL)", name="ck_app_user_login_credentials"),
        CheckConstraint(
            "preferred_mfa_factor_type IN ('totp', 'webauthn')",
            name="ck_app_user_preferred_mfa_factor_type",
        ),
        Index("idx_app_user_tenant_role", "tenant_id", "role_id"),
        Index("idx_app_user_email", "email"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, unique=True, server_default=text("uuidv7()")
    )
    # A user belongs to exactly one tenant with exactly one role. Deleting the tenant deletes
    # its users (every other FK into app_user is CASCADE or SET NULL, so this never blocks).
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False)
    role_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("role.id", ondelete="RESTRICT"), nullable=False)
    first_name: Mapped[str | None] = mapped_column(Text)
    last_name: Mapped[str | None] = mapped_column(Text)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, Computed("display_name", persisted=True))
    email: Mapped[str | None] = mapped_column(Text)
    password_hash: Mapped[str | None] = mapped_column(Text)
    login_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("FALSE"), default=False)
    joined_at: Mapped[date | None] = mapped_column(Date)
    left_at: Mapped[date | None] = mapped_column(Date)
    preferred_language: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'de'"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("TRUE"))
    session_revoke_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    preferred_mfa_factor_type: Mapped[str | None] = mapped_column(Text)
    external_identity_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"), default=dict)


# Authentifizierung und Teilnahme verwenden denselben Datensatz.
AppUser = Participant


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
    # Optionale Uhrzeit (z. B. Beginn der nächsten Sitzung), NULL = ganztägig
    start_time: Mapped[time | None] = mapped_column(Time)
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
    column match) - never mutated after insert. Used to learn adaptive per-tenant score
    thresholds (see word_import_thresholds.adaptive_threshold)."""

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


class DocumentAsset(Base, TimestampMixin):
    """Hochgeladene Datei des Document Studio: Bild (Logo, Briefkopf, Hintergrund, Wasserzeichen,
    Grafik) oder Schrift. Kein Code. Brand-Profile und Vorlagen referenzieren Assets über ihre
    ``public_id``; aufgelöst wird immer mandantengebunden."""

    __tablename__ = "document_asset"
    __table_args__ = (
        CheckConstraint("kind IN ('image', 'font')", name="ck_document_asset_kind"),
        CheckConstraint(
            "category IN ('logo', 'letterhead', 'background', 'watermark', 'graphic', 'image', 'font')",
            name="ck_document_asset_category",
        ),
        Index("idx_document_asset_tenant", "tenant_id", "kind"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, unique=True, server_default=text("uuidv7()")
    )
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'image'"), default="image")
    name: Mapped[str] = mapped_column(Text, nullable=False)
    original_name: Mapped[str | None] = mapped_column(Text)
    mime_type: Mapped[str | None] = mapped_column(Text)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    checksum_sha256: Mapped[str | None] = mapped_column(Text)
    width_px: Mapped[int | None] = mapped_column(Integer)
    height_px: Mapped[int | None] = mapped_column(Integer)
    # Familienname aus der Schriftdatei (nur kind='font')
    font_family: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app_user.id", ondelete="SET NULL"))


class DocumentBrand(Base, TimestampMixin, UpdatedAtMixin):
    """Brand-Profil (Corporate Design) eines Mandanten. Der Inhalt steht in unveränderlichen
    Revisionen (document_brand_revision); ``current_revision`` ist die gültige. ``lock_version``
    erkennt parallele Bearbeitung (optimistische Sperre)."""

    __tablename__ = "document_brand"
    __table_args__ = (
        CheckConstraint("current_revision >= 1", name="ck_document_brand_revision_positive"),
        Index("idx_document_brand_tenant", "tenant_id"),
        Index("uq_document_brand_default", "tenant_id", unique=True, postgresql_where=text("is_default")),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, unique=True, server_default=text("uuidv7()")
    )
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("FALSE"), default=False)
    current_revision: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"), default=1)
    lock_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"), default=1)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app_user.id", ondelete="SET NULL"))
    updated_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app_user.id", ondelete="SET NULL"))


class DocumentBrandRevision(Base):
    """Unveränderlicher Stand eines Brand-Profils (app.documents.brand.BrandTokens). Jede
    gespeicherte Änderung erzeugt eine neue Revision; Exporte halten die verwendete fest."""

    __tablename__ = "document_brand_revision"
    __table_args__ = (UniqueConstraint("brand_id", "revision", name="uq_document_brand_revision"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, unique=True, server_default=text("uuidv7()")
    )
    brand_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("document_brand.id", ondelete="CASCADE"), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    tokens_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"), default=dict)
    tokens_hash: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))
    created_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app_user.id", ondelete="SET NULL"))


class DocumentTemplate(Base, TimestampMixin, UpdatedAtMixin):
    """Dokumentvorlage des Document Studio. ``tenant_id`` NULL = Systemvorlage von hocX
    (``system_key``, nie direkt überschreibbar). ``origin``: system / tenant (eigene Vorlage) /
    copy (angepasste Kopie einer Systemvorlage, ``source_template_id``). Der Inhalt steht in
    Revisionen; ``published_revision_id`` ist die für Exporte gültige."""

    __tablename__ = "document_template"
    __table_args__ = (
        CheckConstraint("origin IN ('system', 'tenant', 'copy')", name="ck_document_template_origin"),
        CheckConstraint("status IN ('active', 'archived')", name="ck_document_template_status"),
        CheckConstraint("(tenant_id IS NULL) = (origin = 'system')", name="ck_document_template_system_tenant"),
        Index("idx_document_template_tenant", "tenant_id", "document_type"),
        Index("uq_document_template_system_key", "system_key", unique=True, postgresql_where=text("system_key IS NOT NULL")),
        Index("uq_document_template_platform_default", "document_type", unique=True, postgresql_where=text("tenant_id IS NULL AND is_platform_default")),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, unique=True, server_default=text("uuidv7()")
    )
    tenant_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"))
    system_key: Mapped[str | None] = mapped_column(Text)
    origin: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'tenant'"), default="tenant")
    source_template_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("document_template.id", ondelete="SET NULL"))
    source_revision_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("document_template_revision.id", ondelete="SET NULL", use_alter=True))
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    document_type: Mapped[str] = mapped_column(Text, nullable=False)
    variant: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'general'"), default="general")
    # Brand-Profil der Vorlage; NULL = Standard-Brand des exportierenden Mandanten
    brand_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("document_brand.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'active'"), default="active")
    published_revision_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("document_template_revision.id", ondelete="SET NULL", use_alter=True))
    # Plattform-Standard je Dokumenttyp (nur Systemvorlagen)
    is_platform_default: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("FALSE"), default=False)
    sort_index: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), default=0)
    created_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app_user.id", ondelete="SET NULL"))
    updated_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app_user.id", ondelete="SET NULL"))


class DocumentTemplateRevision(Base):
    """Revision einer Dokumentvorlage. ``draft`` (höchstens eine je Vorlage, per Autosave
    bearbeitbar, ``lock_version`` gegen parallele Änderungen), ``published`` (gültig für
    Exporte) und ``superseded`` (frühere Veröffentlichung). Veröffentlichte und abgelöste
    Revisionen sind unveränderlich (DB-Trigger ``trg_document_template_revision_immutable``).
    ``content_json`` folgt app.documents.layout.TemplateContent."""

    __tablename__ = "document_template_revision"
    __table_args__ = (
        UniqueConstraint("template_id", "revision_no", name="uq_document_template_revision_no"),
        CheckConstraint("status IN ('draft', 'published', 'superseded')", name="ck_document_template_revision_status"),
        CheckConstraint("brand_mode IN ('follow', 'pinned')", name="ck_document_template_revision_brand_mode"),
        Index("uq_document_template_revision_draft", "template_id", unique=True, postgresql_where=text("status = 'draft'")),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, unique=True, server_default=text("uuidv7()")
    )
    template_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("document_template.id", ondelete="CASCADE"), nullable=False)
    revision_no: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'draft'"), default="draft")
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    content_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    # follow = aktuelle Revision des Brand-Profils, pinned = beim Veröffentlichen festgehaltene
    brand_mode: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'follow'"), default="follow")
    brand_revision_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("document_brand_revision.id", ondelete="SET NULL"))
    lock_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"), default=1)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))
    created_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app_user.id", ondelete="SET NULL"))
    updated_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app_user.id", ondelete="SET NULL"))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app_user.id", ondelete="SET NULL"))


class DocumentComponent(Base, TimestampMixin, UpdatedAtMixin):
    """Wiederverwendbare Komponente eines Mandanten (ein Layoutknoten mit Kindern, z. B. ein
    eigener Briefkopf). Vorlagen verweisen über ``component_ref`` darauf."""

    __tablename__ = "document_component"
    __table_args__ = (Index("idx_document_component_tenant", "tenant_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, unique=True, server_default=text("uuidv7()")
    )
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'general'"), default="general")
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    node_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    lock_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"), default=1)
    created_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app_user.id", ondelete="SET NULL"))
    updated_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app_user.id", ondelete="SET NULL"))


class DocumentTemplateAssignment(Base):
    """Standardvorlage je Dokumenttyp eines Mandanten, optional nur für eine Protokollvorlage
    (``protocol_template_id``). Priorität beim Export: explizit gewählt > Zuweisung der
    Protokollvorlage > Mandanten-Standard > Plattform-Standard (siehe template_service)."""

    __tablename__ = "document_template_assignment"
    __table_args__ = (
        CheckConstraint(
            "document_template_id IS NOT NULL OR brand_id IS NOT NULL", name="ck_document_template_assignment_target"
        ),
        Index(
            "uq_document_template_assignment_tenant",
            "tenant_id",
            "document_type",
            unique=True,
            postgresql_where=text("protocol_template_id IS NULL"),
        ),
        Index(
            "uq_document_template_assignment_protocol_template",
            "tenant_id",
            "document_type",
            "protocol_template_id",
            unique=True,
            postgresql_where=text("protocol_template_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False)
    document_type: Mapped[str] = mapped_column(Text, nullable=False)
    protocol_template_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("template.id", ondelete="CASCADE"))
    # Vorlage und/oder Brand-Profil (z. B. eigenes Logo für eine Untergruppe); NULL = nächste Stufe
    document_template_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("document_template.id", ondelete="CASCADE"))
    brand_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("document_brand.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))
    created_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app_user.id", ondelete="SET NULL"))


class DocumentExport(Base, TimestampMixin):
    """Ein Datensatz pro erzeugtem PDF. ``public_id`` ist die Dokument-ID im PDF (Fusszeile,
    XMP). Hält fest, womit das PDF entstand: Inhalts-Hash (fachlicher Inhalt), Design-Hash
    (Vorlagenrevision, Brand-Revision, Assets), Vorlagen- und Brand-Revision und Sprache."""

    __tablename__ = "document_export"
    __table_args__ = (
        Index("idx_document_export_protocol", "protocol_id", "created_at"),
        Index("idx_document_export_tenant", "tenant_id", "created_at"),
        Index("idx_document_export_stored_file", "stored_file_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, unique=True, server_default=text("uuidv7()")
    )
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False)
    protocol_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("protocol.id", ondelete="CASCADE"))
    document_type: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    version_label: Mapped[str | None] = mapped_column(Text)
    version_major: Mapped[int | None] = mapped_column(Integer)
    version_minor: Mapped[int | None] = mapped_column(Integer)
    content_hash: Mapped[str | None] = mapped_column(Text)
    design_hash: Mapped[str | None] = mapped_column(Text)
    template_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("document_template.id", ondelete="SET NULL"))
    template_revision_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("document_template_revision.id", ondelete="SET NULL"))
    brand_revision_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("document_brand_revision.id", ondelete="SET NULL"))
    options_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"), default=dict)
    language: Mapped[str | None] = mapped_column(Text)
    stored_file_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("stored_file.id", ondelete="SET NULL"))
    created_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app_user.id", ondelete="SET NULL"))



class DocumentRegistry(Base):
    """Register aller ausgelieferten PDFs: SHA-256 der exakt ausgelieferten Bytes. Dauerhaft -
    der Retention-Job löscht nur Dateien, nie Einträge; nur das Löschen des Mandanten entfernt
    sie. public_id = Dokument-ID im PDF (= document_export.public_id). Öffentlich geprüft wird
    ausschliesslich über die Funktion verify_document (Migration 0117)."""

    __tablename__ = "document_registry"
    __table_args__ = (
        UniqueConstraint("sha256", name="uq_document_registry_sha256"),
        CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="ck_document_registry_sha256"),
        Index("idx_document_registry_tenant", "tenant_id", "created_at"),
        Index("idx_document_registry_source_version", "tenant_id", "source_public_id", "version_major", "version_minor"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, unique=True, server_default=text("uuidv7()")
    )
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False)
    sha256: Mapped[str] = mapped_column(Text, nullable=False)
    document_type: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    status_code: Mapped[str | None] = mapped_column(Text)
    version_major: Mapped[int | None] = mapped_column(Integer)
    version_minor: Mapped[int | None] = mapped_column(Integer)
    version_label: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str | None] = mapped_column(Text)
    # Design-Hash (Vorlage, Brand, Assets) - nur informativ, geprüft wird über sha256
    design_hash: Mapped[str | None] = mapped_column(Text)
    # public_id des Protokolls, bewusst ohne FK (überlebt Löschen und Mandanten-Umzug)
    source_public_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))
    created_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app_user.id", ondelete="SET NULL"))
    # TYPST-007: aus einem Archiv importiert, ohne dass dessen PDF diesen Hash belegt hätte
    # (Migration 0119_registry_import_unverified); die Prüfseite kennzeichnet solche Einträge.
    import_unverified: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"), default=False)
    # STUDIO-007: Titel beim Export abweichend vom Protokoll gesetzt (Migration 0120)
    title_overridden: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"), default=False)


class IdentityVerificationRequest(Base):
    """Antrag eines Mandanten-Admins auf Bestätigung der Organisation durch hocX. Ein
    Plattform-Admin bestätigt (setzt tenant.identity_verified_*) oder lehnt mit Begründung ab.
    Höchstens ein offener Antrag je Mandant; der Verlauf bleibt erhalten."""

    __tablename__ = "identity_verification_request"
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'approved', 'rejected', 'withdrawn')", name="ck_identity_verification_request_status"),
        Index("uq_identity_verification_request_pending", "tenant_id", unique=True, postgresql_where=text("status = 'pending'")),
        Index("idx_identity_verification_request_tenant", "tenant_id", "requested_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, unique=True, server_default=text("uuidv7()")
    )
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'pending'"), default="pending")
    tenant_name: Mapped[str] = mapped_column(Text, nullable=False)
    message: Mapped[str | None] = mapped_column(Text)
    requested_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app_user.id", ondelete="SET NULL"))
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))
    decided_by_admin_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("platform_admin.id", ondelete="SET NULL"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_note: Mapped[str | None] = mapped_column(Text)


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
        Index("idx_template_created_by", "created_by"),
        Index("idx_template_cycle_config", "cycle_config_id"),
        CheckConstraint("fine_amount_late >= 0 AND fine_amount_absent >= 0", name="ck_template_fine_amounts"),
        Index("idx_template_fine_account", "fine_account_id", postgresql_where=text("fine_account_id IS NOT NULL")),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, unique=True, server_default=text("uuidv7()")
    )
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False)
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
    # Eigener Bussentarif der Vorlage (0137, FAR-002). False = Mandantentarif (FineTariff) gilt;
    # gelesen in fine_tariff_service.tariff_block_values, live für alle Protokolle der Vorlage.
    fine_tariff_override: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("FALSE"))
    fine_account_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("finance_account.id", ondelete="SET NULL"))
    fine_amount_late: Mapped[float] = mapped_column(Numeric(15, 2), nullable=False, server_default=text("0"))
    fine_amount_absent: Mapped[float] = mapped_column(Numeric(15, 2), nullable=False, server_default=text("0"))


class TemplateParticipant(Base, TimestampMixin):
    __tablename__ = "template_participant"
    __table_args__ = (
        PrimaryKeyConstraint("template_id", "participant_id", name="pk_template_participant"),
        Index("idx_template_participant_template", "template_id"),
        Index("idx_template_participant_participant", "participant_id"),
    )

    template_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("template.id", ondelete="CASCADE"), nullable=False)
    participant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
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
        Index("idx_protocol_created_by", "created_by"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, unique=True, server_default=text("uuidv7()")
    )
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False)
    template_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("template.id", ondelete="RESTRICT"), nullable=False)
    template_version: Mapped[int] = mapped_column(Integer, nullable=False)
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
    # Stand aller Todos beim Abschliessen (siehe ProtocolTodoService.build_protocol_snapshot);
    # NULL solange nicht abgeschlossen bzw. nach dem Zurücksetzen.
    todos_snapshot_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
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
    configuration_snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"), default=dict)
    # Zählt jede Änderung von configuration_snapshot_json (Trigger, Migration 0149) - optimistische
    # Sperre des Konfigurations-PATCH. FetchedValue: nach jedem UPDATE neu laden.
    config_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), server_onupdate=FetchedValue())


Index("idx_protocol_element_block_render", ProtocolElementBlock.protocol_element_id, text("COALESCE(render_order, sort_index)"))


class StoredFile(Base, TimestampMixin):
    __tablename__ = "stored_file"
    __table_args__ = (
        Index("idx_stored_file_tenant_checksum", "tenant_id", "checksum_sha256"),
        Index("idx_stored_file_tenant_source_checksum", "tenant_id", "source_checksum_sha256"),
        Index("idx_stored_file_tenant", "tenant_id"),
        Index("idx_stored_file_tags_gin", "tags", postgresql_using="gin"),
        Index("idx_stored_file_created_by", "created_by"),
        Index(
            "idx_stored_file_scan_status_pending",
            "scan_status",
            postgresql_where=text("scan_status <> 'clean'"),
        ),
        Index("idx_stored_file_tenant_gps", "tenant_id", postgresql_where=text("gps_latitude IS NOT NULL")),
        Index(
            "idx_stored_file_metadata_backfill",
            "id",
            postgresql_where=text("metadata_scanned_at IS NULL AND mime_type LIKE 'image/%'"),
        ),
        CheckConstraint("(gps_latitude IS NULL) = (gps_longitude IS NULL)", name="ck_stored_file_gps_pair"),
        CheckConstraint(
            "gps_latitude IS NULL OR (gps_latitude BETWEEN -90 AND 90 AND gps_longitude BETWEEN -180 AND 180)",
            name="ck_stored_file_gps_range",
        ),
        CheckConstraint(
            "gps_direction_deg IS NULL OR (gps_direction_deg >= 0 AND gps_direction_deg < 360)",
            name="ck_stored_file_gps_direction",
        ),
        CheckConstraint(
            "(exif_taken_source IS NULL OR exif_taken_source IN ('server', 'client', 'backfill'))"
            " AND (gps_source IS NULL OR gps_source IN ('server', 'client', 'backfill'))",
            name="ck_stored_file_metadata_source",
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
    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    checksum_sha256: Mapped[str | None] = mapped_column(Text)
    source_checksum_sha256: Mapped[str | None] = mapped_column(Text)
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
    # EXIF DateTimeOriginal/DigitizedDateTime (see file_service._extract_image_metadata),
    # persisted at ingest time so it can drive the Fotos gallery's sort/grouping and its
    # auto-link-to-Termin matching (see photo_event_link_service.py) without re-reading
    # every file from disk on each request. None for non-images, images PIL couldn't
    # decode, images without EXIF, and files uploaded before this column existed.
    exif_taken_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Konvention (seit 0083): exif_taken_at haelt die lokale Uhrzeit der Kamera, gespeichert
    # als waere sie UTC ("floating"), damit cast(... AS date) immer den Kalendertag des
    # Fotografen liefert. Ein vorhandener EXIF-Offset (OffsetTimeOriginal) steht separat hier.
    exif_taken_offset: Mapped[str | None] = mapped_column(Text)
    # "server" (Analyse beim Upload), "client" (vom Browser geliefert, nur fuer konvertierte
    # Bilder ohne serverseitig pruefbares Original) oder "backfill" - siehe image_metadata_service.
    exif_taken_source: Mapped[str | None] = mapped_column(Text)
    # Vom Benutzer geschaetztes Aufnahmedatum - bewusst reines Kalenderdatum ohne Uhrzeit oder
    # Zeitzone, getrennt von exif_taken_at (echt) und created_at (Upload). Prioritaet siehe
    # capture_date.py: exif_taken_at > estimated_taken_on > created_at.
    estimated_taken_on: Mapped[date | None] = mapped_column(Date)
    estimated_taken_set_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    estimated_taken_set_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app_user.id", ondelete="SET NULL"))
    # GPS (WGS84, Sued/West negativ) fuer eine spaetere Kartenansicht. Als Wert nur ueber
    # berechtigte, mandantengebundene Endpunkte lesbar (/metadata). Exportierte Dateikopien
    # (Download, auch fuer Partner-Mandanten geteilter Alben, und oeffentliche Freigaben, die
    # den Standort teilen) koennen nur in der DB vorhandenes GPS enthalten, siehe
    # image_export_service und UPLOAD_DUPLICATES.md §10/§11.
    gps_latitude: Mapped[float | None] = mapped_column(Float)
    gps_longitude: Mapped[float | None] = mapped_column(Float)
    gps_altitude_m: Mapped[float | None] = mapped_column(Float)
    gps_direction_deg: Mapped[float | None] = mapped_column(Float)
    gps_accuracy_m: Mapped[float | None] = mapped_column(Float)
    gps_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    gps_source: Mapped[str | None] = mapped_column(Text)
    camera_make: Mapped[str | None] = mapped_column(Text)
    camera_model: Mapped[str | None] = mapped_column(Text)
    orientation: Mapped[int | None] = mapped_column(SmallInteger)
    # Letzte serverseitige Metadatenanalyse (Upload oder Backfill) und ihr Ergebnis
    # ("ok", "no_metadata", "unreadable", "missing_file", "source_unavailable") - NULL heisst
    # "noch nie analysiert", der Backfill setzt genau dort an.
    metadata_scanned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_scan_status: Mapped[str | None] = mapped_column(Text)
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
        Index(
            "uq_protocol_todo_package_occurrence",
            "task_package_item_id", "cycle_config_id", "cycle_year", "occurrence_key",
            unique=True,
            postgresql_where=text("task_package_item_id IS NOT NULL"),
        ),
        Index("idx_protocol_todo_cycle", "cycle_config_id", "cycle_year"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, unique=True, server_default=text("uuidv7()")
    )
    # Jedes Todo gehört fest einem Mandanten (Migration 0131); der Protokollblock ist optional.
    # Bei Todos mit Block setzt der Trigger trg_protocol_todo_tenant_from_block den Wert aus dem
    # Protokoll - ohne Angabe lässt das ORM die Spalte im INSERT weg und liest sie danach nach.
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False, server_default=FetchedValue()
    )
    protocol_element_block_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("protocol_element_block.id", ondelete="CASCADE"))
    sort_index: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    task: Mapped[str] = mapped_column(Text, nullable=False)
    assigned_user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app_user.id", ondelete="SET NULL"))
    assigned_participant_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app_user.id", ondelete="SET NULL"))
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
    # Instanz einer Paket-Aufgabe (Migration 0111_task_packages): eine Zeile je
    # (Paket-Aufgabe, Zyklus, Zyklusjahr, Wiederholung). overridden_fields listet die Felder,
    # die von Hand geändert wurden und die das Paket darum nicht mehr überschreibt.
    task_package_item_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("task_package_item.id", ondelete="SET NULL"))
    cycle_config_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("cycle_config.id", ondelete="SET NULL"))
    cycle_year: Mapped[int | None] = mapped_column(Integer)
    occurrence_key: Mapped[str | None] = mapped_column(Text)
    overridden_fields: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"), default=list)
    # Freier Markdown-Text (Migration 0128) - nur im Todo-Popup, nie in Übersicht oder Export.
    notes: Mapped[str | None] = mapped_column(Text)


class ProtocolTodoAssignee(Base):
    """Weitere Verantwortliche eines Todos (z. B. alle Personen eines Ämtlis). Die erste Person
    steht zusätzlich in protocol_todo.assigned_participant_id, damit ältere Leser weiter
    funktionieren."""

    __tablename__ = "protocol_todo_assignee"
    __table_args__ = (
        PrimaryKeyConstraint("protocol_todo_id", "participant_id", name="pk_protocol_todo_assignee"),
        Index("idx_protocol_todo_assignee_participant", "participant_id"),
    )

    protocol_todo_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("protocol_todo.id", ondelete="CASCADE"), nullable=False)
    participant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    sort_index: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), default=0)


class ProtocolTodoFile(Base, TimestampMixin):
    """Mit einem Todo verknüpfte, bereits hochgeladene Datei (Migration 0128). Nur im
    Todo-Popup sichtbar, siehe ProtocolTodoService.get_details."""

    __tablename__ = "protocol_todo_file"
    __table_args__ = (
        PrimaryKeyConstraint("protocol_todo_id", "stored_file_id", name="pk_protocol_todo_file"),
        Index("idx_protocol_todo_file_stored_file", "stored_file_id"),
    )

    protocol_todo_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("protocol_todo.id", ondelete="CASCADE"), nullable=False)
    stored_file_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("stored_file.id", ondelete="CASCADE"), nullable=False)
    sort_index: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), default=0)


class AgendaItem(Base, TimestampMixin, UpdatedAtMixin):
    """Anliegen für eine kommende Sitzung (Migration 0153). Wartet ohne protocol_id auf das
    nächste passende Protokoll seiner Vorlage und wird beim Durchführen fest daran gebunden,
    siehe app/services/agenda_item_service.py."""

    __tablename__ = "agenda_item"
    __table_args__ = (
        CheckConstraint("schedule_kind IN ('next_meeting', 'month')", name="ck_agenda_item_schedule_kind"),
        Index("idx_agenda_item_tenant", "tenant_id"),
        Index("idx_agenda_item_protocol", "protocol_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, unique=True, server_default=text("uuidv7()")
    )
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False)
    template_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("template.id", ondelete="CASCADE"), nullable=False)
    template_element_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("template_element.id", ondelete="SET NULL"))
    protocol_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("protocol.id", ondelete="SET NULL"))
    protocol_element_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("protocol_element.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    schedule_kind: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'next_meeting'"))
    scheduled_month: Mapped[date | None] = mapped_column(Date)
    earliest_date: Mapped[date] = mapped_column(Date, nullable=False)
    postponed_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), default=0)
    created_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app_user.id", ondelete="SET NULL"))


class UserAgendaTemplatePreference(Base):
    """Zuletzt im Anliegen-Popup gewählte Vorlage je Person und Mandant (Migration 0153)."""

    __tablename__ = "user_agenda_template_preference"

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("app_user.id", ondelete="CASCADE"), primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"), primary_key=True)
    template_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("template.id", ondelete="SET NULL"))


class TaskPackage(Base, TimestampMixin, UpdatedAtMixin):
    """Aufgabenpaket (z. B. "Sommerlager"): Sammlung wiederkehrender Aufgaben, die pro Zyklus
    als Todos erzeugt werden. Siehe app/services/task_package_service.py."""

    __tablename__ = "task_package"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_task_package_tenant_name"),
        Index("idx_task_package_tenant", "tenant_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, unique=True, server_default=text("uuidv7()")
    )
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("TRUE"), default=True)


class TaskPackageCycle(Base, TimestampMixin, UpdatedAtMixin):
    """Zuweisung eines Pakets an einen Zyklus ab start_cycle_year (inklusive)."""

    __tablename__ = "task_package_cycle"
    __table_args__ = (
        UniqueConstraint("task_package_id", "cycle_config_id", name="uq_task_package_cycle_package_config"),
        Index("idx_task_package_cycle_config", "cycle_config_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, unique=True, server_default=text("uuidv7()")
    )
    task_package_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("task_package.id", ondelete="CASCADE"), nullable=False)
    cycle_config_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("cycle_config.id", ondelete="CASCADE"), nullable=False)
    start_cycle_year: Mapped[int] = mapped_column(Integer, nullable=False)


class TaskPackageItem(Base, TimestampMixin, UpdatedAtMixin):
    """Eine Aufgabe im Paket. responsible_json hat dieselbe Form wie die Verantwortlichen im
    Protokoll: [{"list_definition_id", "list_entry_id"}] (Ämtli, live aufgelöst) oder
    [{"participant_id"}] (feste Person), jeweils interne IDs."""

    __tablename__ = "task_package_item"
    __table_args__ = (Index("idx_task_package_item_package_sort", "task_package_id", "sort_index"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, unique=True, server_default=text("uuidv7()")
    )
    task_package_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("task_package.id", ondelete="CASCADE"), nullable=False)
    sort_index: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), default=0)
    task: Mapped[str] = mapped_column(Text, nullable=False)
    reference_link: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"), default=list)
    responsible_json: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"), default=list)
    recurrence_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{\"type\": \"once\"}'::jsonb"), default=lambda: {"type": "once"}
    )
    due_rule_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{\"type\": \"none\"}'::jsonb"), default=lambda: {"type": "none"}
    )


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
        Index("idx_gallery_image_live_video", "live_video_stored_file_id"),
        Index("idx_gallery_image_cycle_config", "cycle_config_id"),
        Index("idx_gallery_image_submission_assignment", "submission_assignment_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False)
    stored_file_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("stored_file.id", ondelete="RESTRICT"), nullable=False)
    # Live Photo: the short H.264 clip (its own StoredFile, no gallery_image row of its own) the
    # Fotos grid plays on hover - see apple_media.py. NULL for every ordinary photo.
    live_video_stored_file_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("stored_file.id", ondelete="SET NULL"))
    # The Termin this photo belongs to - either the one the uploader targeted in
    # GalleryUploadModal (event_auto_linked False), or one photo_event_link_service matched
    # automatically by comparing the photo's capture date against every Termin's
    # event_date..event_end_date range (event_auto_linked True), either right after upload
    # or retroactively when a matching Termin is created/its dates change. Kept around (it
    # used to be discarded once the file landed in that Termin's auto-album) so the Fotos
    # page's date-grouped headers can show which Termin/Zyklus a given date belongs to.
    event_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("event.id", ondelete="SET NULL"))
    # True when event_id was set by photo_event_link_service's date matching rather than
    # picked explicitly by the uploader - lets that service re-sync (link/unlink) as Termine
    # are created or their dates edited without ever overriding a manual choice.
    event_auto_linked: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"), default=False)
    # Bezug of a direct *document* upload on the "Dateien" page (POST /files/document-uploads) -
    # at most one of event_id / cycle_config_id / submission_assignment_id (+ element ref/label)
    # is ever set. Photo uploads don't write these: they link through auto-albums instead
    # (see photo_album_service.py). The element label is snapshotted, like
    # GalleryUploadJob.upload_element_label, so the Bezug column needn't re-resolve it.
    cycle_config_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("cycle_config.id", ondelete="SET NULL"))
    submission_assignment_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("submission_assignment.id", ondelete="SET NULL")
    )
    submission_element_ref: Mapped[str | None] = mapped_column(Text)
    submission_element_label: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app_user.id", ondelete="SET NULL"))


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


class UserProtocolTemplatePreference(Base):
    __tablename__ = "user_protocol_template_preference"

    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("app_user.id", ondelete="CASCADE"), primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"), primary_key=True)
    template_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("template.id", ondelete="SET NULL"))


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


class FineTariff(Base):
    """Zentraler Bussentarif eines Mandanten (0113_element_config_schema).

    Vorher trug jeder Anwesenheitsblock eigene Beträge und ein eigenes Konto, sodass zwei
    Vorlagen verschiedene Tarife haben konnten. Der Block wählt jetzt nur noch
    «Bussen aktiv» (configuration_json.fines_enabled); Konto und Beträge kommen von hier.
    """

    __tablename__ = "fine_tariff"
    __table_args__ = (Index("idx_fine_tariff_account", "account_id"),)

    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"), primary_key=True)
    account_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("finance_account.id", ondelete="SET NULL"))
    amount_late: Mapped[float] = mapped_column(Numeric(15, 2), nullable=False, server_default=text("0"))
    amount_absent: Mapped[float] = mapped_column(Numeric(15, 2), nullable=False, server_default=text("0"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))


class AttendanceFine(Base, TimestampMixin):
    __tablename__ = "attendance_fine"
    __table_args__ = (
        Index("idx_attendance_fine_protocol", "protocol_id"),
        Index("idx_attendance_fine_participant", "participant_id"),
        Index("idx_attendance_fine_account", "account_id"),
        Index("idx_attendance_fine_collected_by", "collected_by_user_id"),
        Index("idx_attendance_fine_collected_transaction", "collected_transaction_id"),
        Index("idx_attendance_fine_deleted_by", "deleted_by_user_id"),
        # Migration 0116 (MAIN-BE-016): eine Busse pro Protokoll, Teilnehmer und Typ.
        Index(
            "uq_attendance_fine_participant", "protocol_id", "participant_id", "fine_type",
            unique=True, postgresql_where=text("participant_id IS NOT NULL"),
        ),
        Index(
            "uq_attendance_fine_name", "protocol_id", "participant_name_snapshot", "fine_type",
            unique=True, postgresql_where=text("participant_id IS NULL"),
        ),
        # Baseline bzw. Migration 0115 (MAIN-BE-002/-016)
        CheckConstraint("status IN ('pending', 'collected', 'deleted')", name="attendance_fine_status_check"),
        CheckConstraint("fine_type IN ('late', 'absent')", name="attendance_fine_fine_type_check"),
        CheckConstraint(
            "status <> 'deleted' OR (delete_comment IS NOT NULL AND btrim(delete_comment) <> '')",
            name="ck_attendance_fine_deleted_reason",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, unique=True, server_default=text("uuidv7()")
    )
    protocol_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("protocol.id", ondelete="CASCADE"), nullable=False)
    participant_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app_user.id", ondelete="SET NULL"))
    participant_name_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    fine_type: Mapped[str] = mapped_column(Text, nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(15, 2), nullable=False)
    account_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("finance_account.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'pending'"))
    collected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    collected_transaction_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("finance_transaction.id", ondelete="SET NULL"))
    closed_in_protocol_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("protocol.id", ondelete="SET NULL"))
    collected_by_user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app_user.id", ondelete="SET NULL"))
    # Soft-Delete mit Begründung (MAIN-BE-002, Migration 0115): nur für Bussen, deren
    # Ursprungsprotokoll abgeschlossen ist; closed_in_protocol_id zeigt dann auf das
    # Protokoll, in dem die Löschung aufgeführt wird.
    delete_comment: Mapped[str | None] = mapped_column(Text)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_by_user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app_user.id", ondelete="SET NULL"))


class SubmissionAssignment(Base, TimestampMixin, UpdatedAtMixin):
    """Konfiguration einer Abgabe (Upload-Box), gekoppelt an Termine (per Tag-Filter + Offset), eine Liste (+ Stichtag)
    oder manuell (weder Termine noch Liste: genau ein Element, optional mit Stichtag)."""

    __tablename__ = "submission_assignment"
    __table_args__ = (
        UniqueConstraint("tenant_id", "public_slug", name="uq_submission_assignment_tenant_slug"),
        CheckConstraint("source_type IN ('events', 'list', 'manual')", name="ck_submission_assignment_source_type"),
        CheckConstraint(
            # Tage vor/nach Termin bzw. Stichtag sind bewusst optional (siehe Migration
            # 0056_submission_flexible_window): NULL = kein Zeitfenster, die Abgabe bleibt offen,
            # bis sie manuell geschlossen wird (SubmissionUpload.status = 'closed').
            "(source_type = 'events' AND tag_filter IS NOT NULL "
            "AND list_definition_id IS NULL AND deadline IS NULL) OR "
            "(source_type = 'list' AND list_definition_id IS NOT NULL "
            "AND tag_filter IS NULL AND offset_days_before IS NULL AND offset_days_after IS NULL) OR "
            "(source_type = 'manual' AND tag_filter IS NULL AND list_definition_id IS NULL "
            "AND offset_days_before IS NULL AND offset_days_after IS NULL)",
            name="ck_submission_assignment_source_fields",
        ),
        CheckConstraint("offset_days_before IS NULL OR offset_days_before >= 0", name="ck_submission_assignment_offset_before"),
        CheckConstraint("offset_days_after IS NULL OR offset_days_after >= 0", name="ck_submission_assignment_offset_after"),
        CheckConstraint(
            # Zyklus-Filter nur fuer Termin-Abgaben: cycle_config_id und cycle_offsets gehoeren
            # zusammen (Migration 0079_submission_cycle_filter).
            "(cycle_config_id IS NULL AND jsonb_array_length(cycle_offsets) = 0) OR "
            "(cycle_config_id IS NOT NULL AND source_type = 'events' AND jsonb_array_length(cycle_offsets) > 0)",
            name="ck_submission_assignment_cycle_filter",
        ),
        CheckConstraint("max_files_per_element IS NULL OR max_files_per_element >= 1", name="ck_submission_assignment_max_files"),
        CheckConstraint("max_file_size_mb >= 1", name="ck_submission_assignment_max_size"),
        CheckConstraint("sort_order IN ('alphabetical', 'date', 'proximity')", name="ck_submission_assignment_sort_order"),
        CheckConstraint("auto_close IN ('never', 'first_upload', 'max_files')", name="ck_submission_assignment_auto_close"),
        Index("idx_submission_assignment_tenant_active", "tenant_id", "is_active"),
        Index("idx_submission_assignment_list_definition", "list_definition_id"),
        Index("idx_submission_assignment_cycle_config", "cycle_config_id"),
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
    # Optionaler Zyklus-Filter der Termin-Quelle: nur Termine, die per event_cycle einem der
    # Zyklen (cycle_config + aktuelles Zyklusjahr + Offset) zugeordnet sind. cycle_offsets:
    # 0 = aktueller Zyklus, -1 = vorheriger usw. Ohne cycle_config_id: alle Termine mit dem Tag.
    cycle_config_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("cycle_config.id", ondelete="RESTRICT"))
    cycle_offsets: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"), default=list)
    list_definition_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("list_definition.id", ondelete="RESTRICT"))
    deadline: Mapped[date | None] = mapped_column(Date)
    allowed_file_types: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"), default=list)
    max_files_per_element: Mapped[int | None] = mapped_column(Integer, server_default=text("5"))
    max_file_size_mb: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("20"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("TRUE"))
    sort_order: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'date'"))
    # Element nach einer Abgabe ueber die Abgabebox automatisch schliessen: 'never',
    # 'first_upload' oder 'max_files' (Migration 0099_submission_auto_close).
    auto_close: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'never'"))
    responsible_participant_source: Mapped[str | None] = mapped_column(Text)
    # Ueber welche Abgabe-Links (SubmissionLink) diese Abgabe oeffentlich erreichbar ist. Ohne
    # Link ist sie ueber die Abgabebox nicht erreichbar.
    links: Mapped[list["SubmissionLink"]] = relationship(
        "SubmissionLink",
        secondary="submission_assignment_link",
        order_by="SubmissionLink.id",
        lazy="selectin",
        passive_deletes=True,
    )


class SubmissionLink(Base, TimestampMixin, UpdatedAtMixin):
    """Zugangslink zur oeffentlichen Abgabebox. `token` ist ein zufaelliger, nicht erratbarer
    Wert, der selbst die Authentifizierung ist (Teil der URL: <abgabebox-domain>/<token>);
    `name` ist nur die Klartext-Bezeichnung im Admin-Bereich.

    Der Link legt den Mandanten fest (der separate abgabebox-backend-Service loest ueber das
    Token den Mandanten und die freigegebenen Abgaben auf - der Mandanten-public_slug spielt
    dort keine Rolle mehr). Die restricted Rolle hocx_abgabebox darf nur (id, tenant_id, token)
    lesen, siehe Migration 0075_submission_link."""

    __tablename__ = "submission_link"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_submission_link_tenant_name"),
        # Hoechstens ein Standard-Link je Mandant (wird beim Anlegen einer Abgabe vorausgewaehlt).
        Index("uq_submission_link_tenant_default", "tenant_id", unique=True, postgresql_where=text("is_default")),
        # «verify» ist die Route der Prüfseite in der Abgabebox (/verify) und nie ein Token.
        CheckConstraint("lower(token) <> 'verify'", name="ck_submission_link_token_reserved"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, unique=True, server_default=text("uuidv7()")
    )
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    token: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("FALSE"))


submission_assignment_link_table = Table(
    "submission_assignment_link",
    Base.metadata,
    Column("assignment_id", BigInteger, ForeignKey("submission_assignment.id", ondelete="CASCADE"), primary_key=True),
    Column("link_id", BigInteger, ForeignKey("submission_link.id", ondelete="CASCADE"), primary_key=True),
    Index("idx_submission_assignment_link_link", "link_id"),
)


class SubmissionUpload(Base, TimestampMixin):
    """Append-only Log der Abgabe-Ereignisse (Erstabgabe/Reopen/erneute Abgabe) je Element.

    Bewusst append-only statt mutierbar: die restricted Postgres-Rolle des separaten
    abgabebox-backend-Service darf auf dieser Tabelle nur INSERT (kein UPDATE/DELETE),
    damit ein kompromittierter öffentlicher Prozess frühere Abgaben nicht verändern kann.
    Der aktuelle Zustand eines Elements ist der Status der Zeile mit der höchsten id
    je (assignment_id, event_id, list_entry_id). Uploads einer manuellen Abgabe tragen weder
    event_id noch list_entry_id (Migration 0080_submission_manual_source).
    """

    __tablename__ = "submission_upload"
    __table_args__ = (
        CheckConstraint(
            "event_id IS NULL OR list_entry_id IS NULL",
            name="ck_submission_upload_at_most_one_target",
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


class OverloadRejection(Base):
    """Abgewiesene neue Nutzer bei Überlast (0151_overload_priority), je Prozess alle ~15 s
    zusammengefasst. Plattformdaten ohne RLS wie system_error_log - nur /admin/system liest sie."""

    __tablename__ = "overload_rejection"
    __table_args__ = (
        Index("idx_overload_rejection_created", "created_at"),
        Index("idx_overload_rejection_tenant", "tenant_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))
    instance: Mapped[str] = mapped_column(Text, nullable=False)
    tenant_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"))
    load_priority: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    rejected: Mapped[int] = mapped_column(Integer, nullable=False)
    users: Mapped[int] = mapped_column(Integer, nullable=False)
    pressure_percent: Mapped[int] = mapped_column(Integer, nullable=False)


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
    # Veraltet (0139): neue Einträge verweisen über actor_user_id/actor_admin_id auf das Konto, damit
    # nach dem Löschen einer Person keine E-Mail-Adresse im Protokoll zurückbleibt (PRIV-002).
    actor_email: Mapped[str | None] = mapped_column(Text)
    actor_user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app_user.id", ondelete="SET NULL"))
    actor_admin_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("platform_admin.id", ondelete="SET NULL"))
    request_method: Mapped[str | None] = mapped_column(Text)
    request_path: Mapped[str | None] = mapped_column(Text)
    status_code: Mapped[int | None] = mapped_column(Integer)
    error_type: Mapped[str] = mapped_column(Text, nullable=False)
    error_message: Mapped[str] = mapped_column(Text, nullable=False)
    traceback: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))



class SystemJobStatus(Base):
    """Aktueller Stand eines periodischen Jobs (Loop, Worker, Host-Cron) für /admin/jobs. Wird
    nur über die SQL-Funktionen record_job_run/record_job_start/record_job_heartbeat geschrieben
    (Migration 0105), damit auch die eingeschränkten DB-Rollen melden können - hier nur lesen."""

    __tablename__ = "system_job_status"
    __table_args__ = (
        CheckConstraint("last_status IN ('running', 'success', 'failure')", name="ck_system_job_status_last_status"),
    )

    job_name: Mapped[str] = mapped_column(Text, primary_key=True)
    last_status: Mapped[str | None] = mapped_column(Text)
    last_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_failure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_duration_ms: Mapped[int | None] = mapped_column(Integer)
    last_error: Mapped[str | None] = mapped_column(Text)
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    run_count: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    failure_count: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))


class SystemRuntimeMetric(Base):
    """Laufzeitkennzahlen je Dienstprozess (core/runtime_metrics.py, Migration 0148). Geschrieben
    nur über record_runtime_metrics, gelesen von system_health_service._check_runtime."""

    __tablename__ = "system_runtime_metric"

    instance: Mapped[str] = mapped_column(Text, primary_key=True)
    process_kind: Mapped[str] = mapped_column(Text, nullable=False)
    reported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    metrics: Mapped[dict] = mapped_column(JSONB, nullable=False)


class SystemJobRun(Base):
    """Verlauf der Läufe eines Jobs (siehe SystemJobStatus). Bei hochfrequenten Jobs nur Fehler und
    der erste Erfolg danach, Aufräumen über log_cleanup_loop."""

    __tablename__ = "system_job_run"
    __table_args__ = (
        CheckConstraint("status IN ('success', 'failure')", name="ck_system_job_run_status"),
        Index("idx_system_job_run_job_id", "job_name", "id"),
        Index("idx_system_job_run_finished", "finished_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    job_name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)


class SystemAlertState(Base):
    """Aktuell offenes Problem aus dem Systemmonitoring (siehe app/services/system_alert_service.py)."""

    __tablename__ = "system_alert_state"
    __table_args__ = (CheckConstraint("severity IN ('warning', 'critical')", name="ck_system_alert_state_severity"),)

    problem_key: Mapped[str] = mapped_column(Text, primary_key=True)
    severity: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))
    notified_severity: Mapped[str | None] = mapped_column(Text)
    last_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SystemHealthEvent(Base):
    """Verlauf des Systemmonitorings für /admin/system: Problem aufgetreten/behoben, Container neu gestartet."""

    __tablename__ = "system_health_event"
    __table_args__ = (
        CheckConstraint("kind IN ('problem', 'resolved', 'container_restart')", name="ck_system_health_event_kind"),
        CheckConstraint("severity IN ('info', 'warning', 'critical')", name="ck_system_health_event_severity"),
        Index("idx_system_health_event_created", "created_at"),
        Index("idx_system_health_event_subject", "subject", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PlatformNotificationSettings(Base):
    """ntfy-Konfiguration aus /admin/notifications - genau eine Zeile (id = 1, DB-CHECK). Tokens
    nur verschlüsselt (secret_crypto); status_token_hash prüft der öffentliche Summary-Endpoint."""

    __tablename__ = "platform_notification_settings"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_platform_notification_settings_singleton"),
        CheckConstraint("reminder_hours BETWEEN 0 AND 168", name="ck_platform_notification_settings_reminder_hours"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ntfy_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("FALSE"))
    ntfy_server_url: Mapped[str | None] = mapped_column(Text)
    ntfy_topic: Mapped[str | None] = mapped_column(Text)
    ntfy_token_encrypted: Mapped[str | None] = mapped_column(Text)
    admin_url: Mapped[str | None] = mapped_column(Text)
    reminder_hours: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("6"))
    status_token_hash: Mapped[str | None] = mapped_column(Text)
    status_token_encrypted: Mapped[str | None] = mapped_column(Text)
    last_send_error: Mapped[str | None] = mapped_column(Text)
    last_send_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))

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
    __table_args__ = (Index("idx_photo_album_item_share_pending", "album_id", postgresql_where=text("share_pending")),)

    album_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("photo_album.id", ondelete="CASCADE"), primary_key=True)
    # Overview IDs cover both StoredFile and SubmissionUploadFile.
    file_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    # Current resolved best-of ("Stern") state - auto-recomputed (see
    # photo_album_service.recompute_best_of) except where best_override pins it.
    is_best: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("FALSE"), default=False)
    # A user's manual "immer im Best-of" / "nie im Best-of" pick, surviving future
    # recomputes. NULL = automatically managed (the common case).
    best_override: Mapped[str | None] = mapped_column(Text)
    # TRUE = automatisch in ein geteiltes Album einsortiert, aber noch nicht freigegeben: nur
    # der Besitzer-Mandant sieht das Foto im Album, Partner und Album-Links erst nach der
    # Freigabe (siehe photo_album_share_service.release_pending).
    share_pending: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("FALSE"), default=False)


class PhotoAlbumTenantShare(Base, TimestampMixin):
    """Ladet einen ANDEREN Mandanten in ein eigenes ("manual") Fotoalbum ein - der Besitzer
    bleibt `photo_album.tenant_id`, hier steht nur der eingeladene Partner-Mandant und der
    Stand der Einladung. Erst nach `status = 'accepted'` darf der eingeladene Mandant das
    Album sehen bzw. eigene Fotos hinzufuegen/loeschen (siehe access_service.py,
    photo_album_share_service.py)."""

    __tablename__ = "photo_album_tenant_share"
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'accepted', 'declined')", name="ck_photo_album_tenant_share_status"),
    )

    album_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("photo_album.id", ondelete="CASCADE"), primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"), primary_key=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'pending'"))
    invited_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app_user.id", ondelete="SET NULL"))
    responded_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app_user.id", ondelete="SET NULL"))
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Standort (GPS) der Fotos dieses Albums mit dem Partner teilen - Standard an (Partner
    # vertrauen sich), vom Besitzer abschaltbar. Aus: Originale und Downloads ohne Standort
    # (siehe photo_album_share_service.location_shared_with, files.py).
    share_location: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"), default=True)
    # Öffentliche Links (Migration 0130, Security-Audit SEC-002) - jede Seite schützt ihre Fotos:
    # vom Besitzer gesetzt: der Partner darf dieses Album öffentlich verlinken.
    partner_public_links: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"), default=True)
    # vom Partner gesetzt: seine Fotos in diesem Album dürfen in öffentlichen Links erscheinen.
    partner_photos_public: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"), default=True)


class TenantTrust(Base, TimestampMixin):
    """Vertrauensbeziehung zwischen zwei Mandanten, entsteht beim ersten Annehmen einer
    Album-Freigabe (photo_album_share_service.respond) und bleibt danach bestehen, auch wenn
    die Freigabe selbst wieder endet. Symmetrisch: pro Paar genau eine Zeile mit
    tenant_low_id < tenant_high_id. Erst mit Trust sehen sich die Mandanten gegenseitig mit
    Namen und Profilbild und koennen sich per Namen suchen (siehe tenant_trust_service.py);
    ohne Trust ist ein Mandant nur ueber seine ID auffindbar und bleibt anonym."""

    __tablename__ = "tenant_trust"
    __table_args__ = (CheckConstraint("tenant_low_id < tenant_high_id", name="ck_tenant_trust_ordered"),)

    tenant_low_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"), primary_key=True)
    tenant_high_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"), primary_key=True)


class ShareLink(Base, TimestampMixin):
    """Oeffentlicher Download-Link fuer Dateien/Fotos - `token` ist selbst die Authentifizierung
    (Teil der URL: <app-domain>/share/<token>), analog zu SubmissionLink. Zeigt entweder auf ein
    Album (`album_id` gesetzt - "live", immer der aktuelle Album-Inhalt) oder auf eine feste
    Dateiauswahl (`share_link_file`, wenn `album_id` NULL ist)."""

    __tablename__ = "share_link"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()"))
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    token: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    album_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("photo_album.id", ondelete="CASCADE"))
    created_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app_user.id", ondelete="SET NULL"))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Widerruf ist soft (statt DELETE), damit die Uebersicht "Geteilte Links" auch widerrufene
    # Links mit ihrem Status weiter anzeigen kann.
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Welche Foto-Metadaten oeffentlich mitgehen (siehe photo_metadata_privacy.py) - Standort und
    # Kamera/Geraet standardmaessig nicht, das Aufnahmedatum schon.
    share_location: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"), default=False)
    share_capture_date: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"), default=True)
    share_camera: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"), default=False)


class ShareLinkFile(Base):
    """Feste Dateiauswahl eines ShareLink - nur relevant, wenn share_link.album_id NULL ist.
    Wie PhotoAlbumItem.file_id bewusst ohne FK: deckt sowohl StoredFile.public_id als auch
    SubmissionUploadFile-Overview-IDs ab."""

    __tablename__ = "share_link_file"

    share_link_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("share_link.id", ondelete="CASCADE"), primary_key=True)
    file_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)


class CalendarFeed(Base, TimestampMixin, UpdatedAtMixin):
    """Abonnierbarer iCal-Feed eines Benutzers ("Verknuepfungen") - je einer fuer Termine und
    Todos (`kind`). Der Token in der URL ist die Authentifizierung; gespeichert werden nur sein
    Hash (Nachschlagen) und eine verschluesselte Kopie (erneutes Anzeigen), siehe
    calendar_feed_service.py und Migration 0102."""

    __tablename__ = "calendar_feed"
    __table_args__ = (
        UniqueConstraint("user_id", "kind", name="uq_calendar_feed_user_kind"),
        CheckConstraint("kind IN ('events', 'todos')", name="ck_calendar_feed_kind"),
        CheckConstraint("todo_scope IN ('mine', 'all')", name="ck_calendar_feed_todo_scope"),
        Index("idx_calendar_feed_tenant", "tenant_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, unique=True, server_default=text("uuidv7()")
    )
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    calendar_name: Mapped[str] = mapped_column(Text, nullable=False)
    token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    token_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    # Gegen app_user.session_revoke_at geprueft: "ueberall abmelden"/Passwortwechsel macht auch
    # vorher ausgestellte Feed-URLs ungueltig (wie App-Passwoerter bei Google/Apple).
    token_created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))
    todo_scope: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'mine'"), default="mine")
    include_completed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"), default=False)
    hide_details: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"), default=True)
    last_accessed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


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


class PhotoSimilarityResult(Base):
    """Vorberechnete Gruppen der Tabs "Duplikate"/"Ähnliche" je Mandant und Art (Migration 0152).
    Schreibt der job-worker (FileService.refresh_similarity_results); `groups` sind Listen von
    public_ids, nur Gruppen mit mindestens zwei Bildern."""

    __tablename__ = "photo_similarity_result"
    __table_args__ = (
        CheckConstraint("kind IN ('duplicate', 'series')", name="ck_photo_similarity_result_kind"),
        CheckConstraint("status IN ('ready', 'incomplete', 'too_many')", name="ck_photo_similarity_result_status"),
    )

    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"), primary_key=True)
    kind: Mapped[str] = mapped_column(Text, primary_key=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'ready'"), default="ready")
    fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    image_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), default=0)
    groups: Mapped[list[list[str]]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"), default=list)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))


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
    reserved_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'queued'"))
    # Storage-relative paths of the raw upload(s) staged by the request handler - see
    # upload_pipeline.stage_upload_to_disk. Filenames on disk are randomized
    # (uuid4().hex + suffix), so original_filenames (same order) carries each one's real
    # client-supplied name - used for a non-ZIP entry's StoredFile.original_name (a ZIP's
    # own entries keep their in-archive names instead, see iter_gallery_zip_entries).
    staged_paths: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    original_filenames: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    # «GPS-Daten des Bildes mitsenden» (0147, Datenschutz-Audit Paket 9.3)
    include_gps: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"), default=True)
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
    # Beim Upload bestaetigt: Fotos, die dabei in ein geteiltes Auto-Album fallen, gleich
    # freigeben statt sie als share_pending einzusortieren.
    release_to_shared_albums: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("FALSE"), default=False)
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
    # Im Upload-Popup angegebenes Schaetzdatum - gilt fuer jedes Bild dieses Auftrags, fuer
    # das der Server kein echtes Aufnahmedatum findet (auch ZIP-Eintraege).
    estimated_taken_on: Mapped[date | None] = mapped_column(Date)
    # Clientseitig extrahierte Metadaten je SHA-256 (Browser-Analyse vor dem Upload, nur fuer
    # HEIC/HEIF). Nur Hinweise: angewendet wird ein Eintrag ausschliesslich, wenn der
    # serverseitig neu berechnete Hash der Datei passt (siehe FileService._apply_upload_metadata
    # und _enrich_duplicates). Wird bei Jobende (done/failed) geleert - keine Zweitablage von GPS.
    file_hints: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"), default=dict)
    # Ergebnis je Datei fuer die Upload-Ergebnisanzeige: {name, status, file_id?, applied?, message?}
    # mit status in uploaded/skipped/metadata_updated/failed.
    file_results: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"), default=list)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TenantDataExport(Base):
    """Vereinsexport (Migration 0145, services/data_export/tenant.py): bestellt vom Mandanten-Admin,
    gebaut vom Job tenant_data_export, 7 Tage abrufbar. password_encrypted nur bis zum Bau."""

    __tablename__ = "tenant_data_export"
    __table_args__ = (
        CheckConstraint("status IN ('queued', 'running', 'done', 'failed', 'expired')", name="ck_tenant_data_export_status"),
        Index("idx_tenant_data_export_tenant", "tenant_id", text("created_at DESC")),
        Index("idx_tenant_data_export_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()"))
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False)
    requested_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app_user.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'queued'"))
    include_files: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    language: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'de'"))
    password_encrypted: Mapped[str | None] = mapped_column(Text)
    object_key: Mapped[str | None] = mapped_column(Text)
    filename: Mapped[str | None] = mapped_column(Text)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TenantRetentionPolicy(Base):
    """Aufbewahrungsfristen des Vereins (Migration 0146, services/tenant_retention_service.py).
    NULL = Regel aus."""

    __tablename__ = "tenant_retention_policy"
    __table_args__ = (
        CheckConstraint("submissions_months > 0", name="tenant_retention_policy_submissions_months_check"),
        CheckConstraint("former_members_years > 0", name="tenant_retention_policy_former_members_years_check"),
        CheckConstraint("unlinked_gallery_years > 0", name="tenant_retention_policy_unlinked_gallery_years_check"),
    )

    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"), primary_key=True)
    submissions_months: Mapped[int | None] = mapped_column(SmallInteger)
    former_members_years: Mapped[int | None] = mapped_column(SmallInteger)
    unlinked_gallery_years: Mapped[int | None] = mapped_column(SmallInteger)
    auto_apply: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"), default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))


class RetentionProposal(Base):
    """Vorschlag des Jobs retention_proposals (Migration 0146). subject_id: submission_upload.id,
    app_user.id bzw. stored_file.id je nach kind."""

    __tablename__ = "retention_proposal"
    __table_args__ = (
        CheckConstraint("kind IN ('submission_upload', 'former_member', 'gallery_image')", name="ck_retention_proposal_kind"),
        CheckConstraint("status IN ('open', 'applied', 'dismissed')", name="ck_retention_proposal_status"),
        UniqueConstraint("tenant_id", "kind", "subject_id", name="uq_retention_proposal_subject"),
        Index("idx_retention_proposal_open", "tenant_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()"))
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    subject_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    label: Mapped[str | None] = mapped_column(Text)
    reference_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'open'"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app_user.id", ondelete="SET NULL"))
