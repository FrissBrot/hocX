from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    PrimaryKeyConstraint,
    SmallInteger,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("NOW()"),
    )


class UpdatedAtMixin:
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("NOW()"),
    )


class Tenant(Base, TimestampMixin):
    __tablename__ = "tenant"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)


class Role(Base):
    __tablename__ = "role"

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    code: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text)


class AppUser(Base, TimestampMixin, UpdatedAtMixin):
    __tablename__ = "app_user"
    __table_args__ = (
        UniqueConstraint("tenant_id", "email", name="uq_app_user_tenant_email"),
        UniqueConstraint("tenant_id", "oidc_issuer", "oidc_subject", name="uq_app_user_tenant_oidc"),
        Index("idx_app_user_tenant", "tenant_id"),
        Index("idx_app_user_email", "email"),
        Index("idx_app_user_oidc", "tenant_id", "oidc_issuer", "oidc_subject"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("TRUE"))
    oidc_subject: Mapped[str | None] = mapped_column(Text)
    oidc_issuer: Mapped[str | None] = mapped_column(Text)
    oidc_email: Mapped[str | None] = mapped_column(Text)
    external_identity_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
        default=dict,
    )


class UserRole(Base):
    __tablename__ = "user_role"
    __table_args__ = (PrimaryKeyConstraint("user_id", "role_id", name="pk_user_role"),)

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    role_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("role.id", ondelete="RESTRICT"), nullable=False)


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
    event_category_id: Mapped[int] = mapped_column(
        SmallInteger,
        ForeignKey("event_category.id", ondelete="RESTRICT"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    group_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("group_entity.id", ondelete="SET NULL"))


class DocumentTemplate(Base, TimestampMixin):
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
    document_template_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("document_template.id", ondelete="RESTRICT"),
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'active'"))
    created_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app_user.id", ondelete="SET NULL"))


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
    element_type_id: Mapped[int] = mapped_column(
        SmallInteger,
        ForeignKey("element_type.id", ondelete="RESTRICT"),
        nullable=False,
    )
    render_type_id: Mapped[int] = mapped_column(
        SmallInteger,
        ForeignKey("render_type.id", ondelete="RESTRICT"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    display_title: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    is_editable: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("TRUE"))
    allows_multiple_values: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("FALSE"))
    export_visible: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("TRUE"))
    latex_template: Mapped[str | None] = mapped_column(Text)
    configuration_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
        default=dict,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("TRUE"))


class TemplateElement(Base, TimestampMixin):
    __tablename__ = "template_element"
    __table_args__ = (
        UniqueConstraint("template_id", "sort_index", name="uq_template_element_template_sort"),
        Index("idx_template_element_template_sort", "template_id", "sort_index"),
        Index("idx_template_element_configuration_override_gin", "configuration_override_json", postgresql_using="gin"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    template_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("template.id", ondelete="CASCADE"), nullable=False)
    element_definition_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("element_definition.id", ondelete="RESTRICT"),
        nullable=False,
    )
    sort_index: Mapped[int] = mapped_column(Integer, nullable=False)
    render_order: Mapped[int | None] = mapped_column(Integer)
    section_name: Mapped[str | None] = mapped_column(Text)
    section_order: Mapped[int | None] = mapped_column(Integer)
    is_required: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("FALSE"))
    is_visible: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("TRUE"))
    export_visible: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("TRUE"))
    heading_text: Mapped[str | None] = mapped_column(Text)
    configuration_override_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
        default=dict,
    )


Index(
    "idx_template_element_template_render",
    TemplateElement.template_id,
    text("COALESCE(render_order, sort_index)"),
)


class Protocol(Base, TimestampMixin, UpdatedAtMixin):
    __tablename__ = "protocol"
    __table_args__ = (
        UniqueConstraint("tenant_id", "protocol_number", name="uq_protocol_tenant_number"),
        CheckConstraint("status IN ('draft', 'released', 'archived')", name="ck_protocol_status"),
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
    document_template_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("document_template.id", ondelete="RESTRICT"),
    )
    document_template_version: Mapped[int | None] = mapped_column(Integer)
    document_template_path_snapshot: Mapped[str | None] = mapped_column(Text)
    protocol_number: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    protocol_date: Mapped[date] = mapped_column(Date, nullable=False)
    event_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("event.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'draft'"))
    created_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app_user.id", ondelete="SET NULL"))


class ProtocolElement(Base, TimestampMixin):
    __tablename__ = "protocol_element"
    __table_args__ = (
        UniqueConstraint("protocol_id", "sort_index", name="uq_protocol_element_protocol_sort"),
        Index("idx_protocol_element_protocol_sort", "protocol_id", "sort_index"),
        Index("idx_protocol_element_type", "element_type_id"),
        Index("idx_protocol_element_configuration_gin", "configuration_snapshot_json", postgresql_using="gin"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    protocol_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("protocol.id", ondelete="CASCADE"), nullable=False)
    template_element_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("template_element.id", ondelete="SET NULL"),
    )
    element_definition_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("element_definition.id", ondelete="SET NULL"),
    )
    element_type_id: Mapped[int] = mapped_column(
        SmallInteger,
        ForeignKey("element_type.id", ondelete="RESTRICT"),
        nullable=False,
    )
    render_type_id: Mapped[int] = mapped_column(
        SmallInteger,
        ForeignKey("render_type.id", ondelete="RESTRICT"),
        nullable=False,
    )
    title_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    display_title_snapshot: Mapped[str | None] = mapped_column(Text)
    description_snapshot: Mapped[str | None] = mapped_column(Text)
    is_editable_snapshot: Mapped[bool] = mapped_column(Boolean, nullable=False)
    allows_multiple_values_snapshot: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("FALSE"))
    sort_index: Mapped[int] = mapped_column(Integer, nullable=False)
    render_order: Mapped[int | None] = mapped_column(Integer)
    section_name_snapshot: Mapped[str | None] = mapped_column(Text)
    section_order_snapshot: Mapped[int | None] = mapped_column(Integer)
    is_required_snapshot: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("FALSE"))
    is_visible_snapshot: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("TRUE"))
    export_visible_snapshot: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("TRUE"))
    heading_text_snapshot: Mapped[str | None] = mapped_column(Text)
    latex_template_snapshot: Mapped[str | None] = mapped_column(Text)
    configuration_snapshot_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
        default=dict,
    )


Index(
    "idx_protocol_element_protocol_render",
    ProtocolElement.protocol_id,
    text("COALESCE(render_order, sort_index)"),
)


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
    created_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app_user.id", ondelete="SET NULL"))


class ProtocolText(Base, TimestampMixin, UpdatedAtMixin):
    __tablename__ = "protocol_text"
    __table_args__ = (Index("idx_protocol_text_protocol_element", "protocol_element_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    protocol_element_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("protocol_element.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))


class ProtocolDisplaySnapshot(Base, TimestampMixin):
    __tablename__ = "protocol_display_snapshot"
    __table_args__ = (
        Index("idx_protocol_display_snapshot_protocol_element", "protocol_element_id"),
        Index("idx_protocol_display_snapshot_json_gin", "snapshot_json", postgresql_using="gin"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    protocol_element_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("protocol_element.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    source_type: Mapped[str | None] = mapped_column(Text)
    source_id: Mapped[str | None] = mapped_column(Text)
    compiled_text: Mapped[str | None] = mapped_column(Text)
    snapshot_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
        default=dict,
    )


class TodoStatus(Base):
    __tablename__ = "todo_status"

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    code: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text)


class ProtocolTodo(Base, TimestampMixin, UpdatedAtMixin):
    __tablename__ = "protocol_todo"
    __table_args__ = (
        UniqueConstraint("protocol_element_id", "sort_index", name="uq_protocol_todo_element_sort"),
        Index("idx_protocol_todo_protocol_element", "protocol_element_id"),
        Index("idx_protocol_todo_status_due_date", "todo_status_id", "due_date"),
        Index("idx_protocol_todo_assigned_user", "assigned_user_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    protocol_element_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("protocol_element.id", ondelete="CASCADE"),
        nullable=False,
    )
    sort_index: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    task: Mapped[str] = mapped_column(Text, nullable=False)
    assigned_user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app_user.id", ondelete="SET NULL"))
    todo_status_id: Mapped[int] = mapped_column(
        SmallInteger,
        ForeignKey("todo_status.id", ondelete="RESTRICT"),
        nullable=False,
    )
    due_date: Mapped[date | None] = mapped_column(Date)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reference_link: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app_user.id", ondelete="SET NULL"))


class ProtocolImage(Base, TimestampMixin):
    __tablename__ = "protocol_image"
    __table_args__ = (
        UniqueConstraint("protocol_element_id", "sort_index", name="uq_protocol_image_element_sort"),
        Index("idx_protocol_image_protocol_element", "protocol_element_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    protocol_element_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("protocol_element.id", ondelete="CASCADE"),
        nullable=False,
    )
    stored_file_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("stored_file.id", ondelete="RESTRICT"),
        nullable=False,
    )
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
    generated_file_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("stored_file.id", ondelete="SET NULL"),
    )
    generator_version: Mapped[str | None] = mapped_column(Text)
