from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import Participant, Template, TemplateParticipant


class ParticipantRepository:
    def list(self, db: Session, *, tenant_id: int, active_only: bool = False) -> list[Participant]:
        statement = select(Participant).where(Participant.tenant_id == tenant_id)
        if active_only:
            statement = statement.where(Participant.is_active.is_(True))
        statement = statement.order_by(Participant.display_name.asc(), Participant.id.asc())
        return list(db.scalars(statement))

    def get(self, db: Session, participant_id: int) -> Participant | None:
        return db.get(Participant, participant_id)

    def create(self, db: Session, participant: Participant) -> Participant:
        db.add(participant)
        db.commit()
        db.refresh(participant)
        return participant

    def update(self, db: Session, participant: Participant, values: dict) -> Participant:
        for key, value in values.items():
            setattr(participant, key, value)
        db.add(participant)
        db.commit()
        db.refresh(participant)
        return participant

    def delete(self, db: Session, participant: Participant) -> None:
        db.delete(participant)
        db.commit()

    def delete_many(self, db: Session, participants: list[Participant]) -> int:
        count = len(participants)
        for participant in participants:
            db.delete(participant)
        db.commit()
        return count

    def list_templates_for_participant(self, db: Session, participant_id: int) -> list[Template]:
        statement = (
            select(Template)
            .join(TemplateParticipant, TemplateParticipant.template_id == Template.id)
            .where(TemplateParticipant.participant_id == participant_id)
            .order_by(Template.name.asc(), Template.id.asc())
        )
        return list(db.scalars(statement))

    def replace_templates_for_participant(self, db: Session, participant_id: int, template_ids: list[int]) -> list[Template]:
        db.execute(delete(TemplateParticipant).where(TemplateParticipant.participant_id == participant_id))
        for template_id in template_ids:
            db.add(TemplateParticipant(template_id=template_id, participant_id=participant_id))
        db.commit()
        return self.list_templates_for_participant(db, participant_id)
