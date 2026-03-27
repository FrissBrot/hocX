from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import DocumentTemplate, DocumentTemplatePart, Protocol
from app.repositories.document_template_repository import (
    DocumentTemplatePartRepository,
    DocumentTemplateRepository,
)
from app.schemas.document_template import (
    DocumentTemplateCreate,
    DocumentTemplatePartCreate,
    DocumentTemplatePartRead,
    DocumentTemplatePartUpdate,
    DocumentTemplateRead,
    DocumentTemplateUpdate,
)


PART_SLOT_FILES = {
    "preamble": "preamble.tex",
    "macros": "macros.tex",
    "title_page": "title_page.tex",
    "header_footer": "header_footer.tex",
    "toc": "toc.tex",
    "element_text": "elements/text.tex",
    "element_todo": "elements/todo.tex",
    "element_image": "elements/image.tex",
    "element_display": "elements/display.tex",
    "element_static_text": "elements/static_text.tex",
}


class DocumentTemplateService:
    def __init__(
        self,
        repository: DocumentTemplateRepository | None = None,
        part_repository: DocumentTemplatePartRepository | None = None,
    ) -> None:
        self.repository = repository or DocumentTemplateRepository()
        self.part_repository = part_repository or DocumentTemplatePartRepository()

    def list_document_templates(self, db: Session, tenant_id: int) -> list[DocumentTemplateRead]:
        return [DocumentTemplateRead.model_validate(item) for item in self.repository.list(db, tenant_id)]

    def get_document_template(self, db: Session, document_template_id: int) -> DocumentTemplateRead | None:
        template = self.repository.get(db, document_template_id)
        return DocumentTemplateRead.model_validate(template) if template else None

    def create_document_template(self, db: Session, payload: DocumentTemplateCreate, *, tenant_id: int) -> DocumentTemplateRead:
        entity = DocumentTemplate(
            tenant_id=tenant_id,
            code=payload.code,
            name=payload.name,
            description=payload.description,
            filesystem_path="",
            version=payload.version,
            is_active=payload.is_active,
            is_default=payload.is_default,
            configuration_json=payload.configuration_json,
        )
        created = self.repository.create(db, entity)
        path = self._materialize_template(db, created)
        updated = self.repository.update(db, created, {"filesystem_path": path})
        if updated.is_default:
            self._unset_other_defaults(db, updated.id, updated.tenant_id)
            updated = self.repository.get(db, updated.id)
        return DocumentTemplateRead.model_validate(updated)

    def update_document_template(self, db: Session, document_template_id: int, payload: DocumentTemplateUpdate) -> DocumentTemplateRead | None:
        entity = self.repository.get(db, document_template_id)
        if entity is None:
            return None
        values = payload.model_dump(exclude_unset=True)
        if values:
            updated = self.repository.update(db, entity, values)
        else:
            updated = entity
        path = self._materialize_template(db, updated)
        updated = self.repository.update(db, updated, {"filesystem_path": path})
        if updated.is_default:
            self._unset_other_defaults(db, updated.id, updated.tenant_id)
            updated = self.repository.get(db, updated.id)
        return DocumentTemplateRead.model_validate(updated)

    def delete_document_template(self, db: Session, document_template_id: int) -> bool:
        entity = self.repository.get(db, document_template_id)
        if entity is None:
            return False
        path = Path(entity.filesystem_path)
        self.repository.delete(db, entity)
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)
        return True

    def list_document_template_parts(self, db: Session, tenant_id: int) -> list[DocumentTemplatePartRead]:
        return [DocumentTemplatePartRead.model_validate(item) for item in self.part_repository.list(db, tenant_id)]

    async def create_document_template_part(
        self,
        db: Session,
        payload: DocumentTemplatePartCreate,
        file: UploadFile,
        *,
        tenant_id: int,
    ) -> DocumentTemplatePartRead:
        storage_payload = DocumentTemplatePartCreate(
            tenant_id=tenant_id,
            code=payload.code,
            name=payload.name,
            part_type=payload.part_type,
            description=payload.description,
            version=payload.version,
            is_active=payload.is_active,
        )
        storage_path = await self._save_part_file(storage_payload, file)
        entity = DocumentTemplatePart(
            tenant_id=tenant_id,
            code=payload.code,
            name=payload.name,
            part_type=payload.part_type,
            description=payload.description,
            storage_path=storage_path,
            version=payload.version,
            is_active=payload.is_active,
        )
        created = self.part_repository.create(db, entity)
        return DocumentTemplatePartRead.model_validate(created)

    async def update_document_template_part(
        self,
        db: Session,
        part_id: int,
        payload: DocumentTemplatePartUpdate,
        file: UploadFile | None = None,
    ) -> DocumentTemplatePartRead | None:
        entity = self.part_repository.get(db, part_id)
        if entity is None:
            return None
        values = payload.model_dump(exclude_unset=True)
        if file is not None:
            part_payload = DocumentTemplatePartCreate(
                tenant_id=entity.tenant_id,
                code=values.get("code", entity.code),
                name=values.get("name", entity.name),
                part_type=values.get("part_type", entity.part_type),
                description=values.get("description", entity.description),
                version=values.get("version", entity.version),
                is_active=values.get("is_active", entity.is_active),
            )
            values["storage_path"] = await self._save_part_file(part_payload, file)
        if not values:
            return DocumentTemplatePartRead.model_validate(entity)
        updated = self.part_repository.update(db, entity, values)
        self._refresh_templates_using_part(db, updated.id)
        return DocumentTemplatePartRead.model_validate(updated)

    def delete_document_template_part(self, db: Session, part_id: int) -> bool:
        entity = self.part_repository.get(db, part_id)
        if entity is None:
            return False
        path = Path(settings.storage_root) / entity.storage_path
        self.part_repository.delete(db, entity)
        if path.exists():
            path.unlink()
        self._refresh_templates_using_part(db, part_id)
        return True

    def snapshot_template_for_protocol(self, db: Session, protocol: Protocol, document_template_id: int | None) -> Protocol:
        if document_template_id is None:
            protocol.document_template_id = None
            protocol.document_template_version = None
            protocol.document_template_path_snapshot = None
            db.add(protocol)
            db.commit()
            db.refresh(protocol)
            return protocol

        document_template = self.repository.get(db, document_template_id)
        if document_template is None:
            raise ValueError("Document template not found")
        source_dir = Path(document_template.filesystem_path)
        if not source_dir.exists():
            raise ValueError("Document template files are missing")

        snapshot_dir = (
            Path(settings.storage_root)
            / "document_template_snapshots"
            / f"tenant-{protocol.tenant_id}"
            / f"protocol-{protocol.id}"
            / f"document-template-{document_template.id}-v{document_template.version}"
        )
        if snapshot_dir.exists():
            shutil.rmtree(snapshot_dir)
        snapshot_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source_dir, snapshot_dir)

        protocol.document_template_id = document_template.id
        protocol.document_template_version = document_template.version
        protocol.document_template_path_snapshot = str(snapshot_dir)
        db.add(protocol)
        db.commit()
        db.refresh(protocol)
        return protocol

    async def _save_part_file(self, payload: DocumentTemplatePartCreate, file: UploadFile) -> str:
        suffix = Path(file.filename or "part.tex").suffix or ".tex"
        target_dir = (
            Path(settings.storage_root)
            / "document_template_parts"
            / f"tenant-{payload.tenant_id}"
            / payload.part_type
            / payload.code
        )
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / f"v{payload.version}{suffix}"
        content = await file.read()
        target_path.write_bytes(content)
        return str(target_path.relative_to(settings.storage_root))

    def _materialize_template(self, db: Session, template: DocumentTemplate) -> str:
        output_dir = (
            Path(settings.storage_root)
            / "document_templates"
            / f"tenant-{template.tenant_id}"
            / f"{template.code}-v{template.version}"
        )
        if output_dir.exists():
            shutil.rmtree(output_dir)
        (output_dir / "elements").mkdir(parents=True, exist_ok=True)
        (output_dir / "styles").mkdir(parents=True, exist_ok=True)

        config = template.configuration_json or {}
        slots = config.get("slots", {})
        parts_by_id = {part.id: part for part in self.part_repository.list(db, template.tenant_id)}

        for slot, relative_path in PART_SLOT_FILES.items():
            content = ""
            part_id = slots.get(slot)
            if part_id and part_id in parts_by_id:
                part_file = Path(settings.storage_root) / parts_by_id[part_id].storage_path
                if part_file.exists():
                    content = part_file.read_text(encoding="utf-8")
            target = output_dir / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")

        (output_dir / "styles" / "theme.tex").write_text(
            self._build_theme_tex(config.get("theme", {}), config.get("options", {})),
            encoding="utf-8",
        )
        (output_dir / "main.tex").write_text(self._build_main_tex(), encoding="utf-8")
        return str(output_dir)

    def _build_main_tex(self) -> str:
        return """\\documentclass{article}
\\input{styles/theme.tex}
\\input{preamble.tex}
\\input{macros.tex}
\\begin{document}
\\input{header_footer.tex}
\\input{title_page.tex}
\\input{toc.tex}
\\input{protocol_body.tex}
\\end{document}
"""

    def _unset_other_defaults(self, db: Session, template_id: int, tenant_id: int) -> None:
        db.execute(
            update(DocumentTemplate)
            .where(DocumentTemplate.tenant_id == tenant_id, DocumentTemplate.id != template_id)
            .values(is_default=False)
        )
        db.commit()

    def _refresh_templates_using_part(self, db: Session, part_id: int) -> None:
        part = self.part_repository.get(db, part_id)
        if part is None:
            return
        templates = self.repository.list(db, tenant_id=part.tenant_id)
        for template in templates:
            slots = (template.configuration_json or {}).get("slots", {})
            if part_id in slots.values():
                path = self._materialize_template(db, template)
                self.repository.update(db, template, {"filesystem_path": path})

    def default_document_template_id(self, db: Session, tenant_id: int) -> int | None:
        templates = self.repository.list(db, tenant_id)
        for template in templates:
            if template.is_default and template.is_active:
                return template.id
        return templates[0].id if templates else None

    def part_type_choices(self) -> list[str]:
        return list(PART_SLOT_FILES.keys())

    def slot_choices(self) -> list[str]:
        return list(PART_SLOT_FILES.keys())

    def _build_theme_tex(self, theme: dict, options: dict) -> str:
        primary = str(theme.get("primary_color", "A83F2F")).replace("#", "")
        secondary = str(theme.get("secondary_color", "6F675D")).replace("#", "")
        font_size = str(theme.get("font_size", "11pt"))
        font_family = theme.get("font_family", "default")
        show_toc = bool(options.get("show_toc", True))
        numbering = options.get("numbering_mode", "sections")

        font_setup = ""
        if font_family == "helvet":
            font_setup = "% helvet requested; container falls back to default roman font\n"
        elif font_family == "palatino":
            font_setup = "% palatino requested; container falls back to default roman font\n"

        numbering_setup = "\\setcounter{secnumdepth}{0}\n"
        if numbering == "sections":
            numbering_setup = "\\setcounter{secnumdepth}{2}\n"

        toc_setup = "\\setcounter{tocdepth}{2}\n" if show_toc else "\\setcounter{tocdepth}{-1}\n"
        font_size_value = font_size.replace("pt", "")
        baseline_size = str(int(font_size_value) + 2) if font_size_value.isdigit() else "13"

        return f"""\\usepackage[utf8]{{inputenc}}
\\usepackage{{graphicx}}
\\usepackage{{float}}
\\usepackage{{hyperref}}
\\usepackage[a4paper,margin=2.5cm]{{geometry}}
\\usepackage{{xcolor}}
\\definecolor{{hocxPrimary}}{{HTML}}{{{primary}}}
\\definecolor{{hocxSecondary}}{{HTML}}{{{secondary}}}
\\makeatletter
\\renewcommand\\section{{\\@startsection{{section}}{{1}}{{\\z@}}{{-3.5ex \\@plus -1ex \\@minus -.2ex}}{{2.3ex \\@plus.2ex}}{{\\normalfont\\Large\\bfseries\\color{{hocxPrimary}}}}}}
\\renewcommand\\subsection{{\\@startsection{{subsection}}{{2}}{{\\z@}}{{-3.25ex\\@plus -1ex \\@minus -.2ex}}{{1.5ex \\@plus .2ex}}{{\\normalfont\\large\\bfseries\\color{{hocxSecondary}}}}}}
\\makeatother
\\color{{black}}
\\AtBeginDocument{{\\fontsize{{{font_size_value}}}{{{baseline_size}}}\\selectfont}}
{font_setup}{numbering_setup}{toc_setup}
"""
