from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    DocumentTemplate,
    ElementDefinition,
    ElementType,
    Protocol,
    ProtocolDisplaySnapshot,
    ProtocolElement,
    ProtocolElementBlock,
    ProtocolText,
    Template,
    TemplateElement,
)
from app.services.document_template_service import DocumentTemplateService
from app.repositories.protocol_repository import ProtocolRepository
from app.schemas.protocol import ProtocolCreateFromTemplate, ProtocolUpdate


class ProtocolService:
    def __init__(self, repository: ProtocolRepository | None = None) -> None:
        self.repository = repository or ProtocolRepository()
        self.document_template_service = DocumentTemplateService()

    def list_protocols(self, db: Session, *, tenant_id: int, query: str | None = None, status: str | None = None):
        return self.repository.list(db, tenant_id=tenant_id, query=query, status=status)

    def get_protocol(self, db: Session, protocol_id: int):
        return self.repository.get(db, protocol_id)

    def create_from_template(self, db: Session, payload: ProtocolCreateFromTemplate, *, tenant_id: int, created_by: int | None) -> int:
        template = db.get(Template, payload.template_id)
        if template is None:
            raise ValueError("Template not found")
        if template.tenant_id != tenant_id:
            raise ValueError("Template does not belong to current tenant")

        selected_document_template_id = payload.document_template_id if payload.document_template_id is not None else template.document_template_id
        document_template = db.get(DocumentTemplate, selected_document_template_id) if selected_document_template_id else None
        protocol = Protocol(
            tenant_id=tenant_id,
            template_id=template.id,
            template_version=template.version,
            document_template_id=selected_document_template_id,
            document_template_version=document_template.version if document_template else None,
            document_template_path_snapshot=None,
            protocol_number=payload.protocol_number,
            title=payload.title,
            protocol_date=payload.protocol_date,
            event_id=payload.event_id,
            status="draft",
            created_by=created_by,
        )
        db.add(protocol)
        db.flush()

        text_type_id = db.scalar(select(ElementType.id).where(ElementType.code == "text"))
        display_type_id = db.scalar(select(ElementType.id).where(ElementType.code == "display"))
        static_text_type_id = db.scalar(select(ElementType.id).where(ElementType.code == "static_text"))

        template_rows = db.execute(
            select(TemplateElement, ElementDefinition)
            .join(ElementDefinition, ElementDefinition.id == TemplateElement.element_definition_id)
            .where(TemplateElement.template_id == template.id)
            .order_by(TemplateElement.sort_index.asc(), TemplateElement.id.asc())
        ).all()

        for template_element, definition in template_rows:
            protocol_element = ProtocolElement(
                protocol_id=protocol.id,
                template_element_id=template_element.id,
                sort_index=template_element.sort_index,
                section_name_snapshot=definition.title,
                section_order_snapshot=template_element.sort_index,
                is_required_snapshot=False,
                is_visible_snapshot=True,
                export_visible_snapshot=True,
            )
            db.add(protocol_element)
            db.flush()

            for block in sorted((definition.configuration_json or {}).get("blocks", []), key=lambda entry: (entry.get("sort_index", 0), entry.get("id", 0))):
                protocol_block = ProtocolElementBlock(
                    protocol_element_id=protocol_element.id,
                    template_element_block_id=None,
                    element_definition_id=definition.id,
                    element_type_id=block["element_type_id"],
                    render_type_id=block["render_type_id"],
                    title_snapshot=block["title"],
                    display_title_snapshot=block.get("title"),
                    description_snapshot=block.get("description"),
                    block_title_snapshot=block.get("block_title"),
                    is_editable_snapshot=block.get("is_editable", True),
                    allows_multiple_values_snapshot=block.get("allows_multiple_values", False),
                    sort_index=block["sort_index"],
                    render_order=block.get("render_order"),
                    is_required_snapshot=False,
                    is_visible_snapshot=block.get("is_visible", True),
                    export_visible_snapshot=block.get("export_visible", True),
                    latex_template_snapshot=block.get("latex_template"),
                    configuration_snapshot_json={
                        **block.get("configuration_json", {}),
                        "default_content": block.get("default_content"),
                    },
                )
                db.add(protocol_block)
                db.flush()

                if block["element_type_id"] == text_type_id:
                    db.add(ProtocolText(protocol_element_block_id=protocol_block.id, content=block.get("default_content") or ""))
                elif block["element_type_id"] == static_text_type_id:
                    db.add(ProtocolText(protocol_element_block_id=protocol_block.id, content=block.get("default_content") or ""))
                elif block["element_type_id"] == display_type_id:
                    db.add(
                        ProtocolDisplaySnapshot(
                            protocol_element_block_id=protocol_block.id,
                            source_type=None,
                            source_id=None,
                            compiled_text=None,
                            snapshot_json={},
                        )
                    )

        db.commit()
        db.refresh(protocol)
        protocol = self.document_template_service.snapshot_template_for_protocol(db, protocol, selected_document_template_id)
        return int(protocol.id)

    def update_protocol(self, db: Session, protocol_id: int, payload: ProtocolUpdate):
        protocol = self.repository.get(db, protocol_id)
        if protocol is None:
            return None
        values = payload.model_dump(exclude_unset=True)
        document_template_id = values.pop("document_template_id", None) if "document_template_id" in values else None
        if not values:
            if "document_template_id" in payload.model_fields_set:
                return self.document_template_service.snapshot_template_for_protocol(db, protocol, document_template_id)
            return protocol
        updated = self.repository.update(db, protocol, values)
        if "document_template_id" in payload.model_fields_set:
            return self.document_template_service.snapshot_template_for_protocol(db, updated, document_template_id)
        return updated

    def delete_protocol(self, db: Session, protocol_id: int) -> bool:
        protocol = self.repository.get(db, protocol_id)
        if protocol is None:
            return False
        self.repository.delete(db, protocol)
        return True
