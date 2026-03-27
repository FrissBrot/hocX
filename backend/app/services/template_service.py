from sqlalchemy.orm import Session

from app.models import Template
from app.repositories.template_repository import TemplateRepository
from app.schemas.template import TemplateCreate, TemplateUpdate


class TemplateService:
    def __init__(self, repository: TemplateRepository | None = None) -> None:
        self.repository = repository or TemplateRepository()

    def list_templates(self, db: Session, *, tenant_id: int, query: str | None = None, status: str | None = None):
        return self.repository.list(db, tenant_id=tenant_id, query=query, status=status)

    def get_template(self, db: Session, template_id: int):
        return self.repository.get(db, template_id)

    def create_template(self, db: Session, payload: TemplateCreate, *, tenant_id: int, created_by: int | None):
        template = Template(
            tenant_id=tenant_id,
            document_template_id=payload.document_template_id,
            name=payload.name,
            description=payload.description,
            version=payload.version,
            status=payload.status,
            created_by=created_by,
        )
        return self.repository.create(db, template)

    def update_template(self, db: Session, template_id: int, payload: TemplateUpdate):
        template = self.repository.get(db, template_id)
        if template is None:
            return None
        values = payload.model_dump(exclude_unset=True)
        if not values:
            return template
        return self.repository.update(db, template, values)

    def delete_template(self, db: Session, template_id: int) -> bool:
        template = self.repository.get(db, template_id)
        if template is None:
            return False
        self.repository.delete(db, template)
        return True
