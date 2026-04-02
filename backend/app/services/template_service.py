from sqlalchemy.orm import Session

from app.models import Participant, Template
from app.repositories.template_repository import TemplateRepository
from app.services.access_service import AccessService
from app.services.document_template_service import DocumentTemplateService
from app.schemas.template import TemplateCreate, TemplateUpdate


class TemplateService:
    def __init__(self, repository: TemplateRepository | None = None) -> None:
        self.repository = repository or TemplateRepository()
        self.access_service = AccessService()
        self.document_template_service = DocumentTemplateService()

    def list_templates(
        self,
        db: Session,
        *,
        tenant_id: int,
        query: str | None = None,
        status: str | None = None,
        user_id: int | None = None,
        restrict_to_assigned: bool = False,
    ):
        template_ids = None
        if restrict_to_assigned and user_id is not None:
            template_ids = self.access_service.repository.list_template_ids(db, user_id=user_id, tenant_id=tenant_id)
        return self.repository.list(db, tenant_id=tenant_id, query=query, status=status, template_ids=template_ids)

    def get_template(self, db: Session, template_id: int):
        return self.repository.get(db, template_id)

    def create_template(self, db: Session, payload: TemplateCreate, *, tenant_id: int, created_by: int | None):
        document_template_id = payload.document_template_id
        if document_template_id is None:
            document_template_id = self.document_template_service.default_document_template_id(db, tenant_id)
        else:
            available_document_template_ids = {
                item.id for item in self.document_template_service.repository.list(db, tenant_id)
            }
            if document_template_id not in available_document_template_ids:
                document_template_id = self.document_template_service.default_document_template_id(db, tenant_id)
        template = Template(
            tenant_id=tenant_id,
            document_template_id=document_template_id,
            next_event_id=payload.next_event_id,
            last_event_id=payload.last_event_id,
            name=payload.name,
            description=payload.description,
            protocol_number_pattern=payload.protocol_number_pattern,
            title_pattern=payload.title_pattern,
            auto_create_next_protocol=payload.auto_create_next_protocol,
            cycle_reset_month=payload.cycle_reset_month,
            cycle_reset_day=payload.cycle_reset_day,
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

    def list_template_participants(self, db: Session, template_id: int) -> list[Participant]:
        return self.repository.list_participants(db, template_id)

    def replace_template_participants(self, db: Session, template_id: int, participant_ids: list[int]) -> list[Participant]:
        previous = self.repository.list_participants(db, template_id)
        current = self.repository.replace_participants(db, template_id, participant_ids)
        affected_user_ids = {
            participant.app_user_id
            for participant in [*previous, *current]
            if participant.app_user_id is not None
        }
        template = self.repository.get(db, template_id)
        if template is not None:
            for user_id in affected_user_ids:
                self.access_service.sync_user_access_from_participants(db, user_id=user_id, tenant_id=template.tenant_id)
            db.commit()
        return current
