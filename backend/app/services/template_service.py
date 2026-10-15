import copy
import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CycleConfig, DocumentTemplateAssignment, Event, Participant, Template, TemplateElement
from app.repositories.template_element_repository import TemplateElementRepository
from app.repositories.template_repository import TemplateRepository
from app.schemas.participant import TemplateParticipantAssignmentRead
from app.services import public_id_service
from app.services.access_service import AccessService
from app.schemas.template import TemplateCreate, TemplateUpdate


class TemplateService:
    def __init__(
        self,
        repository: TemplateRepository | None = None,
        template_element_repository: TemplateElementRepository | None = None,
    ) -> None:
        self.repository = repository or TemplateRepository()
        self.template_element_repository = template_element_repository or TemplateElementRepository()
        self.access_service = AccessService()

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

    def _resolve_tenant_refs(
        self,
        db: Session,
        *,
        tenant_id: int,
        next_event_id: uuid.UUID | None = None,
        last_event_id: uuid.UUID | None = None,
        cycle_config_id: uuid.UUID | None = None,
    ) -> dict[str, int | None]:
        """Resolves next_event_id/last_event_id/cycle_config_id from public UUIDs to internal
        ids, scoped to tenant_id - all three are client-supplied on template create/update, so
        this also serves as their ownership validation: without it, a writer could point a
        template at another tenant's Event/CycleConfig, which then leaks into every protocol
        created from it (title/date snapshots, ...). Dokumentvorlage und Brand-Profil einer
        Protokollvorlage verwaltet das Document Studio (document_template_assignment)."""
        resolved: dict[str, int | None] = {}
        for label, model, value in (
            ("next_event_id", Event, next_event_id),
            ("last_event_id", Event, last_event_id),
            ("cycle_config_id", CycleConfig, cycle_config_id),
        ):
            if value is None:
                resolved[label] = None
                continue
            internal_id = public_id_service.resolve_internal_id(db, model, value, tenant_id=tenant_id)
            if internal_id is None:
                raise ValueError(f"{label} does not belong to current tenant")
            resolved[label] = internal_id
        return resolved

    def create_template(self, db: Session, payload: TemplateCreate, *, tenant_id: int, created_by: int | None):
        refs = self._resolve_tenant_refs(
            db,
            tenant_id=tenant_id,
            next_event_id=payload.next_event_id,
            last_event_id=payload.last_event_id,
            cycle_config_id=payload.cycle_config_id,
        )
        template = Template(
            tenant_id=tenant_id,
            next_event_id=refs["next_event_id"],
            last_event_id=refs["last_event_id"],
            name=payload.name,
            description=payload.description,
            protocol_number_pattern=payload.protocol_number_pattern,
            title_pattern=payload.title_pattern,
            auto_create_next_protocol=payload.auto_create_next_protocol,
            cycle_config_id=refs["cycle_config_id"],
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
        refs = self._resolve_tenant_refs(
            db,
            tenant_id=template.tenant_id,
            next_event_id=values.get("next_event_id"),
            last_event_id=values.get("last_event_id"),
            cycle_config_id=values.get("cycle_config_id"),
        )
        for field in ("next_event_id", "last_event_id", "cycle_config_id"):
            if field in values:
                values[field] = refs[field]
        return self.repository.update(db, template, values)

    def delete_template(self, db: Session, template_id: int) -> bool:
        template = self.repository.get(db, template_id)
        if template is None:
            return False
        self.repository.delete(db, template)
        return True

    def duplicate_template(self, db: Session, template_id: int, *, new_name: str, created_by: int | None) -> Template | None:
        source = self.repository.get(db, template_id)
        if source is None:
            return None

        duplicate = Template(
            tenant_id=source.tenant_id,
            next_event_id=source.next_event_id,
            last_event_id=source.last_event_id,
            todo_due_event_tag=source.todo_due_event_tag,
            name=new_name,
            description=source.description,
            protocol_number_pattern=source.protocol_number_pattern,
            title_pattern=source.title_pattern,
            auto_create_next_protocol=source.auto_create_next_protocol,
            cycle_config_id=source.cycle_config_id,
            version=1,
            status=source.status,
            created_by=created_by,
        )
        created = self.repository.create(db, duplicate)

        # Elements stay within the same tenant, so element_definition_id and any participant/list
        # references embedded in configuration_json (e.g. responsibility assignments) remain valid
        # as-is - no remapping needed, unlike a cross-tenant clone.
        for template_element, _definition in self.template_element_repository.list_for_template(db, template_id):
            db.add(
                TemplateElement(
                    template_id=created.id,
                    element_definition_id=template_element.element_definition_id,
                    sort_index=template_element.sort_index,
                    section_name=template_element.section_name,
                    section_order=template_element.section_order,
                    is_required=template_element.is_required,
                    is_visible=template_element.is_visible,
                    export_visible=template_element.export_visible,
                    configuration_json=copy.deepcopy(template_element.configuration_json or {}),
                )
            )
        # PDF-Vorlage/Brand-Profil der Protokollvorlage (Document Studio) gelten auch für die
        # Kopie - früher kopierte das Duplizieren den Hausstil mit
        for assignment in db.scalars(select(DocumentTemplateAssignment).where(DocumentTemplateAssignment.protocol_template_id == source.id)):
            db.add(
                DocumentTemplateAssignment(
                    tenant_id=assignment.tenant_id,
                    document_type=assignment.document_type,
                    protocol_template_id=created.id,
                    document_template_id=assignment.document_template_id,
                    brand_id=assignment.brand_id,
                    created_by=created_by,
                )
            )
        db.commit()

        assignments = [
            (participant.id, exclude_from_attendance)
            for participant, exclude_from_attendance in self.repository.list_participant_assignments(db, template_id)
        ]
        if assignments:
            self.repository.replace_participants(db, created.id, assignments)

        return created

    def _serialize_template_participants(self, rows: list[tuple[Participant, bool]]) -> list[dict[str, object]]:
        return [
            {
                **TemplateParticipantAssignmentRead.model_validate(participant).model_dump(),
                "exclude_from_attendance": exclude_from_attendance,
            }
            for participant, exclude_from_attendance in rows
        ]

    def list_template_participants(
        self, db: Session, template_id: int, *, as_of: date | None = None
    ) -> list[dict[str, object]]:
        return self._serialize_template_participants(
            self.repository.list_participant_assignments(db, template_id, as_of=as_of)
        )

    def replace_template_participants(
        self,
        db: Session,
        template_id: int,
        assignments: list[tuple[int, bool]],
    ) -> list[dict[str, object]]:
        previous = self.repository.list_participant_assignments(db, template_id)
        current = self.repository.replace_participants(db, template_id, assignments)
        affected_user_ids = {
            participant.id
            for participant, _ in [*previous, *current]
        }
        template = self.repository.get(db, template_id)
        if template is not None:
            for user_id in affected_user_ids:
                self.access_service.sync_user_access_from_participants(db, user_id=user_id, tenant_id=template.tenant_id)
            db.commit()
        return self._serialize_template_participants(current)
