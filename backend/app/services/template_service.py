from sqlalchemy.orm import Session

from app.models import Template
from app.repositories.template_repository import TemplateRepository
from app.schemas.template import TemplateCreate


class TemplateService:
    def __init__(self, repository: TemplateRepository | None = None) -> None:
        self.repository = repository or TemplateRepository()

    def list_templates(self, db: Session):
        return self.repository.list(db)

    def get_template(self, db: Session, template_id: int):
        return self.repository.get(db, template_id)

    def create_template(self, db: Session, payload: TemplateCreate):
        template = Template(
            tenant_id=payload.tenant_id,
            document_template_id=payload.document_template_id,
            name=payload.name,
            description=payload.description,
            version=payload.version,
            status=payload.status,
            created_by=payload.created_by,
        )
        return self.repository.create(db, template)

