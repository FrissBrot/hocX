"""Exports a tenant to a portable .zip (manifest.json + referenced files).

Three cumulative scopes, mirroring the three options in the admin panel:
- "structure": config only - cycles, templates/forms, document templates, lists, finance
  accounts, verified custom domains, the tenant's users with their role/MFA/calendar
  subscriptions, booked features and storage packages, trust relations to partner
  tenants. No participants, events, or protocols.
- "structure_lists": structure + the list entries themselves.
- "full": structure + all operational data - participants, events, protocols (with all
  their content), finance transactions/fines, todos, files/gallery, photo albums incl.
  partner shares, public share links, cycle snapshots of the lists. No Abgabebox (public
  upload box) data.
- "full_abgabebox": full + Abgabebox assignments/links/uploads/uploaded files and the
  albums bound to an Abgabe - a complete backup of the tenant.

Zugangsdaten (Passwort-Hashes, TOTP-Secrets im Klartext, Link- und Kalender-Tokens) kommen nur mit
``include_credentials=True`` ins Archiv (Datenschutz-Audit Paket 6): dann gilt es wie ein
Datenbank-Dump. Ohne sie setzt der Import zufällige Passwörter, lässt MFA weg und erzeugt neue
Link- und Abo-URLs (TenantImportService behandelt fehlende Werte schon so).

Every row keeps its public_id; the import reuses it whenever it is still free on the
target (see TenantImportService._claim_public_id), so references stored by public_id
(element_ref strings, album items, word-import drafts, bookmarked URLs) keep working.

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
    ProtocolTodoAssignee,
    ProtocolTodoFile,
    AgendaItem,
    TaskPackage,
    TaskPackageCycle,
    TaskPackageItem,
    AttendanceFine,
    CycleConfig,
    DocumentExport,
    DocumentRegistry,
    DocumentAsset,
    DocumentBrand,
    DocumentBrandRevision,
    DocumentComponent,
    DocumentTemplate,
    DocumentTemplateAssignment,
    DocumentTemplateRevision,
    ElementDefinition,
    Event,
    EventCycle,
    FinanceAccount,
    FineTariff,
    FinanceTransaction,
    GalleryImage,
    GroupEntity,
    Leader,
    ListDefinition,
    ListEntry,
    Participant,
    PlatformAdmin,
    Protocol,
    ProtocolDisplaySnapshot,
    ProtocolElement,
    ProtocolElementBlock,
    ProtocolImage,
    ProtocolText,
    ProtocolTodo,
    StoredFile,
    SubmissionAssignment,
    SubmissionLink,
    SubmissionUpload,
    SubmissionUploadFile,
    SubmissionUploadLog,
    TableSnapshot,
    Template,
    TemplateElement,
    TemplateElementBlock,
    TemplateParticipant,
    Tenant,
    TenantDomain,
    TenantFeature,
    TenantStoragePackage,
    TenantTrust,
    UserProtocolAccess,
    UserProtocolScroll,
    UserMfaFactor,
    UserTemplateAccess,
    WordImportDocument,
    WordImportProfile,
    WordImportSuggestionOutcome,
)
from app.models.entities import (
    CalendarFeed,
    PhotoAlbum,
    PhotoAlbumItem,
    PhotoAlbumTenantShare,
    ShareLink,
    ShareLinkFile,
    submission_assignment_link_table,
)
from app.core.storage import get_object_store, namespace_for_root, write_object_to_zip
from app.services.tenant_transfer_common import (
    LOOKUP_COLUMNS,
    USER_ID_COLUMNS,
    LookupCodeCache,
    UserIdentityCache,
    json_safe,
    row_to_dict,
)

# Bumped 1 -> 2: exported rows now include a public_id column (see build_row in
# tenant_transfer_common.py, which drops it on import so each row gets a fresh UUIDv7).
# Bumped 2 -> 3: users belong to exactly one tenant - app_user rows carry their role as
# `role_id` (a role code) instead of a separate user_tenant_role table, and only the exported
# tenant's own users are bundled. TenantImportService still reads version 2.
# Format 3 also gained (without a version bump - purely additive tables an older importer just
# ignores) photo albums, table snapshots, links/feeds/shares and tenant settings.
FORMAT_VERSION = 8  # 8: Baustein-Bibliothek (element_definition.is_library); 7: Document Studio (Brand-Profile, Assets, Vorlagen, Komponenten, Zuweisungen); 6: Dokumentenregister; 5: Dokument-Engine (Hausstile, Stil-Assets, Rezepte, document_export)
ExportScope = Literal["structure", "structure_lists", "full", "full_abgabebox"]


class TenantExportService:
    def export(self, db: Session, tenant_id: int, scope: ExportScope, *, include_credentials: bool = False) -> tuple[Path, str]:
        tenant = db.get(Tenant, tenant_id)
        if tenant is None:
            raise ValueError("Tenant not found")
        manifest, pending_files = self.collect(db, tenant_id, scope, include_credentials=include_credentials)

        tmp = tempfile.NamedTemporaryFile(prefix="hocx-export-", suffix=".zip", delete=False)
        tmp.close()
        zip_path = Path(tmp.name)
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=None))
            for namespace, key, member_name in pending_files:
                # Gestreamt aus dem Objektspeicher; verschwindet ein Objekt zwischen Inventur und
                # Schreiben, bricht der Export ab statt ein Manifest mit Verweis ins Leere zu liefern.
                write_object_to_zip(zf, namespace, key, member_name)

        safe_name = "".join(c if c.isalnum() or c in "-_" else "-" for c in tenant.name).strip("-") or "tenant"
        filename = f"{safe_name}-{scope}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.hocxexport.zip"
        return zip_path, filename

    def object_exists(self, namespace: str, key: str) -> bool:
        """Ob eine referenzierte Datei existiert. Der Mandanten-Restore aus dem Backup
        überschreibt das (historische Quelle: Manifest des Sicherungspunkts statt aktuellem
        Objektspeicher)."""
        return get_object_store().exists(namespace, key)

    def collect(
        self, db: Session, tenant_id: int, scope: ExportScope, *, include_credentials: bool = False
    ) -> tuple[dict[str, Any], list[tuple[str, str, str]]]:
        """Manifest (Tabellen) und Liste der Dateien (namespace, key, member_name) - ohne ZIP."""
        tenant = db.get(Tenant, tenant_id)
        if tenant is None:
            raise ValueError("Tenant not found")

        self._lookup_cache = LookupCodeCache(db)
        self._user_cache = UserIdentityCache(db, tenant_id=tenant_id)
        self._pending_files: list[tuple[str, str, str]] = []

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

        # The tenant's own users travel with it, password_hash included: a tenant transfer is a
        # move/restore, and the members keep the login they already have (see
        # TenantImportService._import_app_users). Every user belongs to exactly one tenant, so
        # there is nobody else to bundle - references to any other tenant's user were already
        # exported as NULL by UserIdentityCache. The role is exported as a code (LOOKUP_COLUMNS);
        # tenant_id is dropped, the import assigns the new tenant.
        users = db.scalars(select(AppUser).where(AppUser.tenant_id == tenant_id).order_by(AppUser.id)).all()
        user_rows = self._rows(users, "app_user")
        for row in user_rows:
            row.pop("tenant_id", None)
        tables["app_user"] = user_rows

        # MFA belongs to the user rather than directly to the tenant. TOTP ciphertext is tied
        # to this installation's ADMIN_AUTH_SECRET, so export the plaintext secret and let the
        # target installation encrypt it with its own key during import.
        member_user_ids = {u.id for u in users}
        factors = (
            db.scalars(select(UserMfaFactor).where(UserMfaFactor.user_id.in_(member_user_ids))).all()
            if member_user_ids
            else []
        )
        factor_rows = []
        for factor in factors:
            row = row_to_dict(factor)
            row["user_id"] = self._user_cache.reference_for(factor.user_id)
            row["totp_secret"] = decrypt_secret(factor.secret_encrypted) if factor.secret_encrypted else None
            row.pop("secret_encrypted", None)
            factor_rows.append(row)
        tables["user_mfa_factor"] = factor_rows
        self._export_tenant_settings(db, tenant_id, tables)
        self._export_calendar_feeds(db, tenant_id, tables)
        self._export_tenant_trusts(db, tenant_id, tables)
        if not include_credentials:
            _strip_credentials(tables)

        manifest = {
            "format_version": FORMAT_VERSION,
            "scope": scope,
            "include_credentials": include_credentials,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "source_tenant_name": tenant.name,
            "tables": tables,
        }
        return manifest, list(self._pending_files)

    # ── generic row/file helpers ─────────────────────────────────────────

    def _row(self, obj: Any, table_name: str) -> dict[str, Any]:
        data = row_to_dict(obj)
        for column, model in LOOKUP_COLUMNS.get(table_name, {}).items():
            if data.get(column) is not None:
                data[column] = self._lookup_cache.code_for(model, data[column])
        for column in USER_ID_COLUMNS.get(table_name, []):
            if column in data:
                data[column] = self._user_cache.reference_for(data[column])
        return data

    def _rows(self, objs: list[Any], table_name: str) -> list[dict[str, Any]]:
        return [self._row(obj, table_name) for obj in objs]

    def _register_file(self, root: str, storage_path: str, member_prefix: str) -> str | None:
        namespace = namespace_for_root(root)
        try:
            if not self.object_exists(namespace, storage_path):
                return None
        except ValueError:
            return None
        suffix = Path(storage_path).suffix
        member_name = f"{member_prefix}{suffix}"
        self._pending_files.append((namespace, storage_path, member_name))
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

        # Document Studio: Assets (mit Datei), Brand-Profile samt Revisionen, wiederverwendbare
        # Komponenten, Mandantenvorlagen samt Revisionen und Zuweisungen. Systemvorlagen gehören
        # der Installation und werden nicht exportiert (Verweise darauf per system_key).
        asset_rows = []
        for asset in db.scalars(select(DocumentAsset).where(DocumentAsset.tenant_id == tenant_id)).all():
            row = self._row(asset, "document_asset")
            row["storage_path"] = self._register_file(settings.storage_root, asset.storage_path, f"files/document_assets/{asset.id}")
            asset_rows.append(row)
        tables["document_asset"] = asset_rows
        brands = db.scalars(select(DocumentBrand).where(DocumentBrand.tenant_id == tenant_id)).all()
        tables["document_brand"] = self._rows(brands, "document_brand")
        brand_ids = [brand.id for brand in brands]
        tables["document_brand_revision"] = self._rows(
            db.scalars(select(DocumentBrandRevision).where(DocumentBrandRevision.brand_id.in_(brand_ids))).all() if brand_ids else [], "document_brand_revision"
        )
        tables["document_component"] = self._rows(
            db.scalars(select(DocumentComponent).where(DocumentComponent.tenant_id == tenant_id)).all(), "document_component"
        )
        document_templates = db.scalars(select(DocumentTemplate).where(DocumentTemplate.tenant_id == tenant_id)).all()
        template_rows = self._rows(document_templates, "document_template")
        system_keys = {
            row.id: row.system_key
            for row in db.scalars(select(DocumentTemplate).where(DocumentTemplate.tenant_id.is_(None))).all()
        }
        for row in template_rows:
            row["source_system_key"] = system_keys.get(row.get("source_template_id"))
        tables["document_template"] = template_rows
        document_template_ids = [template.id for template in document_templates]
        tables["document_template_revision"] = self._rows(
            db.scalars(select(DocumentTemplateRevision).where(DocumentTemplateRevision.template_id.in_(document_template_ids))).all() if document_template_ids else [],
            "document_template_revision",
        )
        assignment_rows = self._rows(
            db.scalars(select(DocumentTemplateAssignment).where(DocumentTemplateAssignment.tenant_id == tenant_id)).all(), "document_template_assignment"
        )
        for row in assignment_rows:
            row["system_key"] = system_keys.get(row.get("document_template_id"))
        tables["document_template_assignment"] = assignment_rows

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
        # Zentraler Bussentarif (0113_element_config_schema) - eine Zeile pro Mandant.
        tables["fine_tariff"] = self._rows(
            db.scalars(select(FineTariff).where(FineTariff.tenant_id == tenant_id)).all(), "fine_tariff"
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
        # Aufgabenpakete sind Konfiguration (wie Vorlagen). responsible_json enthält interne
        # Listen-/Personen-IDs, die der Import umschlüsselt.
        task_packages = db.scalars(select(TaskPackage).where(TaskPackage.tenant_id == tenant_id)).all()
        tables["task_package"] = self._rows(task_packages, "task_package")
        task_package_ids = [package.id for package in task_packages]
        tables["task_package_cycle"] = self._rows(
            db.scalars(select(TaskPackageCycle).where(TaskPackageCycle.task_package_id.in_(task_package_ids))).all()
            if task_package_ids
            else [],
            "task_package_cycle",
        )
        tables["task_package_item"] = self._rows(
            db.scalars(select(TaskPackageItem).where(TaskPackageItem.task_package_id.in_(task_package_ids))).all()
            if task_package_ids
            else [],
            "task_package_item",
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
            # Abgabebox-Links travel WITH their token: a restore must keep every link that was
            # handed out working. The import only issues a fresh token if this exact token is
            # already in use on the target (i.e. the source tenant still exists there).
            tables["submission_link"] = self._rows(
                db.scalars(select(SubmissionLink).where(SubmissionLink.tenant_id == tenant_id)).all(), "submission_link"
            )
            link_ids = [row["id"] for row in tables["submission_link"]]
            tables["submission_assignment_link"] = [
                {"assignment_id": assignment_id, "link_id": link_id}
                for assignment_id, link_id in (
                    db.execute(
                        select(submission_assignment_link_table).where(submission_assignment_link_table.c.link_id.in_(link_ids))
                    ).all()
                    if link_ids
                    else []
                )
            ]

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

        tables["gallery_image"] = self._rows(
            db.scalars(select(GalleryImage).where(GalleryImage.tenant_id == tenant_id)).all(), "gallery_image"
        )

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
        todo_ids = [row["id"] for row in tables["protocol_todo"]]
        tables["protocol_todo_assignee"] = self._rows(
            db.scalars(select(ProtocolTodoAssignee).where(ProtocolTodoAssignee.protocol_todo_id.in_(todo_ids))).all()
            if todo_ids
            else [],
            "protocol_todo_assignee",
        )
        tables["protocol_todo_file"] = self._rows(
            db.scalars(select(ProtocolTodoFile).where(ProtocolTodoFile.protocol_todo_id.in_(todo_ids))).all()
            if todo_ids
            else [],
            "protocol_todo_file",
        )
        # Anliegen (0153): Bezüge auf Vorlage/-punkt, Protokoll und -element über die ID-Maps des Imports.
        tables["agenda_item"] = self._rows(
            db.scalars(select(AgendaItem).where(AgendaItem.tenant_id == tenant_id)).all(), "agenda_item"
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
        # Cycle snapshots of the Listen feature (historical record, see
        # table_snapshot_service.py) - the import remaps the row copies inside snapshot_json.
        tables["table_snapshot"] = self._rows(
            db.scalars(select(TableSnapshot).where(TableSnapshot.tenant_id == tenant_id)).all(), "table_snapshot"
        )
        self._export_photo_albums(db, tenant_id, tables, include_abgabebox=include_abgabebox)
        # Export-Datensätze (Version, Inhalts-Hash) - die PDFs selbst reisen als stored_file mit.
        export_rows = self._rows(
            db.scalars(select(DocumentExport).where(DocumentExport.tenant_id == tenant_id)).all(), "document_export"
        )
        # Systemvorlagen sind installationsübergreifend nur über system_key auflösbar
        system_template_keys = {
            row.id: row.system_key
            for row in db.scalars(select(DocumentTemplate).where(DocumentTemplate.tenant_id.is_(None))).all()
        }
        for row in export_rows:
            row["system_key"] = system_template_keys.get(row.get("template_id"))
        tables["document_export"] = export_rows
        # Dokumentenregister: nach einem Umzug bleiben ausgelieferte PDFs prüfbar.
        tables["document_registry"] = self._rows(
            db.scalars(select(DocumentRegistry).where(DocumentRegistry.tenant_id == tenant_id)).all(), "document_registry"
        )

    def _export_photo_albums(self, db: Session, tenant_id: int, tables: dict[str, Any], *, include_abgabebox: bool) -> None:
        """Own albums (not the partner side of a shared album - photo_album_tenant_share and
        tenant_trust describe a relationship to another tenant, which a single-tenant export
        can't carry). Abgabe-bound albums only travel with the Abgabebox scope, because their
        submission_assignment isn't part of a plain "full" export. Items reference files by
        public_id (StoredFile or SubmissionUploadFile); only items whose file is itself part of
        this export are included - a partner tenant's photo in one of our shared albums stays
        behind."""
        albums = db.scalars(select(PhotoAlbum).where(PhotoAlbum.tenant_id == tenant_id)).all()
        if not include_abgabebox:
            albums = [album for album in albums if album.submission_assignment_id is None]
        tables["photo_album"] = self._rows(albums, "photo_album")
        exported_file_ids = {row["public_id"] for row in tables.get("stored_file", []) if row.get("public_id")}
        exported_file_ids |= {row["public_id"] for row in tables.get("submission_upload_file", []) if row.get("public_id")}
        album_ids = [album.id for album in albums]
        items = (
            db.scalars(select(PhotoAlbumItem).where(PhotoAlbumItem.album_id.in_(album_ids))).all() if album_ids else []
        )
        tables["photo_album_item"] = [
            row for row in self._rows(items, "photo_album_item") if row.get("file_id") in exported_file_ids
        ]

        # Album-Freigaben, both directions. A partner tenant is referenced by its public_id (the
        # only identity that survives a move to another installation) - the import restores the
        # relation only if that tenant exists on the target.
        # 1) partners invited into one of our own albums
        own_shares = (
            db.scalars(select(PhotoAlbumTenantShare).where(PhotoAlbumTenantShare.album_id.in_(album_ids))).all()
            if album_ids
            else []
        )
        # 2) albums of other tenants we were invited into (+ the photos we contributed there)
        received_shares = db.scalars(
            select(PhotoAlbumTenantShare)
            .join(PhotoAlbum, PhotoAlbum.id == PhotoAlbumTenantShare.album_id)
            .where(PhotoAlbumTenantShare.tenant_id == tenant_id, PhotoAlbum.tenant_id != tenant_id)
        ).all()
        share_rows = []
        for share, direction in [(s, "own_album") for s in own_shares] + [(s, "partner_album") for s in received_shares]:
            row = self._row(share, "photo_album_tenant_share")
            row["direction"] = direction
            if direction == "own_album":
                row["partner_tenant_public_id"] = self._tenant_public_id(db, share.tenant_id)
            else:
                row["partner_tenant_public_id"] = self._tenant_public_id(db, db.get(PhotoAlbum, share.album_id).tenant_id)
            row.pop("tenant_id", None)
            share_rows.append(row)
        tables["photo_album_tenant_share"] = share_rows
        received_album_ids = [share.album_id for share in received_shares]
        contributed = (
            db.scalars(select(PhotoAlbumItem).where(PhotoAlbumItem.album_id.in_(received_album_ids))).all()
            if received_album_ids
            else []
        )
        tables["partner_album_item"] = [
            row for row in self._rows(contributed, "photo_album_item") if row.get("file_id") in exported_file_ids
        ]

        # Öffentliche Freigabe-Links (Album live oder feste Dateiauswahl), mit Token - see
        # submission_link above for why. A link to an album that isn't part of this export
        # (Abgabe album in scope "full") would have nothing to show and is left out.
        exported_album_ids = {str(album_id) for album_id in album_ids}
        links = [
            link
            for link in db.scalars(select(ShareLink).where(ShareLink.tenant_id == tenant_id)).all()
            if link.album_id is None or str(link.album_id) in exported_album_ids
        ]
        tables["share_link"] = self._rows(links, "share_link")
        link_ids = [link.id for link in links]
        tables["share_link_file"] = [
            row
            for row in self._rows(
                db.scalars(select(ShareLinkFile).where(ShareLinkFile.share_link_id.in_(link_ids))).all() if link_ids else [],
                "share_link_file",
            )
            if row.get("file_id") in exported_file_ids
        ]

    # ── tenant-level settings / relations (every scope) ──────────────────

    def _tenant_public_id(self, db: Session, tenant_id: int) -> str | None:
        tenant = db.get(Tenant, tenant_id)
        return str(tenant.public_id) if tenant is not None else None

    def _admin_email(self, db: Session, admin_id: int | None) -> str | None:
        admin = db.get(PlatformAdmin, admin_id) if admin_id is not None else None
        return admin.email if admin is not None else None

    def _export_tenant_settings(self, db: Session, tenant_id: int, tables: dict[str, Any]) -> None:
        """Freigeschaltete Features und zugebuchte Speicherpakete - like plan_code on the tenant
        row itself, part of what the tenant is entitled to. The platform admin who granted them
        is exported by email (platform_admin ids are installation-specific)."""
        feature_rows = []
        for feature in db.scalars(select(TenantFeature).where(TenantFeature.tenant_id == tenant_id)).all():
            row = row_to_dict(feature)
            row["enabled_by_admin_id"] = self._admin_email(db, feature.enabled_by_admin_id)
            feature_rows.append(row)
        tables["tenant_feature"] = feature_rows
        package_rows = []
        for package in db.scalars(select(TenantStoragePackage).where(TenantStoragePackage.tenant_id == tenant_id)).all():
            row = row_to_dict(package)
            row["added_by_admin_id"] = self._admin_email(db, package.added_by_admin_id)
            package_rows.append(row)
        tables["tenant_storage_package"] = package_rows

    def _export_calendar_feeds(self, db: Session, tenant_id: int, tables: dict[str, Any]) -> None:
        """Kalender-Abos der Benutzer. The token is stored Fernet-encrypted with this
        installation's ADMIN_AUTH_SECRET (like the TOTP secrets above), so it's exported in
        plaintext and re-encrypted by the target - keeping every subscribed calendar URL valid."""
        feed_rows = []
        for feed in db.scalars(select(CalendarFeed).where(CalendarFeed.tenant_id == tenant_id)).all():
            row = self._row(feed, "calendar_feed")
            row["token"] = decrypt_secret(feed.token_encrypted)
            row.pop("token_encrypted", None)
            row.pop("token_hash", None)
            feed_rows.append(row)
        tables["calendar_feed"] = feed_rows

    def _export_tenant_trusts(self, db: Session, tenant_id: int, tables: dict[str, Any]) -> None:
        trusts = db.scalars(
            select(TenantTrust).where((TenantTrust.tenant_low_id == tenant_id) | (TenantTrust.tenant_high_id == tenant_id))
        ).all()
        tables["tenant_trust"] = [
            {
                "partner_tenant_public_id": self._tenant_public_id(
                    db, trust.tenant_high_id if trust.tenant_low_id == tenant_id else trust.tenant_low_id
                ),
                "created_at": json_safe(trust.created_at),
            }
            for trust in trusts
        ]


# Tabelle -> Spalten, die ein Login oder einen Link öffnen. Ohne include_credentials geleert.
_CREDENTIAL_COLUMNS: dict[str, tuple[str, ...]] = {
    "app_user": ("password_hash",),
    "calendar_feed": ("token",),
    "submission_link": ("token",),
    "share_link": ("token",),
}


def _strip_credentials(tables: dict[str, Any]) -> None:
    tables["user_mfa_factor"] = []
    for table, columns in _CREDENTIAL_COLUMNS.items():
        for row in tables.get(table) or []:
            for column in columns:
                if column in row:
                    row[column] = None
