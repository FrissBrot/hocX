"""Abgabe-Links: Zugang zur oeffentlichen Abgabebox.

Ein Link besteht aus einem Klartext-Namen (nur fuer den Admin-Bereich) und einem zufaelligen
Token, das selbst die Authentifizierung ist: die Abgabebox ist unter
<abgabebox-domain>/<token> erreichbar, der separate abgabebox-backend-Service loest darueber
Mandant und freigegebene Abgaben auf (siehe abgabebox-backend/app/repository.py).
"""

from __future__ import annotations

import secrets
import uuid

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import SubmissionLink, TenantDomain
from app.models.entities import SubmissionAssignment, submission_assignment_link_table
from app.schemas.submission import SubmissionLinkCreate, SubmissionLinkRead, SubmissionLinkUpdate
from app.services import public_id_service

DEFAULT_LINK_NAME = "Standard"
# 24 Bytes = 192 Bit Entropie, als URL-safe Base64 (32 Zeichen) - nicht erratbar.
_TOKEN_BYTES = 24


def generate_token() -> str:
    return secrets.token_urlsafe(_TOKEN_BYTES)


def abgabebox_base_url(db: Session, tenant_id: int) -> str:
    """Prefers the tenant's own verified Abgabebox domain, falls back to the shared default."""
    domain_row = (
        db.query(TenantDomain)
        .filter(TenantDomain.tenant_id == tenant_id, TenantDomain.purpose == "abgabebox", TenantDomain.status == "active")
        .one_or_none()
    )
    if domain_row is not None:
        return f"https://{domain_row.domain}"
    return settings.abgabebox_base_url


def link_url(base_url: str, link: SubmissionLink) -> str:
    return f"{base_url}/{link.token}"


def create_default_link(db: Session, tenant_id: int, *, commit: bool = True) -> SubmissionLink:
    """The link every new tenant starts with (also used when cloning/importing a tenant, which
    must never carry over the source tenant's tokens). Commits unless commit=False (then only
    flushes, for callers inside a larger transaction)."""
    link = SubmissionLink(tenant_id=tenant_id, name=DEFAULT_LINK_NAME, token=generate_token(), is_default=True)
    db.add(link)
    if commit:
        db.commit()
        db.refresh(link)
    else:
        db.flush()
    return link


def attach_assignments(db: Session, link: SubmissionLink, assignment_ids: list[int]) -> None:
    """Make the given Abgaben reachable over `link` (no-op for already attached ones)."""
    if not assignment_ids:
        return
    db.execute(
        pg_insert(submission_assignment_link_table)
        .values([{"assignment_id": assignment_id, "link_id": link.id} for assignment_id in assignment_ids])
        .on_conflict_do_nothing()
    )


def default_links(db: Session, tenant_id: int) -> list[SubmissionLink]:
    return list(
        db.scalars(select(SubmissionLink).where(SubmissionLink.tenant_id == tenant_id, SubmissionLink.is_default.is_(True)))
    )


def resolve_links(db: Session, public_ids: list[uuid.UUID], *, tenant_id: int) -> list[SubmissionLink]:
    """Client-supplied link ids, scoped to the tenant - a foreign or unknown id fails to
    resolve (same ownership-check-by-scoped-lookup as SubmissionService._resolve_list_definition_tenant)."""
    unique_ids = list(dict.fromkeys(public_ids))
    if not unique_ids:
        return []
    links = list(
        db.scalars(
            select(SubmissionLink)
            .where(SubmissionLink.tenant_id == tenant_id, SubmissionLink.public_id.in_(unique_ids))
            .order_by(SubmissionLink.id)
        )
    )
    if len(links) != len(unique_ids):
        raise ValueError("Link nicht gefunden")
    return links


def preferred_link(assignment: SubmissionAssignment) -> SubmissionLink | None:
    """The link used where a single URL is needed (e.g. the todo reference link): the default
    link if the Abgabe is attached to it, otherwise the oldest attached link."""
    links = list(assignment.links)
    return next((link for link in links if link.is_default), links[0] if links else None)


class SubmissionLinkService:
    def _read(self, db: Session, link: SubmissionLink, *, base_url: str, assignment_count: int) -> SubmissionLinkRead:
        return SubmissionLinkRead(
            id=link.public_id,
            name=link.name,
            is_default=link.is_default,
            token=link.token,
            url=link_url(base_url, link),
            assignment_count=assignment_count,
            created_at=link.created_at,
        )

    def _assignment_count(self, db: Session, link_id: int) -> int:
        return db.scalar(
            select(func.count()).select_from(submission_assignment_link_table).where(submission_assignment_link_table.c.link_id == link_id)
        ) or 0

    def list_links(self, db: Session, *, tenant_id: int) -> list[SubmissionLinkRead]:
        links = list(db.scalars(select(SubmissionLink).where(SubmissionLink.tenant_id == tenant_id).order_by(SubmissionLink.id)))
        counts = dict(
            db.execute(
                select(submission_assignment_link_table.c.link_id, func.count())
                .where(submission_assignment_link_table.c.link_id.in_([link.id for link in links]))
                .group_by(submission_assignment_link_table.c.link_id)
            ).all()
        ) if links else {}
        base_url = abgabebox_base_url(db, tenant_id)
        return [self._read(db, link, base_url=base_url, assignment_count=counts.get(link.id, 0)) for link in links]

    def get_link(self, db: Session, link_public_id: uuid.UUID, *, tenant_id: int) -> SubmissionLink | None:
        return public_id_service.get_by_public_id(db, SubmissionLink, link_public_id, tenant_id=tenant_id)

    def read(self, db: Session, link: SubmissionLink) -> SubmissionLinkRead:
        return self._read(
            db,
            link,
            base_url=abgabebox_base_url(db, link.tenant_id),
            assignment_count=self._assignment_count(db, link.id),
        )

    def _ensure_name_free(self, db: Session, *, tenant_id: int, name: str, except_id: int | None = None) -> None:
        statement = select(SubmissionLink.id).where(
            SubmissionLink.tenant_id == tenant_id, func.lower(SubmissionLink.name) == name.lower()
        )
        if except_id is not None:
            statement = statement.where(SubmissionLink.id != except_id)
        if db.scalar(statement) is not None:
            raise ValueError("Ein Link mit diesem Namen existiert bereits")

    def _clear_default(self, db: Session, tenant_id: int) -> None:
        db.execute(
            update(SubmissionLink)
            .where(SubmissionLink.tenant_id == tenant_id, SubmissionLink.is_default.is_(True))
            .values(is_default=False)
        )

    def create_link(self, db: Session, payload: SubmissionLinkCreate, *, tenant_id: int) -> SubmissionLinkRead:
        self._ensure_name_free(db, tenant_id=tenant_id, name=payload.name)
        if payload.is_default:
            self._clear_default(db, tenant_id)
        link = SubmissionLink(tenant_id=tenant_id, name=payload.name, token=generate_token(), is_default=payload.is_default)
        db.add(link)
        db.commit()
        db.refresh(link)
        return self.read(db, link)

    def update_link(self, db: Session, link: SubmissionLink, payload: SubmissionLinkUpdate) -> SubmissionLinkRead:
        if payload.name is not None and payload.name != link.name:
            self._ensure_name_free(db, tenant_id=link.tenant_id, name=payload.name, except_id=link.id)
            link.name = payload.name
        if payload.is_default is not None and payload.is_default != link.is_default:
            if payload.is_default:
                self._clear_default(db, link.tenant_id)
                db.flush()
            link.is_default = payload.is_default
        db.add(link)
        db.commit()
        db.refresh(link)
        return self.read(db, link)

    def regenerate_token(self, db: Session, link: SubmissionLink) -> SubmissionLinkRead:
        """Invalidates the old URL immediately - for when a link leaked or was shared too widely."""
        link.token = generate_token()
        db.add(link)
        db.commit()
        db.refresh(link)
        return self.read(db, link)

    def delete_link(self, db: Session, link: SubmissionLink) -> None:
        # submission_assignment_link rows go with it (ON DELETE CASCADE).
        db.execute(delete(SubmissionLink).where(SubmissionLink.id == link.id))
        db.commit()
        db.expire_all()

    def assignments_for_link(self, db: Session, link: SubmissionLink) -> list[SubmissionAssignment]:
        return list(
            db.scalars(
                select(SubmissionAssignment)
                .join(submission_assignment_link_table, submission_assignment_link_table.c.assignment_id == SubmissionAssignment.id)
                .where(submission_assignment_link_table.c.link_id == link.id)
            )
        )
