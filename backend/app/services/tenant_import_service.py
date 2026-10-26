"""Imports a tenant from a .zip produced by TenantExportService.

Always walks the full table pipeline (clone_full's dependency order) regardless of which
scope the export used - tables absent from a lower-scope export are simply missing from
the manifest and default to an empty list, so e.g. participant_map/event_map naturally
stay empty for a "structure"-scope import and every table that depends on them degrades
exactly the way TenantCloneService.clone_structure's hand-written empty maps already do.

Returns the new Tenant plus a list of human-readable warnings (skipped rows) to show the
admin - a missing target user or a source file that had already gone missing before
export are recoverable situations, not reasons to fail the whole import.
"""

from __future__ import annotations

import hashlib
import contextlib
import json
import re
import secrets
import shutil
import tempfile
import uuid
import zipfile
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import inspect as sa_inspect
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app import scanner
from app.core.config import settings
from app.core.storage import MAIN, get_object_store, namespace_for_root, new_object_key
from app.core.secret_crypto import decrypt_secret, encrypt_secret
from app.core.security import hash_password
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
    Feature,
    Participant,
    Plan,
    PlatformAdmin,
    Protocol,
    ProtocolDisplaySnapshot,
    ProtocolElement,
    ProtocolElementBlock,
    ProtocolImage,
    ProtocolText,
    ProtocolTodo,
    StoragePackage,
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
    TenantRole,
    TenantRolePermission,
    TenantStoragePackage,
    UserMfaFactor,
    UserProtocolAccess,
    UserProtocolScroll,
    UserRole,
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
from app.services import (
    calendar_feed_service,
    domain_verification_service,
    role_service,
    share_link_service,
    submission_link_service,
    traefik_config_service,
)
from app.services.element_config import derive_fine_tariff, upgrade_snapshot_config, upgrade_template_element_config
from app.services.tenant_transfer_common import (
    LOOKUP_COLUMNS,
    REDACTED_PASSWORD_HASH_MARKER,
    USER_ID_COLUMNS,
    LookupCodeCache,
    UserIdentityCache,
    WordImportIdMaps,
    build_row,
    coerce_value,
    new_uuid7,
    remap_block_configuration,
    remap_element_definition_config,
    remap_occurrence_key,
    remap_list_value,
    remap_repeat_source_todo,
    remap_responsible_assignments,
    remap_table_snapshot_rows,
    remap_template_element_config,
    remap_word_import_analysis,
    remap_word_import_profile_config,
    remap_todos_snapshot,
    replace_public_ids,
)

SUPPORTED_FORMAT_VERSIONS = {2, 3, 4, 5, 6, 7, 8, 9}  # 9: Rollen je Mandant (RBAC); 8: Baustein-Bibliothek (ältere Archive: is_library = TRUE); 7: Document Studio; 6: Dokumentenregister; 5: Dokument-Engine (Hausstile statt Dokumentvorlagen)  # 2: separate user_tenant_role table; 3: role on app_user

# Zip-bomb guard, same idea as file_service.py's MAX_ZIP_ENTRIES/MAX_ZIP_TOTAL_BYTES for the
# word-import ZIP upload, just scaled up: a full-tenant export can legitimately contain many
# more files (every stored_file/protocol_image/abgabebox upload the tenant has) and be much
# larger than a single word-import ZIP, but it still needs a hard ceiling so a corrupted or
# malicious archive can't exhaust disk via extractall() (M19, 2026-08-12 audit - _safe_extract
# previously only guarded against zip-slip path traversal, not entry count/decompressed size).
MAX_IMPORT_ZIP_ENTRIES = 20_000
MAX_IMPORT_ZIP_TOTAL_BYTES = 2 * 1024 * 1024 * 1024  # 2 GB combined uncompressed size


class TenantImportService:
    def import_zip(self, db: Session, zip_path: Path, new_name: str) -> tuple[Tenant, list[str]]:
        with tempfile.TemporaryDirectory(prefix="hocx-import-") as extract_dir_str:
            extract_dir = Path(extract_dir_str)
            with zipfile.ZipFile(zip_path) as zf:
                _safe_extract(zf, extract_dir)

            manifest_path = extract_dir / "manifest.json"
            if not manifest_path.exists():
                raise ValueError("Kein manifest.json im Archiv gefunden - kein gültiges hocX-Export-Archiv.")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            return self.import_manifest(db, manifest, ExtractedDirSource(extract_dir), new_name)

    def import_manifest(self, db: Session, manifest: dict[str, Any], source: "ImportFileSource", new_name: str) -> tuple[Tenant, list[str]]:
        """Gemeinsamer Importpfad: ZIP-Upload (ExtractedDirSource) und Mandanten-Restore aus dem
        Backup (app/backup/tenant_recovery.py, Dateien direkt aus Borg ohne ZIP)."""
        if manifest.get("format_version") not in SUPPORTED_FORMAT_VERSIONS:
            raise ValueError(f"Nicht unterstützte Export-Version: {manifest.get('format_version')!r}")

        self.db = db
        self.source = source
        self.tables: dict[str, Any] = manifest.get("tables", {})
        self.format_version = manifest["format_version"]
        self._user_id_map: dict[int, int] = {}
        self.lookup_cache = LookupCodeCache(db)
        self.user_cache = UserIdentityCache(db)
        self.warnings: list[str] = []
        # SHA-256 der tatsächlich importierten PDF-Bytes (TYPST-007): nur dafür gilt ein
        # Register-Eintrag aus dem Archiv als belegt.
        self._imported_pdf_hashes: set[str] = set()
        self._created_tenant_id: int | None = None
        # old public_id (lowercase) -> newly assigned one, only for the rare rows whose
        # exported public_id is already taken on this installation (see _claim_uuid).
        self._public_id_map: dict[str, str] = {}
        self._taken_public_ids: dict[tuple[type, str], set[str]] = {}
        # Partner tenants a relation (trust, album share) was restored to - reported once.
        # Exported public_ids of the StoredFile/SubmissionUploadFile rows that actually
        # made it in (a file can be skipped: missing from the archive, or infected).
        self._imported_file_public_ids: set[str] = set()
        # New ids of protocol blocks whose repeat_source points at a todo - remapped in a
        # second pass once the todos exist (see _remap_todo_repeat_sources).
        self._todo_repeat_block_ids: list[int] = []

        try:
            new_tenant = self._run(new_name)
        except Exception as exc:
            # The pipeline below commits progressively (one table at a time, matching
            # TenantCloneService's style) rather than as one big transaction - a failure
            # partway through would otherwise leave a broken, half-imported tenant sitting
            # in the tenant list instead of a clean "import failed". Tear it down before the
            # error propagates - über delete_tenant inkl. Dateien und RESTRICT-Reihenfolge
            # (Audit MAIN-BE-006); die Originalexception bleibt erhalten.
            db.rollback()
            if self._created_tenant_id is not None:
                from app.services.admin_tenant_service import AdminTenantService

                AdminTenantService().cleanup_partial_tenant(db, self._created_tenant_id, original=exc)
                # Objekte unter tenant_imports/tenant-<id>/ (ohne Zeile, z. B. nach einem Fehler
                # zwischen Schreiben und Registrieren) zusätzlich entfernen.
                self._remove_imported_objects_for(db, self._created_tenant_id)
            raise
        return new_tenant, self.warnings

    @property
    def source(self) -> "ImportFileSource":
        """Dateiquelle des laufenden Imports. Kompatibilität: wer (wie ältere Aufrufer/Tests) nur
        extract_dir setzt, bekommt die ZIP-Quelle mit ihrer Pfadprüfung."""
        current = self.__dict__.get("_source")
        if current is None and self.__dict__.get("extract_dir") is not None:
            return ExtractedDirSource(self.__dict__["extract_dir"])
        if current is None:
            raise RuntimeError("Keine Dateiquelle für den Import gesetzt")
        return current

    @source.setter
    def source(self, value: "ImportFileSource") -> None:
        self.__dict__["_source"] = value

    @staticmethod
    def _remove_imported_objects_for(db: Session, tenant_id: int) -> None:
        from app.core.storage import delete_prefix

        for root in (settings.storage_root, settings.abgabebox_storage_root):
            try:
                delete_prefix(db, namespace_for_root(root), f"tenant_imports/tenant-{tenant_id}/")
                db.commit()
            except Exception as exc:  # noqa: BLE001 - Aufräumen best effort, Fehler sichtbar machen
                db.rollback()
                from app.core.error_log import record_system_error

                record_system_error(db, exc=exc)

    def _t(self, name: str) -> list[dict[str, Any]]:
        return self.tables.get(name, [])

    # ── public_id preservation ────────────────────────────────────────────

    def _build(self, model: type, data: dict[str, Any], overrides: dict[str, Any] | None = None) -> Any:
        """build_row() plus public_id handling: the exported public_id is reused whenever it
        is still free on this installation, so everything that references a row by public_id
        instead of by FK (element_ref strings, photo_album_item.file_id, table snapshots,
        word-import drafts, bookmarked URLs) keeps working after a restore. Only when it is
        already taken - typically re-importing an export while the source tenant still exists
        here - a fresh one is assigned and recorded in _public_id_map, which every
        public_id-based reference is rewritten through (replace_public_ids).

        Reusing a manifest-supplied value is safe: public_id is UNIQUE, a value already in use
        is never reused (so an archive can't hijack an existing row's identity), and access is
        always tenant-scoped on top of the public_id lookup."""
        row = build_row(model, data, overrides)
        old_public_id = data.get("public_id")
        if old_public_id is not None and "public_id" in sa_inspect(model).columns:
            row.public_id = self._claim_uuid(model, "public_id", str(old_public_id))
        return row

    def _claim_uuid(self, model: type, column: str, old_value: str) -> uuid.UUID:
        """Reuses `old_value` for `model.<column>` (a UNIQUE uuid column: public_id, or the
        uuid primary key of photo_album/share_link) if it's still free, otherwise assigns a
        fresh one and records old -> new in _public_id_map. One map serves every column -
        uuids are globally unique, so nothing can get mixed up."""
        key = old_value.lower()
        taken = self._taken_public_ids.get((model, column))
        if taken is None:
            taken = self._load_taken_uuids(model, column)
        try:
            parsed = uuid.UUID(key)
        except ValueError:
            parsed = None
        if parsed is None or key in taken:
            new_value = new_uuid7()
            self._public_id_map[key] = str(new_value)
            return new_value
        # Also guards against the same value appearing twice inside one archive.
        taken.add(key)
        return parsed

    def _load_taken_uuids(self, model: type, column: str) -> set[str]:
        """One query per table (chunked) instead of one per row: which of the exported values
        of this column already exist on the installation."""
        rows = self.tables.get(model.__tablename__, [])
        rows = [rows] if isinstance(rows, dict) else rows
        candidates: list[uuid.UUID] = []
        for row in rows:
            try:
                candidates.append(uuid.UUID(str(row.get(column))))
            except ValueError:
                continue
        attribute = getattr(model, column)
        taken: set[str] = set()
        for start in range(0, len(candidates), 1000):
            chunk = candidates[start:start + 1000]
            taken.update(str(value) for value in self.db.scalars(select(attribute).where(attribute.in_(chunk))))
        self._taken_public_ids[(model, column)] = taken
        return taken

    def _claim_token(self, model: type, token: str | None, generate, label: str) -> str:
        """Link tokens ARE the credential and stay unique installation-wide. The exported token
        is kept, so every handed-out URL keeps working after a restore - unless it's already in
        use here: then the source tenant still exists on this installation, and sharing its
        credential would open the source's link for the imported tenant as well."""
        if token and submission_link_service.is_reserved_token(token):
            self.warnings.append(f"{label}: Token «{token}» ist reserviert - neuer Link erzeugt.")
            return generate()
        if token and self.db.scalar(select(model.id).where(model.token == token)) is None:
            return token
        if token:
            self.warnings.append(
                f"{label}: Token ist auf dieser Installation bereits vergeben - neuer Link erzeugt, die alte URL gilt weiter für den Quell-Mandanten."
            )
        return generate()

    def _lookup_tenant_by_public_id(self, public_id: str | None) -> Tenant | None:
        if not public_id:
            return None
        try:
            parsed = uuid.UUID(str(public_id))
        except ValueError:
            return None
        tenant = self.db.scalar(select(Tenant).where(Tenant.public_id == parsed))
        return tenant if tenant is not None and tenant.id != self._created_tenant_id else None

    def _admin_id_for(self, email: str | None) -> int | None:
        if not email:
            return None
        return self.db.scalar(select(PlatformAdmin.id).where(PlatformAdmin.email == email))

    def _remap_public_refs(self, value: Any) -> Any:
        return replace_public_ids(value, self._public_id_map)

    # ── generic helpers ───────────────────────────────────────────────────

    def _resolve_row(self, table_name: str, data: dict[str, Any]) -> dict[str, Any]:
        """Applies lookup-code and user-identity resolution in place, returns the (possibly mutated) dict."""
        data = dict(data)
        for column, model in LOOKUP_COLUMNS.get(table_name, {}).items():
            if data.get(column) is not None:
                data[column] = self.lookup_cache.id_for(model, data[column])
        for column in USER_ID_COLUMNS.get(table_name, []):
            if column in data:
                data[column] = self.user_cache.id_for(data[column])
        return data

    def _restore_file(self, member_path: str | None, *, root: str, new_tenant_id: int, subdir: str) -> str | None:
        if member_path is None:
            return None
        if not self.source.exists(member_path):
            return None
        # subdir kann Werte aus dem Manifest enthalten (part_type/code) - validate_key schliesst
        # Traversal-Segmente aus, der Key bleibt unter tenant_imports/tenant-<id>/.
        try:
            key = new_object_key("tenant_imports", f"tenant-{new_tenant_id}", *[p for p in subdir.split("/") if p], filename=member_path)
        except ValueError:
            return None
        if not self.source.store(self.db, namespace_for_root(root), key, member_path):
            return None
        return key

    def _warn_missing_user(self, table_name: str, email: str | None) -> None:
        if email is not None:
            self.warnings.append(f"{table_name}: Benutzer '{email}' existiert im importierten Mandanten nicht - Zeile übersprungen.")

    # ── pipeline ──────────────────────────────────────────────────────────

    def _run(self, new_name: str) -> Tenant:
        new_tenant = self._import_tenant_base(new_name)
        self._created_tenant_id = new_tenant.id
        # Restore-Aufträge merken sich den neuen Mandanten, um nach einem Absturz mitten im
        # Import aufräumen zu können (app/backup/run_restore.py).
        if (callback := getattr(self, "on_tenant_created", None)) is not None:
            callback(new_tenant.id)
        # From here on only the new tenant's own accounts can be referenced by email.
        self.user_cache.tenant_id = new_tenant.id
        self._import_roles(new_tenant.id)
        self._import_app_users(new_tenant.id)
        self._import_user_mfa_factors()
        self._import_tenant_domains(new_tenant.id)
        self._import_tenant_settings(new_tenant.id)
        self._import_calendar_feeds(new_tenant.id)
        self._import_tenant_trusts(new_tenant.id)
        group_map = self._import_simple(GroupEntity, self._t("group_entity"), "group_entity", {"tenant_id": new_tenant.id})
        self._import_simple(Leader, self._t("leader"), "leader", {"tenant_id": new_tenant.id})
        participant_map = self._import_participants(new_tenant.id)
        cycle_config_map = self._import_simple(CycleConfig, self._t("cycle_config"), "cycle_config", {"tenant_id": new_tenant.id})
        document_style_map = self._import_document_brands(new_tenant.id)
        event_map = self._import_events(new_tenant.id, group_map, participant_map)
        # Fuer im Editor gewaehlte (als public UUID gespeicherte) Referenzen in Block-Snapshots,
        # siehe remap_block_configuration. Exporte vor Format 2 haben keine public_id-Spalte.
        self._participant_public_ids = {str(row["public_id"]).lower(): row["id"] for row in self._t("app_user" if self.format_version >= 4 else "participant") if row.get("public_id")}
        self._event_public_ids = {str(row["public_id"]).lower(): row["id"] for row in self._t("event") if row.get("public_id")}
        self._import_event_cycles(event_map, cycle_config_map)
        list_definition_map = self._import_simple(ListDefinition, self._t("list_definition"), "list_definition", {"tenant_id": new_tenant.id})
        list_entry_map = self._import_list_entries(list_definition_map, participant_map, event_map)
        finance_account_map = self._import_simple(FinanceAccount, self._t("finance_account"), "finance_account", {"tenant_id": new_tenant.id})
        self._import_fine_tariff(new_tenant.id, finance_account_map)
        element_definition_map = self._import_element_definitions(
            new_tenant.id, participant_map=participant_map, event_map=event_map,
            list_definition_map=list_definition_map, list_entry_map=list_entry_map, finance_account_map=finance_account_map,
        )
        template_map, template_element_map, template_element_block_map = self._import_templates(
            new_tenant.id,
            cycle_config_map=cycle_config_map,
            element_definition_map=element_definition_map,
            event_map=event_map,
            participant_map=participant_map,
            list_definition_map=list_definition_map,
            list_entry_map=list_entry_map,
            finance_account_map=finance_account_map,
        )
        self._import_word_import_profiles(
            new_tenant.id, template_map,
            WordImportIdMaps(
                participant_map=participant_map, event_map=event_map, list_definition_map=list_definition_map,
                list_entry_map=list_entry_map, template_element_map=template_element_map,
            ),
        )
        self._restore_last_word_import_template(new_tenant, template_map)
        self._import_template_participants(template_map, participant_map)
        submission_assignment_map = self._import_submission_assignments(new_tenant.id, list_definition_map, cycle_config_map)
        self._import_submission_links(new_tenant.id, submission_assignment_map)
        submission_upload_map = self._import_submission_uploads(submission_assignment_map, event_map, list_entry_map)
        self._import_submission_upload_logs(submission_assignment_map)
        stored_file_map = self._import_stored_files(new_tenant.id)
        self._import_submission_upload_files(submission_upload_map, stored_file_map)
        self._import_gallery_images(
            new_tenant.id, stored_file_map, event_map,
            cycle_config_map=cycle_config_map, submission_assignment_map=submission_assignment_map,
        )
        protocol_map = self._import_protocols(new_tenant.id, template_map, event_map)
        self._import_word_import_documents(
            new_tenant.id, template_map, stored_file_map, protocol_map,
            WordImportIdMaps(
                participant_map=participant_map, event_map=event_map, list_definition_map=list_definition_map,
                list_entry_map=list_entry_map, template_element_map=template_element_map, protocol_map=protocol_map,
            ),
        )
        self._import_word_import_suggestion_outcomes(new_tenant.id, template_map)
        protocol_element_map = self._import_protocol_elements(
            protocol_map, template_element_map,
            participant_map=participant_map, list_definition_map=list_definition_map, list_entry_map=list_entry_map,
        )
        protocol_element_block_map = self._import_protocol_element_blocks(
            protocol_element_map, template_element_block_map, element_definition_map, participant_map,
            event_map=event_map, list_definition_map=list_definition_map, list_entry_map=list_entry_map,
            finance_account_map=finance_account_map,
        )
        self._import_protocol_texts(protocol_element_block_map)
        self._import_protocol_display_snapshots(protocol_element_block_map)
        self._import_protocol_images(protocol_element_block_map, stored_file_map)
        document_template_maps = self._import_document_templates(new_tenant.id, template_map, document_style_map)
        self._import_document_exports(new_tenant.id, protocol_map, stored_file_map, document_template_maps, document_style_map)
        finance_transaction_map = self._import_finance_transactions(finance_account_map, protocol_map)
        self._import_attendance_fines(protocol_map, participant_map, finance_account_map, finance_transaction_map)
        task_package_item_map = self._import_task_packages(
            new_tenant.id, cycle_config_map=cycle_config_map, participant_map=participant_map,
            list_definition_map=list_definition_map, list_entry_map=list_entry_map,
        )
        todo_map = self._import_protocol_todos(
            new_tenant.id, protocol_element_block_map, participant_map, event_map, protocol_map, submission_assignment_map,
            task_package_item_map=task_package_item_map, cycle_config_map=cycle_config_map,
        )
        self._import_protocol_todo_assignees(todo_map, participant_map)
        self._import_protocol_todo_files(todo_map, stored_file_map)
        self._remap_todo_repeat_sources(todo_map)
        self._restore_todo_snapshots(protocol_map, protocol_element_block_map)
        self._import_agenda_items(new_tenant.id, template_map, template_element_map, protocol_map, protocol_element_map)
        album_map = self._import_photo_albums(new_tenant.id, cycle_config_map, submission_assignment_map)
        self._import_album_shares(new_tenant.id, album_map)
        self._import_share_links(new_tenant.id, album_map)
        self._import_table_snapshots(
            new_tenant.id, cycle_config_map,
            list_definition_map=list_definition_map, list_entry_map=list_entry_map,
            participant_map=participant_map, event_map=event_map,
        )
        self._import_user_template_access(new_tenant.id, template_map)
        self._import_user_protocol_access(new_tenant.id, protocol_map)
        self._import_user_protocol_scrolls(protocol_map)
        return new_tenant

    def _restore_todo_snapshots(self, protocol_map: dict[int, int], protocol_element_block_map: dict[int, int]) -> None:
        """Eingefrorene Todo-Liste abgeschlossener Protokolle übernehmen (Audit MAIN-BE-012) -
        Block-Keys über die Block-Map, public_ids über _public_id_map."""
        changed = False
        for row in self._t("protocol"):
            snapshot = row.get("todos_snapshot_json")
            new_protocol_id = protocol_map.get(row["id"])
            if not isinstance(snapshot, dict) or new_protocol_id is None:
                continue
            protocol = self.db.get(Protocol, new_protocol_id)
            if protocol is None:
                continue
            protocol.todos_snapshot_json = remap_todos_snapshot(snapshot, protocol_element_block_map, self._public_id_map)
            changed = True
        if changed:
            self.db.commit()

    # ── tenant base ───────────────────────────────────────────────────────

    def _import_tenant_base(self, new_name: str) -> Tenant:
        data = self._resolve_row("tenant", self.tables["tenant"])
        # last_word_import_template_id is dropped here and reassigned in _run() once
        # template_map exists (see below) - it's a source-tenant template id, which means
        # nothing in the freshly assigned target id space and, worse, is an FK the DB
        # enforces: committing it unchanged would either crash the whole import outright
        # (no template with that id exists yet on the target) or, on a coincidental id
        # collision, silently point at a template belonging to a completely different
        # tenant.
        overrides: dict[str, Any] = {
            "name": new_name, "profile_image_path": None, "public_slug": None, "last_word_import_template_id": None,
        }
        # plan.code is installation-wide seed data maintained in the admin panel - a plan
        # the source had doesn't necessarily exist here (FK would abort the whole import).
        if data.get("plan_code") and self.db.get(Plan, data["plan_code"]) is None:
            self.warnings.append(f"Preisplan '{data['plan_code']}' existiert auf dieser Installation nicht - Mandant ohne Plan importiert.")
            overrides["plan_code"] = None
        new_tenant = self._build(Tenant, data, overrides)
        self.db.add(new_tenant)
        self.db.commit()
        self.db.refresh(new_tenant)
        image_path = self._restore_file(data.get("profile_image_path"), root=settings.storage_root, new_tenant_id=new_tenant.id, subdir="profile")
        if image_path is not None:
            new_tenant.profile_image_path = image_path
            self.db.add(new_tenant)
            self.db.commit()
            self.db.refresh(new_tenant)
        return new_tenant

    def _restore_last_word_import_template(self, new_tenant: Tenant, template_map: dict[int, int]) -> None:
        old_template_id = self.tables.get("tenant", {}).get("last_word_import_template_id")
        if old_template_id is None:
            return
        new_template_id = template_map.get(old_template_id)
        if new_template_id is None:
            return
        new_tenant.last_word_import_template_id = new_template_id
        self.db.add(new_tenant)
        self.db.commit()

    def _legacy_role_codes_by_email(self) -> dict[str, str] | None:
        """format_version 2 kept roles in a separate user_tenant_role table (export scoped to
        the exported tenant, user_id already an email, role_id already a code). None for
        format_version 3+, where app_user rows carry their role themselves."""
        if "user_tenant_role" not in self.tables:
            return None
        return {row["user_id"]: row["role_id"] for row in self._t("user_tenant_role") if row.get("user_id")}

    def _import_roles(self, new_tenant_id: int) -> None:
        """Format 9+: Rollen des Mandanten. Die Standardrollen legt der Trigger beim Anlegen des
        Mandanten an - übernommen werden Name, Beschreibung und Berechtigungen (admin bleibt fest),
        eigene Rollen werden neu angelegt. Unbekannte Berechtigungen (neuere Installation) fallen
        weg. Ältere Formate: nur Standardrollen, siehe _roles_for_user."""
        from app.core.permissions import ADMIN_ROLE_KEY, P

        self._role_map: dict[int, int] = {}
        known = {permission.value for permission in P}
        used_names: set[str] = set()
        for row in self._t("tenant_role"):
            system_key = row.get("system_key")
            if system_key:
                role = role_service.system_role(self.db, new_tenant_id, system_key)
            else:
                role = TenantRole(tenant_id=new_tenant_id)
            if system_key != ADMIN_ROLE_KEY:
                name = (row.get("name") or "").strip() or None
                if name is None and not system_key:
                    name = "Rolle"
                if name is not None:
                    base, counter = name, 2
                    while name.lower() in used_names:
                        name, counter = f"{base} ({counter})", counter + 1
                    used_names.add(name.lower())
                role.name = name
                role.description = row.get("description")
                self.db.add(role)
                self.db.flush()
                self.db.execute(delete(TenantRolePermission).where(TenantRolePermission.role_id == role.id))
                for key in sorted({key for key in row.get("permissions") or [] if key in known}):
                    self.db.add(TenantRolePermission(role_id=role.id, permission_key=key))
            self.db.flush()
            self._role_map[row["id"]] = role.id
        self.db.commit()

    def _roles_for_user(self, row: dict[str, Any], tenant_id: int, legacy_code: str | None) -> list[int]:
        """Interne tenant_role-IDs für ein importiertes Konto: Format 9+ über role_refs, ältere
        Formate über den Rollencode (Standardrolle; unbekannt -> reader mit Warnung)."""
        if self.format_version >= 9:
            mapped = [self._role_map[ref] for ref in row.get("role_refs") or [] if ref in self._role_map]
            if mapped:
                return mapped
            return [role_service.system_role(self.db, tenant_id, "reader").id]
        code = legacy_code or "reader"
        try:
            return [role_service.system_role(self.db, tenant_id, code).id]
        except RuntimeError:
            self.warnings.append(f"Benutzer '{row.get('email')}': Rolle {code!r} unbekannt - als 'reader' importiert.")
            return [role_service.system_role(self.db, tenant_id, "reader").id]

    def _import_app_users(self, new_tenant_id: int) -> None:
        """Creates a login-capable account (password_hash included) in the new tenant for every
        exported user, so the tenant's members can log in on the target immediately and every
        USER_ID_COLUMNS reference below resolves.

        A user belongs to exactly one tenant, so an email that already has an account on this
        installation can NOT be linked to the new tenant: that account lives in another tenant.
        It is left completely untouched (password included), reported as a warning, and every
        reference to it resolves to nobody (UserIdentityCache.tenant_id is the new tenant)."""
        legacy_roles = self._legacy_role_codes_by_email()
        for row in self._t("app_user"):
            email = row.get("email")
            login_enabled = row.get("login_enabled", (row.get("external_identity_json") or {}).get("login_enabled", True))
            if login_enabled and self.user_cache.email_exists(email):
                self.warnings.append(
                    f"Benutzer '{email}' existiert auf dieser Installation bereits in einem anderen Mandanten - "
                    "nicht übernommen, Verknüpfungen entfallen."
                )
                continue
            if legacy_roles is not None and email not in legacy_roles:
                # Legacy export: an account that was only referenced as metadata (e.g. created_by),
                # not a member of the exported tenant. There is no tenant to put it in.
                continue
            role_code = legacy_roles[email] if legacy_roles is not None else row.get("role_id")
            role_ids = self._roles_for_user(row, new_tenant_id, role_code)
            overrides: dict[str, Any] = {"tenant_id": new_tenant_id, "login_enabled": login_enabled}
            if login_enabled and email:
                overrides["email"] = email.strip().lower()
            if not login_enabled:
                overrides["password_hash"] = None
            overrides["external_identity_json"] = {
                k: v for k, v in (row.get("external_identity_json") or {}).items()
                if k not in {"participant_email", "login_enabled", "merged_user_ids"}
                and not (k == "source" and v == "participant_auto")
            }
            if login_enabled and (row.get("password_hash") == REDACTED_PASSWORD_HASH_MARKER or not row.get("password_hash")):
                # Defensive: a (legacy) row without a real password hash still needs a
                # NOT NULL, properly-hashed password - a random one, so the account can't be
                # logged into until a tenant admin sets a real password (UserUpdate.password).
                overrides["password_hash"] = hash_password(secrets.token_urlsafe(32))
            # DECISION (audit finding, evaluated deliberately - not left unnoticed): if this row
            # is a real member of the exported tenant, `overrides` above does NOT touch
            # password_hash, so build_row copies the source's real bcrypt hash unchanged onto the
            # new account on this installation. That is intentional for a genuine tenant move
            # (operator exports a tenant off one installation and imports it on another): the
            # member keeps the password they already know and can log in immediately, exactly
            # like restoring a backup would. A forced reset here would actively hurt that
            # legitimate case for no clear security gain - the hash isn't being exposed to a new
            # party, it just now exists on two installations that the same tenant owns/operates.
            # A deeper mitigation (e.g. a `must_change_password` flag forcing a reset on next
            # login) was considered and rejected as out of scope for this pass: it needs a new
            # nullable-then-backfilled column, an Alembic migration, and a frontend gate on first
            # login after import - real work, and overkill for a Mittel-severity finding whose
            # actual exposure (same secret duplicated across installations the same operator
            # controls) is much smaller than a credential leaked to an outside party. If a
            # password-change-while-logged-in endpoint lands (see user_service.py), an operator
            # can already tell freshly imported members to rotate their password by convention
            # without any code change here.
            new_user = self._build(AppUser, row, overrides)
            self.db.add(new_user)
            self.db.flush()
            for role_id in dict.fromkeys(role_ids):
                self.db.add(UserRole(tenant_id=new_tenant_id, user_id=new_user.id, role_id=role_id))
            self.db.flush()
            self._user_id_map[row["id"]] = new_user.id
            self.user_cache.set_id(str(row.get("public_id")), new_user.id)
            if self.format_version < 4:
                self.user_cache.set_id(email, new_user.id)
        self.db.commit()

    def _import_participants(self, tenant_id: int) -> dict[int, int]:
        if self.format_version >= 4:
            return dict(self._user_id_map)
        # Alte Archive enthielten Stammdaten und Zugang als getrennte Zeilen.
        id_map: dict[int, int] = {}
        for row in self._t("participant"):
            user_id = self.user_cache.id_for(row.get("app_user_id"))
            user = self.db.get(AppUser, user_id) if user_id is not None else None
            if user is None:
                user = self._build(AppUser, row, {"tenant_id": tenant_id, "login_enabled": False, "password_hash": None})
                self.db.add(user)
                self.db.flush()
                role_service.assign_default_role(self.db, user)
            else:
                for field in ("first_name", "last_name", "display_name", "email", "is_active", "joined_at", "left_at"):
                    if field in row:
                        setattr(user, field, coerce_value(AppUser.__table__.c[field], row[field]))
                if row.get("public_id"):
                    self._public_id_map[str(row["public_id"])] = str(user.public_id)
            self.db.flush()
            id_map[row["id"]] = user.id
        self.db.commit()
        return id_map

    def _import_user_mfa_factors(self) -> None:
        """Restore member MFA configuration, merging safely into existing target users."""
        exported_users = {str(row.get("public_id")) if self.format_version >= 4 else row.get("email"): row for row in self._t("app_user")}
        imported_factor_types: dict[int, set[str]] = {}

        for row in self._t("user_mfa_factor"):
            email = row.get("user_id")
            user_id = self.user_cache.id_for(email)
            if user_id is None:
                self._warn_missing_user("user_mfa_factor", email)
                continue

            factor_type = row.get("factor_type")
            existing = self.db.query(UserMfaFactor).filter(UserMfaFactor.user_id == user_id).all()
            if factor_type == "totp":
                secret = row.get("totp_secret")
                if not secret:
                    self.warnings.append(f"MFA von '{email}': TOTP-Secret fehlt - Faktor übersprungen.")
                    continue
                if any(f.factor_type == "totp" and f.secret_encrypted and decrypt_secret(f.secret_encrypted) == secret for f in existing):
                    imported_factor_types.setdefault(user_id, set()).add("totp")
                    continue
                overrides = {"user_id": user_id, "secret_encrypted": encrypt_secret(secret)}
            elif factor_type == "webauthn":
                credential_id = row.get("webauthn_credential_id")
                collision = self.db.query(UserMfaFactor).filter(
                    UserMfaFactor.webauthn_credential_id == credential_id
                ).first()
                if collision is not None:
                    if collision.user_id == user_id:
                        imported_factor_types.setdefault(user_id, set()).add("webauthn")
                    else:
                        self.warnings.append(
                            f"MFA von '{email}': Passkey-Credential ist bereits einem anderen Benutzer zugeordnet - Faktor übersprungen."
                        )
                    continue
                overrides = {"user_id": user_id, "secret_encrypted": None}
            else:
                self.warnings.append(f"MFA von '{email}': Unbekannter Faktor-Typ '{factor_type}' - Faktor übersprungen.")
                continue

            self.db.add(self._build(UserMfaFactor, row, overrides))
            imported_factor_types.setdefault(user_id, set()).add(factor_type)

        self.db.flush()
        for email, user_row in exported_users.items():
            user_id = self.user_cache.id_for(email)
            preferred = user_row.get("preferred_mfa_factor_type")
            if user_id is None or preferred not in imported_factor_types.get(user_id, set()):
                continue
            user = self.db.get(AppUser, user_id)
            if user is not None:
                user.preferred_mfa_factor_type = preferred
                self.db.add(user)
        self.db.commit()

    def _import_tenant_domains(self, new_tenant_id: int) -> None:
        """Restores verified custom domains with their original verification_token/status/
        verified_at unchanged - a tenant import reconstructs the source tenant 1:1, and a
        domain already verified on the source (its DNS TXT record already holds this exact
        token) should stay verified on the target rather than forcing the admin through
        domain verification again. `domain` is globally unique across the whole
        installation among active domains (uq_tenant_domain_active_domain, Migration 0129), so a domain already active - by hocX
        itself (settings.traefik_domain/traefik_abgabebox_domain) or by any tenant already
        on this installation, e.g. re-importing an export while the source tenant still
        exists here - is skipped with a warning rather than failing the whole import.
        Mirrors TenantService.create_domain's reserved-domain check and its
        traefik_config_service.regenerate() call after any active domain changes."""
        reserved = {d for d in (settings.traefik_domain, settings.traefik_abgabebox_domain) if d}
        needs_traefik_regenerate = False
        for row in self._t("tenant_domain"):
            data = self._resolve_row("tenant_domain", row)
            domain = data.get("domain")
            if not domain or not domain_verification_service.is_valid_domain_format(domain):
                self.warnings.append(f"Domain '{domain}' hat ein ungültiges Format und wurde nicht importiert.")
                continue
            if domain in reserved:
                self.warnings.append(f"Domain '{domain}' ist durch die Installation selbst belegt, wurde nicht importiert.")
                continue
            if self.db.query(TenantDomain).filter(TenantDomain.domain == domain, TenantDomain.status == "active").first() is not None:
                self.warnings.append(f"Domain '{domain}' ist auf dieser Installation bereits vergeben, wurde nicht importiert.")
                continue
            new_row = self._build(TenantDomain, data, {"tenant_id": new_tenant_id})
            self.db.add(new_row)
            if data.get("status") == "active":
                needs_traefik_regenerate = True
        self.db.commit()
        if needs_traefik_regenerate:
            traefik_config_service.regenerate(self.db)

    # ── generic single-tenant-scoped table import ────────────────────────

    def _import_simple(self, model: type, rows: list[dict[str, Any]], table_name: str, overrides: dict[str, Any]) -> dict[int, int]:
        id_map: dict[int, int] = {}
        for row in rows:
            data = self._resolve_row(table_name, row)
            new_row = self._build(model, data, overrides)
            self.db.add(new_row)
            self.db.flush()
            id_map[row["id"]] = new_row.id
        self.db.commit()
        return id_map

    # ── structure tables with extra remapping ────────────────────────────

    def _import_element_definitions(
        self, new_tenant_id: int, *, participant_map, event_map, list_definition_map, list_entry_map, finance_account_map,
    ) -> dict[int, int]:
        id_map: dict[int, int] = {}
        for row in self._t("element_definition"):
            data = self._resolve_row("element_definition", row)
            new_row = self._build(ElementDefinition, data, {
                "tenant_id": new_tenant_id,
                "configuration_json": remap_element_definition_config(
                    data.get("configuration_json"), participant_map=participant_map, event_map=event_map,
                    list_definition_map=list_definition_map, list_entry_map=list_entry_map,
                    finance_account_map=finance_account_map,
                ),
            })
            self.db.add(new_row)
            self.db.flush()
            id_map[row["id"]] = new_row.id
        self.db.commit()
        return id_map

    def _restore_asset(self, new_tenant_id: int, data: dict[str, Any], *, kind: str, category: str) -> DocumentAsset | None:
        path = self._restore_file(data.get("storage_path"), root=settings.storage_root, new_tenant_id=new_tenant_id, subdir="document_assets")
        if path is None:
            self.warnings.append(f"Dokument-Asset '{data.get('name')}': Datei fehlte im Export, übersprungen.")
            return None
        asset = self._build(DocumentAsset, {**data, "kind": kind, "category": category}, {"tenant_id": new_tenant_id, "storage_path": path})
        self.db.add(asset)
        self.db.flush()
        return asset

    def _import_document_brands(self, new_tenant_id: int) -> dict[str, int]:
        """Assets und Brand-Profile (Document Studio). Ältere Archive: Hausstile (Format 5/6)
        und TeX-basierte Dokumentvorlagen (Format ≤ 4) werden wie in Migration 0118 bzw. 0115
        in Brand-Profile übersetzt (app.documents.legacy).
        Rückgabe: "brand:<alte id>", "revision:<alte id>", "style:<alte id>",
        "template:<alte document_template-id>" → neue ID."""
        from app.documents import assets as asset_service
        from app.documents import brand_service
        from app.documents.legacy import brand_tokens_from_legacy, brand_tokens_from_style, has_custom_slots, legacy_part_refs

        id_map: dict[str, int] = {}
        default_brand: int | None = None
        for row in self._t("document_asset"):
            data = self._resolve_row("document_asset", row)
            self._restore_asset(new_tenant_id, data, kind=data.get("kind") or "image", category=data.get("category") or ("font" if data.get("kind") == "font" else "image"))
        for row in self._t("document_brand"):
            data = self._resolve_row("document_brand", row)
            brand = self._build(DocumentBrand, data, {"tenant_id": new_tenant_id, "is_default": False})
            self.db.add(brand)
            self.db.flush()
            id_map[f"brand:{row['id']}"] = brand.id
            if row.get("is_default"):
                default_brand = brand.id
        for row in self._t("document_brand_revision"):
            data = self._resolve_row("document_brand_revision", row)
            brand_id = id_map.get(f"brand:{data.get('brand_id')}")
            if brand_id is None:
                continue
            revision = self._build(DocumentBrandRevision, data, {"brand_id": brand_id, "tokens_json": self._checked_brand_tokens(new_tenant_id, data)})
            self.db.add(revision)
            self.db.flush()
            id_map[f"revision:{row['id']}"] = revision.id

        # Format 5/6: Hausstile und ihre Assets
        for row in self._t("document_style_asset"):
            data = self._resolve_row("document_style_asset", row)
            self._restore_asset(new_tenant_id, data, kind=data.get("kind") or "image", category="font" if data.get("kind") == "font" else "image")
        for row in self._t("document_style"):
            data = self._resolve_row("document_style", row)
            tokens = brand_tokens_from_style(data.get("style_key"), self._remap_public_refs(data.get("tokens_json") or {}))
            brand = brand_service.create_brand(self.db, new_tenant_id, name=data.get("name") or "Brand", tokens=self._valid_brand_tokens(new_tenant_id, tokens))
            id_map[f"style:{row['id']}"] = brand.id
            if row.get("is_default") and default_brand is None:
                default_brand = brand.id

        # Format ≤ 4: TeX-Dokumentvorlagen übersetzen, Bild-/Schrift-Parts übernehmen
        parts = {row["id"]: row for row in self._t("document_template_part")}
        restored: dict[tuple[int, str], DocumentAsset] = {}
        lost_slots = False
        for row in self._t("document_template") if self.format_version <= 4 else []:
            config = row.get("configuration_json") or {}
            lost_slots = lost_slots or has_custom_slots(config)
            role_ids: dict[str, str] = {}
            for role, part_id in legacy_part_refs(config).items():
                part = parts.get(part_id)
                kind = "font" if role.startswith("font_") else "image"
                if part is None:
                    continue
                key = (part_id, kind)
                if key not in restored:
                    path = self._restore_file(part.get("storage_path"), root=settings.storage_root, new_tenant_id=new_tenant_id, subdir="document_assets")
                    if path is None:
                        continue
                    content = get_object_store().get_bytes(MAIN, path)
                    family = None
                    if kind == "font":
                        try:
                            family = asset_service.font_family_of(content)
                        except Exception:  # noqa: BLE001 - unlesbare Schrift: Brand nutzt Hausschrift
                            family = None
                    asset = DocumentAsset(tenant_id=new_tenant_id, kind=kind, category="font" if kind == "font" else ("logo" if role == "logo" else "image"), name=part.get("name") or kind, original_name=Path(path).name, storage_path=path, file_size_bytes=len(content), font_family=family)
                    self.db.add(asset)
                    self.db.flush()
                    restored[key] = asset
                role_ids[role] = str(restored[key].public_id)
            tokens = brand_tokens_from_legacy(config, role_ids)
            brand = brand_service.create_brand(self.db, new_tenant_id, name=row.get("name") or "Brand", tokens=self._valid_brand_tokens(new_tenant_id, tokens))
            id_map[f"template:{row['id']}"] = brand.id
            if row.get("is_default") and default_brand is None:
                default_brand = brand.id
        if lost_slots:
            self.warnings.append("Eigener Vorlagen-Code (TeX) wird nicht mehr unterstützt und wurde nicht übernommen; Farben, Schrift, Varianten, Logo und Fussbild sind als Brand-Profil importiert.")

        if default_brand is not None:
            brand_service._set_default(self.db, new_tenant_id, self.db.get(DocumentBrand, default_brand))
        self.db.flush()
        brand_service.ensure_default_brand(self.db, new_tenant_id)
        self.db.commit()
        return id_map

    def _checked_brand_tokens(self, new_tenant_id: int, data: dict[str, Any]) -> dict[str, Any]:
        """Tokens einer importierten Brand-Revision gegen das Schema prüfen (STUDIO-011). Ungültige
        Tokens werden durch Standardwerte ersetzt (wie beim Laden, brand_service.tokens_of) und
        gemeldet, statt erst Bibliothek und Export scheitern zu lassen."""
        from app.documents.brand import BrandTokens, parse_tokens

        raw = self._remap_public_refs(data.get("tokens_json") or {})
        try:
            tokens = parse_tokens(raw)
        except ValueError as exc:
            self.warnings.append(f"Brand-Revision {data.get('revision')} eines Brand-Profils war ungültig und wurde durch Standardwerte ersetzt: {exc}")
            tokens = BrandTokens()
        return self._valid_brand_tokens(new_tenant_id, tokens).model_dump(mode="json")

    def _valid_brand_tokens(self, new_tenant_id: int, tokens: Any) -> Any:
        """Asset-Referenzen, deren Datei fehlte, entfernen (sonst lehnt das Brand-Profil sie ab)."""
        from app.documents import assets as asset_service
        from app.documents.brand import BrandTokens

        found = asset_service.assets_by_ids(self.db, new_tenant_id, tokens.asset_ids())
        data = tokens.model_dump(mode="json")
        for key in ("logo", "logo_alt", "letterhead", "background", "watermark", "footer_image"):
            value = data["assets"].get(key)
            if value and uuid.UUID(value) not in found:
                data["assets"][key] = None
        data["assets"]["images"] = [item for item in data["assets"].get("images", []) if uuid.UUID(item["asset_id"]) in found]
        for role in ("body", "heading"):
            choice = data["typography"][role]
            choice["asset_ids"] = [value for value in choice.get("asset_ids", []) if uuid.UUID(value) in found]
            if not choice["asset_ids"] and not choice.get("builtin"):
                choice["builtin"] = "inter"
        return BrandTokens.model_validate(data)

    def _import_document_templates(self, new_tenant_id: int, template_map: dict[int, int], brand_map: dict[str, int]) -> dict[str, int]:
        """Komponenten, Mandantenvorlagen samt Revisionen und Zuweisungen (Format 7). Ältere
        Archive: Rezepte (Format 5/6) werden zu Mandantenvorlagen (app.documents.legacy), die
        Hausstil-Wahl einer Protokollvorlage zu einer Brand-Zuweisung.
        Rückgabe: "template:<alte id>", "revision:<alte id>", "recipe:<alte id>" → neue ID."""
        from app.documents.layout import TemplateContent, content_json, parse_content
        from app.documents.legacy import content_from_recipe
        from app.documents.hashing import json_hash
        from app.documents import template_service

        id_map: dict[str, int] = {}
        system = {row.system_key: row.id for row in self.db.scalars(select(DocumentTemplate).where(DocumentTemplate.tenant_id.is_(None))).all()}
        for row in self._t("document_component"):
            data = self._resolve_row("document_component", row)
            try:
                node = template_service.parse_component_node(self._remap_public_refs(data.get("node_json") or {})).model_dump(mode="json")
            except ValueError as exc:
                self.warnings.append(f"Komponente '{data.get('name')}' ist ungültig und wurde nicht übernommen: {exc}")
                continue
            self.db.add(self._build(DocumentComponent, data, {"tenant_id": new_tenant_id, "node_json": node}))
            self.db.flush()
        templates: dict[int, DocumentTemplate] = {}
        for row in self._t("document_template") if self.format_version >= 7 else []:
            data = self._resolve_row("document_template", row)
            new_row = self._build(DocumentTemplate, data, {
                "tenant_id": new_tenant_id,
                "system_key": None,
                "brand_id": brand_map.get(f"brand:{data['brand_id']}") if data.get("brand_id") else None,
                "source_template_id": system.get(row.get("source_system_key")) if row.get("source_system_key") else None,
                "source_revision_id": None,
                "published_revision_id": None,
                "origin": data.get("origin") if data.get("origin") in ("tenant", "copy") else "tenant",
                "is_platform_default": False,
            })
            self.db.add(new_row)
            self.db.flush()
            id_map[f"template:{row['id']}"] = new_row.id
            templates[row["id"]] = new_row
        for row in self._t("document_template_revision") if self.format_version >= 7 else []:
            data = self._resolve_row("document_template_revision", row)
            template = templates.get(data.get("template_id"))
            if template is None:
                continue
            try:
                if data.get("status") not in ("draft", "published", "superseded"):
                    raise ValueError(f"Status {data.get('status')!r}")
                checked = content_json(parse_content(self._remap_public_refs(data.get("content_json") or {})))
            except ValueError as exc:
                # Ungültige Revision weglassen (sonst 500/422 erst in Bibliothek und Export)
                self.warnings.append(f"Revision {data.get('revision_no')} der Dokumentvorlage '{template.name}' ist ungültig und wurde nicht übernommen: {exc}")
                continue
            new_revision = self._build(DocumentTemplateRevision, data, {
                "template_id": template.id,
                "content_json": checked,
                "brand_revision_id": brand_map.get(f"revision:{data['brand_revision_id']}") if data.get("brand_revision_id") else None,
            })
            self.db.add(new_revision)
            self.db.flush()
            id_map[f"revision:{row['id']}"] = new_revision.id
        for row in self._t("document_template") if self.format_version >= 7 else []:
            if row.get("published_revision_id") and f"revision:{row['published_revision_id']}" in id_map:
                templates[row["id"]].published_revision_id = id_map[f"revision:{row['published_revision_id']}"]
        for row in self._t("document_template_assignment"):
            data = self._resolve_row("document_template_assignment", row)
            document_template_id = id_map.get(f"template:{data.get('document_template_id')}") if data.get("document_template_id") else None
            if document_template_id is None and row.get("system_key"):
                document_template_id = system.get(row["system_key"])
            brand_id = brand_map.get(f"brand:{data['brand_id']}") if data.get("brand_id") else None
            protocol_template_id = template_map.get(data["protocol_template_id"]) if data.get("protocol_template_id") else None
            if (data.get("protocol_template_id") and protocol_template_id is None) or (document_template_id is None and brand_id is None):
                continue
            self.db.add(DocumentTemplateAssignment(tenant_id=new_tenant_id, document_type=data["document_type"], protocol_template_id=protocol_template_id, document_template_id=document_template_id, brand_id=brand_id))
        self.db.flush()

        # Format 5/6: Rezepte → veröffentlichte Mandantenvorlagen
        for row in self._t("document_recipe"):
            data = self._resolve_row("document_recipe", row)
            try:
                content = TemplateContent.model_validate(content_from_recipe(self._remap_public_refs(data.get("blocks_json") or []), data.get("options_json") or {}))
                document_type = data.get("document_type") or "custom"
                template, revision = template_service.create_template(self.db, new_tenant_id, name=data.get("name") or document_type, document_type=document_type if document_type in _document_types() else "custom", content=content)
            except ValueError as exc:
                self.warnings.append(f"Dokument-Rezept '{data.get('name')}' konnte nicht übernommen werden: {exc}")
                continue
            if data.get("style_id") and f"style:{data['style_id']}" in brand_map:
                template.brand_id = brand_map[f"style:{data['style_id']}"]
            revision.status = "published"
            template.published_revision_id = revision.id
            self.db.flush()
            id_map[f"recipe:{row['id']}"] = template.id
        # Format ≤ 6: Hausstil einer Protokollvorlage → Brand-Zuweisung für Protokolle
        for row in self._t("template") if self.format_version <= 6 else []:
            brand_id = brand_map.get(f"style:{row.get('document_style_id')}") if row.get("document_style_id") else brand_map.get(f"template:{row.get('document_template_id')}") if row.get("document_template_id") else None
            protocol_template_id = template_map.get(row["id"])
            if brand_id is None or protocol_template_id is None:
                continue
            brand = self.db.get(DocumentBrand, brand_id)
            if brand is not None and not brand.is_default:
                self.db.add(DocumentTemplateAssignment(tenant_id=new_tenant_id, document_type="protocol", protocol_template_id=protocol_template_id, brand_id=brand_id))
        self.db.commit()
        return id_map

    def _import_document_exports(self, new_tenant_id: int, protocol_map: dict[int, int], stored_file_map: dict[int, int], template_maps: dict[str, int], brand_map: dict[str, int]) -> None:
        """Export-Datensätze. Ältere Archive: protocol_export_cache (PDF) → document_export.
        Vorlagenbezug: Mandantenvorlagen über ihre neue ID, Systemvorlagen über ``system_key``
        (ab Format 7 mitexportiert; die Revision einer Systemvorlage ist installationsabhängig
        und bleibt leer). Brand-Revisionen über die beim Brand-Import entstandene Zuordnung."""
        system = {row.system_key: row.id for row in self.db.scalars(select(DocumentTemplate).where(DocumentTemplate.tenant_id.is_(None))).all()}
        for row in self._t("document_export"):
            data = self._resolve_row("document_export", row)
            if data.get("protocol_id") and protocol_map.get(data["protocol_id"]) is None:
                continue
            template_id = template_maps.get(f"template:{data['template_id']}") if data.get("template_id") else None
            if template_id is None and data.get("recipe_id"):
                template_id = template_maps.get(f"recipe:{data['recipe_id']}")
            if template_id is None and row.get("system_key"):
                template_id = system.get(row["system_key"])
            self.db.add(self._build(DocumentExport, data, {
                "tenant_id": new_tenant_id,
                "protocol_id": protocol_map.get(data["protocol_id"]) if data.get("protocol_id") else None,
                "template_id": template_id,
                "template_revision_id": template_maps.get(f"revision:{data['template_revision_id']}") if data.get("template_revision_id") else None,
                "brand_revision_id": brand_map.get(f"revision:{data['brand_revision_id']}") if data.get("brand_revision_id") else None,
                "stored_file_id": stored_file_map.get(data["stored_file_id"]) if data.get("stored_file_id") else None,
            }))
        for row in self._t("protocol_export_cache"):
            new_protocol_id = protocol_map.get(row.get("protocol_id"))
            if new_protocol_id is None or row.get("export_format") != "pdf":
                continue
            old_file_id = row.get("generated_file_id")
            self.db.add(DocumentExport(
                tenant_id=new_tenant_id,
                protocol_id=new_protocol_id,
                document_type="protocol",
                stored_file_id=stored_file_map.get(old_file_id) if old_file_id else None,
            ))
        self.db.commit()
        self._import_document_registry(new_tenant_id)

    def _import_document_registry(self, new_tenant_id: int) -> None:
        """Register-Einträge mit ihrer Dokument-ID (sie steht im PDF). Ein Hash gehört
        installationsweit genau einem Mandanten: liegt er hier schon vor (Archiv in dieselbe
        Installation zurückgespielt, während das Original noch existiert), behält das Original
        die Zuordnung und der Eintrag wird übersprungen."""
        rows = self._t("document_registry")
        if not rows:
            return
        hashes = [str(row.get("sha256") or "").lower() for row in rows]
        taken = set(self.db.scalars(select(DocumentRegistry.sha256).where(DocumentRegistry.sha256.in_(hashes))).all())
        skipped = 0
        unverified = 0
        for row in rows:
            data = self._resolve_row("document_registry", row)
            sha256 = str(data.get("sha256") or "").lower()
            if not re.fullmatch(r"[0-9a-f]{64}", sha256) or sha256 in taken:
                skipped += 1
                continue
            source = data.get("source_public_id")
            if source:
                source = self._public_id_map.get(str(source).lower(), str(source))
            # TYPST-007: Das Archiv ist nicht vertrauenswürdig. Ohne die PDF mit genau diesem Hash
            # im Archiv bleibt der Eintrag erhalten (Exporte werden nach Fristablauf gelöscht),
            # die Prüfseite kennzeichnet ihn aber als «importiert, nicht verifiziert».
            import_unverified = sha256 not in self._imported_pdf_hashes
            unverified += import_unverified
            self.db.add(self._build(DocumentRegistry, data, {
                "tenant_id": new_tenant_id, "sha256": sha256, "source_public_id": source, "import_unverified": import_unverified,
            }))
            taken.add(sha256)
        if skipped:
            self.warnings.append(
                f"Dokumentenregister: {skipped} Einträge übersprungen (Datei ist auf dieser Installation bereits einem Mandanten zugeordnet)."
            )
        if unverified:
            self.warnings.append(
                f"Dokumentenregister: {unverified} Einträge ohne zugehörige PDF im Archiv - auf der Prüfseite als «importiert, nicht verifiziert» gekennzeichnet."
            )
        self.db.commit()

    # ── full-scope tables ─────────────────────────────────────────────────

    def _import_events(self, new_tenant_id: int, group_map: dict[int, int], participant_map: dict[int, int]) -> dict[int, int]:
        id_map: dict[int, int] = {}

        def remap_ids(ids: list[int] | None) -> list[int] | None:
            if not ids:
                return ids
            # An id that can't be resolved is dropped, never kept: it would be a source-tenant
            # participant id, i.e. nobody (or somebody of another tenant) on this installation.
            return [participant_map[i] for i in ids if i in participant_map]

        for row in self._t("event"):
            data = self._resolve_row("event", row)
            new_row = self._build(Event, data, {
                "tenant_id": new_tenant_id,
                "group_id": group_map.get(data["group_id"]) if data.get("group_id") else None,
                "organizer_ids": remap_ids(data.get("organizer_ids")),
                "leadership_ids": remap_ids(data.get("leadership_ids")),
                "participant_ids": remap_ids(data.get("participant_ids")),
                "spezial1_ids": remap_ids(data.get("spezial1_ids")),
                "spezial2_ids": remap_ids(data.get("spezial2_ids")),
                "spezial3_ids": remap_ids(data.get("spezial3_ids")),
            })
            self.db.add(new_row)
            self.db.flush()
            id_map[row["id"]] = new_row.id
        self.db.commit()
        return id_map

    def _import_event_cycles(self, event_map: dict[int, int], cycle_config_map: dict[int, int]) -> None:
        for row in self._t("event_cycle"):
            new_event_id = event_map.get(row["event_id"])
            new_cycle_config_id = cycle_config_map.get(row["cycle_config_id"])
            if new_event_id is None or new_cycle_config_id is None:
                continue
            self.db.add(EventCycle(event_id=new_event_id, cycle_config_id=new_cycle_config_id, cycle_year=row["cycle_year"]))
        self.db.commit()

    def _import_list_entries(self, list_definition_map: dict[int, int], participant_map: dict[int, int], event_map: dict[int, int]) -> dict[int, int]:
        value_types_by_old_definition_id = {
            row["id"]: (row.get("column_one_value_type"), row.get("column_two_value_type")) for row in self._t("list_definition")
        }
        id_map: dict[int, int] = {}
        for row in self._t("list_entry"):
            new_definition_id = list_definition_map.get(row["list_definition_id"])
            if new_definition_id is None:
                continue
            col1_type, col2_type = value_types_by_old_definition_id.get(row["list_definition_id"], (None, None))
            new_row = self._build(ListEntry, row, {
                "list_definition_id": new_definition_id,
                "column_one_value_json": remap_list_value(col1_type, row.get("column_one_value_json"), participant_map, event_map),
                "column_two_value_json": remap_list_value(col2_type, row.get("column_two_value_json"), participant_map, event_map),
            })
            self.db.add(new_row)
            self.db.flush()
            id_map[row["id"]] = new_row.id
        self.db.commit()
        return id_map

    def _import_templates(
        self, new_tenant_id: int, *, cycle_config_map, element_definition_map,
        event_map, participant_map, list_definition_map, list_entry_map, finance_account_map,
    ) -> tuple[dict[int, int], dict[int, int], dict[int, int]]:
        template_map: dict[int, int] = {}
        for row in self._t("template"):
            data = self._resolve_row("template", row)
            new_row = self._build(Template, data, {
                "tenant_id": new_tenant_id,
                "next_event_id": event_map.get(data["next_event_id"]) if data.get("next_event_id") else None,
                "last_event_id": event_map.get(data["last_event_id"]) if data.get("last_event_id") else None,
                "cycle_config_id": cycle_config_map.get(data["cycle_config_id"]) if data.get("cycle_config_id") else None,
                # Eigener Bussentarif der Vorlage (0137); ältere Exporte kennen die Spalten nicht.
                "fine_account_id": finance_account_map.get(data["fine_account_id"]) if data.get("fine_account_id") else None,
            })
            self.db.add(new_row)
            self.db.flush()
            template_map[row["id"]] = new_row.id
        self.db.commit()

        template_element_map: dict[int, int] = {}
        for row in self._t("template_element"):
            new_template_id = template_map.get(row["template_id"])
            new_element_definition_id = element_definition_map.get(row["element_definition_id"])
            if new_template_id is None:
                continue
            if new_element_definition_id is None:
                # element_definition is always tenant-owned and exported with the template -
                # only a corrupted/hand-edited archive gets here. Never fall back to the
                # source id: that would link the element to another tenant's definition.
                self.warnings.append(f"Vorlagen-Element {row.get('id')}: Elementdefinition fehlt im Export, übersprungen.")
                continue
            new_row = self._build(TemplateElement, row, {
                "template_id": new_template_id,
                "element_definition_id": new_element_definition_id,
                # Exporte älterer Versionen können Altformate enthalten (element_config.py).
                "configuration_json": upgrade_template_element_config(remap_template_element_config(
                    row.get("configuration_json"), participant_map=participant_map,
                    list_definition_map=list_definition_map, list_entry_map=list_entry_map,
                )),
            })
            self.db.add(new_row)
            self.db.flush()
            template_element_map[row["id"]] = new_row.id
        self.db.commit()

        template_element_block_map: dict[int, int] = {}
        for row in self._t("template_element_block"):
            new_template_element_id = template_element_map.get(row["template_element_id"])
            new_element_definition_id = element_definition_map.get(row["element_definition_id"])
            if new_template_element_id is None or new_element_definition_id is None:
                continue
            new_row = self._build(TemplateElementBlock, row, {
                "template_element_id": new_template_element_id,
                "element_definition_id": new_element_definition_id,
                "configuration_override_json": remap_block_configuration(
                    row.get("configuration_override_json"), participant_map=participant_map,
                    event_map=event_map, list_definition_map=list_definition_map, list_entry_map=list_entry_map,
                    finance_account_map=finance_account_map,
                    participant_public_ids=self._participant_public_ids, event_public_ids=self._event_public_ids,
                ),
            })
            self.db.add(new_row)
            self.db.flush()
            template_element_block_map[row["id"]] = new_row.id
        self.db.commit()

        return template_map, template_element_map, template_element_block_map

    def _import_template_participants(self, template_map: dict[int, int], participant_map: dict[int, int]) -> None:
        for row in self._t("template_participant"):
            new_template_id = template_map.get(row["template_id"])
            new_participant_id = participant_map.get(row["participant_id"])
            if new_template_id is None or new_participant_id is None:
                continue
            self.db.add(TemplateParticipant(
                template_id=new_template_id, participant_id=new_participant_id,
                exclude_from_attendance=row.get("exclude_from_attendance", False),
            ))
        self.db.commit()

    def _import_word_import_profiles(self, new_tenant_id: int, template_map: dict[int, int], maps: WordImportIdMaps) -> None:
        for row in self._t("word_import_profile"):
            old_template_id = row.get("template_id")
            self.db.add(self._build(WordImportProfile, row, {
                "tenant_id": new_tenant_id,
                "template_id": template_map.get(old_template_id) if old_template_id else None,
                # Learned mappings point at participants/events/lists/template elements by id.
                "mapping_config_json": remap_word_import_profile_config(row.get("mapping_config_json"), maps),
            }))
        self.db.commit()

    def _import_submission_assignments(
        self, new_tenant_id: int, list_definition_map: dict[int, int], cycle_config_map: dict[int, int]
    ) -> dict[int, int]:
        id_map: dict[int, int] = {}
        for row in self._t("submission_assignment"):
            data = self._resolve_row("submission_assignment", row)
            overrides: dict[str, Any] = {
                "tenant_id": new_tenant_id,
                "list_definition_id": list_definition_map.get(data["list_definition_id"]) if data.get("list_definition_id") else None,
            }
            if data.get("cycle_config_id"):
                # Zyklus-Filter (Migration 0079): cycle_config_id and cycle_offsets belong together
                # (ck_submission_assignment_cycle_filter) - clear both if the cycle is missing.
                overrides["cycle_config_id"] = cycle_config_map.get(data["cycle_config_id"])
                if overrides["cycle_config_id"] is None:
                    overrides["cycle_offsets"] = []
                    self.warnings.append(f"Abgabe '{data.get('title')}': Zyklus fehlt im Export, Zyklus-Filter entfernt.")
            new_row = self._build(SubmissionAssignment, data, overrides)
            self.db.add(new_row)
            self.db.flush()
            id_map[row["id"]] = new_row.id
        self.db.commit()
        return id_map

    def _import_submission_uploads(self, submission_assignment_map: dict[int, int], event_map: dict[int, int], list_entry_map: dict[int, int]) -> dict[int, int]:
        id_map: dict[int, int] = {}
        for row in self._t("submission_upload"):
            new_assignment_id = submission_assignment_map.get(row["assignment_id"])
            if new_assignment_id is None:
                continue
            new_event_id = event_map.get(row["event_id"]) if row.get("event_id") else None
            new_list_entry_id = list_entry_map.get(row["list_entry_id"]) if row.get("list_entry_id") else None
            if row.get("event_id") and new_event_id is None:
                continue
            if row.get("list_entry_id") and new_list_entry_id is None:
                continue
            new_row = self._build(SubmissionUpload, row, {
                "assignment_id": new_assignment_id, "event_id": new_event_id, "list_entry_id": new_list_entry_id,
            })
            self.db.add(new_row)
            self.db.flush()
            id_map[row["id"]] = new_row.id
        self.db.commit()
        return id_map

    def _import_submission_upload_logs(self, submission_assignment_map: dict[int, int]) -> None:
        for row in self._t("submission_upload_log"):
            new_assignment_id = submission_assignment_map.get(row["assignment_id"])
            if new_assignment_id is None:
                continue
            self.db.add(self._build(SubmissionUploadLog, row, {
                "assignment_id": new_assignment_id,
                "element_ref": self._remap_public_refs(row.get("element_ref")),
            }))
        self.db.commit()

    def _import_stored_files(self, new_tenant_id: int) -> dict[int, int]:
        abgabebox_ids = {row["stored_file_id"] for row in self._t("submission_upload_file")}
        id_map: dict[int, int] = {}
        for row in self._t("stored_file"):
            data = self._resolve_row("stored_file", row)
            is_abgabebox = row["id"] in abgabebox_ids
            root = settings.abgabebox_storage_root if is_abgabebox else settings.storage_root
            member = data.get("storage_path")
            if member is None or not self.source.exists(member):
                self.warnings.append(f"Datei '{row.get('original_name')}' fehlte im Export, übersprungen.")
                continue
            # SECURITY (audit S4, 2026-08-16): never trust data["scan_status"] from the
            # manifest (self._build() forces it to "pending" regardless, see
            # FORCED_SECURE_DEFAULTS) - actually run the restored bytes past ClamAV here,
            # the same way a fresh upload does (file_service.py's save_word_import_document),
            # so an imported file goes through the real scan workflow instead of either
            # trusting an attacker-supplied verdict or sitting at "pending" forever with no
            # sweep ever reaching it (the periodic rescan sweeps are scoped to their own
            # storage-path prefixes, which tenant-import restores don't share).
            # Geprüft wird die entpackte Datei, bevor sie überhaupt im Objektspeicher landet.
            pdf_hash = None
            with self.source.local_file(member) as source:
                scan_status = scanner.scan_file(source, host=settings.clamav_host, port=settings.clamav_port)
                # TYPST-007: Hash der mitgelieferten PDF (genau die importierten Bytes); die lokale
                # Datei gibt es nur innerhalb dieses Blocks (Borg-Restore: temporäre Kopie).
                if source.suffix.lower() == ".pdf" or data.get("mime_type") == "application/pdf":
                    digest = hashlib.sha256()
                    with source.open("rb") as handle:
                        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                            digest.update(chunk)
                    pdf_hash = digest.hexdigest()
            if scan_status == "infected":
                self.warnings.append(f"Datei '{row.get('original_name')}' wurde von der Virenprüfung als infiziert erkannt und wurde nicht importiert.")
                continue
            new_storage_path = self._restore_file(data.get("storage_path"), root=root, new_tenant_id=new_tenant_id, subdir="files")
            if new_storage_path is None:
                self.warnings.append(f"Datei '{row.get('original_name')}' fehlte im Export, übersprungen.")
                continue
            # thumbnail_path NULL (Audit MAIN-BE-003): Thumbnails heissen "<id>.jpg" im global
            # geteilten thumbnail_root - der exportierte Name zeigt hier auf die Vorschau einer
            # beliebigen anderen Datei (oft eines anderen Mandanten). ensure_thumbnail erzeugt
            # die Vorschau beim ersten Abruf neu.
            if pdf_hash is not None:
                self._imported_pdf_hashes.add(pdf_hash)
            new_row = self._build(
                StoredFile,
                data,
                {"tenant_id": new_tenant_id, "storage_path": new_storage_path, "scan_status": scan_status, "thumbnail_path": None},
            )
            self.db.add(new_row)
            if row.get("public_id"):
                self._imported_file_public_ids.add(str(row["public_id"]).lower())
            self.db.flush()
            id_map[row["id"]] = new_row.id
        self.db.commit()
        return id_map

    def _import_submission_upload_files(self, submission_upload_map: dict[int, int], stored_file_map: dict[int, int]) -> None:
        for row in self._t("submission_upload_file"):
            new_upload_id = submission_upload_map.get(row["upload_id"])
            new_stored_file_id = stored_file_map.get(row["stored_file_id"])
            if new_upload_id is None or new_stored_file_id is None:
                continue
            self.db.add(self._build(SubmissionUploadFile, row, {"upload_id": new_upload_id, "stored_file_id": new_stored_file_id}))
            if row.get("public_id"):
                self._imported_file_public_ids.add(str(row["public_id"]).lower())
        self.db.commit()

    def _import_gallery_images(
        self,
        new_tenant_id: int,
        stored_file_map: dict[int, int],
        event_map: dict[int, int],
        *,
        cycle_config_map: dict[int, int],
        submission_assignment_map: dict[int, int],
    ) -> None:
        for row in self._t("gallery_image"):
            data = self._resolve_row("gallery_image", row)
            new_stored_file_id = stored_file_map.get(row["stored_file_id"])
            if new_stored_file_id is None:
                # The underlying file was itself skipped on import (missing from the export,
                # or flagged infected on re-scan - see _import_stored_files) - nothing left to
                # mark as a gallery image.
                continue
            self.db.add(self._build(GalleryImage, data, {
                "tenant_id": new_tenant_id,
                "stored_file_id": new_stored_file_id,
                # Live Photo clip: a stored_file of the same tenant, so it goes through the same
                # remap (NULL if the clip itself was skipped on import - the photo stays a photo).
                "live_video_stored_file_id": (
                    stored_file_map.get(data["live_video_stored_file_id"]) if data.get("live_video_stored_file_id") else None
                ),
                # Audit fix (2026-09-17): event_id was passed through unremapped here while
                # every other imported table's event FK (e.g. _import_protocols) goes through
                # event_map - event.id is a global sequence, so an unremapped value either
                # violates the FK constraint (no such id in the new tenant) or, worse, silently
                # cross-links the imported photo to a same-numbered event belonging to a
                # completely different tenant.
                "event_id": event_map.get(data["event_id"]) if data.get("event_id") else None,
                # Same reasoning for the document-upload Bezug columns: unremapped they'd
                # point at another tenant's Zyklus/Abgabe (both ids are global sequences).
                "cycle_config_id": cycle_config_map.get(data["cycle_config_id"]) if data.get("cycle_config_id") else None,
                "submission_assignment_id": (
                    submission_assignment_map.get(data["submission_assignment_id"])
                    if data.get("submission_assignment_id")
                    else None
                ),
                # "event-<public_id>"/"entry-<public_id>" of the Abgabe-Element - only
                # meaningful together with the assignment above.
                "submission_element_ref": (
                    self._remap_public_refs(data.get("submission_element_ref"))
                    if data.get("submission_assignment_id") and submission_assignment_map.get(data["submission_assignment_id"])
                    else None
                ),
            }))
        self.db.commit()

    def _import_protocols(self, new_tenant_id: int, template_map, event_map) -> dict[int, int]:
        id_map: dict[int, int] = {}
        for row in self._t("protocol"):
            data = self._resolve_row("protocol", row)
            new_template_id = template_map.get(data["template_id"])
            if new_template_id is None:
                continue
            new_row = self._build(Protocol, data, {
                "tenant_id": new_tenant_id,
                "template_id": new_template_id,
                "event_id": event_map.get(data["event_id"]) if data.get("event_id") else None,
                # Die Todo-Momentaufnahme referenziert Block-IDs des Quellmandanten - sie wird
                # nach dem Import der Blöcke umgeschrieben (_restore_todo_snapshots).
                "todos_snapshot_json": None,
            })
            self.db.add(new_row)
            self.db.flush()
            id_map[row["id"]] = new_row.id
        self.db.commit()
        return id_map

    def _import_word_import_documents(
        self, new_tenant_id: int, template_map: dict[int, int], stored_file_map: dict[int, int],
        protocol_map: dict[int, int], maps: WordImportIdMaps,
    ) -> None:
        for row in self._t("word_import_document"):
            data = self._resolve_row("word_import_document", row)
            new_template_id = template_map.get(data["template_id"])
            new_stored_file_id = stored_file_map.get(data["stored_file_id"])
            if new_template_id is None or new_stored_file_id is None:
                self.warnings.append(
                    f"Word-Import '{data.get('original_filename')}': Vorlage oder Quelldatei fehlt, übersprungen."
                )
                continue
            self.db.add(self._build(WordImportDocument, data, {
                "tenant_id": new_tenant_id,
                "template_id": new_template_id,
                "stored_file_id": new_stored_file_id,
                "protocol_id": protocol_map.get(data["protocol_id"]) if data.get("protocol_id") else None,
                # The analysis holds internal ids (participants, events, lists, template
                # elements, protocols) ...
                "analysis_snapshot_json": remap_word_import_analysis(data.get("analysis_snapshot_json"), maps),
                # ... the reviewer's draft only public ids (it's written by the frontend).
                "review_draft_json": self._remap_public_refs(data.get("review_draft_json") or {}),
            }))
        self.db.commit()

    def _import_word_import_suggestion_outcomes(self, new_tenant_id: int, template_map: dict[int, int]) -> None:
        for row in self._t("word_import_suggestion_outcome"):
            old_template_id = row.get("template_id")
            self.db.add(self._build(WordImportSuggestionOutcome, row, {
                "tenant_id": new_tenant_id,
                "template_id": template_map.get(old_template_id) if old_template_id else None,
            }))
        self.db.commit()

    def _import_protocol_elements(
        self, protocol_map: dict[int, int], template_element_map: dict[int, int], *,
        participant_map: dict[int, int], list_definition_map: dict[int, int], list_entry_map: dict[int, int],
    ) -> dict[int, int]:
        id_map: dict[int, int] = {}
        for row in self._t("protocol_element"):
            new_protocol_id = protocol_map.get(row["protocol_id"])
            if new_protocol_id is None:
                continue
            new_row = self._build(ProtocolElement, row, {
                "protocol_id": new_protocol_id,
                "template_element_id": template_element_map.get(row["template_element_id"]) if row.get("template_element_id") else None,
                "responsible_assignments_snapshot": remap_responsible_assignments(
                    row.get("responsible_assignments_snapshot"), participant_map=participant_map,
                    list_definition_map=list_definition_map, list_entry_map=list_entry_map,
                ),
            })
            self.db.add(new_row)
            self.db.flush()
            id_map[row["id"]] = new_row.id
        self.db.commit()
        return id_map

    def _import_protocol_element_blocks(
        self, protocol_element_map, template_element_block_map, element_definition_map, participant_map,
        *, event_map, list_definition_map, list_entry_map, finance_account_map,
    ) -> dict[int, int]:
        id_map: dict[int, int] = {}
        for row in self._t("protocol_element_block"):
            data = self._resolve_row("protocol_element_block", row)
            new_protocol_element_id = protocol_element_map.get(data["protocol_element_id"])
            if new_protocol_element_id is None:
                continue
            new_row = self._build(ProtocolElementBlock, data, {
                "protocol_element_id": new_protocol_element_id,
                "template_element_block_id": template_element_block_map.get(data["template_element_block_id"]) if data.get("template_element_block_id") else None,
                "element_definition_id": element_definition_map.get(data["element_definition_id"]) if data.get("element_definition_id") else None,
                "configuration_snapshot_json": upgrade_snapshot_config(data.get("element_type_id"), remap_block_configuration(
                    data.get("configuration_snapshot_json"), participant_map=participant_map,
                    event_map=event_map, list_definition_map=list_definition_map, list_entry_map=list_entry_map,
                    finance_account_map=finance_account_map,
                    participant_public_ids=self._participant_public_ids, event_public_ids=self._event_public_ids,
                )),
            })
            self.db.add(new_row)
            self.db.flush()
            id_map[row["id"]] = new_row.id
            if (new_row.configuration_snapshot_json or {}).get("repeat_source_type") == "todo":
                self._todo_repeat_block_ids.append(new_row.id)
        self.db.commit()
        return id_map

    def _import_protocol_texts(self, protocol_element_block_map: dict[int, int]) -> None:
        for row in self._t("protocol_text"):
            new_block_id = protocol_element_block_map.get(row["protocol_element_block_id"])
            if new_block_id is None:
                continue
            self.db.add(self._build(ProtocolText, row, {"protocol_element_block_id": new_block_id}))
        self.db.commit()

    def _import_protocol_display_snapshots(self, protocol_element_block_map: dict[int, int]) -> None:
        for row in self._t("protocol_display_snapshot"):
            new_block_id = protocol_element_block_map.get(row["protocol_element_block_id"])
            if new_block_id is None:
                continue
            self.db.add(self._build(ProtocolDisplaySnapshot, row, {"protocol_element_block_id": new_block_id}))
        self.db.commit()

    def _import_protocol_images(self, protocol_element_block_map: dict[int, int], stored_file_map: dict[int, int]) -> None:
        for row in self._t("protocol_image"):
            new_block_id = protocol_element_block_map.get(row["protocol_element_block_id"])
            new_stored_file_id = stored_file_map.get(row["stored_file_id"])
            if new_block_id is None or new_stored_file_id is None:
                continue
            self.db.add(self._build(ProtocolImage, row, {"protocol_element_block_id": new_block_id, "stored_file_id": new_stored_file_id}))
        self.db.commit()

    def _import_finance_transactions(self, finance_account_map: dict[int, int], protocol_map: dict[int, int]) -> dict[int, int]:
        id_map: dict[int, int] = {}
        for row in self._t("finance_transaction"):
            new_account_id = finance_account_map.get(row["account_id"])
            if new_account_id is None:
                continue
            new_row = self._build(FinanceTransaction, row, {
                "account_id": new_account_id,
                "protocol_id": protocol_map.get(row["protocol_id"]) if row.get("protocol_id") else None,
            })
            self.db.add(new_row)
            self.db.flush()
            id_map[row["id"]] = new_row.id
        self.db.commit()
        return id_map

    def _import_attendance_fines(self, protocol_map, participant_map, finance_account_map, finance_transaction_map) -> None:
        # Ältere Archive können doppelte Bussen enthalten (vor Migration 0116). Pro Protokoll,
        # Teilnehmer und Typ bleibt wie in 0116 die Busse mit dem stärksten Status bzw. die
        # älteste - sonst bräche der Unique-Index den ganzen Import ab.
        status_rank = {"collected": 0, "pending": 1}
        keepers: dict[tuple, dict] = {}
        for row in self._t("attendance_fine"):
            data = self._resolve_row("attendance_fine", row)
            participant_key = f"id:{data['participant_id']}" if data.get("participant_id") else f"name:{data.get('participant_name_snapshot')}"
            key = (data["protocol_id"], participant_key, data.get("fine_type"))
            rank = (status_rank.get(data.get("status"), 2), str(data.get("created_at") or ""), data.get("id") or 0)
            current = keepers.get(key)
            if current is None or rank < current["rank"]:
                keepers[key] = {"rank": rank, "data": data}
        skipped = len(self._t("attendance_fine")) - len(keepers)
        if skipped:
            self.warnings.append(f"attendance_fine: {skipped} doppelte Busse(n) zusammengeführt.")
        for keeper in keepers.values():
            data = keeper["data"]
            new_protocol_id = protocol_map.get(data["protocol_id"])
            new_account_id = finance_account_map.get(data["account_id"])
            if new_protocol_id is None or new_account_id is None:
                continue
            new_row = self._build(AttendanceFine, data, {
                "protocol_id": new_protocol_id,
                "participant_id": participant_map.get(data["participant_id"]) if data.get("participant_id") else None,
                "account_id": new_account_id,
                "collected_transaction_id": finance_transaction_map.get(data["collected_transaction_id"]) if data.get("collected_transaction_id") else None,
                "closed_in_protocol_id": protocol_map.get(data["closed_in_protocol_id"]) if data.get("closed_in_protocol_id") else None,
            })
            self.db.add(new_row)
        self.db.commit()

    def _import_task_packages(self, new_tenant_id, *, cycle_config_map, participant_map, list_definition_map, list_entry_map) -> dict[int, int]:
        package_map = self._import_simple(TaskPackage, self._t("task_package"), "task_package", {"tenant_id": new_tenant_id})
        for row in self._t("task_package_cycle"):
            package_id = package_map.get(row["task_package_id"])
            cycle_config_id = cycle_config_map.get(row["cycle_config_id"])
            if package_id is None or cycle_config_id is None:
                continue
            self.db.add(self._build(TaskPackageCycle, row, {"task_package_id": package_id, "cycle_config_id": cycle_config_id}))
        item_map: dict[int, int] = {}
        for row in self._t("task_package_item"):
            package_id = package_map.get(row["task_package_id"])
            if package_id is None:
                continue
            responsible = []
            for entry in row.get("responsible_json") or []:
                if entry.get("participant_id"):
                    participant_id = participant_map.get(entry["participant_id"])
                    if participant_id:
                        responsible.append({"participant_id": participant_id})
                elif entry.get("list_definition_id") and entry.get("list_entry_id"):
                    list_definition_id = list_definition_map.get(entry["list_definition_id"])
                    list_entry_id = list_entry_map.get(entry["list_entry_id"])
                    if list_definition_id and list_entry_id:
                        responsible.append({"list_definition_id": list_definition_id, "list_entry_id": list_entry_id})
            new_row = self._build(TaskPackageItem, row, {"task_package_id": package_id, "responsible_json": responsible})
            self.db.add(new_row)
            self.db.flush()
            item_map[row["id"]] = new_row.id
        self.db.commit()
        return item_map

    def _import_protocol_todo_assignees(self, todo_map: dict[int, int], participant_map: dict[int, int]) -> None:
        for row in self._t("protocol_todo_assignee"):
            todo_id = todo_map.get(row["protocol_todo_id"])
            participant_id = participant_map.get(row["participant_id"])
            if todo_id is None or participant_id is None:
                continue
            self.db.add(ProtocolTodoAssignee(protocol_todo_id=todo_id, participant_id=participant_id, sort_index=row.get("sort_index") or 0))
        self.db.commit()

    def _import_protocol_todo_files(self, todo_map: dict[int, int], stored_file_map: dict[int, int]) -> None:
        for row in self._t("protocol_todo_file"):
            todo_id = todo_map.get(row["protocol_todo_id"])
            stored_file_id = stored_file_map.get(row["stored_file_id"])
            if todo_id is None or stored_file_id is None:
                continue
            self.db.add(ProtocolTodoFile(protocol_todo_id=todo_id, stored_file_id=stored_file_id, sort_index=row.get("sort_index") or 0))
        self.db.commit()

    def _import_protocol_todos(
        self, new_tenant_id, protocol_element_block_map, participant_map, event_map, protocol_map, submission_assignment_map,
        *, task_package_item_map: dict[int, int] | None = None, cycle_config_map: dict[int, int] | None = None,
    ) -> dict[int, int]:
        id_map: dict[int, int] = {}
        task_package_item_map = task_package_item_map or {}
        cycle_config_map = cycle_config_map or {}
        for row in self._t("protocol_todo"):
            data = self._resolve_row("protocol_todo", row)
            new_row = self._build(ProtocolTodo, data, {
                "tenant_id": new_tenant_id,
                "task_package_item_id": task_package_item_map.get(data["task_package_item_id"]) if data.get("task_package_item_id") else None,
                "cycle_config_id": cycle_config_map.get(data["cycle_config_id"]) if data.get("cycle_config_id") else None,
                "occurrence_key": remap_occurrence_key(data.get("occurrence_key"), event_map),
                "protocol_element_block_id": protocol_element_block_map.get(data["protocol_element_block_id"]) if data.get("protocol_element_block_id") else None,
                "assigned_participant_id": participant_map.get(data["assigned_participant_id"]) if data.get("assigned_participant_id") else None,
                "due_event_id": event_map.get(data["due_event_id"]) if data.get("due_event_id") else None,
                "closed_in_protocol_id": protocol_map.get(data["closed_in_protocol_id"]) if data.get("closed_in_protocol_id") else None,
                "submission_assignment_id": submission_assignment_map.get(data["submission_assignment_id"]) if data.get("submission_assignment_id") else None,
                "element_ref": self._remap_public_refs(data.get("element_ref")),
            })
            self.db.add(new_row)
            self.db.flush()
            id_map[row["id"]] = new_row.id
        self.db.commit()
        return id_map

    def _import_agenda_items(
        self, new_tenant_id: int, template_map: dict[int, int], template_element_map: dict[int, int],
        protocol_map: dict[int, int], protocol_element_map: dict[int, int],
    ) -> None:
        for row in self._t("agenda_item"):
            template_id = template_map.get(row["template_id"])
            if template_id is None:
                continue
            data = self._resolve_row("agenda_item", row)
            self.db.add(self._build(AgendaItem, data, {
                "tenant_id": new_tenant_id,
                "template_id": template_id,
                "template_element_id": template_element_map.get(data["template_element_id"]) if data.get("template_element_id") else None,
                "protocol_id": protocol_map.get(data["protocol_id"]) if data.get("protocol_id") else None,
                "protocol_element_id": protocol_element_map.get(data["protocol_element_id"]) if data.get("protocol_element_id") else None,
            }))
        self.db.commit()

    def _remap_todo_repeat_sources(self, todo_map: dict[int, int]) -> None:
        """Second pass for blocks bound to a todo ("Wiederholen aus Todo") - the todos are
        created after the blocks, see remap_repeat_source_todo."""
        for block_id in self._todo_repeat_block_ids:
            block = self.db.get(ProtocolElementBlock, block_id)
            new_config = remap_repeat_source_todo(block.configuration_snapshot_json if block else None, todo_map)
            if new_config is not None:
                block.configuration_snapshot_json = new_config
                self.db.add(block)
        self.db.commit()

    # ── photo albums / cycle snapshots ────────────────────────────────────

    def _import_photo_albums(
        self, new_tenant_id: int, cycle_config_map: dict[int, int], submission_assignment_map: dict[int, int]
    ) -> dict[str, uuid.UUID]:
        album_map: dict[str, uuid.UUID] = {}
        for row in self._t("photo_album"):
            overrides: dict[str, Any] = {"tenant_id": new_tenant_id}
            if row.get("cycle_config_id") is not None:
                overrides["cycle_config_id"] = cycle_config_map.get(row["cycle_config_id"])
                if overrides["cycle_config_id"] is None:
                    continue
            if row.get("submission_assignment_id") is not None:
                overrides["submission_assignment_id"] = submission_assignment_map.get(row["submission_assignment_id"])
                if overrides["submission_assignment_id"] is None:
                    # Abgabe not part of this import (scope "full") - ck_photo_album_kind_fields
                    # needs it, so the auto album can't exist; it's re-created on demand.
                    continue
                overrides["submission_element_ref"] = self._remap_public_refs(row.get("submission_element_ref"))
            # photo_album's primary key IS its public identity (album URLs, partner shares,
            # share links) - kept like a public_id whenever it's still free.
            new_album = self._build(PhotoAlbum, row, overrides)
            new_album.id = self._claim_uuid(PhotoAlbum, "id", str(row["id"]))
            self.db.add(new_album)
            album_map[str(row["id"]).lower()] = new_album.id
        self.db.flush()
        for row in self._t("photo_album_item"):
            new_album_id = album_map.get(str(row.get("album_id")).lower())
            old_file_id = str(row.get("file_id")).lower()
            if new_album_id is None or old_file_id not in self._imported_file_public_ids:
                continue
            self.db.add(PhotoAlbumItem(
                album_id=new_album_id,
                file_id=uuid.UUID(self._public_id_map.get(old_file_id, old_file_id)),
                is_best=bool(row.get("is_best")),
                best_override=row.get("best_override"),
                share_pending=bool(row.get("share_pending")),
            ))
        self.db.commit()
        return album_map

    # ── links, feeds, partner relations, tenant settings ──────────────────

    def _import_submission_links(self, new_tenant_id: int, submission_assignment_map: dict[int, int]) -> None:
        """Abgabebox-Links with their tokens and Abgabe assignment (scope full_abgabebox). Older
        archives and exports without Abgabebox carry none - the tenant then gets the default
        link every new tenant starts with, with every imported Abgabe attached."""
        if not self._t("submission_link"):
            submission_link_service.attach_assignments(
                self.db,
                submission_link_service.create_default_link(self.db, new_tenant_id),
                list(submission_assignment_map.values()),
            )
            self.db.commit()
            return
        link_map: dict[int, int] = {}
        for row in self._t("submission_link"):
            new_link = self._build(SubmissionLink, row, {
                "tenant_id": new_tenant_id,
                "token": self._claim_token(
                    SubmissionLink, row.get("token"), submission_link_service.generate_token, f"Abgabebox-Link '{row.get('name')}'"
                ),
            })
            self.db.add(new_link)
            self.db.flush()
            link_map[row["id"]] = new_link.id
        for row in self._t("submission_assignment_link"):
            new_assignment_id = submission_assignment_map.get(row.get("assignment_id"))
            new_link_id = link_map.get(row.get("link_id"))
            if new_assignment_id is not None and new_link_id is not None:
                self.db.execute(
                    pg_insert(submission_assignment_link_table)
                    .values(assignment_id=new_assignment_id, link_id=new_link_id)
                    .on_conflict_do_nothing()
                )
        self.db.commit()

    def _import_share_links(self, new_tenant_id: int, album_map: dict[str, uuid.UUID]) -> None:
        for row in self._t("share_link"):
            data = self._resolve_row("share_link", row)
            overrides: dict[str, Any] = {
                "tenant_id": new_tenant_id,
                "token": self._claim_token(
                    ShareLink, data.get("token"), share_link_service.generate_token, f"Freigabe-Link '{data.get('name')}'"
                ),
            }
            if data.get("album_id") is not None:
                overrides["album_id"] = album_map.get(str(data["album_id"]).lower())
                if overrides["album_id"] is None:
                    continue
            new_link = self._build(ShareLink, data, overrides)
            new_link.id = self._claim_uuid(ShareLink, "id", str(row["id"]))
            self.db.add(new_link)
            self.db.flush()
            for file_row in self._t("share_link_file"):
                if str(file_row.get("share_link_id")).lower() != str(row["id"]).lower():
                    continue
                old_file_id = str(file_row.get("file_id")).lower()
                if old_file_id not in self._imported_file_public_ids:
                    continue
                self.db.add(ShareLinkFile(
                    share_link_id=new_link.id, file_id=uuid.UUID(self._public_id_map.get(old_file_id, old_file_id))
                ))
        self.db.commit()

    def _import_calendar_feeds(self, new_tenant_id: int) -> None:
        """Kalender-Abos with their token (exported in plaintext, re-encrypted with this
        installation's ADMIN_AUTH_SECRET) - subscribed calendar URLs keep working."""
        for row in self._t("calendar_feed"):
            data = self._resolve_row("calendar_feed", row)
            if data.get("user_id") is None:
                self._warn_missing_user("calendar_feed", row.get("user_id"))
                continue
            token = row.get("token")
            if not token or self.db.scalar(
                select(CalendarFeed.id).where(CalendarFeed.token_hash == calendar_feed_service.hash_token(token))
            ) is not None:
                if token:
                    self.warnings.append(
                        f"Kalender-Abo von '{row.get('user_id')}': Token bereits vergeben - neue Abo-URL erzeugt."
                    )
                token = calendar_feed_service.generate_token()
            self.db.add(self._build(CalendarFeed, data, {
                "tenant_id": new_tenant_id,
                "token_hash": calendar_feed_service.hash_token(token),
                "token_encrypted": encrypt_secret(token),
            }))
        self.db.commit()

    def _import_fine_tariff(self, new_tenant_id: int, finance_account_map: dict[int, int]) -> None:
        """Zentraler Bussentarif. Exporte vor 0113 kennen fine_tariff nicht - dann wird der
        Tarif wie in der Migration aus den Anwesenheitsblöcken der Elementdefinitionen
        abgeleitet (häufigster Wert), bevor element_config die Blockwerte entfernt."""
        rows = self._t("fine_tariff")
        if rows:
            source = rows[0]
            account_id = finance_account_map.get(source.get("account_id")) if source.get("account_id") is not None else None
            amount_late = source.get("amount_late") or 0
            amount_absent = source.get("amount_absent") or 0
        else:
            derived = derive_fine_tariff([row.get("configuration_json") for row in self._t("element_definition")])
            if derived is None:
                return
            try:
                account_id = finance_account_map.get(int(derived["account_id"]))
            except (TypeError, ValueError):
                account_id = None
            amount_late = derived["amount_late"]
            amount_absent = derived["amount_absent"]
        self.db.add(FineTariff(tenant_id=new_tenant_id, account_id=account_id, amount_late=amount_late, amount_absent=amount_absent))
        self.db.commit()

    def _import_tenant_settings(self, new_tenant_id: int) -> None:
        for row in self._t("tenant_feature"):
            if self.db.get(Feature, row.get("feature_code")) is None:
                self.warnings.append(f"Feature '{row.get('feature_code')}' existiert auf dieser Installation nicht - übersprungen.")
                continue
            self.db.add(self._build(TenantFeature, row, {
                "tenant_id": new_tenant_id, "enabled_by_admin_id": self._admin_id_for(row.get("enabled_by_admin_id")),
            }))
        for row in self._t("tenant_storage_package"):
            if self.db.get(StoragePackage, row.get("package_code")) is None:
                self.warnings.append(f"Speicherpaket '{row.get('package_code')}' existiert auf dieser Installation nicht - übersprungen.")
                continue
            self.db.add(self._build(TenantStoragePackage, row, {
                "tenant_id": new_tenant_id, "added_by_admin_id": self._admin_id_for(row.get("added_by_admin_id")),
            }))
        self.db.commit()

    def _import_tenant_trusts(self, new_tenant_id: int) -> None:
        """Vertrauensbeziehungen werden nie aus dem Archiv übernommen (Security-Audit SEC-001): ein
        Archiv belegt keine Zustimmung des Partners, und der neue Mandant ist nicht der, dem der
        Partner vertraut hat. Trust entsteht wie gewohnt, sobald der Partner eine (wieder
        ausgesprochene) Album-Einladung annimmt - siehe _import_album_shares."""
        skipped = sum(1 for _ in self._t("tenant_trust"))
        if skipped:
            self.warnings.append(
                f"{skipped} Vertrauensbeziehung(en) zu anderen Mandanten nicht übernommen - sie entstehen neu, "
                "sobald der Partner eine Album-Einladung annimmt."
            )

    def _import_album_shares(self, new_tenant_id: int, album_map: dict[str, uuid.UUID]) -> None:
        """Album-Freigaben nur als neue, offene Einladungen (Security-Audit SEC-001).

        Ein Archiv belegt keine Zustimmung eines anderen Mandanten - es kann von einem Umzug
        stammen, aber genauso eine Kopie eines noch bestehenden Mandanten oder manipuliert sein.
        Deshalb:
        - eigene Alben, die mit einem Partner geteilt waren: wieder als Einladung (`pending`) an
          den Partner, der erneut zustimmen muss; Standort-Freigabe wie im Archiv.
        - Einladungen in Alben anderer Mandanten (`partner_album`) und die dort abgelegten eigenen
          Fotos (`partner_album_item`) werden verworfen - der Partner kann neu einladen.
        Gleiche Regel wie beim Mandanten-Restore aus dem Backup (COPY_EXCLUDED_TABLES), dort
        fallen Freigaben ganz weg."""
        reinvited: set[str] = set()
        dropped_received = 0
        for row in self._t("photo_album_tenant_share"):
            data = self._resolve_row("photo_album_tenant_share", row)
            if data.get("direction") == "partner_album":
                dropped_received += 1
                continue
            partner = self._lookup_tenant_by_public_id(data.get("partner_tenant_public_id"))
            if partner is None or partner.id == new_tenant_id:
                self.warnings.append("Album-Freigabe mit einem Mandanten, der auf dieser Installation fehlt - übersprungen.")
                continue
            album_id = album_map.get(str(data.get("album_id")).lower())
            if album_id is None:
                continue
            self.db.execute(
                pg_insert(PhotoAlbumTenantShare)
                .values(
                    album_id=album_id, tenant_id=partner.id, status="pending", invited_by=None,
                    share_location=bool(data.get("share_location", True)),
                    partner_public_links=bool(data.get("partner_public_links", True)),
                )
                .on_conflict_do_nothing()
            )
            reinvited.add(partner.name)
        dropped_received_items = sum(1 for _ in self._t("partner_album_item"))
        if dropped_received:
            self.warnings.append(
                f"{dropped_received} Freigabe(n) für Alben anderer Mandanten nicht übernommen"
                + (f" (inkl. {dropped_received_items} dort abgelegter Fotos)" if dropped_received_items else "")
                + " - der jeweilige Partner muss neu einladen."
            )
        if reinvited:
            self.warnings.append(
                "Album-Freigaben als neue Einladung an folgende Mandanten verschickt (Zustimmung erneut nötig): "
                + ", ".join(sorted(reinvited))
            )
        self.db.commit()

    def _import_table_snapshots(
        self, new_tenant_id: int, cycle_config_map: dict[int, int], *,
        list_definition_map: dict[int, int], list_entry_map: dict[int, int],
        participant_map: dict[int, int], event_map: dict[int, int],
    ) -> None:
        for row in self._t("table_snapshot"):
            data = self._resolve_row("table_snapshot", row)
            new_cycle_config_id = cycle_config_map.get(data.get("cycle_config_id"))
            if new_cycle_config_id is None:
                continue
            self.db.add(self._build(TableSnapshot, data, {
                "tenant_id": new_tenant_id,
                "cycle_config_id": new_cycle_config_id,
                "snapshot_json": remap_table_snapshot_rows(
                    data.get("table_name"), data.get("snapshot_json"), new_tenant_id=new_tenant_id,
                    list_definition_map=list_definition_map, list_entry_map=list_entry_map,
                    participant_map=participant_map, event_map=event_map, public_id_map=self._public_id_map,
                ),
            }))
        self.db.commit()


    def _import_user_template_access(self, new_tenant_id: int, template_map: dict[int, int]) -> None:
        for row in self._t("user_template_access"):
            data = self._resolve_row("user_template_access", row)
            new_template_id = template_map.get(row["template_id"])
            if new_template_id is None:
                continue
            if data.get("user_id") is None:
                self._warn_missing_user("user_template_access", row.get("user_id"))
                continue
            self.db.add(self._build(UserTemplateAccess, data, {"tenant_id": new_tenant_id, "template_id": new_template_id}))
        self.db.commit()

    def _import_user_protocol_access(self, new_tenant_id: int, protocol_map: dict[int, int]) -> None:
        for row in self._t("user_protocol_access"):
            data = self._resolve_row("user_protocol_access", row)
            new_protocol_id = protocol_map.get(row["protocol_id"])
            if new_protocol_id is None:
                continue
            if data.get("user_id") is None:
                self._warn_missing_user("user_protocol_access", row.get("user_id"))
                continue
            self.db.add(self._build(UserProtocolAccess, data, {"tenant_id": new_tenant_id, "protocol_id": new_protocol_id}))
        self.db.commit()

    def _import_user_protocol_scrolls(self, protocol_map: dict[int, int]) -> None:
        for row in self._t("user_protocol_scroll"):
            data = self._resolve_row("user_protocol_scroll", row)
            new_protocol_id = protocol_map.get(row["protocol_id"])
            if new_protocol_id is None:
                continue
            if data.get("user_id") is None:
                self._warn_missing_user("user_protocol_scroll", row.get("user_id"))
                continue
            # Composite primary key: build_row intentionally only drops a literal `id`,
            # so both remapped key columns are supplied explicitly here.
            self.db.add(self._build(UserProtocolScroll, data, {"protocol_id": new_protocol_id}))
        self.db.commit()


def _resolve_within_extract_dir(base_dir: Path, relative_name: str) -> Path:
    """Resolves `relative_name` against `base_dir` and rejects any result that would land
    outside of it - covers both `../../etc/passwd`-style traversal and absolute paths
    (`Path(base) / "/etc/passwd"` silently discards `base` per Python's own Path semantics,
    so an absolute member name would otherwise land wherever the attacker points it).
    Shared by _safe_extract() (zip member names) and TenantImportService._restore_file()
    (manifest.json's storage_path/profile_image_path fields) - both are attacker-controlled
    strings from the same untrusted import zip (audit S4, 2026-08-16)."""
    base_resolved = base_dir.resolve()
    target = (base_dir / relative_name).resolve()
    if not target.is_relative_to(base_resolved):
        raise ValueError(f"Unsicherer Pfad im Import-Archiv: {relative_name}")
    return target


IMPORT_FREE_RESERVE_BYTES = 1024**3


def _safe_extract(zf: zipfile.ZipFile, dest_dir: Path) -> None:
    infolist = zf.infolist()

    # Zip-bomb guard (M19): check declared entry count/uncompressed size - same as
    # file_service.py's extract_word_import_files_from_zip - before ever calling extractall,
    # which would otherwise happily write an unbounded amount of data to disk.
    if len(infolist) > MAX_IMPORT_ZIP_ENTRIES:
        raise ValueError(
            f"Import-Archiv enthält zu viele Dateien (> {MAX_IMPORT_ZIP_ENTRIES}) - Import abgebrochen."
        )
    total_uncompressed = sum(member.file_size for member in infolist)
    if total_uncompressed > MAX_IMPORT_ZIP_TOTAL_BYTES:
        raise ValueError(
            f"Import-Archiv ist entpackt zu gross (> {MAX_IMPORT_ZIP_TOTAL_BYTES // (1024 * 1024)} MB) - Import abgebrochen."
        )

    # Freier Platz für das Entpacken (Concurrency-Audit CONC-021): der Datenträger von /tmp teilen
    # sich Multipart-Puffer, Uploads und Exporte aller Mandanten - ein voller Datenträger liesse
    # alle anderen Uploads scheitern, statt dass dieser eine Import sauber abbricht.
    free_bytes = shutil.disk_usage(dest_dir).free
    if total_uncompressed + IMPORT_FREE_RESERVE_BYTES > free_bytes:
        raise ValueError("Zu wenig freier Speicher zum Entpacken des Import-Archivs - Import abgebrochen.")

    for member in infolist:
        _resolve_within_extract_dir(dest_dir, member.filename)
    zf.extractall(dest_dir)


def _document_types() -> tuple[str, ...]:
    from app.documents.doc_types import DOCUMENT_TYPE_KEYS

    return DOCUMENT_TYPE_KEYS


class ImportFileSource:
    """Woher die Dateien eines Imports kommen. Pfade (member) stammen aus dem Manifest und sind
    damit nicht vertrauenswürdig - jede Quelle prüft sie selbst."""

    def exists(self, member: str) -> bool:  # pragma: no cover - Schnittstelle
        raise NotImplementedError

    def store(self, db: Session, namespace: str, key: str, member: str) -> bool:  # pragma: no cover
        raise NotImplementedError

    def local_file(self, member: str):  # pragma: no cover - contextmanager -> Path
        raise NotImplementedError


class ExtractedDirSource(ImportFileSource):
    """Entpacktes ZIP (normaler Import mit 2-GiB-/Eintragsgrenze aus _safe_extract)."""

    def __init__(self, extract_dir: Path) -> None:
        self.extract_dir = extract_dir

    def _path(self, member: str) -> Path:
        return _resolve_within_extract_dir(self.extract_dir, member)

    def exists(self, member: str) -> bool:
        return self._path(member).is_file()

    def store(self, db: Session, namespace: str, key: str, member: str) -> bool:
        source = self._path(member)
        if not source.is_file():
            return False
        get_object_store().put_file(db, namespace, key, source)
        return True

    @contextlib.contextmanager
    def local_file(self, member: str):
        yield self._path(member)
