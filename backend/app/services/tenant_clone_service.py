from __future__ import annotations

import copy
import shutil
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import inspect as sa_inspect, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import (
    AttendanceFine,
    CycleConfig,
    DocumentTemplate,
    DocumentTemplatePart,
    ElementDefinition,
    Event,
    EventCycle,
    FinanceAccount,
    FinanceTransaction,
    GroupEntity,
    Leader,
    ListDefinition,
    ListEntry,
    Participant,
    Protocol,
    ProtocolDisplaySnapshot,
    ProtocolElement,
    ProtocolElementBlock,
    ProtocolImage,
    ProtocolText,
    ProtocolTodo,
    StoredFile,
    SubmissionAssignment,
    SubmissionUpload,
    SubmissionUploadFile,
    SubmissionUploadLog,
    Template,
    TemplateElement,
    TemplateElementBlock,
    TemplateParticipant,
    Tenant,
    TenantOidcConfig,
    UserProtocolAccess,
    UserTemplateAccess,
    UserTenantRole,
)
from app.services.document_template_service import DocumentTemplateService
from app.services.file_service import _safe_storage_path

_ALWAYS_EXCLUDE = {"id", "created_at", "updated_at"}


def _copy_row(source: Any, overrides: dict[str, Any] | None = None) -> Any:
    """Builds a new, unattached ORM instance with the same column values as `source`.

    `id`/`created_at`/`updated_at` are always dropped so the DB assigns fresh ones. JSONB/other
    mutable values are deep-copied so the new row never shares object identity with `source`.
    """
    model = type(source)
    mapper = sa_inspect(model)
    values = {
        column.key: copy.deepcopy(getattr(source, column.key))
        for column in mapper.columns
        if column.key not in _ALWAYS_EXCLUDE
    }
    if overrides:
        values.update(overrides)
    return model(**values)


class TenantCloneService:
    """Clones a tenant either as an empty structure/config copy or as a full data backup.

    Known, deliberate limitations (disclosed rather than silently handled):
    - `ProtocolExportCache` (cached PDF/LaTeX exports) is never cloned — it is regeneratable.
    - `UserProtocolScroll` (per-user scroll position) is never cloned — ephemeral UI state.
    - Cloned protocols keep pointing at the ORIGINAL tenant's `document_template_path_snapshot`
      directory (an immutable historical export artifact), it is not physically duplicated.
    - Only participant-ID references we know the shape of are remapped: `Event.*_ids`,
      `ListEntry` values, and `attendance_entries[].participant_id` inside protocol block
      snapshots. Any other participant/event IDs embedded in free-form block configuration_json
      (e.g. matrix-element cell data) are left untouched.
    """

    def __init__(self) -> None:
        self.document_template_service = DocumentTemplateService()

    # ── public entry points ──────────────────────────────────────────────

    def clone_structure(self, db: Session, source_tenant_id: int, new_name: str) -> Tenant:
        source = db.get(Tenant, source_tenant_id)
        if source is None:
            raise ValueError("Source tenant not found")

        new_tenant = self._clone_tenant_base(db, source, new_name)
        self._clone_oidc_config(db, source.id, new_tenant.id)
        cycle_config_map = self._clone_cycle_configs(db, source.id, new_tenant.id)
        element_definition_map = self._clone_element_definitions(db, source.id, new_tenant.id)
        part_map = self._clone_document_template_parts(db, source.id, new_tenant.id)
        document_template_map = self._clone_document_templates(db, source.id, new_tenant.id, part_map)
        self._clone_templates(
            db, source.id, new_tenant.id,
            document_template_map=document_template_map,
            cycle_config_map=cycle_config_map,
            element_definition_map=element_definition_map,
            event_map={},
            participant_map={},
            list_definition_map={},
            list_entry_map={},
        )
        self._clone_list_definitions(db, source.id, new_tenant.id)
        self._clone_finance_accounts(db, source.id, new_tenant.id)
        return new_tenant

    def clone_full(self, db: Session, source_tenant_id: int, new_name: str) -> Tenant:
        source = db.get(Tenant, source_tenant_id)
        if source is None:
            raise ValueError("Source tenant not found")

        new_tenant = self._clone_tenant_base(db, source, new_name)
        self._clone_oidc_config(db, source.id, new_tenant.id)
        group_map = self._clone_group_entities(db, source.id, new_tenant.id)
        self._clone_leaders(db, source.id, new_tenant.id)
        participant_map = self._clone_participants(db, source.id, new_tenant.id)
        cycle_config_map = self._clone_cycle_configs(db, source.id, new_tenant.id)
        element_definition_map = self._clone_element_definitions(db, source.id, new_tenant.id)
        part_map = self._clone_document_template_parts(db, source.id, new_tenant.id)
        document_template_map = self._clone_document_templates(db, source.id, new_tenant.id, part_map)
        event_map = self._clone_events(db, source.id, new_tenant.id, group_map=group_map, participant_map=participant_map)
        self._clone_event_cycles(db, event_map=event_map, cycle_config_map=cycle_config_map)
        list_definition_map = self._clone_list_definitions(db, source.id, new_tenant.id)
        list_entry_map = self._clone_list_entries(
            db, list_definition_map=list_definition_map, participant_map=participant_map, event_map=event_map
        )
        template_map, template_element_map, template_element_block_map = self._clone_templates(
            db, source.id, new_tenant.id,
            document_template_map=document_template_map,
            cycle_config_map=cycle_config_map,
            element_definition_map=element_definition_map,
            event_map=event_map,
            participant_map=participant_map,
            list_definition_map=list_definition_map,
            list_entry_map=list_entry_map,
        )
        self._clone_template_participants(db, template_map=template_map, participant_map=participant_map)
        submission_assignment_map = self._clone_submission_assignments(
            db, source.id, new_tenant.id, list_definition_map=list_definition_map
        )
        submission_upload_map = self._clone_submission_uploads(
            db, submission_assignment_map=submission_assignment_map, event_map=event_map, list_entry_map=list_entry_map
        )
        self._clone_submission_upload_logs(db, submission_assignment_map=submission_assignment_map)
        finance_account_map = self._clone_finance_accounts(db, source.id, new_tenant.id)
        stored_file_map = self._clone_stored_files(db, source.id, new_tenant.id)
        self._clone_submission_upload_files(db, submission_upload_map=submission_upload_map, stored_file_map=stored_file_map)
        protocol_map = self._clone_protocols(
            db, source.id, new_tenant.id, template_map=template_map, document_template_map=document_template_map, event_map=event_map
        )
        protocol_element_map = self._clone_protocol_elements(db, protocol_map=protocol_map, template_element_map=template_element_map)
        protocol_element_block_map = self._clone_protocol_element_blocks(
            db,
            protocol_element_map=protocol_element_map,
            template_element_block_map=template_element_block_map,
            element_definition_map=element_definition_map,
            participant_map=participant_map,
        )
        self._clone_protocol_texts(db, protocol_element_block_map=protocol_element_block_map)
        self._clone_protocol_display_snapshots(db, protocol_element_block_map=protocol_element_block_map)
        self._clone_protocol_images(db, protocol_element_block_map=protocol_element_block_map, stored_file_map=stored_file_map)
        finance_transaction_map = self._clone_finance_transactions(db, finance_account_map=finance_account_map, protocol_map=protocol_map)
        self._clone_attendance_fines(
            db,
            protocol_map=protocol_map,
            participant_map=participant_map,
            finance_account_map=finance_account_map,
            finance_transaction_map=finance_transaction_map,
        )
        self._clone_protocol_todos(
            db, source.id, new_tenant.id,
            protocol_element_block_map=protocol_element_block_map,
            participant_map=participant_map,
            event_map=event_map,
            protocol_map=protocol_map,
            submission_assignment_map=submission_assignment_map,
        )
        self._clone_user_template_access(db, source.id, new_tenant.id, template_map=template_map)
        self._clone_user_protocol_access(db, source.id, new_tenant.id, protocol_map=protocol_map)
        self._clone_user_tenant_roles(db, source.id, new_tenant.id)
        return new_tenant

    # ── tenant base + physical files ───────────────────────────────────────

    def _clone_tenant_base(self, db: Session, source: Tenant, new_name: str) -> Tenant:
        new_tenant = Tenant(
            name=new_name,
            profile_image_path=None,
            tag_config_json=copy.deepcopy(source.tag_config_json or {}),
            public_slug=None,
        )
        db.add(new_tenant)
        db.commit()
        db.refresh(new_tenant)
        image_path = self._clone_tenant_profile_image(source.profile_image_path, new_tenant_id=new_tenant.id)
        if image_path is not None:
            new_tenant.profile_image_path = image_path
            db.add(new_tenant)
            db.commit()
            db.refresh(new_tenant)
        return new_tenant

    def _clone_tenant_profile_image(self, source_path: str | None, *, new_tenant_id: int) -> str | None:
        if not source_path:
            return None
        source = _safe_storage_path(settings.storage_root, source_path)
        if not source.exists():
            return None
        suffix = Path(source_path).suffix or ".png"
        profile_dir = Path(settings.upload_root) / "tenant-profiles"
        profile_dir.mkdir(parents=True, exist_ok=True)
        target = profile_dir / f"tenant-{new_tenant_id}-{uuid4().hex}{suffix}"
        shutil.copy2(source, target)
        return str(target.relative_to(Path(settings.storage_root).resolve()))

    def _clone_stored_file_content(self, storage_path: str, *, root: str, new_tenant_id: int) -> str:
        root_path = Path(root).resolve()
        source = _safe_storage_path(root, storage_path)
        suffix = Path(storage_path).suffix or ".bin"
        target_dir = root_path / "tenant_clones" / f"tenant-{new_tenant_id}"
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / f"{uuid4().hex}{suffix}"
        if source.exists():
            shutil.copy2(source, target_path)
        return str(target_path.relative_to(root_path))

    def _clone_document_template_part_file(
        self, source_storage_path: str, *, new_tenant_id: int, part_type: str, code: str, version: int
    ) -> str:
        source = _safe_storage_path(settings.storage_root, source_storage_path)
        suffix = Path(source_storage_path).suffix or ".tex"
        target_dir = Path(settings.storage_root) / "document_template_parts" / f"tenant-{new_tenant_id}" / part_type / code
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / f"v{version}{suffix}"
        if source.exists():
            shutil.copy2(source, target_path)
        return str(target_path.relative_to(Path(settings.storage_root).resolve()))

    # ── structure/config tables ─────────────────────────────────────────

    def _clone_oidc_config(self, db: Session, source_tenant_id: int, new_tenant_id: int) -> None:
        source = db.scalar(select(TenantOidcConfig).where(TenantOidcConfig.tenant_id == source_tenant_id))
        if source is None:
            return
        db.add(_copy_row(source, {"tenant_id": new_tenant_id}))
        db.commit()

    def _clone_cycle_configs(self, db: Session, source_tenant_id: int, new_tenant_id: int) -> dict[int, int]:
        rows = db.scalars(select(CycleConfig).where(CycleConfig.tenant_id == source_tenant_id)).all()
        id_map: dict[int, int] = {}
        for row in rows:
            new_row = _copy_row(row, {"tenant_id": new_tenant_id})
            db.add(new_row)
            db.flush()
            id_map[row.id] = new_row.id
        db.commit()
        return id_map

    def _clone_element_definitions(self, db: Session, source_tenant_id: int, new_tenant_id: int) -> dict[int, int]:
        rows = db.scalars(select(ElementDefinition).where(ElementDefinition.tenant_id == source_tenant_id)).all()
        id_map: dict[int, int] = {}
        for row in rows:
            new_row = _copy_row(row, {"tenant_id": new_tenant_id})
            db.add(new_row)
            db.flush()
            id_map[row.id] = new_row.id
        db.commit()
        return id_map

    def _clone_document_template_parts(self, db: Session, source_tenant_id: int, new_tenant_id: int) -> dict[int, int]:
        rows = db.scalars(select(DocumentTemplatePart).where(DocumentTemplatePart.tenant_id == source_tenant_id)).all()
        id_map: dict[int, int] = {}
        for row in rows:
            new_storage_path = self._clone_document_template_part_file(
                row.storage_path, new_tenant_id=new_tenant_id, part_type=row.part_type, code=row.code, version=row.version,
            )
            new_row = _copy_row(row, {"tenant_id": new_tenant_id, "storage_path": new_storage_path})
            db.add(new_row)
            db.flush()
            id_map[row.id] = new_row.id
        db.commit()
        return id_map

    def _remap_document_template_config(self, config: dict | None, part_map: dict[int, int]) -> dict:
        config = copy.deepcopy(config or {})
        slots = config.get("slots")
        if isinstance(slots, dict):
            config["slots"] = {k: part_map.get(v, v) for k, v in slots.items()}
        theme = config.get("theme")
        if isinstance(theme, dict):
            font_parts = theme.get("font_parts")
            if isinstance(font_parts, dict):
                theme["font_parts"] = {k: part_map.get(v, v) for k, v in font_parts.items()}
        title_assets = config.get("title_assets")
        if isinstance(title_assets, dict):
            config["title_assets"] = {k: part_map.get(v, v) for k, v in title_assets.items()}
        return config

    def _clone_document_templates(
        self, db: Session, source_tenant_id: int, new_tenant_id: int, part_map: dict[int, int]
    ) -> dict[int, int]:
        rows = db.scalars(select(DocumentTemplate).where(DocumentTemplate.tenant_id == source_tenant_id)).all()
        id_map: dict[int, int] = {}
        for row in rows:
            new_row = _copy_row(row, {
                "tenant_id": new_tenant_id,
                "filesystem_path": "",
                "configuration_json": self._remap_document_template_config(row.configuration_json, part_map),
            })
            db.add(new_row)
            db.flush()
            id_map[row.id] = new_row.id
        db.commit()
        for new_id in id_map.values():
            template = self.document_template_service.repository.get(db, new_id)
            if template is None:
                continue
            path = self.document_template_service._materialize_template(db, template)
            self.document_template_service.repository.update(db, template, {"filesystem_path": path})
        return id_map

    def _clone_list_definitions(self, db: Session, source_tenant_id: int, new_tenant_id: int) -> dict[int, int]:
        rows = db.scalars(select(ListDefinition).where(ListDefinition.tenant_id == source_tenant_id)).all()
        id_map: dict[int, int] = {}
        for row in rows:
            new_row = _copy_row(row, {"tenant_id": new_tenant_id})
            db.add(new_row)
            db.flush()
            id_map[row.id] = new_row.id
        db.commit()
        return id_map

    def _clone_finance_accounts(self, db: Session, source_tenant_id: int, new_tenant_id: int) -> dict[int, int]:
        rows = db.scalars(select(FinanceAccount).where(FinanceAccount.tenant_id == source_tenant_id)).all()
        id_map: dict[int, int] = {}
        for row in rows:
            new_row = _copy_row(row, {"tenant_id": new_tenant_id})
            db.add(new_row)
            db.flush()
            id_map[row.id] = new_row.id
        db.commit()
        return id_map

    def _remap_template_element_config(
        self,
        config: dict | None,
        *,
        participant_map: dict[int, int],
        list_definition_map: dict[int, int],
        list_entry_map: dict[int, int],
    ) -> dict:
        config = copy.deepcopy(config or {})
        responsibility = config.get("responsibility")
        if not isinstance(responsibility, dict) or not isinstance(responsibility.get("assignments"), list):
            return config
        new_assignments = []
        for assignment in responsibility["assignments"]:
            if not isinstance(assignment, dict):
                continue
            new_participant_id = participant_map.get(assignment.get("participant_id"))
            if new_participant_id is None:
                # The participant this assignment pointed at doesn't exist in the new tenant
                # (e.g. structure-only clone, or the participant wasn't cloned) - drop it rather
                # than keep a dangling reference to an id from the source tenant.
                continue
            new_assignment = {**assignment, "participant_id": new_participant_id}
            list_definition_id = assignment.get("list_definition_id")
            list_entry_id = assignment.get("list_entry_id")
            if list_definition_id and list_entry_id:
                new_list_definition_id = list_definition_map.get(list_definition_id)
                new_list_entry_id = list_entry_map.get(list_entry_id)
                if new_list_definition_id is None or new_list_entry_id is None:
                    new_assignment["list_definition_id"] = None
                    new_assignment["list_entry_id"] = None
                    new_assignment["locked"] = False
                else:
                    new_assignment["list_definition_id"] = new_list_definition_id
                    new_assignment["list_entry_id"] = new_list_entry_id
            new_assignments.append(new_assignment)
        return {**config, "responsibility": {**responsibility, "assignments": new_assignments}}

    def _clone_templates(
        self,
        db: Session,
        source_tenant_id: int,
        new_tenant_id: int,
        *,
        document_template_map: dict[int, int],
        cycle_config_map: dict[int, int],
        element_definition_map: dict[int, int],
        event_map: dict[int, int],
        participant_map: dict[int, int],
        list_definition_map: dict[int, int],
        list_entry_map: dict[int, int],
    ) -> tuple[dict[int, int], dict[int, int], dict[int, int]]:
        templates = db.scalars(select(Template).where(Template.tenant_id == source_tenant_id)).all()
        template_map: dict[int, int] = {}
        for row in templates:
            new_row = _copy_row(row, {
                "tenant_id": new_tenant_id,
                "document_template_id": document_template_map.get(row.document_template_id) if row.document_template_id else None,
                "next_event_id": event_map.get(row.next_event_id) if row.next_event_id else None,
                "last_event_id": event_map.get(row.last_event_id) if row.last_event_id else None,
                "cycle_config_id": cycle_config_map.get(row.cycle_config_id) if row.cycle_config_id else None,
            })
            db.add(new_row)
            db.flush()
            template_map[row.id] = new_row.id
        db.commit()

        template_element_map: dict[int, int] = {}
        if template_map:
            elements = db.scalars(select(TemplateElement).where(TemplateElement.template_id.in_(template_map.keys()))).all()
            for row in elements:
                new_row = _copy_row(row, {
                    "template_id": template_map[row.template_id],
                    "element_definition_id": element_definition_map.get(row.element_definition_id, row.element_definition_id),
                    "configuration_json": self._remap_template_element_config(
                        row.configuration_json,
                        participant_map=participant_map,
                        list_definition_map=list_definition_map,
                        list_entry_map=list_entry_map,
                    ),
                })
                db.add(new_row)
                db.flush()
                template_element_map[row.id] = new_row.id
            db.commit()

        template_element_block_map: dict[int, int] = {}
        if template_element_map:
            blocks = db.scalars(
                select(TemplateElementBlock).where(TemplateElementBlock.template_element_id.in_(template_element_map.keys()))
            ).all()
            for row in blocks:
                new_row = _copy_row(row, {
                    "template_element_id": template_element_map[row.template_element_id],
                    "element_definition_id": element_definition_map.get(row.element_definition_id, row.element_definition_id),
                })
                db.add(new_row)
                db.flush()
                template_element_block_map[row.id] = new_row.id
            db.commit()

        return template_map, template_element_map, template_element_block_map

    # ── full-copy-only tables ────────────────────────────────────────────

    def _clone_group_entities(self, db: Session, source_tenant_id: int, new_tenant_id: int) -> dict[int, int]:
        rows = db.scalars(select(GroupEntity).where(GroupEntity.tenant_id == source_tenant_id)).all()
        id_map: dict[int, int] = {}
        for row in rows:
            new_row = _copy_row(row, {"tenant_id": new_tenant_id})
            db.add(new_row)
            db.flush()
            id_map[row.id] = new_row.id
        db.commit()
        return id_map

    def _clone_leaders(self, db: Session, source_tenant_id: int, new_tenant_id: int) -> None:
        rows = db.scalars(select(Leader).where(Leader.tenant_id == source_tenant_id)).all()
        for row in rows:
            db.add(_copy_row(row, {"tenant_id": new_tenant_id}))
        db.commit()

    def _clone_participants(self, db: Session, source_tenant_id: int, new_tenant_id: int) -> dict[int, int]:
        rows = db.scalars(select(Participant).where(Participant.tenant_id == source_tenant_id)).all()
        id_map: dict[int, int] = {}
        for row in rows:
            new_row = _copy_row(row, {"tenant_id": new_tenant_id})
            db.add(new_row)
            db.flush()
            id_map[row.id] = new_row.id
        db.commit()
        return id_map

    def _clone_events(
        self, db: Session, source_tenant_id: int, new_tenant_id: int, *, group_map: dict[int, int], participant_map: dict[int, int]
    ) -> dict[int, int]:
        rows = db.scalars(select(Event).where(Event.tenant_id == source_tenant_id)).all()
        id_map: dict[int, int] = {}

        def remap_ids(ids: list[int] | None) -> list[int] | None:
            if not ids:
                return ids
            return [participant_map.get(i, i) for i in ids]

        for row in rows:
            new_row = _copy_row(row, {
                "tenant_id": new_tenant_id,
                "group_id": group_map.get(row.group_id) if row.group_id else None,
                "organizer_ids": remap_ids(row.organizer_ids),
                "leadership_ids": remap_ids(row.leadership_ids),
                "participant_ids": remap_ids(row.participant_ids),
                "spezial1_ids": remap_ids(row.spezial1_ids),
                "spezial2_ids": remap_ids(row.spezial2_ids),
                "spezial3_ids": remap_ids(row.spezial3_ids),
            })
            db.add(new_row)
            db.flush()
            id_map[row.id] = new_row.id
        db.commit()
        return id_map

    def _clone_event_cycles(self, db: Session, *, event_map: dict[int, int], cycle_config_map: dict[int, int]) -> None:
        if not event_map:
            return
        rows = db.scalars(select(EventCycle).where(EventCycle.event_id.in_(event_map.keys()))).all()
        for row in rows:
            new_event_id = event_map.get(row.event_id)
            new_cycle_config_id = cycle_config_map.get(row.cycle_config_id)
            if new_event_id is None or new_cycle_config_id is None:
                continue
            db.add(EventCycle(event_id=new_event_id, cycle_config_id=new_cycle_config_id, cycle_year=row.cycle_year))
        db.commit()

    def _clone_template_participants(self, db: Session, *, template_map: dict[int, int], participant_map: dict[int, int]) -> None:
        if not template_map:
            return
        rows = db.scalars(select(TemplateParticipant).where(TemplateParticipant.template_id.in_(template_map.keys()))).all()
        for row in rows:
            new_template_id = template_map.get(row.template_id)
            new_participant_id = participant_map.get(row.participant_id)
            if new_template_id is None or new_participant_id is None:
                continue
            db.add(TemplateParticipant(
                template_id=new_template_id,
                participant_id=new_participant_id,
                exclude_from_attendance=row.exclude_from_attendance,
            ))
        db.commit()

    def _remap_list_value(
        self, value_type: str | None, raw: dict | None, participant_map: dict[int, int], event_map: dict[int, int]
    ) -> dict:
        value = copy.deepcopy(raw or {})
        if value_type == "participant" and "participant_id" in value:
            value["participant_id"] = participant_map.get(value["participant_id"], value["participant_id"])
        elif value_type == "participants" and isinstance(value.get("participant_ids"), list):
            value["participant_ids"] = [participant_map.get(i, i) for i in value["participant_ids"]]
        elif value_type == "event" and "event_id" in value:
            value["event_id"] = event_map.get(value["event_id"], value["event_id"])
        return value

    def _clone_list_entries(
        self, db: Session, *, list_definition_map: dict[int, int], participant_map: dict[int, int], event_map: dict[int, int]
    ) -> dict[int, int]:
        if not list_definition_map:
            return {}
        new_definitions = {new_id: db.get(ListDefinition, new_id) for new_id in list_definition_map.values()}
        rows = db.scalars(select(ListEntry).where(ListEntry.list_definition_id.in_(list_definition_map.keys()))).all()
        id_map: dict[int, int] = {}
        for row in rows:
            new_definition_id = list_definition_map.get(row.list_definition_id)
            if new_definition_id is None:
                continue
            definition = new_definitions.get(new_definition_id)
            new_row = _copy_row(row, {
                "list_definition_id": new_definition_id,
                "column_one_value_json": self._remap_list_value(
                    definition.column_one_value_type if definition else None, row.column_one_value_json, participant_map, event_map
                ),
                "column_two_value_json": self._remap_list_value(
                    definition.column_two_value_type if definition else None, row.column_two_value_json, participant_map, event_map
                ),
            })
            db.add(new_row)
            db.flush()
            id_map[row.id] = new_row.id
        db.commit()
        return id_map

    def _clone_submission_assignments(
        self, db: Session, source_tenant_id: int, new_tenant_id: int, *, list_definition_map: dict[int, int]
    ) -> dict[int, int]:
        rows = db.scalars(select(SubmissionAssignment).where(SubmissionAssignment.tenant_id == source_tenant_id)).all()
        id_map: dict[int, int] = {}
        for row in rows:
            new_row = _copy_row(row, {
                "tenant_id": new_tenant_id,
                "list_definition_id": list_definition_map.get(row.list_definition_id) if row.list_definition_id else None,
            })
            db.add(new_row)
            db.flush()
            id_map[row.id] = new_row.id
        db.commit()
        return id_map

    def _clone_submission_uploads(
        self, db: Session, *, submission_assignment_map: dict[int, int], event_map: dict[int, int], list_entry_map: dict[int, int]
    ) -> dict[int, int]:
        if not submission_assignment_map:
            return {}
        rows = db.scalars(select(SubmissionUpload).where(SubmissionUpload.assignment_id.in_(submission_assignment_map.keys()))).all()
        id_map: dict[int, int] = {}
        for row in rows:
            new_assignment_id = submission_assignment_map.get(row.assignment_id)
            if new_assignment_id is None:
                continue
            new_event_id = event_map.get(row.event_id) if row.event_id else None
            new_list_entry_id = list_entry_map.get(row.list_entry_id) if row.list_entry_id else None
            if row.event_id and new_event_id is None:
                continue
            if row.list_entry_id and new_list_entry_id is None:
                continue
            new_row = _copy_row(row, {
                "assignment_id": new_assignment_id,
                "event_id": new_event_id,
                "list_entry_id": new_list_entry_id,
            })
            db.add(new_row)
            db.flush()
            id_map[row.id] = new_row.id
        db.commit()
        return id_map

    def _clone_submission_upload_logs(self, db: Session, *, submission_assignment_map: dict[int, int]) -> None:
        if not submission_assignment_map:
            return
        rows = db.scalars(select(SubmissionUploadLog).where(SubmissionUploadLog.assignment_id.in_(submission_assignment_map.keys()))).all()
        for row in rows:
            new_assignment_id = submission_assignment_map.get(row.assignment_id)
            if new_assignment_id is None:
                continue
            db.add(_copy_row(row, {"assignment_id": new_assignment_id}))
        db.commit()

    def _clone_stored_files(self, db: Session, source_tenant_id: int, new_tenant_id: int) -> dict[int, int]:
        rows = db.scalars(select(StoredFile).where(StoredFile.tenant_id == source_tenant_id)).all()
        if not rows:
            return {}
        source_ids = [row.id for row in rows]
        abgabebox_ids = set(
            db.scalars(select(SubmissionUploadFile.stored_file_id).where(SubmissionUploadFile.stored_file_id.in_(source_ids))).all()
        )
        id_map: dict[int, int] = {}
        for row in rows:
            root = settings.abgabebox_storage_root if row.id in abgabebox_ids else settings.storage_root
            new_storage_path = self._clone_stored_file_content(row.storage_path, root=root, new_tenant_id=new_tenant_id)
            new_row = _copy_row(row, {"tenant_id": new_tenant_id, "storage_path": new_storage_path})
            db.add(new_row)
            db.flush()
            id_map[row.id] = new_row.id
        db.commit()
        return id_map

    def _clone_submission_upload_files(
        self, db: Session, *, submission_upload_map: dict[int, int], stored_file_map: dict[int, int]
    ) -> None:
        if not submission_upload_map:
            return
        rows = db.scalars(select(SubmissionUploadFile).where(SubmissionUploadFile.upload_id.in_(submission_upload_map.keys()))).all()
        for row in rows:
            new_upload_id = submission_upload_map.get(row.upload_id)
            new_stored_file_id = stored_file_map.get(row.stored_file_id)
            if new_upload_id is None or new_stored_file_id is None:
                continue
            db.add(_copy_row(row, {"upload_id": new_upload_id, "stored_file_id": new_stored_file_id}))
        db.commit()

    def _clone_protocols(
        self,
        db: Session,
        source_tenant_id: int,
        new_tenant_id: int,
        *,
        template_map: dict[int, int],
        document_template_map: dict[int, int],
        event_map: dict[int, int],
    ) -> dict[int, int]:
        rows = db.scalars(select(Protocol).where(Protocol.tenant_id == source_tenant_id)).all()
        id_map: dict[int, int] = {}
        for row in rows:
            new_template_id = template_map.get(row.template_id)
            if new_template_id is None:
                continue
            new_row = _copy_row(row, {
                "tenant_id": new_tenant_id,
                "template_id": new_template_id,
                "document_template_id": document_template_map.get(row.document_template_id) if row.document_template_id else None,
                "event_id": event_map.get(row.event_id) if row.event_id else None,
                # document_template_path_snapshot intentionally left pointing at the ORIGINAL
                # tenant's immutable snapshot directory - see class docstring.
            })
            db.add(new_row)
            db.flush()
            id_map[row.id] = new_row.id
        db.commit()
        return id_map

    def _clone_protocol_elements(self, db: Session, *, protocol_map: dict[int, int], template_element_map: dict[int, int]) -> dict[int, int]:
        if not protocol_map:
            return {}
        rows = db.scalars(select(ProtocolElement).where(ProtocolElement.protocol_id.in_(protocol_map.keys()))).all()
        id_map: dict[int, int] = {}
        for row in rows:
            new_protocol_id = protocol_map.get(row.protocol_id)
            if new_protocol_id is None:
                continue
            new_row = _copy_row(row, {
                "protocol_id": new_protocol_id,
                "template_element_id": template_element_map.get(row.template_element_id) if row.template_element_id else None,
            })
            db.add(new_row)
            db.flush()
            id_map[row.id] = new_row.id
        db.commit()
        return id_map

    def _remap_block_configuration(self, config: dict | None, participant_map: dict[int, int]) -> dict:
        config = config or {}
        entries = config.get("attendance_entries")
        if not isinstance(entries, list):
            return copy.deepcopy(config)
        new_entries = []
        for entry in entries:
            new_entry = dict(entry)
            participant_id = new_entry.get("participant_id")
            if participant_id in participant_map:
                new_entry["participant_id"] = participant_map[participant_id]
            new_entries.append(new_entry)
        rest = {k: copy.deepcopy(v) for k, v in config.items() if k != "attendance_entries"}
        return {**rest, "attendance_entries": new_entries}

    def _clone_protocol_element_blocks(
        self,
        db: Session,
        *,
        protocol_element_map: dict[int, int],
        template_element_block_map: dict[int, int],
        element_definition_map: dict[int, int],
        participant_map: dict[int, int],
    ) -> dict[int, int]:
        if not protocol_element_map:
            return {}
        rows = db.scalars(
            select(ProtocolElementBlock).where(ProtocolElementBlock.protocol_element_id.in_(protocol_element_map.keys()))
        ).all()
        id_map: dict[int, int] = {}
        for row in rows:
            new_protocol_element_id = protocol_element_map.get(row.protocol_element_id)
            if new_protocol_element_id is None:
                continue
            new_row = _copy_row(row, {
                "protocol_element_id": new_protocol_element_id,
                "template_element_block_id": template_element_block_map.get(row.template_element_block_id) if row.template_element_block_id else None,
                "element_definition_id": element_definition_map.get(row.element_definition_id) if row.element_definition_id else None,
                "configuration_snapshot_json": self._remap_block_configuration(row.configuration_snapshot_json, participant_map),
            })
            db.add(new_row)
            db.flush()
            id_map[row.id] = new_row.id
        db.commit()
        return id_map

    def _clone_protocol_texts(self, db: Session, *, protocol_element_block_map: dict[int, int]) -> None:
        if not protocol_element_block_map:
            return
        rows = db.scalars(select(ProtocolText).where(ProtocolText.protocol_element_block_id.in_(protocol_element_block_map.keys()))).all()
        for row in rows:
            new_block_id = protocol_element_block_map.get(row.protocol_element_block_id)
            if new_block_id is None:
                continue
            db.add(_copy_row(row, {"protocol_element_block_id": new_block_id}))
        db.commit()

    def _clone_protocol_display_snapshots(self, db: Session, *, protocol_element_block_map: dict[int, int]) -> None:
        if not protocol_element_block_map:
            return
        rows = db.scalars(
            select(ProtocolDisplaySnapshot).where(ProtocolDisplaySnapshot.protocol_element_block_id.in_(protocol_element_block_map.keys()))
        ).all()
        for row in rows:
            new_block_id = protocol_element_block_map.get(row.protocol_element_block_id)
            if new_block_id is None:
                continue
            db.add(_copy_row(row, {"protocol_element_block_id": new_block_id}))
        db.commit()

    def _clone_protocol_images(self, db: Session, *, protocol_element_block_map: dict[int, int], stored_file_map: dict[int, int]) -> None:
        if not protocol_element_block_map:
            return
        rows = db.scalars(select(ProtocolImage).where(ProtocolImage.protocol_element_block_id.in_(protocol_element_block_map.keys()))).all()
        for row in rows:
            new_block_id = protocol_element_block_map.get(row.protocol_element_block_id)
            new_stored_file_id = stored_file_map.get(row.stored_file_id)
            if new_block_id is None or new_stored_file_id is None:
                continue
            db.add(_copy_row(row, {"protocol_element_block_id": new_block_id, "stored_file_id": new_stored_file_id}))
        db.commit()

    def _clone_finance_transactions(self, db: Session, *, finance_account_map: dict[int, int], protocol_map: dict[int, int]) -> dict[int, int]:
        if not finance_account_map:
            return {}
        rows = db.scalars(select(FinanceTransaction).where(FinanceTransaction.account_id.in_(finance_account_map.keys()))).all()
        id_map: dict[int, int] = {}
        for row in rows:
            new_account_id = finance_account_map.get(row.account_id)
            if new_account_id is None:
                continue
            new_row = _copy_row(row, {
                "account_id": new_account_id,
                "protocol_id": protocol_map.get(row.protocol_id) if row.protocol_id else None,
            })
            db.add(new_row)
            db.flush()
            id_map[row.id] = new_row.id
        db.commit()
        return id_map

    def _clone_attendance_fines(
        self,
        db: Session,
        *,
        protocol_map: dict[int, int],
        participant_map: dict[int, int],
        finance_account_map: dict[int, int],
        finance_transaction_map: dict[int, int],
    ) -> None:
        if not protocol_map:
            return
        rows = db.scalars(select(AttendanceFine).where(AttendanceFine.protocol_id.in_(protocol_map.keys()))).all()
        for row in rows:
            new_protocol_id = protocol_map.get(row.protocol_id)
            new_account_id = finance_account_map.get(row.account_id)
            if new_protocol_id is None or new_account_id is None:
                continue
            new_row = _copy_row(row, {
                "protocol_id": new_protocol_id,
                "participant_id": participant_map.get(row.participant_id) if row.participant_id else None,
                "account_id": new_account_id,
                "collected_transaction_id": finance_transaction_map.get(row.collected_transaction_id) if row.collected_transaction_id else None,
                "closed_in_protocol_id": protocol_map.get(row.closed_in_protocol_id) if row.closed_in_protocol_id else None,
            })
            db.add(new_row)
        db.commit()

    def _clone_protocol_todos(
        self,
        db: Session,
        source_tenant_id: int,
        new_tenant_id: int,
        *,
        protocol_element_block_map: dict[int, int],
        participant_map: dict[int, int],
        event_map: dict[int, int],
        protocol_map: dict[int, int],
        submission_assignment_map: dict[int, int],
    ) -> None:
        rows = db.scalars(select(ProtocolTodo).where(ProtocolTodo.tenant_id == source_tenant_id)).all()
        for row in rows:
            new_row = _copy_row(row, {
                "tenant_id": new_tenant_id,
                "protocol_element_block_id": protocol_element_block_map.get(row.protocol_element_block_id) if row.protocol_element_block_id else None,
                "assigned_participant_id": participant_map.get(row.assigned_participant_id) if row.assigned_participant_id else None,
                "due_event_id": event_map.get(row.due_event_id) if row.due_event_id else None,
                "closed_in_protocol_id": protocol_map.get(row.closed_in_protocol_id) if row.closed_in_protocol_id else None,
                "submission_assignment_id": submission_assignment_map.get(row.submission_assignment_id) if row.submission_assignment_id else None,
            })
            db.add(new_row)
        db.commit()

    def _clone_user_template_access(self, db: Session, source_tenant_id: int, new_tenant_id: int, *, template_map: dict[int, int]) -> None:
        if not template_map:
            return
        rows = db.scalars(select(UserTemplateAccess).where(UserTemplateAccess.tenant_id == source_tenant_id)).all()
        for row in rows:
            new_template_id = template_map.get(row.template_id)
            if new_template_id is None:
                continue
            db.add(_copy_row(row, {"tenant_id": new_tenant_id, "template_id": new_template_id}))
        db.commit()

    def _clone_user_protocol_access(self, db: Session, source_tenant_id: int, new_tenant_id: int, *, protocol_map: dict[int, int]) -> None:
        if not protocol_map:
            return
        rows = db.scalars(select(UserProtocolAccess).where(UserProtocolAccess.tenant_id == source_tenant_id)).all()
        for row in rows:
            new_protocol_id = protocol_map.get(row.protocol_id)
            if new_protocol_id is None:
                continue
            db.add(_copy_row(row, {"tenant_id": new_tenant_id, "protocol_id": new_protocol_id}))
        db.commit()

    def _clone_user_tenant_roles(self, db: Session, source_tenant_id: int, new_tenant_id: int) -> None:
        rows = db.scalars(select(UserTenantRole).where(UserTenantRole.tenant_id == source_tenant_id)).all()
        for row in rows:
            db.add(_copy_row(row, {"tenant_id": new_tenant_id}))
        db.commit()
