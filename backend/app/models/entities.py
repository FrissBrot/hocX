from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Integer, SmallInteger, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Tenant(Base):
    __tablename__ = "tenant"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Role(Base):
    __tablename__ = "role"

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    code: Mapped[str] = mapped_column(Text, unique=True)
    description: Mapped[str | None] = mapped_column(Text)


class AppUser(Base):
    __tablename__ = "app_user"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(Text)
    email: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    oidc_subject: Mapped[str | None] = mapped_column(Text)
    oidc_issuer: Mapped[str | None] = mapped_column(Text)
    oidc_email: Mapped[str | None] = mapped_column(Text)
    external_identity_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DocumentTemplate(Base):
    __tablename__ = "document_template"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int | None] = mapped_column(ForeignKey("tenant.id", ondelete="CASCADE"))
    code: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    filesystem_path: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Template(Base):
    __tablename__ = "template"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id", ondelete="CASCADE"))
    document_template_id: Mapped[int | None] = mapped_column(ForeignKey("document_template.id", ondelete="RESTRICT"))
    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    status: Mapped[str] = mapped_column(String(32), default="active", server_default="active")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("app_user.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ElementDefinition(Base):
    __tablename__ = "element_definition"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id", ondelete="CASCADE"))
    element_type_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("element_type.id", ondelete="RESTRICT"))
    render_type_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("render_type.id", ondelete="RESTRICT"))
    title: Mapped[str] = mapped_column(Text)
    display_title: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    is_editable: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    allows_multiple_values: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    export_visible: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    latex_template: Mapped[str | None] = mapped_column(Text)
    configuration_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, server_default="{}")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TemplateElement(Base):
    __tablename__ = "template_element"

    id: Mapped[int] = mapped_column(primary_key=True)
    template_id: Mapped[int] = mapped_column(ForeignKey("template.id", ondelete="CASCADE"))
    element_definition_id: Mapped[int] = mapped_column(ForeignKey("element_definition.id", ondelete="RESTRICT"))
    sort_index: Mapped[int] = mapped_column(Integer)
    render_order: Mapped[int | None] = mapped_column(Integer)
    section_name: Mapped[str | None] = mapped_column(Text)
    section_order: Mapped[int | None] = mapped_column(Integer)
    is_required: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    is_visible: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    export_visible: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    heading_text: Mapped[str | None] = mapped_column(Text)
    configuration_override_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Protocol(Base):
    __tablename__ = "protocol"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id", ondelete="CASCADE"))
    template_id: Mapped[int] = mapped_column(ForeignKey("template.id", ondelete="RESTRICT"))
    template_version: Mapped[int] = mapped_column(Integer)
    document_template_id: Mapped[int | None] = mapped_column(ForeignKey("document_template.id", ondelete="RESTRICT"))
    document_template_version: Mapped[int | None] = mapped_column(Integer)
    document_template_path_snapshot: Mapped[str | None] = mapped_column(Text)
    protocol_number: Mapped[str] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(Text)
    protocol_date: Mapped[date] = mapped_column(Date)
    event_id: Mapped[int | None] = mapped_column(ForeignKey("event.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(32), default="draft", server_default="draft")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("app_user.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProtocolElement(Base):
    __tablename__ = "protocol_element"

    id: Mapped[int] = mapped_column(primary_key=True)
    protocol_id: Mapped[int] = mapped_column(ForeignKey("protocol.id", ondelete="CASCADE"))
    element_type_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("element_type.id", ondelete="RESTRICT"))
    render_type_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("render_type.id", ondelete="RESTRICT"))
    title_snapshot: Mapped[str] = mapped_column(Text)
    is_editable_snapshot: Mapped[bool] = mapped_column(Boolean)
    sort_index: Mapped[int] = mapped_column(Integer)
    export_visible_snapshot: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    configuration_snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProtocolText(Base):
    __tablename__ = "protocol_text"

    id: Mapped[int] = mapped_column(primary_key=True)
    protocol_element_id: Mapped[int] = mapped_column(ForeignKey("protocol_element.id", ondelete="CASCADE"), unique=True)
    content: Mapped[str] = mapped_column(Text, default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProtocolTodo(Base):
    __tablename__ = "protocol_todo"

    id: Mapped[int] = mapped_column(primary_key=True)
    protocol_element_id: Mapped[int] = mapped_column(ForeignKey("protocol_element.id", ondelete="CASCADE"))
    sort_index: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    task: Mapped[str] = mapped_column(Text)
    todo_status_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("todo_status.id", ondelete="RESTRICT"))
    due_date: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

