"""Template Library: Dokumentvorlagen, Revisionen, Veröffentlichung, Zuweisungen, Komponenten.

Lebenszyklus einer Vorlage:

- Jede Vorlage hat höchstens einen **Entwurf** (``draft``). Der Designer speichert ihn per
  Autosave; ``lock_version`` erkennt parallele Bearbeitung (optimistische Sperre, HTTP 409).
- **Veröffentlichen** prüft die Vorlage (compiler.validate_template), macht den Entwurf zur
  gültigen Revision (``published``) und die vorherige zur abgelösten (``superseded``).
  Veröffentlichte und abgelöste Revisionen sind unveränderlich (zusätzlich per DB-Trigger).
- **Systemvorlagen** (tenant_id NULL) kommen aus system_templates.py und sind für Mandanten
  nur lesbar; anpassen heisst duplizieren (``origin=copy``).
- **Zuweisung** (document_template_assignment): Standardvorlage je Dokumenttyp, optional je
  Protokollvorlage, optional mit eigenem Brand-Profil.

Priorität beim Export (``resolve_template``): explizit gewählt > Zuweisung der
Protokollvorlage > Mandanten-Standard des Dokumenttyps > Plattform-Standard (Systemvorlage) >
erste veröffentlichte Systemvorlage des Typs.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import false, func, or_, select, update
from sqlalchemy.orm import Session

from app.documents import brand_service
from app.documents.compiler import Diagnostic, has_errors, validate_template
from app.documents.doc_types import DOCUMENT_TYPES, get_type
from app.documents.hashing import json_hash
from app.documents.layout import LAYOUT_SCHEMA_VERSION, Node, TemplateContent, all_node_lists, content_json, iter_nodes, parse_content
from app.documents.locking import lock_row
from app.models import (
    DocumentBrand,
    DocumentBrandRevision,
    DocumentComponent,
    DocumentExport,
    DocumentTemplate,
    DocumentTemplateAssignment,
    DocumentTemplateRevision,
    Template,
)

_NODE_ADAPTER = TypeAdapter(Node)


class TemplateConflictError(Exception):
    """Der Entwurf wurde inzwischen geändert (optimistische Sperre)."""

    def __init__(self, current_lock_version: int) -> None:
        super().__init__("conflict")
        self.current_lock_version = current_lock_version


class TemplateStateError(ValueError):
    """Kuratierter Zustandsfehler (Text-Schlüssel aus documentPdf ``apiError.*``)."""


class TemplatePublishError(ValueError):
    def __init__(self, diagnostics: list[Diagnostic]) -> None:
        super().__init__("apiError.templateInvalid")
        self.diagnostics = diagnostics


# ── Lesen ────────────────────────────────────────────────────────────────────


def visible_filter(tenant_id: int):
    """Vorlagen, die ein Mandant sieht: eigene und Systemvorlagen."""
    return or_(DocumentTemplate.tenant_id == tenant_id, DocumentTemplate.tenant_id.is_(None))


def list_templates(
    db: Session,
    tenant_id: int,
    *,
    document_type: str | None = None,
    include_archived: bool = False,
    origin: str | None = None,
) -> list[DocumentTemplate]:
    statement = select(DocumentTemplate).where(visible_filter(tenant_id))
    if document_type:
        statement = statement.where(DocumentTemplate.document_type == document_type)
    if not include_archived:
        statement = statement.where(DocumentTemplate.status == "active")
    if origin:
        statement = statement.where(DocumentTemplate.origin == origin)
    return list(db.scalars(statement.order_by(DocumentTemplate.document_type, DocumentTemplate.tenant_id.is_(None), DocumentTemplate.sort_index, DocumentTemplate.name)))


def get_template(db: Session, tenant_id: int | None, public_id: uuid.UUID) -> DocumentTemplate | None:
    """Vorlage des Mandanten oder Systemvorlage; ``tenant_id=None`` = nur Systemvorlagen."""
    statement = select(DocumentTemplate).where(DocumentTemplate.public_id == public_id)
    statement = statement.where(DocumentTemplate.tenant_id.is_(None) if tenant_id is None else visible_filter(tenant_id))
    return db.scalar(statement)


def is_editable_by_tenant(template: DocumentTemplate, tenant_id: int) -> bool:
    return template.tenant_id == tenant_id


def get_revision(db: Session, template: DocumentTemplate, public_id: uuid.UUID) -> DocumentTemplateRevision | None:
    return db.scalar(select(DocumentTemplateRevision).where(DocumentTemplateRevision.template_id == template.id, DocumentTemplateRevision.public_id == public_id))


def draft_revision(db: Session, template: DocumentTemplate, *, refresh: bool = False) -> DocumentTemplateRevision | None:
    query = select(DocumentTemplateRevision).where(DocumentTemplateRevision.template_id == template.id, DocumentTemplateRevision.status == "draft")
    if refresh:
        # Nach lock_row: aktuellen Stand statt des Objekts aus der Identity Map lesen
        query = query.execution_options(populate_existing=True)
    return db.scalar(query)


def published_revision(db: Session, template: DocumentTemplate) -> DocumentTemplateRevision | None:
    return db.get(DocumentTemplateRevision, template.published_revision_id) if template.published_revision_id else None


def list_revisions(db: Session, template: DocumentTemplate, limit: int = 100) -> list[DocumentTemplateRevision]:
    return list(
        db.scalars(
            select(DocumentTemplateRevision).where(DocumentTemplateRevision.template_id == template.id).order_by(DocumentTemplateRevision.revision_no.desc()).limit(limit)
        )
    )


def revision_content(revision: DocumentTemplateRevision) -> TemplateContent:
    return parse_content(revision.content_json)


def working_revision(db: Session, template: DocumentTemplate) -> DocumentTemplateRevision | None:
    """Entwurf, sonst die veröffentlichte Revision (Ausgangspunkt im Designer)."""
    return draft_revision(db, template) or published_revision(db, template)


# ── Schreiben ────────────────────────────────────────────────────────────────


def _next_revision_no(db: Session, template: DocumentTemplate) -> int:
    return (db.scalar(select(func.max(DocumentTemplateRevision.revision_no)).where(DocumentTemplateRevision.template_id == template.id)) or 0) + 1


def _new_revision(
    db: Session,
    template: DocumentTemplate,
    content: TemplateContent,
    *,
    status: str,
    user_id: int | None,
    brand_mode: str = "follow",
    note: str | None = None,
) -> DocumentTemplateRevision:
    data = content_json(content)
    revision = DocumentTemplateRevision(
        template_id=template.id,
        revision_no=_next_revision_no(db, template),
        status=status,
        schema_version=LAYOUT_SCHEMA_VERSION,
        content_json=data,
        content_hash=json_hash(data),
        brand_mode=brand_mode,
        note=note,
        created_by=user_id,
        updated_by=user_id,
    )
    db.add(revision)
    db.flush()
    return revision


def _check_brand(db: Session, tenant_id: int, brand_id: uuid.UUID | None) -> int | None:
    if brand_id is None:
        return None
    brand = brand_service.get_brand(db, tenant_id, brand_id)
    if brand is None:
        raise TemplateStateError("apiError.notFound")
    return brand.id


def create_template(
    db: Session,
    tenant_id: int,
    *,
    name: str,
    document_type: str,
    content: TemplateContent | None = None,
    description: str | None = None,
    category: str | None = None,
    brand_id: uuid.UUID | None = None,
    user_id: int | None = None,
    origin: Literal["tenant", "copy"] = "tenant",
    source: DocumentTemplate | None = None,
    source_revision: DocumentTemplateRevision | None = None,
) -> tuple[DocumentTemplate, DocumentTemplateRevision]:
    doc_type = get_type(document_type)
    template = DocumentTemplate(
        tenant_id=tenant_id,
        origin=origin,
        source_template_id=source.id if source is not None else None,
        source_revision_id=source_revision.id if source_revision is not None else None,
        name=name.strip()[:160] or document_type,
        description=(description or "").strip()[:600] or None,
        document_type=document_type,
        variant=source.variant if source is not None else None,
        category=category or doc_type.category,
        brand_id=_check_brand(db, tenant_id, brand_id),
        status="active",
        created_by=user_id,
        updated_by=user_id,
    )
    db.add(template)
    db.flush()
    revision = _new_revision(db, template, content or TemplateContent(), status="draft", user_id=user_id)
    return template, revision


def duplicate_template(db: Session, tenant_id: int, source: DocumentTemplate, *, name: str, user_id: int | None) -> tuple[DocumentTemplate, DocumentTemplateRevision]:
    """Kopie als neue Mandantenvorlage. Von einer Systemvorlage entsteht eine «angepasste
    Kopie» (Herkunft bleibt sichtbar), Basis ist die veröffentlichte Revision; bei eigenen
    Vorlagen der aktuelle Arbeitsstand."""
    base = published_revision(db, source) if source.tenant_id is None else working_revision(db, source)
    if base is None:
        raise TemplateStateError("apiError.templateNotPublished")
    content = revision_content(base)
    return create_template(
        db,
        tenant_id,
        name=name,
        document_type=source.document_type,
        content=content,
        description=source.description if source.tenant_id is not None else None,
        category=source.category,
        brand_id=None,
        user_id=user_id,
        origin="copy" if source.tenant_id is None else "tenant",
        source=source,
        source_revision=base,
    )


def update_template_meta(
    db: Session,
    template: DocumentTemplate,
    *,
    name: str | None = None,
    description: str | None = None,
    brand_id: uuid.UUID | None | Literal["unset"] = "unset",
    category: str | None = None,
    user_id: int | None = None,
) -> DocumentTemplate:
    if name is not None and name.strip():
        template.name = name.strip()[:160]
    if description is not None:
        template.description = description.strip()[:600] or None
    if brand_id != "unset":
        template.brand_id = _check_brand(db, template.tenant_id, brand_id) if template.tenant_id is not None else None
    if category is not None and category.strip():
        template.category = category.strip()[:60]
    template.updated_by = user_id
    db.flush()
    return template


def save_draft(
    db: Session,
    template: DocumentTemplate,
    content: TemplateContent,
    *,
    expected_lock_version: int | None,
    user_id: int | None,
    brand_mode: str | None = None,
    note: str | None = None,
) -> DocumentTemplateRevision:
    """Autosave: Entwurf anlegen oder ersetzen. Ohne vorhandenen Entwurf entsteht einer aus dem
    gesendeten Inhalt (``expected_lock_version`` wird dann ignoriert)."""
    lock_row(db, template)
    draft = draft_revision(db, template, refresh=True)
    data = content_json(content)
    if draft is None:
        published = published_revision(db, template)
        return _new_revision(
            db,
            template,
            content,
            status="draft",
            user_id=user_id,
            brand_mode=brand_mode or (published.brand_mode if published is not None else "follow"),
            note=note,
        )
    if expected_lock_version is not None and expected_lock_version != draft.lock_version:
        raise TemplateConflictError(draft.lock_version)
    draft.content_json = data
    draft.content_hash = json_hash(data)
    draft.schema_version = LAYOUT_SCHEMA_VERSION
    if brand_mode is not None:
        draft.brand_mode = brand_mode
    if note is not None:
        draft.note = note.strip()[:300] or None
    draft.lock_version += 1
    draft.updated_by = user_id
    draft.updated_at = datetime.now(UTC)
    template.updated_by = user_id
    template.updated_at = datetime.now(UTC)
    db.flush()
    return draft


def discard_draft(db: Session, template: DocumentTemplate) -> None:
    lock_row(db, template)
    draft = draft_revision(db, template, refresh=True)
    if draft is None:
        return
    if template.published_revision_id is None:
        raise TemplateStateError("apiError.lastRevision")
    db.delete(draft)
    db.flush()


def _brand_for_pin(db: Session, template: DocumentTemplate, tenant_id: int) -> DocumentBrandRevision | None:
    brand = db.get(DocumentBrand, template.brand_id) if template.brand_id else brand_service.default_brand(db, tenant_id)
    return brand_service.current_revision(db, brand) if brand is not None else None


def publish(db: Session, template: DocumentTemplate, *, user_id: int | None, note: str | None = None, tenant_id: int | None = None) -> DocumentTemplateRevision:
    lock_row(db, template)
    draft = draft_revision(db, template, refresh=True)
    if draft is None:
        raise TemplateStateError("apiError.noDraft")
    content = revision_content(draft)
    diagnostics = validate_template(db, template.tenant_id, content, document_type=template.document_type)
    if has_errors(diagnostics):
        raise TemplatePublishError(diagnostics)
    previous = published_revision(db, template)
    if previous is not None:
        previous.status = "superseded"
        db.flush()
    draft.status = "published"
    draft.published_at = datetime.now(UTC)
    draft.published_by = user_id
    if note is not None:
        draft.note = note.strip()[:300] or None
    if draft.brand_mode == "pinned" and template.tenant_id is not None:
        pinned = _brand_for_pin(db, template, template.tenant_id)
        draft.brand_revision_id = pinned.id if pinned is not None else None
    template.published_revision_id = draft.id
    template.updated_by = user_id
    db.flush()
    return draft


def restore_revision(db: Session, template: DocumentTemplate, revision: DocumentTemplateRevision, *, user_id: int | None) -> DocumentTemplateRevision:
    """Älteren Stand als Entwurf übernehmen (ersetzt einen vorhandenen Entwurf)."""
    content = revision_content(revision)
    lock_row(db, template)
    draft = draft_revision(db, template, refresh=True)
    if draft is not None and draft.id == revision.id:
        return draft
    if draft is not None:
        return save_draft(db, template, content, expected_lock_version=None, user_id=user_id, brand_mode=revision.brand_mode, note=f"restore:{revision.revision_no}")
    return _new_revision(db, template, content, status="draft", user_id=user_id, brand_mode=revision.brand_mode, note=f"restore:{revision.revision_no}")


def set_archived(db: Session, template: DocumentTemplate, archived: bool, *, user_id: int | None) -> DocumentTemplate:
    template.status = "archived" if archived else "active"
    template.updated_by = user_id
    if archived:
        # Archivierte Vorlagen sind nirgends mehr Standard
        for assignment in db.scalars(select(DocumentTemplateAssignment).where(DocumentTemplateAssignment.document_template_id == template.id)):
            if assignment.brand_id is None:
                db.delete(assignment)
            else:
                assignment.document_template_id = None
        if template.tenant_id is None:
            template.is_platform_default = False
    db.flush()
    return template


def delete_template(db: Session, template: DocumentTemplate) -> None:
    """Nur nie exportierte Mandantenvorlagen: sonst ginge die Herkunft historischer PDFs
    verloren - dafür gibt es «Archivieren»."""
    if template.tenant_id is None:
        raise TemplateStateError("apiError.systemTemplate")
    exported = db.scalar(select(func.count(DocumentExport.id)).where(DocumentExport.template_id == template.id))
    if exported:
        raise TemplateStateError("apiError.templateInUse")
    # Zuweisungen mit eigenem Brand-Profil behalten das Profil (wie beim Archivieren); sonst
    # entfernte der FK (ON DELETE CASCADE) die ganze Zuweisung samt Brand
    for assignment in db.scalars(select(DocumentTemplateAssignment).where(DocumentTemplateAssignment.document_template_id == template.id)):
        if assignment.brand_id is None:
            db.delete(assignment)
        else:
            assignment.document_template_id = None
    template.published_revision_id = None
    db.flush()
    db.delete(template)
    db.flush()


# ── Vergleich ────────────────────────────────────────────────────────────────


def _node_index(content: TemplateContent) -> dict[str, tuple[str, Any, str | None]]:
    index: dict[str, tuple[str, Any, str | None]] = {}
    for area, nodes in all_node_lists(content):

        def walk(items: list[Any], parent: str | None) -> None:
            for node in items:
                index[node.id] = (area, node, parent)
                children = getattr(node, "children", None)
                if children:
                    walk(children, node.id)

        walk(nodes, None)
    return index


def compare_revisions(old: TemplateContent, new: TemplateContent) -> dict[str, Any]:
    """Strukturvergleich zweier Revisionen: hinzugefügte, entfernte, geänderte und verschobene
    Knoten sowie geänderte Seiten-/Dokumenteinstellungen."""
    old_index, new_index = _node_index(old), _node_index(new)

    def own(node: Any) -> dict[str, Any]:
        return node.model_dump(mode="json", exclude={"children"})

    changes: list[dict[str, Any]] = []
    for node_id, (area, node, parent) in new_index.items():
        if node_id not in old_index:
            changes.append({"change": "added", "node_id": node_id, "type": node.type, "name": node.name, "area": area})
            continue
        old_area, old_node, old_parent = old_index[node_id]
        old_own, new_own = own(old_node), own(node)
        if old_own != new_own:
            fields = sorted(key for key in set(old_own) | set(new_own) if old_own.get(key) != new_own.get(key))
            changes.append({"change": "modified", "node_id": node_id, "type": node.type, "name": node.name, "area": area, "fields": fields})
        if old_parent != parent or old_area != area:
            changes.append({"change": "moved", "node_id": node_id, "type": node.type, "name": node.name, "area": area})
    for node_id, (area, node, _parent) in old_index.items():
        if node_id not in new_index:
            changes.append({"change": "removed", "node_id": node_id, "type": node.type, "name": node.name, "area": area})
    settings = [
        key
        for key in ("page", "settings", "title_page")
        if getattr(old, key).model_dump(mode="json", exclude={"children"}) != getattr(new, key).model_dump(mode="json", exclude={"children"})
    ]
    masters_changed = [master.id for master in new.masters if (old.master(master.id) is None or old.master(master.id).model_dump(mode="json", exclude={"header", "footer", "background"}) != master.model_dump(mode="json", exclude={"header", "footer", "background"}))]
    return {"nodes": changes, "settings": settings, "masters": masters_changed}


# ── Zuweisungen und Auflösung ────────────────────────────────────────────────


def list_assignments(db: Session, tenant_id: int) -> list[DocumentTemplateAssignment]:
    return list(db.scalars(select(DocumentTemplateAssignment).where(DocumentTemplateAssignment.tenant_id == tenant_id).order_by(DocumentTemplateAssignment.document_type, DocumentTemplateAssignment.protocol_template_id.is_not(None))))


def set_assignment(
    db: Session,
    tenant_id: int,
    *,
    document_type: str,
    template: DocumentTemplate | None,
    brand: DocumentBrand | None,
    protocol_template: Template | None = None,
    user_id: int | None = None,
) -> DocumentTemplateAssignment | None:
    """Standard setzen oder (ohne Vorlage und Brand) entfernen."""
    doc_type = get_type(document_type)
    if template is not None:
        if template.document_type != document_type:
            raise TemplateStateError("apiError.templateTypeMismatch")
        if template.status != "active" or template.published_revision_id is None:
            raise TemplateStateError("apiError.templateNotPublished")
        if template.tenant_id not in (None, tenant_id):
            raise TemplateStateError("apiError.notFound")
    if brand is not None and (brand.tenant_id != tenant_id or brand.archived_at is not None):
        raise TemplateStateError("apiError.notFound")
    if protocol_template is not None:
        if protocol_template.tenant_id != tenant_id:
            raise TemplateStateError("apiError.notFound")
        if not doc_type.needs_protocol:
            raise TemplateStateError("apiError.assignmentScope")
    statement = select(DocumentTemplateAssignment).where(
        DocumentTemplateAssignment.tenant_id == tenant_id,
        DocumentTemplateAssignment.document_type == document_type,
        DocumentTemplateAssignment.protocol_template_id == protocol_template.id if protocol_template is not None else DocumentTemplateAssignment.protocol_template_id.is_(None),
    )
    assignment = db.scalar(statement)
    if template is None and brand is None:
        if assignment is not None:
            db.delete(assignment)
            db.flush()
        return None
    if assignment is None:
        assignment = DocumentTemplateAssignment(tenant_id=tenant_id, document_type=document_type, protocol_template_id=protocol_template.id if protocol_template is not None else None, created_by=user_id)
        db.add(assignment)
    assignment.document_template_id = template.id if template is not None else None
    assignment.brand_id = brand.id if brand is not None else None
    db.flush()
    return assignment


@dataclass
class ResolvedTemplate:
    template: DocumentTemplate
    revision: DocumentTemplateRevision
    source: str
    brand_id: int | None  # Brand aus der Zuweisung (Protokollvorlage oder Mandant)


def _usable(template: DocumentTemplate | None, tenant_id: int, document_type: str) -> bool:
    return (
        template is not None
        and template.status == "active"
        and template.published_revision_id is not None
        and template.document_type == document_type
        and template.tenant_id in (None, tenant_id)
    )


def resolve_template(
    db: Session,
    tenant_id: int,
    document_type: str,
    *,
    explicit: DocumentTemplate | None = None,
    protocol_template_id: int | None = None,
    use_draft: bool = False,
) -> ResolvedTemplate:
    get_type(document_type)
    assignments = {
        (row.protocol_template_id is not None): row
        for row in db.scalars(
            select(DocumentTemplateAssignment).where(
                DocumentTemplateAssignment.tenant_id == tenant_id,
                DocumentTemplateAssignment.document_type == document_type,
                or_(
                    DocumentTemplateAssignment.protocol_template_id.is_(None),
                    DocumentTemplateAssignment.protocol_template_id == protocol_template_id if protocol_template_id is not None else false(),
                ),
            )
        )
    }
    scoped, tenant_default = assignments.get(True), assignments.get(False)
    brand_id = (scoped.brand_id if scoped is not None and scoped.brand_id else None) or (tenant_default.brand_id if tenant_default is not None else None)

    def done(template: DocumentTemplate, source: str) -> ResolvedTemplate:
        revision = (draft_revision(db, template) if use_draft else None) or published_revision(db, template)
        if revision is None:
            raise TemplateStateError("apiError.templateNotPublished")
        return ResolvedTemplate(template=template, revision=revision, source=source, brand_id=brand_id)

    if explicit is not None:
        if explicit.tenant_id not in (None, tenant_id) or explicit.document_type != document_type:
            raise TemplateStateError("apiError.templateTypeMismatch")
        if use_draft and draft_revision(db, explicit) is not None:
            return done(explicit, "explicit")
        if not _usable(explicit, tenant_id, document_type):
            raise TemplateStateError("apiError.templateNotPublished")
        return done(explicit, "explicit")
    for assignment, source in ((scoped, "protocol_template"), (tenant_default, "tenant_default")):
        if assignment is not None and assignment.document_template_id:
            template = db.get(DocumentTemplate, assignment.document_template_id)
            if _usable(template, tenant_id, document_type):
                return done(template, source)
    platform = db.scalar(
        select(DocumentTemplate).where(
            DocumentTemplate.tenant_id.is_(None),
            DocumentTemplate.document_type == document_type,
            DocumentTemplate.is_platform_default.is_(True),
            DocumentTemplate.status == "active",
            DocumentTemplate.published_revision_id.is_not(None),
        )
    )
    if platform is not None:
        return done(platform, "platform_default")
    fallback = db.scalar(
        select(DocumentTemplate)
        .where(
            DocumentTemplate.tenant_id.is_(None),
            DocumentTemplate.document_type == document_type,
            DocumentTemplate.status == "active",
            DocumentTemplate.published_revision_id.is_not(None),
        )
        .order_by(DocumentTemplate.sort_index, DocumentTemplate.id)
    )
    if fallback is None:
        raise TemplateStateError("apiError.noTemplate")
    return done(fallback, "fallback")


def default_template_ids(db: Session, tenant_id: int) -> dict[str, int]:
    """Dokumenttyp → ID der aktuell geltenden Standardvorlage (für die Bibliothek)."""
    result: dict[str, int] = {}
    for document_type in DOCUMENT_TYPES:
        try:
            result[document_type] = resolve_template(db, tenant_id, document_type).template.id
        except TemplateStateError:
            continue
    return result


def resolve_brand_revision(
    db: Session,
    tenant_id: int,
    resolved: ResolvedTemplate | None,
    *,
    explicit_brand: DocumentBrand | None = None,
) -> DocumentBrandRevision | None:
    """Brand-Revision eines Exports. Priorität: explizit > Zuweisung > Brand der Vorlage >
    Standard-Brand des Mandanten. Eine veröffentlichte Revision mit ``brand_mode=pinned``
    verwendet die beim Veröffentlichen festgehaltene Revision (sofern noch vorhanden)."""
    if explicit_brand is not None:
        return brand_service.current_revision(db, explicit_brand)
    if resolved is not None:
        revision = resolved.revision
        if revision.status != "draft" and revision.brand_mode == "pinned" and revision.brand_revision_id:
            pinned = brand_service.get_revision(db, tenant_id, revision.brand_revision_id)
            if pinned is not None:
                return pinned
        for brand_id in (resolved.brand_id, resolved.template.brand_id):
            if brand_id:
                brand = db.get(DocumentBrand, brand_id)
                if brand is not None and brand.tenant_id == tenant_id:
                    return brand_service.current_revision(db, brand)
    brand = brand_service.ensure_default_brand(db, tenant_id)
    return brand_service.current_revision(db, brand)


# ── Wiederverwendbare Komponenten ────────────────────────────────────────────


def list_components(db: Session, tenant_id: int) -> list[DocumentComponent]:
    return list(db.scalars(select(DocumentComponent).where(DocumentComponent.tenant_id == tenant_id).order_by(DocumentComponent.category, DocumentComponent.name)))


def get_component(db: Session, tenant_id: int, public_id: uuid.UUID) -> DocumentComponent | None:
    return db.scalar(select(DocumentComponent).where(DocumentComponent.tenant_id == tenant_id, DocumentComponent.public_id == public_id))


def parse_component_node(raw: dict[str, Any]) -> Any:
    node = _NODE_ADAPTER.validate_python(raw)
    if node.type in ("component_ref",):
        raise ValueError("Komponente darf kein Verweis sein")
    for child, _depth in iter_nodes([node]):
        if child.type == "component_ref":
            raise ValueError("Komponenten dürfen keine Komponentenverweise enthalten")
    return node


def save_component(
    db: Session,
    tenant_id: int,
    *,
    component: DocumentComponent | None,
    name: str | None,
    node: dict[str, Any] | None,
    description: str | None = None,
    category: str | None = None,
    expected_lock_version: int | None = None,
    user_id: int | None = None,
) -> DocumentComponent:
    if component is None:
        if node is None:
            raise TemplateStateError("apiError.invalidBlock")
        component = DocumentComponent(tenant_id=tenant_id, name=(name or "").strip()[:120] or "Komponente", schema_version=LAYOUT_SCHEMA_VERSION, node_json={}, created_by=user_id)
        db.add(component)
    else:
        lock_row(db, component)
        if expected_lock_version is not None and expected_lock_version != component.lock_version:
            raise TemplateConflictError(component.lock_version)
        component.lock_version += 1
    if name is not None and name.strip():
        component.name = name.strip()[:120]
    if description is not None:
        component.description = description.strip()[:600] or None
    if category is not None and category.strip():
        component.category = category.strip()[:60]
    if node is not None:
        try:
            parsed = parse_component_node(node)
        except ValidationError as exc:
            raise TemplateStateError("apiError.invalidBlock") from exc
        component.node_json = parsed.model_dump(mode="json")
        component.schema_version = LAYOUT_SCHEMA_VERSION
    component.updated_by = user_id
    db.flush()
    return component


def delete_component(db: Session, component: DocumentComponent) -> None:
    """Nur unbenutzte Komponenten (kein Verweis in Entwürfen oder veröffentlichten Revisionen)."""
    from sqlalchemy import Text

    needle = str(component.public_id)
    used = db.scalar(
        select(func.count(DocumentTemplateRevision.id))
        .join(DocumentTemplate, DocumentTemplate.id == DocumentTemplateRevision.template_id)
        .where(DocumentTemplate.tenant_id == component.tenant_id, DocumentTemplateRevision.content_json.cast(Text()).contains(needle))
    )
    if used:
        raise TemplateStateError("apiError.componentInUse")
    db.delete(component)
    db.flush()


def clear_platform_default(db: Session, document_type: str) -> None:
    db.execute(update(DocumentTemplate).where(DocumentTemplate.tenant_id.is_(None), DocumentTemplate.document_type == document_type).values(is_platform_default=False))
