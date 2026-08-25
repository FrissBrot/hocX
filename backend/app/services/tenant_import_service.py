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

import json
import secrets
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from app import scanner
from app.core.config import settings
from app.core.security import hash_password
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
    UserTemplateAccess,
    UserTenantRole,
)
from app.services import traefik_config_service
from app.services.document_template_service import DocumentTemplateService
from app.services.tenant_transfer_common import (
    LOOKUP_COLUMNS,
    REDACTED_PASSWORD_HASH_MARKER,
    USER_ID_COLUMNS,
    LookupCodeCache,
    UserEmailCache,
    build_row,
    remap_block_configuration,
    remap_document_template_config,
    remap_element_definition_config,
    remap_list_value,
    remap_template_element_config,
)

SUPPORTED_FORMAT_VERSION = 1

# Zip-bomb guard, same idea as file_service.py's MAX_ZIP_ENTRIES/MAX_ZIP_TOTAL_BYTES for the
# word-import ZIP upload, just scaled up: a full-tenant export can legitimately contain many
# more files (every stored_file/protocol_image/abgabebox upload the tenant has) and be much
# larger than a single word-import ZIP, but it still needs a hard ceiling so a corrupted or
# malicious archive can't exhaust disk via extractall() (M19, 2026-08-12 audit - _safe_extract
# previously only guarded against zip-slip path traversal, not entry count/decompressed size).
MAX_IMPORT_ZIP_ENTRIES = 20_000
MAX_IMPORT_ZIP_TOTAL_BYTES = 2 * 1024 * 1024 * 1024  # 2 GB combined uncompressed size


class TenantImportService:
    def __init__(self) -> None:
        self.document_template_service = DocumentTemplateService()

    def import_zip(self, db: Session, zip_path: Path, new_name: str) -> tuple[Tenant, list[str]]:
        with tempfile.TemporaryDirectory(prefix="hocx-import-") as extract_dir_str:
            extract_dir = Path(extract_dir_str)
            with zipfile.ZipFile(zip_path) as zf:
                _safe_extract(zf, extract_dir)

            manifest_path = extract_dir / "manifest.json"
            if not manifest_path.exists():
                raise ValueError("Kein manifest.json im Archiv gefunden - kein gültiges hocX-Export-Archiv.")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest.get("format_version") != SUPPORTED_FORMAT_VERSION:
                raise ValueError(f"Nicht unterstützte Export-Version: {manifest.get('format_version')!r}")

            self.db = db
            self.extract_dir = extract_dir
            self.tables: dict[str, Any] = manifest.get("tables", {})
            self.lookup_cache = LookupCodeCache(db)
            self.user_cache = UserEmailCache(db)
            self.warnings: list[str] = []
            self._created_tenant_id: int | None = None

            try:
                new_tenant = self._run(new_name)
            except Exception:
                # The pipeline below commits progressively (one table at a time, matching
                # TenantCloneService's style) rather than as one big transaction - a failure
                # partway through would otherwise leave a broken, half-imported tenant sitting
                # in the tenant list instead of a clean "import failed". Tear it down (cascade
                # deletes every row written so far) before the error propagates.
                db.rollback()
                if self._created_tenant_id is not None:
                    db.query(Tenant).filter(Tenant.id == self._created_tenant_id).delete()
                    db.commit()
                raise
            return new_tenant, self.warnings

    def _t(self, name: str) -> list[dict[str, Any]]:
        return self.tables.get(name, [])

    # ── generic helpers ───────────────────────────────────────────────────

    def _resolve_row(self, table_name: str, data: dict[str, Any]) -> dict[str, Any]:
        """Applies lookup-code and user-email resolution in place, returns the (possibly mutated) dict."""
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
        # SECURITY (audit S4, 2026-08-16): member_path comes straight out of the attacker-
        # controlled manifest.json inside the uploaded import zip - joining it onto
        # extract_dir unchecked would let a manifest with e.g. "../../../etc/passwd" or an
        # absolute path (Path(a) / "/etc/passwd" silently discards "a" entirely, per Python's
        # Path semantics) read arbitrary files off the server's filesystem into the new
        # tenant's storage. _safe_extract() already guards the zip's own entries the same way
        # for the same reason - reuse that exact containment check here.
        source = _resolve_within_extract_dir(self.extract_dir, member_path)
        if not source.exists():
            return None
        suffix = Path(member_path).suffix
        target_dir = Path(root) / "tenant_imports" / f"tenant-{new_tenant_id}" / subdir
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / f"{uuid4().hex}{suffix}"
        shutil.copy2(source, target_path)
        return str(target_path.relative_to(Path(root).resolve()))

    def _warn_missing_user(self, table_name: str, email: str | None) -> None:
        if email is not None:
            self.warnings.append(f"{table_name}: Benutzer '{email}' existiert auf dieser Installation nicht - Zeile übersprungen.")

    # ── pipeline ──────────────────────────────────────────────────────────

    def _run(self, new_name: str) -> Tenant:
        new_tenant = self._import_tenant_base(new_name)
        self._created_tenant_id = new_tenant.id
        self._import_app_users(new_tenant.id, self.tables.get("tenant", {}).get("id"))
        self._import_tenant_domains(new_tenant.id)
        group_map = self._import_simple(GroupEntity, self._t("group_entity"), "group_entity", {"tenant_id": new_tenant.id})
        self._import_simple(Leader, self._t("leader"), "leader", {"tenant_id": new_tenant.id})
        participant_map = self._import_simple(Participant, self._t("participant"), "participant", {"tenant_id": new_tenant.id})
        cycle_config_map = self._import_simple(CycleConfig, self._t("cycle_config"), "cycle_config", {"tenant_id": new_tenant.id})
        part_map = self._import_document_template_parts(new_tenant.id)
        document_template_map = self._import_document_templates(new_tenant.id, part_map)
        event_map = self._import_events(new_tenant.id, group_map, participant_map)
        self._import_event_cycles(event_map, cycle_config_map)
        list_definition_map = self._import_simple(ListDefinition, self._t("list_definition"), "list_definition", {"tenant_id": new_tenant.id})
        list_entry_map = self._import_list_entries(list_definition_map, participant_map, event_map)
        finance_account_map = self._import_simple(FinanceAccount, self._t("finance_account"), "finance_account", {"tenant_id": new_tenant.id})
        element_definition_map = self._import_element_definitions(
            new_tenant.id, participant_map=participant_map, event_map=event_map,
            list_definition_map=list_definition_map, list_entry_map=list_entry_map, finance_account_map=finance_account_map,
        )
        template_map, template_element_map, template_element_block_map = self._import_templates(
            new_tenant.id,
            document_template_map=document_template_map,
            cycle_config_map=cycle_config_map,
            element_definition_map=element_definition_map,
            event_map=event_map,
            participant_map=participant_map,
            list_definition_map=list_definition_map,
            list_entry_map=list_entry_map,
            finance_account_map=finance_account_map,
        )
        self._restore_last_word_import_template(new_tenant, template_map)
        self._import_template_participants(template_map, participant_map)
        submission_assignment_map = self._import_submission_assignments(new_tenant.id, list_definition_map)
        submission_upload_map = self._import_submission_uploads(submission_assignment_map, event_map, list_entry_map)
        self._import_submission_upload_logs(submission_assignment_map)
        stored_file_map = self._import_stored_files(new_tenant.id)
        self._import_submission_upload_files(submission_upload_map, stored_file_map)
        protocol_map = self._import_protocols(new_tenant.id, template_map, document_template_map, event_map)
        protocol_element_map = self._import_protocol_elements(protocol_map, template_element_map)
        protocol_element_block_map = self._import_protocol_element_blocks(
            protocol_element_map, template_element_block_map, element_definition_map, participant_map,
            event_map=event_map, list_definition_map=list_definition_map, list_entry_map=list_entry_map,
            finance_account_map=finance_account_map,
        )
        self._import_protocol_texts(protocol_element_block_map)
        self._import_protocol_display_snapshots(protocol_element_block_map)
        self._import_protocol_images(protocol_element_block_map, stored_file_map)
        finance_transaction_map = self._import_finance_transactions(finance_account_map, protocol_map)
        self._import_attendance_fines(protocol_map, participant_map, finance_account_map, finance_transaction_map)
        self._import_protocol_todos(new_tenant.id, protocol_element_block_map, participant_map, event_map, protocol_map, submission_assignment_map)
        self._import_user_template_access(new_tenant.id, template_map)
        self._import_user_protocol_access(new_tenant.id, protocol_map)
        self._import_user_tenant_roles(new_tenant.id)
        return new_tenant

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
        new_tenant = build_row(
            Tenant, data, {"name": new_name, "profile_image_path": None, "public_slug": None, "last_word_import_template_id": None}
        )
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

    def _import_app_users(self, new_tenant_id: int, old_tenant_id: int | None) -> None:
        """Creates a login-capable account (password_hash included) for every exported user
        who doesn't already have one on this installation, matched by email - without this,
        every USER_ID_COLUMNS reference below would resolve to nobody (or, before this
        existed, silently link to a same-email account that was never actually created here,
        so the imported tenant's users had no way to log in on the target at all). An account
        that already exists by email is left completely untouched, including its password -
        only a brand new account gets the source's password_hash."""
        for row in self._t("app_user"):
            email = row.get("email")
            if self.user_cache.id_for(email) is not None:
                continue
            old_default_tenant_id = row.get("default_tenant_id")
            overrides: dict[str, Any] = {
                "default_tenant_id": new_tenant_id if old_default_tenant_id is not None and old_default_tenant_id == old_tenant_id else None,
            }
            if row.get("password_hash") == REDACTED_PASSWORD_HASH_MARKER or not row.get("password_hash"):
                # This row was only a metadata reference (e.g. created_by) in the exporting
                # tenant, not an actual member of it - TenantExportService.export deliberately
                # stripped its real password_hash before it ever left that installation (see
                # REDACTED_PASSWORD_HASH_MARKER). Give the freshly created account a random,
                # cryptographically secure, properly-hashed password instead: the column is
                # NOT NULL so it can't be left empty, and reusing/forwarding a foreign hash
                # would be exactly the leak the export-side redaction was meant to prevent.
                # The account exists (so every USER_ID_COLUMNS reference below still resolves)
                # but cannot log in until a tenant admin sets a real password (UserUpdate.password).
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
            new_user = build_row(AppUser, row, overrides)
            self.db.add(new_user)
            self.db.flush()
            self.user_cache.set_id(email, new_user.id)
        self.db.commit()

    def _import_tenant_domains(self, new_tenant_id: int) -> None:
        """Restores verified custom domains with their original verification_token/status/
        verified_at unchanged - a tenant import reconstructs the source tenant 1:1, and a
        domain already verified on the source (its DNS TXT record already holds this exact
        token) should stay verified on the target rather than forcing the admin through
        domain verification again. `domain` is globally unique across the whole
        installation (uq_tenant_domain_domain), so a domain already claimed - by hocX
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
            if domain in reserved:
                self.warnings.append(f"Domain '{domain}' ist durch die Installation selbst belegt, wurde nicht importiert.")
                continue
            if self.db.query(TenantDomain).filter(TenantDomain.domain == domain).first() is not None:
                self.warnings.append(f"Domain '{domain}' ist auf dieser Installation bereits vergeben, wurde nicht importiert.")
                continue
            new_row = build_row(TenantDomain, data, {"tenant_id": new_tenant_id})
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
            new_row = build_row(model, data, overrides)
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
            new_row = build_row(ElementDefinition, data, {
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

    def _import_document_template_parts(self, new_tenant_id: int) -> dict[int, int]:
        id_map: dict[int, int] = {}
        for row in self._t("document_template_part"):
            data = self._resolve_row("document_template_part", row)
            new_storage_path = self._restore_file(
                data.get("storage_path"), root=settings.storage_root, new_tenant_id=new_tenant_id,
                subdir=f"document_template_parts/{row.get('part_type', 'part')}/{row.get('code', 'code')}",
            )
            if new_storage_path is None:
                self.warnings.append(f"document_template_part '{row.get('code')}' (v{row.get('version')}): Datei fehlte im Export, übersprungen.")
                continue
            new_row = build_row(DocumentTemplatePart, data, {"tenant_id": new_tenant_id, "storage_path": new_storage_path})
            self.db.add(new_row)
            self.db.flush()
            id_map[row["id"]] = new_row.id
        self.db.commit()
        return id_map

    def _import_document_templates(self, new_tenant_id: int, part_map: dict[int, int]) -> dict[int, int]:
        id_map: dict[int, int] = {}
        for row in self._t("document_template"):
            data = self._resolve_row("document_template", row)
            new_row = build_row(DocumentTemplate, data, {
                "tenant_id": new_tenant_id,
                "filesystem_path": "",
                "configuration_json": remap_document_template_config(data.get("configuration_json"), part_map),
            })
            self.db.add(new_row)
            self.db.flush()
            id_map[row["id"]] = new_row.id
        self.db.commit()
        for new_id in id_map.values():
            template = self.document_template_service.repository.get(self.db, new_id)
            if template is None:
                continue
            path = self.document_template_service._materialize_template(self.db, template)
            self.document_template_service.repository.update(self.db, template, {"filesystem_path": path})
        return id_map

    # ── full-scope tables ─────────────────────────────────────────────────

    def _import_events(self, new_tenant_id: int, group_map: dict[int, int], participant_map: dict[int, int]) -> dict[int, int]:
        id_map: dict[int, int] = {}

        def remap_ids(ids: list[int] | None) -> list[int] | None:
            if not ids:
                return ids
            return [participant_map.get(i, i) for i in ids]

        for row in self._t("event"):
            data = self._resolve_row("event", row)
            new_row = build_row(Event, data, {
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
            new_row = build_row(ListEntry, row, {
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
        self, new_tenant_id: int, *, document_template_map, cycle_config_map, element_definition_map,
        event_map, participant_map, list_definition_map, list_entry_map, finance_account_map,
    ) -> tuple[dict[int, int], dict[int, int], dict[int, int]]:
        template_map: dict[int, int] = {}
        for row in self._t("template"):
            data = self._resolve_row("template", row)
            new_row = build_row(Template, data, {
                "tenant_id": new_tenant_id,
                "document_template_id": document_template_map.get(data["document_template_id"]) if data.get("document_template_id") else None,
                "next_event_id": event_map.get(data["next_event_id"]) if data.get("next_event_id") else None,
                "last_event_id": event_map.get(data["last_event_id"]) if data.get("last_event_id") else None,
                "cycle_config_id": cycle_config_map.get(data["cycle_config_id"]) if data.get("cycle_config_id") else None,
            })
            self.db.add(new_row)
            self.db.flush()
            template_map[row["id"]] = new_row.id
        self.db.commit()

        template_element_map: dict[int, int] = {}
        for row in self._t("template_element"):
            new_template_id = template_map.get(row["template_id"])
            if new_template_id is None:
                continue
            new_row = build_row(TemplateElement, row, {
                "template_id": new_template_id,
                "element_definition_id": element_definition_map.get(row["element_definition_id"], row["element_definition_id"]),
                "configuration_json": remap_template_element_config(
                    row.get("configuration_json"), participant_map=participant_map,
                    list_definition_map=list_definition_map, list_entry_map=list_entry_map,
                ),
            })
            self.db.add(new_row)
            self.db.flush()
            template_element_map[row["id"]] = new_row.id
        self.db.commit()

        template_element_block_map: dict[int, int] = {}
        for row in self._t("template_element_block"):
            new_template_element_id = template_element_map.get(row["template_element_id"])
            if new_template_element_id is None:
                continue
            new_row = build_row(TemplateElementBlock, row, {
                "template_element_id": new_template_element_id,
                "element_definition_id": element_definition_map.get(row["element_definition_id"], row["element_definition_id"]),
                "configuration_override_json": remap_block_configuration(
                    row.get("configuration_override_json"), participant_map=participant_map,
                    event_map=event_map, list_definition_map=list_definition_map, list_entry_map=list_entry_map,
                    finance_account_map=finance_account_map,
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

    def _import_submission_assignments(self, new_tenant_id: int, list_definition_map: dict[int, int]) -> dict[int, int]:
        id_map: dict[int, int] = {}
        for row in self._t("submission_assignment"):
            data = self._resolve_row("submission_assignment", row)
            new_row = build_row(SubmissionAssignment, data, {
                "tenant_id": new_tenant_id,
                "list_definition_id": list_definition_map.get(data["list_definition_id"]) if data.get("list_definition_id") else None,
            })
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
            new_row = build_row(SubmissionUpload, row, {
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
            self.db.add(build_row(SubmissionUploadLog, row, {"assignment_id": new_assignment_id}))
        self.db.commit()

    def _import_stored_files(self, new_tenant_id: int) -> dict[int, int]:
        abgabebox_ids = {row["stored_file_id"] for row in self._t("submission_upload_file")}
        id_map: dict[int, int] = {}
        for row in self._t("stored_file"):
            data = self._resolve_row("stored_file", row)
            is_abgabebox = row["id"] in abgabebox_ids
            root = settings.abgabebox_storage_root if is_abgabebox else settings.storage_root
            new_storage_path = self._restore_file(data.get("storage_path"), root=root, new_tenant_id=new_tenant_id, subdir="files")
            if new_storage_path is None:
                self.warnings.append(f"Datei '{row.get('original_name')}' fehlte im Export, übersprungen.")
                continue
            # SECURITY (audit S4, 2026-08-16): never trust data["scan_status"] from the
            # manifest (build_row() forces it to "pending" regardless, see
            # FORCED_SECURE_DEFAULTS) - actually run the restored bytes past ClamAV here,
            # the same way a fresh upload does (file_service.py's save_word_import_document),
            # so an imported file goes through the real scan workflow instead of either
            # trusting an attacker-supplied verdict or sitting at "pending" forever with no
            # sweep ever reaching it (the periodic rescan sweeps are scoped to their own
            # storage-path prefixes, which tenant-import restores don't share).
            absolute_path = Path(root).resolve() / new_storage_path
            scan_status = scanner.scan_file(absolute_path, host=settings.clamav_host, port=settings.clamav_port)
            if scan_status == "infected":
                absolute_path.unlink(missing_ok=True)
                self.warnings.append(f"Datei '{row.get('original_name')}' wurde von der Virenprüfung als infiziert erkannt und wurde nicht importiert.")
                continue
            new_row = build_row(StoredFile, data, {"tenant_id": new_tenant_id, "storage_path": new_storage_path, "scan_status": scan_status})
            self.db.add(new_row)
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
            self.db.add(build_row(SubmissionUploadFile, row, {"upload_id": new_upload_id, "stored_file_id": new_stored_file_id}))
        self.db.commit()

    def _import_protocols(self, new_tenant_id: int, template_map, document_template_map, event_map) -> dict[int, int]:
        id_map: dict[int, int] = {}
        for row in self._t("protocol"):
            data = self._resolve_row("protocol", row)
            new_template_id = template_map.get(data["template_id"])
            if new_template_id is None:
                continue
            new_row = build_row(Protocol, data, {
                "tenant_id": new_tenant_id,
                "template_id": new_template_id,
                "document_template_id": document_template_map.get(data["document_template_id"]) if data.get("document_template_id") else None,
                "event_id": event_map.get(data["event_id"]) if data.get("event_id") else None,
            })
            self.db.add(new_row)
            self.db.flush()
            id_map[row["id"]] = new_row.id
        self.db.commit()
        return id_map

    def _import_protocol_elements(self, protocol_map: dict[int, int], template_element_map: dict[int, int]) -> dict[int, int]:
        id_map: dict[int, int] = {}
        for row in self._t("protocol_element"):
            new_protocol_id = protocol_map.get(row["protocol_id"])
            if new_protocol_id is None:
                continue
            new_row = build_row(ProtocolElement, row, {
                "protocol_id": new_protocol_id,
                "template_element_id": template_element_map.get(row["template_element_id"]) if row.get("template_element_id") else None,
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
            new_row = build_row(ProtocolElementBlock, data, {
                "protocol_element_id": new_protocol_element_id,
                "template_element_block_id": template_element_block_map.get(data["template_element_block_id"]) if data.get("template_element_block_id") else None,
                "element_definition_id": element_definition_map.get(data["element_definition_id"]) if data.get("element_definition_id") else None,
                "configuration_snapshot_json": remap_block_configuration(
                    data.get("configuration_snapshot_json"), participant_map=participant_map,
                    event_map=event_map, list_definition_map=list_definition_map, list_entry_map=list_entry_map,
                    finance_account_map=finance_account_map,
                ),
            })
            self.db.add(new_row)
            self.db.flush()
            id_map[row["id"]] = new_row.id
        self.db.commit()
        return id_map

    def _import_protocol_texts(self, protocol_element_block_map: dict[int, int]) -> None:
        for row in self._t("protocol_text"):
            new_block_id = protocol_element_block_map.get(row["protocol_element_block_id"])
            if new_block_id is None:
                continue
            self.db.add(build_row(ProtocolText, row, {"protocol_element_block_id": new_block_id}))
        self.db.commit()

    def _import_protocol_display_snapshots(self, protocol_element_block_map: dict[int, int]) -> None:
        for row in self._t("protocol_display_snapshot"):
            new_block_id = protocol_element_block_map.get(row["protocol_element_block_id"])
            if new_block_id is None:
                continue
            self.db.add(build_row(ProtocolDisplaySnapshot, row, {"protocol_element_block_id": new_block_id}))
        self.db.commit()

    def _import_protocol_images(self, protocol_element_block_map: dict[int, int], stored_file_map: dict[int, int]) -> None:
        for row in self._t("protocol_image"):
            new_block_id = protocol_element_block_map.get(row["protocol_element_block_id"])
            new_stored_file_id = stored_file_map.get(row["stored_file_id"])
            if new_block_id is None or new_stored_file_id is None:
                continue
            self.db.add(build_row(ProtocolImage, row, {"protocol_element_block_id": new_block_id, "stored_file_id": new_stored_file_id}))
        self.db.commit()

    def _import_finance_transactions(self, finance_account_map: dict[int, int], protocol_map: dict[int, int]) -> dict[int, int]:
        id_map: dict[int, int] = {}
        for row in self._t("finance_transaction"):
            new_account_id = finance_account_map.get(row["account_id"])
            if new_account_id is None:
                continue
            new_row = build_row(FinanceTransaction, row, {
                "account_id": new_account_id,
                "protocol_id": protocol_map.get(row["protocol_id"]) if row.get("protocol_id") else None,
            })
            self.db.add(new_row)
            self.db.flush()
            id_map[row["id"]] = new_row.id
        self.db.commit()
        return id_map

    def _import_attendance_fines(self, protocol_map, participant_map, finance_account_map, finance_transaction_map) -> None:
        for row in self._t("attendance_fine"):
            data = self._resolve_row("attendance_fine", row)
            new_protocol_id = protocol_map.get(data["protocol_id"])
            new_account_id = finance_account_map.get(data["account_id"])
            if new_protocol_id is None or new_account_id is None:
                continue
            new_row = build_row(AttendanceFine, data, {
                "protocol_id": new_protocol_id,
                "participant_id": participant_map.get(data["participant_id"]) if data.get("participant_id") else None,
                "account_id": new_account_id,
                "collected_transaction_id": finance_transaction_map.get(data["collected_transaction_id"]) if data.get("collected_transaction_id") else None,
                "closed_in_protocol_id": protocol_map.get(data["closed_in_protocol_id"]) if data.get("closed_in_protocol_id") else None,
            })
            self.db.add(new_row)
        self.db.commit()

    def _import_protocol_todos(self, new_tenant_id, protocol_element_block_map, participant_map, event_map, protocol_map, submission_assignment_map) -> None:
        for row in self._t("protocol_todo"):
            data = self._resolve_row("protocol_todo", row)
            new_row = build_row(ProtocolTodo, data, {
                "tenant_id": new_tenant_id,
                "protocol_element_block_id": protocol_element_block_map.get(data["protocol_element_block_id"]) if data.get("protocol_element_block_id") else None,
                "assigned_participant_id": participant_map.get(data["assigned_participant_id"]) if data.get("assigned_participant_id") else None,
                "due_event_id": event_map.get(data["due_event_id"]) if data.get("due_event_id") else None,
                "closed_in_protocol_id": protocol_map.get(data["closed_in_protocol_id"]) if data.get("closed_in_protocol_id") else None,
                "submission_assignment_id": submission_assignment_map.get(data["submission_assignment_id"]) if data.get("submission_assignment_id") else None,
            })
            self.db.add(new_row)
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
            self.db.add(build_row(UserTemplateAccess, data, {"tenant_id": new_tenant_id, "template_id": new_template_id}))
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
            self.db.add(build_row(UserProtocolAccess, data, {"tenant_id": new_tenant_id, "protocol_id": new_protocol_id}))
        self.db.commit()

    def _import_user_tenant_roles(self, new_tenant_id: int) -> None:
        for row in self._t("user_tenant_role"):
            data = self._resolve_row("user_tenant_role", row)
            if data.get("user_id") is None:
                self._warn_missing_user("user_tenant_role", row.get("user_id"))
                continue
            self.db.add(build_row(UserTenantRole, data, {"tenant_id": new_tenant_id}))
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

    for member in infolist:
        _resolve_within_extract_dir(dest_dir, member.filename)
    zf.extractall(dest_dir)
