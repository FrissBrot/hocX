from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    Date,
    DateTime,
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
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))


class UpdatedAtMixin:
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))


class Tenant(Base, TimestampMixin):
    __tablename__ = "tenant"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    profile_image_path: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))
    tag_config_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"), default=dict)
    public_slug: Mapped[str | None] = mapped_column(Text, unique=True)


class TenantOidcConfig(Base, TimestampMixin, UpdatedAtMixin):
    __tablename__ = "tenant_oidc_config"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False, unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("FALSE"))
    auto_redirect: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("FALSE"))
    issuer_url: Mapped[str] = mapped_column(Text, nullable=False)
    client_id: Mapped[str] = mapped_column(Text, nullable=False)
    client_secret: Mapped[str] = mapped_column(Text, nullable=False)
    scopes: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'openid email profile'"))


class Role(Base):
    __tablename__ = "role"

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    code: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text)


class AppUser(Base, TimestampMixin, UpdatedAtMixin):
    __tablename__ = "app_user"
    __table_args__ = (
        UniqueConstraint("email", name="uq_app_user_email"),
        UniqueConstraint("oidc_issuer", "oidc_subject", name="uq_app_user_oidc"),
        Index("idx_app_user_default_tenant", "default_tenant_id"),
        Index("idx_app_user_email", "email"),
        Index("idx_app_user_oidc", "oidc_issuer", "oidc_subject"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
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
    oidc_subject: Mapped[str | None] = mapped_column(Text)
    oidc_issuer: Mapped[str | None] = mapped_column(Text)
    oidc_email: Mapped[str | None] = mapped_column(Text)
    external_identity_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"), default=dict)


class PlatformAdmin(Base, TimestampMixin, UpdatedAtMixin):
    """Betreiber-Account fürs zentrale Admin-Panel. Komplett getrennt vom Kunden-`AppUser`-System."""

    __tablename__ = "platform_admin"
    __table_args__ = (UniqueConstraint("email", name="uq_platform_admin_email"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("TRUE"))
    session_revoke_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UserRole(Base):
    __tablename__ = "user_role"
    __table_args__ = (PrimaryKeyConstraint("user_id", "role_id", name="pk_user_role"),)

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
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("TRUE"))
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_until: Mapped[date | None] = mapped_column(Date)


class Leader(Base, TimestampMixin, UpdatedAtMixin):
    __tablename__ = "leader"
    __table_args__ = (Index("idx_leader_tenant_active", "tenant_id", "is_active"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("TRUE"))
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_until: Mapped[date | None] = mapped_column(Date)


class Participant(Base, TimestampMixin, UpdatedAtMixin):
    __tablename__ = "participant"
    __table_args__ = (
        Index("idx_participant_tenant_active", "tenant_id", "is_active"),
        UniqueConstraint("tenant_id", "display_name", name="uq_participant_tenant_display_name"),
        UniqueConstraint("tenant_id", "app_user_id", name="uq_participant_tenant_app_user"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False)
    app_user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app_user.id", ondelete="SET NULL"))
    first_name: Mapped[str | None] = mapped_column(Text)
    last_name: Mapped[str | None] = mapped_column(Text)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("TRUE"))


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
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False)
    event_date: Mapped[date] = mapped_column(Date, nullable=False)
    event_end_date: Mapped[date | None] = mapped_column(Date)
    event_category_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("event_category.id", ondelete="RESTRICT"), nullable=False)
    tag: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    participant_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    is_cancelled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
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
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    reset_month: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("12"))
    reset_day: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("31"))
    name_pattern: Mapped[str | None] = mapped_column(Text)


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
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    column_one_title: Mapped[str] = mapped_column(Text, nullable=False)
    column_one_value_type: Mapped[str] = mapped_column(Text, nullable=False)
    column_two_title: Mapped[str] = mapped_column(Text, nullable=False)
    column_two_value_type: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("TRUE"))


class ListEntry(Base, TimestampMixin, UpdatedAtMixin):
    __tablename__ = "list_entry"
    __table_args__ = (
        Index("idx_list_entry_definition_sort", "list_definition_id", "sort_index"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
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
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
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
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
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
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
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
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
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
    created_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app_user.id", ondelete="SET NULL"))


class ProtocolElement(Base, TimestampMixin):
    __tablename__ = "protocol_element"
    __table_args__ = (
        UniqueConstraint("protocol_id", "sort_index", name="uq_protocol_element_protocol_sort"),
        Index("idx_protocol_element_protocol_sort", "protocol_id", "sort_index"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    protocol_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("protocol.id", ondelete="CASCADE"), nullable=False)
    template_element_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("template_element.id", ondelete="SET NULL"))
    sort_index: Mapped[int] = mapped_column(Integer, nullable=False)
    section_name_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    section_order_snapshot: Mapped[int | None] = mapped_column(Integer)
    is_required_snapshot: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("FALSE"))
    is_visible_snapshot: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("TRUE"))
    export_visible_snapshot: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("TRUE"))


class ProtocolElementBlock(Base, TimestampMixin):
    __tablename__ = "protocol_element_block"
    __table_args__ = (
        UniqueConstraint("protocol_element_id", "sort_index", name="uq_protocol_element_block_sort"),
        Index("idx_protocol_element_block_sort", "protocol_element_id", "sort_index"),
        Index("idx_protocol_element_block_type", "element_type_id"),
        Index("idx_protocol_element_block_configuration_gin", "configuration_snapshot_json", postgresql_using="gin"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
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
    __table_args__ = (Index("idx_stored_file_tenant", "tenant_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False)
    original_name: Mapped[str] = mapped_column(Text, nullable=False)
    mime_type: Mapped[str | None] = mapped_column(Text)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    latex_path: Mapped[str | None] = mapped_column(Text)
    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    checksum_sha256: Mapped[str | None] = mapped_column(Text)
    scan_status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'clean'"))
    created_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app_user.id", ondelete="SET NULL"))


class ProtocolText(Base, TimestampMixin, UpdatedAtMixin):
    __tablename__ = "protocol_text"
    __table_args__ = (Index("idx_protocol_text_protocol_element_block", "protocol_element_block_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    protocol_element_block_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("protocol_element_block.id", ondelete="CASCADE"), nullable=False, unique=True)
    content: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))


class ProtocolDisplaySnapshot(Base, TimestampMixin):
    __tablename__ = "protocol_display_snapshot"
    __table_args__ = (
        Index("idx_protocol_display_snapshot_protocol_element_block", "protocol_element_block_id"),
        Index("idx_protocol_display_snapshot_json_gin", "snapshot_json", postgresql_using="gin"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
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
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
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


class ProtocolImage(Base, TimestampMixin):
    __tablename__ = "protocol_image"
    __table_args__ = (
        UniqueConstraint("protocol_element_block_id", "sort_index", name="uq_protocol_image_block_sort"),
        Index("idx_protocol_image_protocol_element_block", "protocol_element_block_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    protocol_element_block_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("protocol_element_block.id", ondelete="CASCADE"), nullable=False)
    stored_file_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("stored_file.id", ondelete="RESTRICT"), nullable=False)
    sort_index: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    title: Mapped[str | None] = mapped_column(Text)
    caption: Mapped[str | None] = mapped_column(Text)


class ProtocolExportCache(Base, TimestampMixin):
    __tablename__ = "protocol_export_cache"
    __table_args__ = (
        CheckConstraint("export_format IN ('latex', 'pdf')", name="ck_protocol_export_cache_format"),
        Index("idx_protocol_export_cache_protocol", "protocol_id", "export_format"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
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
    account_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("finance_account.id", ondelete="CASCADE"), nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(15, 2), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    transaction_date: Mapped[date] = mapped_column(Date, nullable=False)
    protocol_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("protocol.id", ondelete="SET NULL"))


class UserProtocolScroll(Base):
    __tablename__ = "user_protocol_scroll"
    __table_args__ = (PrimaryKeyConstraint("user_id", "protocol_id"),)

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
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
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
            "(source_type = 'events' AND tag_filter IS NOT NULL AND offset_days_before IS NOT NULL "
            "AND offset_days_after IS NOT NULL AND list_definition_id IS NULL AND deadline IS NULL) OR "
            "(source_type = 'list' AND list_definition_id IS NOT NULL AND deadline IS NOT NULL "
            "AND tag_filter IS NULL AND offset_days_before IS NULL AND offset_days_after IS NULL)",
            name="ck_submission_assignment_source_fields",
        ),
        CheckConstraint("offset_days_before IS NULL OR offset_days_before >= 0", name="ck_submission_assignment_offset_before"),
        CheckConstraint("offset_days_after IS NULL OR offset_days_after >= 0", name="ck_submission_assignment_offset_after"),
        CheckConstraint("max_files_per_element >= 1", name="ck_submission_assignment_max_files"),
        CheckConstraint("max_file_size_mb >= 1", name="ck_submission_assignment_max_size"),
        Index("idx_submission_assignment_tenant_active", "tenant_id", "is_active"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
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
    max_files_per_element: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("5"))
    max_file_size_mb: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("20"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("TRUE"))
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
        CheckConstraint("status IN ('submitted', 'reopened')", name="ck_submission_upload_status"),
        Index("idx_submission_upload_assignment_event", "assignment_id", "event_id"),
        Index("idx_submission_upload_assignment_list_entry", "assignment_id", "list_entry_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
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
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    upload_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("submission_upload.id", ondelete="CASCADE"), nullable=False)
    stored_file_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("stored_file.id", ondelete="RESTRICT"), nullable=False)
    sort_index: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    delete_comment: Mapped[str | None] = mapped_column(Text, nullable=True)


class SubmissionUploadLog(Base):
    __tablename__ = "submission_upload_log"
    __table_args__ = (
        Index("idx_upload_log_assignment_element", "assignment_id", "element_ref"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    assignment_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("submission_assignment.id", ondelete="CASCADE"), nullable=False)
    element_ref: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))

