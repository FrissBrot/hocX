from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Template


class TemplateRepository:
    def list(self, db: Session) -> list[Template]:
        return list(db.scalars(select(Template).order_by(Template.id.desc())))

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
