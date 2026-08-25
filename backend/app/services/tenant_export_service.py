"""Exports a tenant to a portable .zip (manifest.json + referenced files).

Three cumulative scopes, mirroring the three options in the admin panel:
- "structure": config only - cycles, templates/forms, document templates, lists, finance
  accounts, verified custom domains, and which users have which role in this tenant. No
  participants, events, or protocols.
- "full": structure + all operational data - participants, events, protocols (with all
  their content), finance transactions/fines, todos. No Abgabebox (public upload box)
  data.
- "full_abgabebox": full + Abgabebox assignments/uploads/uploaded files.

See tenant_transfer_common.py for why lookup-table and app_user references are exported
by code/email rather than by (installation-specific) numeric id.
"""

from __future__ import annotations

import json
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.secret_crypto import decrypt_secret
from app.models import (
    AppUser,
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
    ProtocolExportCache,
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
    TenantDomain,
    UserProtocolAccess,
    UserProtocolScroll,
    UserMfaFactor,
    UserTemplateAccess,
    UserTenantRole,
    WordImportDocument,
    WordImportProfile,
    WordImportSuggestionOutcome,
)
from app.services.file_service import _safe_storage_path
from app.services.tenant_transfer_common import (
    LOOKUP_COLUMNS,
    REDACTED_PASSWORD_HASH_MARKER,
    USER_ID_COLUMNS,
    LookupCodeCache,
    UserEmailCache,
    row_to_dict,
)

FORMAT_VERSION = 1
ExportScope = Literal["structure", "structure_lists", "full", "full_abgabebox"]


class TenantExportService:
    def export(self, db: Session, tenant_id: int, scope: ExportScope) -> tuple[Path, str]:
        tenant = db.get(Tenant, tenant_id)
        if tenant is None:
            raise ValueError("Tenant not found")

        self._lookup_cache = LookupCodeCache(db)
        self._user_cache = UserEmailCache(db)
        self._pending_files: list[tuple[Path, str]] = []

        tables: dict[str, Any] = {}
        tables["tenant"] = self._row(tenant, "tenant")
        if tenant.profile_image_path:
            member = self._register_file(settings.storage_root, tenant.profile_image_path, "files/tenant_profile_image")
            tables["tenant"]["profile_image_path"] = member

        self._export_structure(db, tenant_id, tables)
        if scope == "structure_lists":
            self._export_list_entries(db, tables)
        if scope in ("full", "full_abgabebox"):
            self._export_full(db, tenant_id, tables, include_abgabebox=scope == "full_abgabebox")

        # Bundled last, once every USER_ID_COLUMNS lookup above has recorded which app_user
        # ids actually got referenced. Deliberately not scoped by tenant_id (that column
        # doesn't exist on app_user - it's a systemwide table), just by "was this user
        # referenced anywhere in what we just exported".
        #
        # password_hash is only kept for users who are actual MEMBERS of the exported tenant
        # (a user_tenant_role row for this tenant_id, collected below from the row already
        # produced by _export_structure) - they're the real target audience of a tenant
        # transfer, and it makes sense for their login to travel with them (see
        # TenantImportService._import_app_users). Everyone else here is a pure metadata
        # reference (e.g. created_by on a template/protocol/stored_file) with no membership
        # in this tenant - their password_hash is replaced with an unusable placeholder so a
        # tenant export (handed to a potentially different, untrusted installation) never
        # bundles a foreign tenant's users' real credentials.
        referenced_user_ids = self._user_cache.referenced_ids()
        users = db.query(AppUser).filter(AppUser.id.in_(referenced_user_ids)).all() if referenced_user_ids else []
        member_emails = {row["user_id"] for row in tables.get("user_tenant_role", []) if row.get("user_id")}
        user_rows = []
        for u in users:
            row = row_to_dict(u)
            if u.email not in member_emails:
                row["password_hash"] = REDACTED_PASSWORD_HASH_MARKER
            user_rows.append(row)
        tables["app_user"] = user_rows

        # MFA belongs to the system-wide AppUser rather than directly to a tenant. Only
        # factors of actual tenant members travel with a tenant export; metadata-only user
        # references must not leak authentication credentials. TOTP ciphertext is tied to
        # this installation's ADMIN_AUTH_SECRET, so export the plaintext secret and let the
        # target installation encrypt it with its own key during import.
        member_user_ids = {u.id for u in users if u.email in member_emails}
        factors = (
            db.scalars(select(UserMfaFactor).where(UserMfaFactor.user_id.in_(member_user_ids))).all()
            if member_user_ids
            else []
        )
        factor_rows = []
        for factor in factors:
            row = row_to_dict(factor)
            row["user_id"] = self._user_cache.email_for(factor.user_id)
            row["totp_secret"] = decrypt_secret(factor.secret_encrypted) if factor.secret_encrypted else None
            row.pop("secret_encrypted", None)
            factor_rows.append(row)
        tables["user_mfa_factor"] = factor_rows

        manifest = {
            "format_version": FORMAT_VERSION,
            "scope": scope,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "source_tenant_name": tenant.name,
            "tables": tables,
        }

        tmp = tempfile.NamedTemporaryFile(prefix="hocx-export-", suffix=".zip", delete=False)
        tmp.close()
        zip_path = Path(tmp.name)
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=None))
            for disk_path, member_name in self._pending_files:
                zf.write(disk_path, member_name)

        safe_name = "".join(c if c.isalnum() or c in "-_" else "-" for c in tenant.name).strip("-") or "tenant"
        filename = f"{safe_name}-{scope}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.hocxexport.zip"
        return zip_path, filename

    # ── generic row/file helpers ─────────────────────────────────────────

    def _row(self, obj: Any, table_name: str) -> dict[str, Any]:
        data = row_to_dict(obj)
        for column, model in LOOKUP_COLUMNS.get(table_name, {}).items():
            if data.get(column) is not None:
                data[column] = self._lookup_cache.code_for(model, data[column])
        for column in USER_ID_COLUMNS.get(table_name, []):
            if column in data:
                data[column] = self._user_cache.email_for(data[column])
        return data

    def _rows(self, objs: list[Any], table_name: str) -> list[dict[str, Any]]:
        return [self._row(obj, table_name) for obj in objs]

    def _register_file(self, root: str, storage_path: str, member_prefix: str) -> str | None:
        source = _safe_storage_path(root, storage_path)
        if not source.exists():
            return None
        suffix = Path(storage_path).suffix
        member_name = f"{member_prefix}{suffix}"
        self._pending_files.append((source, member_name))
        return member_name

    # ── structure scope ──────────────────────────────────────────────────

    def _export_structure(self, db: Session, tenant_id: int, tables: dict[str, Any]) -> None:
        tables["cycle_config"] = self._rows(
            db.scalars(select(CycleConfig).where(CycleConfig.tenant_id == tenant_id)).all(), "cycle_config"
        )
        tables["element_definition"] = self._rows(
            db.scalars(select(ElementDefinition).where(ElementDefinition.tenant_id == tenant_id)).all(),
            "element_definition",
        )

        parts = db.scalars(select(DocumentTemplatePart).where(DocumentTemplatePart.tenant_id == tenant_id)).all()
        part_rows = []
        for part in parts:
            row = self._row(part, "document_template_part")
            row["storage_path"] = self._register_file(
                settings.storage_root, part.storage_path, f"files/document_template_parts/{part.id}"
            )
            part_rows.append(row)
        tables["document_template_part"] = part_rows

        tables["document_template"] = self._rows(
            db.scalars(select(DocumentTemplate).where(DocumentTemplate.tenant_id == tenant_id)).all(),
            "document_template",
        )

        templates = db.scalars(select(Template).where(Template.tenant_id == tenant_id)).all()
        tables["template"] = self._rows(templates, "template")
        template_ids = [t.id for t in templates]

        template_elements = (
            db.scalars(select(TemplateElement).where(TemplateElement.template_id.in_(template_ids))).all()
            if template_ids
            else []
        )
        tables["template_element"] = self._rows(template_elements, "template_element")
        template_element_ids = [te.id for te in template_elements]

        template_element_blocks = (
            db.scalars(
                select(TemplateElementBlock).where(TemplateElementBlock.template_element_id.in_(template_element_ids))
            ).all()
            if template_element_ids
            else []
        )
        tables["template_element_block"] = self._rows(template_element_blocks, "template_element_block")

        tables["list_definition"] = self._rows(
            db.scalars(select(ListDefinition).where(ListDefinition.tenant_id == tenant_id)).all(), "list_definition"
        )
        tables["finance_account"] = self._rows(
            db.scalars(select(FinanceAccount).where(FinanceAccount.tenant_id == tenant_id)).all(), "finance_account"
        )
        tables["user_tenant_role"] = self._rows(
            db.scalars(select(UserTenantRole).where(UserTenantRole.tenant_id == tenant_id)).all(), "user_tenant_role"
        )
        # verification_token/status/verified_at travel unchanged (no LOOKUP_COLUMNS/
        # USER_ID_COLUMNS entry needed) - a tenant import is meant to reconstruct the source
        # 1:1, and a domain already verified on the source (its DNS TXT record already holds
        # this exact token) should stay verified on the target instead of forcing the admin
        # through domain verification again. See TenantImportService._import_tenant_domains
        # for how a global domain-uniqueness collision on the target is handled.
        tables["tenant_domain"] = self._rows(
            db.scalars(select(TenantDomain).where(TenantDomain.tenant_id == tenant_id)).all(), "tenant_domain"
        )
        # Learned Word-import mappings are template configuration and therefore belong
        # to every structure backup, not only to exports containing operational data.
        tables["word_import_profile"] = self._rows(
            db.scalars(select(WordImportProfile).where(WordImportProfile.tenant_id == tenant_id)).all(),
            "word_import_profile",
        )

    def _export_list_entries(self, db: Session, tables: dict[str, Any]) -> None:
        list_definition_ids = [row["id"] for row in tables["list_definition"]]
        list_entries = (
            db.scalars(select(ListEntry).where(ListEntry.list_definition_id.in_(list_definition_ids))).all()
            if list_definition_ids
            else []
        )
        tables["list_entry"] = self._rows(list_entries, "list_entry")

    # ── full scope ────────────────────────────────────────────────────────

    def _export_full(self, db: Session, tenant_id: int, tables: dict[str, Any], *, include_abgabebox: bool) -> None:
        tables["group_entity"] = self._rows(
            db.scalars(select(GroupEntity).where(GroupEntity.tenant_id == tenant_id)).all(), "group_entity"
        )
        tables["leader"] = self._rows(db.scalars(select(Leader).where(Leader.tenant_id == tenant_id)).all(), "leader")

        participants = db.scalars(select(Participant).where(Participant.tenant_id == tenant_id)).all()
        tables["participant"] = self._rows(participants, "participant")

        events = db.scalars(select(Event).where(Event.tenant_id == tenant_id)).all()
        tables["event"] = self._rows(events, "event")
        event_ids = [e.id for e in events]

        tables["event_cycle"] = self._rows(
            db.scalars(select(EventCycle).where(EventCycle.event_id.in_(event_ids))).all() if event_ids else [],
            "event_cycle",
        )

        self._export_list_entries(db, tables)

        template_ids = [row["id"] for row in tables["template"]]
        tables["template_participant"] = self._rows(
            db.scalars(select(TemplateParticipant).where(TemplateParticipant.template_id.in_(template_ids))).all()
            if template_ids
            else [],
            "template_participant",
        )

        submission_assignments: list[Any] = []
        submission_uploads: list[Any] = []
        if include_abgabebox:
            submission_assignments = db.scalars(
                select(SubmissionAssignment).where(SubmissionAssignment.tenant_id == tenant_id)
            ).all()
            tables["submission_assignment"] = self._rows(submission_assignments, "submission_assignment")
            assignment_ids = [a.id for a in submission_assignments]
            submission_uploads = (
                db.scalars(select(SubmissionUpload).where(SubmissionUpload.assignment_id.in_(assignment_ids))).all()
                if assignment_ids
                else []
            )
            tables["submission_upload"] = self._rows(submission_uploads, "submission_upload")
            tables["submission_upload_log"] = self._rows(
                db.scalars(select(SubmissionUploadLog).where(SubmissionUploadLog.assignment_id.in_(assignment_ids))).all()
                if assignment_ids
                else [],
                "submission_upload_log",
            )

        tables["finance_transaction"] = self._rows(
            db.scalars(
                select(FinanceTransaction).where(
                    FinanceTransaction.account_id.in_([row["id"] for row in tables["finance_account"]])
                )
            ).all()
            if tables["finance_account"]
            else [],
            "finance_transaction",
        )

        stored_files = db.scalars(select(StoredFile).where(StoredFile.tenant_id == tenant_id)).all()
        upload_ids = [u.id for u in submission_uploads]
        # Computed independently of `include_abgabebox`/`submission_uploads` above (which are
        # only populated for scope="full_abgabebox") - a "full" export still needs to know
        # which stored_file rows are Abgabebox uploads so it can cleanly EXCLUDE them, rather
        # than trying (and failing) to find them under the wrong storage root.
        abgabebox_stored_file_ids = set(
            db.scalars(
                select(SubmissionUploadFile.stored_file_id)
                .join(SubmissionUpload, SubmissionUploadFile.upload_id == SubmissionUpload.id)
                .join(SubmissionAssignment, SubmissionUpload.assignment_id == SubmissionAssignment.id)
                .where(SubmissionAssignment.tenant_id == tenant_id)
            ).all()
        )
        stored_file_rows = []
        for f in stored_files:
            is_abgabebox = f.id in abgabebox_stored_file_ids
            if is_abgabebox and not include_abgabebox:
                continue
            row = self._row(f, "stored_file")
            root = settings.abgabebox_storage_root if is_abgabebox else settings.storage_root
            row["storage_path"] = self._register_file(root, f.storage_path, f"files/stored_files/{f.id}")
            stored_file_rows.append(row)
        tables["stored_file"] = stored_file_rows

        if include_abgabebox:
            tables["submission_upload_file"] = self._rows(
                db.scalars(select(SubmissionUploadFile).where(SubmissionUploadFile.upload_id.in_(upload_ids))).all()
                if upload_ids
                else [],
                "submission_upload_file",
            )

        protocols = db.scalars(select(Protocol).where(Protocol.tenant_id == tenant_id)).all()
        tables["protocol"] = self._rows(protocols, "protocol")
        protocol_ids = [p.id for p in protocols]

        # Keep the import queue/history as well as its link to the generated protocol.
        # The referenced original files are already included through the tenant-wide
        # StoredFile export above.
        tables["word_import_document"] = self._rows(
            db.scalars(select(WordImportDocument).where(WordImportDocument.tenant_id == tenant_id)).all(),
            "word_import_document",
        )
        tables["word_import_suggestion_outcome"] = self._rows(
            db.scalars(
                select(WordImportSuggestionOutcome).where(WordImportSuggestionOutcome.tenant_id == tenant_id)
            ).all(),
            "word_import_suggestion_outcome",
        )

        protocol_elements = (
            db.scalars(select(ProtocolElement).where(ProtocolElement.protocol_id.in_(protocol_ids))).all()
            if protocol_ids
            else []
        )
        tables["protocol_element"] = self._rows(protocol_elements, "protocol_element")
        protocol_element_ids = [pe.id for pe in protocol_elements]

        protocol_element_blocks = (
            db.scalars(
                select(ProtocolElementBlock).where(ProtocolElementBlock.protocol_element_id.in_(protocol_element_ids))
            ).all()
            if protocol_element_ids
            else []
        )
        tables["protocol_element_block"] = self._rows(protocol_element_blocks, "protocol_element_block")
        block_ids = [b.id for b in protocol_element_blocks]

        tables["protocol_text"] = self._rows(
            db.scalars(select(ProtocolText).where(ProtocolText.protocol_element_block_id.in_(block_ids))).all()
            if block_ids
            else [],
            "protocol_text",
        )
        tables["protocol_display_snapshot"] = self._rows(
            db.scalars(
                select(ProtocolDisplaySnapshot).where(ProtocolDisplaySnapshot.protocol_element_block_id.in_(block_ids))
            ).all()
            if block_ids
            else [],
            "protocol_display_snapshot",
        )
        tables["protocol_image"] = self._rows(
            db.scalars(select(ProtocolImage).where(ProtocolImage.protocol_element_block_id.in_(block_ids))).all()
            if block_ids
            else [],
            "protocol_image",
        )

        tables["attendance_fine"] = self._rows(
            db.scalars(select(AttendanceFine).where(AttendanceFine.protocol_id.in_(protocol_ids))).all()
            if protocol_ids
            else [],
            "attendance_fine",
        )
        tables["protocol_todo"] = self._rows(
            db.scalars(select(ProtocolTodo).where(ProtocolTodo.tenant_id == tenant_id)).all(), "protocol_todo"
        )
        tables["user_template_access"] = self._rows(
            db.scalars(select(UserTemplateAccess).where(UserTemplateAccess.tenant_id == tenant_id)).all(),
            "user_template_access",
        )
        tables["user_protocol_access"] = self._rows(
            db.scalars(select(UserProtocolAccess).where(UserProtocolAccess.tenant_id == tenant_id)).all(),
            "user_protocol_access",
        )
        tables["user_protocol_scroll"] = self._rows(
            db.scalars(select(UserProtocolScroll).where(UserProtocolScroll.protocol_id.in_(protocol_ids))).all()
            if protocol_ids
            else [],
            "user_protocol_scroll",
        )
        tables["protocol_export_cache"] = self._rows(
            db.scalars(select(ProtocolExportCache).where(ProtocolExportCache.protocol_id.in_(protocol_ids))).all()
            if protocol_ids
            else [],
            "protocol_export_cache",
        )
