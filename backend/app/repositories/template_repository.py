from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Template


class TemplateRepository:
    def list(self, db: Session, *, tenant_id: int, query: str | None = None, status: str | None = None) -> list[Template]:
        statement = select(Template).where(Template.tenant_id == tenant_id)
        if query:
            statement = statement.where(Template.name.ilike(f"%{query}%"))
        if status:
            statement = statement.where(Template.status == status)
        statement = statement.order_by(Template.id.desc())
        return list(db.scalars(statement))

    def get(self, db: Session, template_id: int) -> Template | None:
        return db.get(Template, template_id)

    def create(self, db: Session, template: Template) -> Template:
        db.add(template)
        db.commit()
        db.refresh(template)
        return template

    def update(self, db: Session, template: Template, values: dict) -> Template:
        for key, value in values.items():
            setattr(template, key, value)
        db.add(template)
        db.commit()
        db.refresh(template)
        return template

    def delete(self, db: Session, template: Template) -> None:
        db.delete(template)
        db.commit()
