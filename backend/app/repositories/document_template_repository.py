from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DocumentTemplate, DocumentTemplatePart


class DocumentTemplateRepository:
    def list(self, db: Session, tenant_id: int = 1) -> list[DocumentTemplate]:
        return list(
            db.scalars(
                select(DocumentTemplate)
                .where(DocumentTemplate.tenant_id == tenant_id)
                .order_by(DocumentTemplate.is_default.desc(), DocumentTemplate.name.asc(), DocumentTemplate.id.asc())
            )
        )

    def get(self, db: Session, document_template_id: int) -> DocumentTemplate | None:
        return db.get(DocumentTemplate, document_template_id)

    def create(self, db: Session, entity: DocumentTemplate) -> DocumentTemplate:
        db.add(entity)
        db.commit()
        db.refresh(entity)
        return entity

    def update(self, db: Session, entity: DocumentTemplate, values: dict) -> DocumentTemplate:
        for key, value in values.items():
            setattr(entity, key, value)
        db.add(entity)
        db.commit()
        db.refresh(entity)
        return entity

    def delete(self, db: Session, entity: DocumentTemplate) -> None:
        db.delete(entity)
        db.commit()


class DocumentTemplatePartRepository:
    def list(self, db: Session, tenant_id: int = 1) -> list[DocumentTemplatePart]:
        return list(
            db.scalars(
                select(DocumentTemplatePart)
                .where(DocumentTemplatePart.tenant_id == tenant_id)
                .order_by(DocumentTemplatePart.part_type.asc(), DocumentTemplatePart.name.asc(), DocumentTemplatePart.id.asc())
            )
        )

    def get(self, db: Session, part_id: int) -> DocumentTemplatePart | None:
        return db.get(DocumentTemplatePart, part_id)

    def create(self, db: Session, entity: DocumentTemplatePart) -> DocumentTemplatePart:
        db.add(entity)
        db.commit()
        db.refresh(entity)
        return entity

    def update(self, db: Session, entity: DocumentTemplatePart, values: dict) -> DocumentTemplatePart:
        for key, value in values.items():
            setattr(entity, key, value)
        db.add(entity)
        db.commit()
        db.refresh(entity)
        return entity

    def delete(self, db: Session, entity: DocumentTemplatePart) -> None:
        db.delete(entity)
        db.commit()
