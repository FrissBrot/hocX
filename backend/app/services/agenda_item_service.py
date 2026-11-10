"""Anliegen (Tabelle agenda_item, Migration 0153): Punkte, die in einer kommenden Sitzung
besprochen werden sollen.

Ein Anliegen gehört zu einer Protokollvorlage und einem ihrer Punkte (template_element).
Solange es nicht gebunden ist (protocol_id NULL), erscheint es im *Zielprotokoll*: dem
frühesten Protokoll derselben Vorlage im Status geplant/vorbereitet mit Datum ab
earliest_date (bei gleichem Datum das ältere). Ein Protokoll im Editor zeigt also seine
gebundenen Anliegen plus alle wartenden, deren Zielprotokoll es ist - ohne eigenen Block in
der Vorlage.

Beim Übergang nach "durchgeführt" (auch beim Überspringen, siehe
ProtocolService._run_status_transition_hooks) bindet das Protokoll seine wartenden Anliegen
fest (protocol_id, protocol_element_id). Danach zieht ein neues Protokoll sie nicht mehr an
sich. Gebundene Anliegen eines abgeschlossenen Protokolls sind eingefroren.

Vertagen löst die Bindung, zählt postponed_count hoch und setzt earliest_date neu:
"nächste Sitzung" = der Tag nach dem bisherigen (gebundenen oder Ziel-)Protokoll, ein Monat
= der Monatserste, frühestens heute bzw. nach dem bisherigen Protokoll.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session, aliased

from app.models.entities import AgendaItem, Participant, Protocol, ProtocolElement, Template, TemplateElement

# Status, in denen ein Protokoll wartende Anliegen anzieht.
OPEN_PROTOCOL_STATUSES = ("geplant", "vorbereitet")
SCHEDULE_KINDS = ("next_meeting", "month")


class AgendaItemFrozenError(ValueError):
    """Das Anliegen gehört zu einem abgeschlossenen Protokoll und ist eingefroren."""


@dataclass
class Schedule:
    kind: str
    month: date | None = None


def month_start(value: date) -> date:
    return value.replace(day=1)


def _target_protocol_subquery(item=AgendaItem):
    """Korrelierte Unterabfrage: Zielprotokoll eines wartenden Anliegens."""
    return (
        select(Protocol.id)
        .where(
            Protocol.tenant_id == item.tenant_id,
            Protocol.template_id == item.template_id,
            Protocol.status.in_(OPEN_PROTOCOL_STATUSES),
            Protocol.protocol_date >= item.earliest_date,
        )
        .order_by(Protocol.protocol_date.asc(), Protocol.id.asc())
        .limit(1)
        .correlate(item)
        .scalar_subquery()
    )


class AgendaItemService:
    # ── Lesen ────────────────────────────────────────────────────────────

    def target_protocol_ids(self, db: Session, item_ids: list[int]) -> dict[int, int | None]:
        if not item_ids:
            return {}
        rows = db.execute(
            select(AgendaItem.id, _target_protocol_subquery()).where(AgendaItem.id.in_(item_ids))
        ).all()
        return {row[0]: row[1] for row in rows}

    def _pending_for_protocol_query(self, protocol: Protocol):
        """Wartende Anliegen, deren Zielprotokoll `protocol` ist (unabhängig von dessen Status)."""
        other = aliased(Protocol)
        earlier_open = (
            select(other.id)
            .where(
                other.tenant_id == AgendaItem.tenant_id,
                other.template_id == AgendaItem.template_id,
                other.id != protocol.id,
                other.status.in_(OPEN_PROTOCOL_STATUSES),
                other.protocol_date >= AgendaItem.earliest_date,
                or_(
                    other.protocol_date < protocol.protocol_date,
                    and_(other.protocol_date == protocol.protocol_date, other.id < protocol.id),
                ),
            )
            .correlate(AgendaItem)
            .exists()
        )
        return select(AgendaItem).where(
            AgendaItem.tenant_id == protocol.tenant_id,
            AgendaItem.template_id == protocol.template_id,
            AgendaItem.protocol_id.is_(None),
            AgendaItem.earliest_date <= protocol.protocol_date,
            ~earlier_open,
        )

    def items_for_protocol(self, db: Session, protocol: Protocol) -> list[AgendaItem]:
        """Gebundene Anliegen des Protokolls plus (solange es offen ist) die wartenden, deren
        Zielprotokoll es ist. Sortiert nach Erstellung."""
        items = list(db.scalars(select(AgendaItem).where(AgendaItem.protocol_id == protocol.id)).all())
        if protocol.status in OPEN_PROTOCOL_STATUSES:
            items.extend(db.scalars(self._pending_for_protocol_query(protocol)).all())
        items.sort(key=lambda item: (item.created_at, item.id))
        return items

    def placements(self, db: Session, protocol: Protocol, items: list[AgendaItem]) -> dict[int, int | None]:
        """Protokollelement je Anliegen: das gebundene Element, sonst das Element zum
        Vorlagenpunkt, sonst None (Anzeige unter «Weitere Anliegen»)."""
        elements = db.execute(
            select(ProtocolElement.id, ProtocolElement.template_element_id)
            .where(ProtocolElement.protocol_id == protocol.id)
            .order_by(ProtocolElement.sort_index.asc())
        ).all()
        element_ids = {row.id for row in elements}
        by_template_element: dict[int, int] = {}
        for row in elements:
            if row.template_element_id is not None:
                by_template_element.setdefault(row.template_element_id, row.id)
        result: dict[int, int | None] = {}
        for item in items:
            if item.protocol_id == protocol.id and item.protocol_element_id in element_ids:
                result[item.id] = item.protocol_element_id
            elif item.template_element_id is not None:
                result[item.id] = by_template_element.get(item.template_element_id)
            else:
                result[item.id] = None
        return result

    def list_for_tenant(self, db: Session, tenant_id: int, *, template_ids: set[int] | None = None) -> list[AgendaItem]:
        stmt = select(AgendaItem).where(AgendaItem.tenant_id == tenant_id)
        if template_ids is not None:
            if not template_ids:
                return []
            stmt = stmt.where(AgendaItem.template_id.in_(template_ids))
        return list(db.scalars(stmt.order_by(AgendaItem.created_at.desc(), AgendaItem.id.desc())).all())

    def creator_names(self, db: Session, items: list[AgendaItem]) -> dict[int, str]:
        ids = {item.created_by for item in items if item.created_by is not None}
        if not ids:
            return {}
        return dict(db.execute(select(Participant.id, Participant.display_name).where(Participant.id.in_(ids))).all())

    def is_frozen(self, db: Session, item: AgendaItem) -> bool:
        if item.protocol_id is None:
            return False
        status = db.scalar(select(Protocol.status).where(Protocol.id == item.protocol_id))
        return status == "abgeschlossen"

    # ── Schreiben ────────────────────────────────────────────────────────

    def _validate_point(self, db: Session, template: Template, template_element_id: int | None) -> None:
        if template_element_id is None:
            return
        owner = db.scalar(select(TemplateElement.template_id).where(TemplateElement.id == template_element_id))
        if owner != template.id:
            raise ValueError("Template element does not belong to the template")

    def _clean_title(self, title: str) -> str:
        cleaned = (title or "").strip()
        if not cleaned:
            raise ValueError("Title is required")
        return cleaned

    def _clean_body(self, body: str | None) -> str | None:
        if body is None:
            return None
        return body if body.strip() else None

    def _earliest_for(self, schedule: Schedule, *, after: date | None, today: date) -> date:
        """after: Datum des Protokolls, nach dem das Anliegen frühestens wieder erscheint."""
        floor = today if after is None else max(today, after + timedelta(days=1))
        if schedule.kind == "month":
            if schedule.month is None:
                raise ValueError("Month is required")
            return max(month_start(schedule.month), floor)
        return floor

    def create(
        self,
        db: Session,
        *,
        tenant_id: int,
        template: Template,
        template_element_id: int | None,
        title: str,
        body: str | None,
        schedule: Schedule,
        created_by: int | None,
        today: date | None = None,
    ) -> AgendaItem:
        if template.tenant_id != tenant_id:
            raise ValueError("Template does not belong to the tenant")
        self._validate_point(db, template, template_element_id)
        today = today or date.today()
        item = AgendaItem(
            tenant_id=tenant_id,
            template_id=template.id,
            template_element_id=template_element_id,
            title=self._clean_title(title),
            body=self._clean_body(body),
            schedule_kind=schedule.kind,
            scheduled_month=month_start(schedule.month) if schedule.kind == "month" and schedule.month else None,
            earliest_date=self._earliest_for(schedule, after=None, today=today),
            created_by=created_by,
        )
        db.add(item)
        db.commit()
        db.refresh(item)
        return item

    def create_in_protocol(
        self,
        db: Session,
        *,
        protocol: Protocol,
        protocol_element: ProtocolElement | None,
        title: str,
        body: str | None,
        created_by: int | None,
    ) -> AgendaItem:
        """Im Editor erstellt: sofort an dieses Protokoll gebunden."""
        if protocol.status == "abgeschlossen":
            raise AgendaItemFrozenError("Protocol is abgeschlossen")
        if protocol_element is not None and protocol_element.protocol_id != protocol.id:
            raise ValueError("Protocol element does not belong to the protocol")
        item = AgendaItem(
            tenant_id=protocol.tenant_id,
            template_id=protocol.template_id,
            template_element_id=protocol_element.template_element_id if protocol_element else None,
            protocol_id=protocol.id,
            protocol_element_id=protocol_element.id if protocol_element else None,
            title=self._clean_title(title),
            body=self._clean_body(body),
            schedule_kind="next_meeting",
            earliest_date=protocol.protocol_date,
            created_by=created_by,
        )
        db.add(item)
        db.commit()
        db.refresh(item)
        return item

    def update(
        self,
        db: Session,
        item: AgendaItem,
        *,
        fields: set[str],
        title: str | None = None,
        body: str | None = None,
        template: Template | None = None,
        template_element_id: int | None = None,
        schedule: Schedule | None = None,
        today: date | None = None,
    ) -> AgendaItem:
        """`fields` nennt die gesetzten Felder. Vorlage, Punkt und Termin lassen sich nur bei
        wartenden Anliegen ändern (gebundene: vertagen)."""
        if self.is_frozen(db, item):
            raise AgendaItemFrozenError("Agenda item belongs to an abgeschlossen protocol")
        if "title" in fields:
            item.title = self._clean_title(title or "")
        if "body" in fields:
            item.body = self._clean_body(body)
        structural = {"template_id", "template_element_id", "schedule"} & fields
        if structural and item.protocol_id is not None:
            raise ValueError("Bound agenda items can only be postponed")
        if "template_id" in fields and template is not None and template.id != item.template_id:
            if template.tenant_id != item.tenant_id:
                raise ValueError("Template does not belong to the tenant")
            item.template_id = template.id
            item.template_element_id = None
        if "template_element_id" in fields:
            target_template = db.get(Template, item.template_id)
            self._validate_point(db, target_template, template_element_id)
            item.template_element_id = template_element_id
        if "schedule" in fields and schedule is not None:
            self._apply_schedule(item, schedule, after=None, today=today or date.today())
        db.add(item)
        db.commit()
        db.refresh(item)
        return item

    def _apply_schedule(self, item: AgendaItem, schedule: Schedule, *, after: date | None, today: date) -> None:
        item.schedule_kind = schedule.kind
        item.scheduled_month = month_start(schedule.month) if schedule.kind == "month" and schedule.month else None
        item.earliest_date = self._earliest_for(schedule, after=after, today=today)

    def postpone(self, db: Session, item: AgendaItem, schedule: Schedule, *, today: date | None = None) -> AgendaItem:
        if self.is_frozen(db, item):
            raise AgendaItemFrozenError("Agenda item belongs to an abgeschlossen protocol")
        reference_id = item.protocol_id or self.target_protocol_ids(db, [item.id]).get(item.id)
        reference_date = db.scalar(select(Protocol.protocol_date).where(Protocol.id == reference_id)) if reference_id else None
        self._apply_schedule(item, schedule, after=reference_date, today=today or date.today())
        item.protocol_id = None
        item.protocol_element_id = None
        item.postponed_count = (item.postponed_count or 0) + 1
        db.add(item)
        db.commit()
        db.refresh(item)
        return item

    def delete(self, db: Session, item: AgendaItem) -> None:
        if self.is_frozen(db, item):
            raise AgendaItemFrozenError("Agenda item belongs to an abgeschlossen protocol")
        db.delete(item)
        db.commit()

    def bind_to_protocol(self, db: Session, protocol: Protocol) -> int:
        """Beim Durchführen: wartende Anliegen mit diesem Zielprotokoll fest binden. Ohne
        Commit - Teil des Statusübergangs."""
        pending = list(db.scalars(self._pending_for_protocol_query(protocol)).all())
        if not pending:
            return 0
        placement = self.placements(db, protocol, pending)
        for item in pending:
            item.protocol_id = protocol.id
            item.protocol_element_id = placement.get(item.id)
            db.add(item)
        db.flush()
        return len(pending)

    # ── Vorlagen-Präferenz ───────────────────────────────────────────────

    def templates_with_points(self, db: Session, tenant_id: int, *, template_ids: set[int] | None = None) -> list[dict]:
        stmt = select(Template).where(Template.tenant_id == tenant_id, Template.status == "active")
        if template_ids is not None:
            if not template_ids:
                return []
            stmt = stmt.where(Template.id.in_(template_ids))
        templates = list(db.scalars(stmt.order_by(Template.name.asc())).all())
        if not templates:
            return []
        points = db.execute(
            select(TemplateElement.template_id, TemplateElement.public_id, TemplateElement.section_name)
            .where(TemplateElement.template_id.in_([template.id for template in templates]), TemplateElement.is_visible.is_(True))
            .order_by(TemplateElement.template_id, TemplateElement.sort_index)
        ).all()
        by_template: dict[int, list[dict]] = {}
        for row in points:
            by_template.setdefault(row.template_id, []).append({"id": row.public_id, "name": row.section_name})
        return [
            {"id": template.public_id, "name": template.name, "points": by_template.get(template.id, [])}
            for template in templates
        ]
