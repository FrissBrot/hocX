from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import Participant, Template, TemplateParticipant


class TemplateRepository:
    def list(
        self,
        db: Session,
        *,
        tenant_id: int,
        query: str | None = None,
        status: str | None = None,
        template_ids: list[int] | None = None,
    ) -> list[Template]:
        statement = select(Template).where(Template.tenant_id == tenant_id)
        if template_ids is not None:
            if not template_ids:
                return []
            statement = statement.where(Template.id.in_(template_ids))
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

    def list_participant_assignments(self, db: Session, template_id: int) -> list[tuple[Participant, bool]]:
        statement = (
            select(Participant, TemplateParticipant.exclude_from_attendance)
            .join(TemplateParticipant, TemplateParticipant.participant_id == Participant.id)
            .where(TemplateParticipant.template_id == template_id)
            .order_by(Participant.display_name.asc(), Participant.id.asc())
        )
        return [(participant, bool(exclude_from_attendance)) for participant, exclude_from_attendance in db.execute(statement).all()]

    def list_participants(self, db: Session, template_id: int) -> list[Participant]:
        return [participant for participant, _ in self.list_participant_assignments(db, template_id)]

    def replace_participants(self, db: Session, template_id: int, assignments: list[tuple[int, bool]]) -> list[tuple[Participant, bool]]:
        db.execute(delete(TemplateParticipant).where(TemplateParticipant.template_id == template_id))
        for participant_id, exclude_from_attendance in assignments:
            db.add(
                TemplateParticipant(
                    template_id=template_id,
                    participant_id=participant_id,
                    exclude_from_attendance=exclude_from_attendance,
                )
            )
        db.commit()
        return self.list_participant_assignments(db, template_id)
