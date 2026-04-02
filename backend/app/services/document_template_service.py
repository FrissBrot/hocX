from __future__ import annotations

import re
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
    "element_static_text": "elements/static_text.tex",
    "element_form": "elements/form.tex",
    "element_events": "elements/events.tex",
    "element_bullet_list": "elements/bullet_list.tex",
    "element_attendance": "elements/attendance.tex",
    "element_session_date": "elements/session_date.tex",
}

FONT_SLOT_TARGETS = {
    "font_regular": "fonts/regular",
    "font_bold": "fonts/bold",
    "font_italic": "fonts/italic",
    "font_bold_italic": "fonts/bold_italic",
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

    def ensure_default_template_for_tenant(self, db: Session, tenant_id: int, tenant_name: str | None = None) -> DocumentTemplate:
        existing = self.repository.list(db, tenant_id)
        for template in existing:
            if template.is_default and template.is_active:
                path = self._materialize_template(db, template)
                refreshed = self.repository.update(db, template, {"filesystem_path": path})
                return refreshed
        for template in existing:
            if template.code == "default_protocol":
                values = {
                    "name": template.name or "Default Protocol",
                    "description": template.description or "Default polished protocol layout",
                    "is_default": True,
                    "is_active": True,
                    "configuration_json": self._default_template_configuration(tenant_name),
                }
                updated = self.repository.update(db, template, values)
                path = self._materialize_template(db, updated)
                return self.repository.update(db, updated, {"filesystem_path": path})

        entity = DocumentTemplate(
            tenant_id=tenant_id,
            code="default_protocol",
            name="Default Protocol",
            description="Default polished protocol layout",
            filesystem_path="",
            version=1,
            is_active=True,
            is_default=True,
            configuration_json=self._default_template_configuration(tenant_name),
        )
        created = self.repository.create(db, entity)
        path = self._materialize_template(db, created)
        return self.repository.update(db, created, {"filesystem_path": path})

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

    def _generate_part_code(self, db: Session, *, tenant_id: int, name: str, part_type: str, version: int) -> str:
        base = re.sub(r"[^a-z0-9]+", "-", f"{part_type}-{name}".lower()).strip("-")
        if not base:
            base = f"{part_type}-part"
        existing_codes = {
            part.code
            for part in self.part_repository.list(db, tenant_id)
            if part.version == version and part.code
        }
        if base not in existing_codes:
            return base
        suffix = 2
        while f"{base}-{suffix}" in existing_codes:
            suffix += 1
        return f"{base}-{suffix}"

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
            code=payload.code or self._generate_part_code(db, tenant_id=tenant_id, name=payload.name, part_type=payload.part_type, version=payload.version),
            name=payload.name,
            part_type=payload.part_type,
            description=payload.description,
            version=payload.version,
            is_active=payload.is_active,
        )
        storage_path = await self._save_part_file(storage_payload, file)
        entity = DocumentTemplatePart(
            tenant_id=tenant_id,
            code=storage_payload.code or "",
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
            if not content:
                content = self._default_slot_content(slot)
            target = output_dir / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")

        font_files: dict[str, str] = {}
        theme_config = config.get("theme", {})
        font_slots = theme_config.get("font_parts", {})
        for slot, target_stem in FONT_SLOT_TARGETS.items():
            part_id = font_slots.get(slot)
            if not part_id or part_id not in parts_by_id:
                continue
            part_file = Path(settings.storage_root) / parts_by_id[part_id].storage_path
            if not part_file.exists():
                continue
            suffix = part_file.suffix or ".ttf"
            target = output_dir / f"{target_stem}{suffix}"
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(part_file, target)
            font_files[slot] = target.relative_to(output_dir).as_posix()

        options = config.get("options", {})
        (output_dir / "styles" / "theme.tex").write_text(
            self._build_theme_tex(theme_config, options, font_files),
            encoding="utf-8",
        )
        (output_dir / "main.tex").write_text(
            self._build_main_tex(show_toc=bool(options.get("show_toc", True))),
            encoding="utf-8",
        )
        return str(output_dir)

    def _default_template_configuration(self, tenant_name: str | None = None) -> dict:
        return {
            "theme": {
                "primary_color": "174B7A",
                "secondary_color": "4F6D7A",
                "font_size": "11pt",
                "font_family": "arial",
                "font_parts": {},
                "tenant_name": tenant_name or "",
            },
            "options": {
                "show_toc": True,
                "numbering_mode": "sections",
            },
            "slots": {},
        }

    def _default_slot_content(self, slot: str) -> str:
        if slot == "preamble":
            return r"""\usepackage[T1]{fontenc}
\usepackage[english]{babel}
\IfFileExists{lmodern.sty}{\usepackage{lmodern}}{}
\usepackage[protrusion=true,expansion=false]{microtype}
\usepackage{tabularx}
\usepackage{array}
\usepackage{longtable}
\usepackage{booktabs}
\usepackage{fancyhdr}
\usepackage{setspace}
\onehalfspacing
"""
        if slot == "macros":
            return r"""\newcommand{\HocxMetaLine}[2]{\noindent\textbf{#1}\hfill #2\par}
"""
        if slot == "title_page":
            return r"""\begin{titlepage}
\thispagestyle{empty}
\vspace*{2.5cm}
{\color{hocxPrimary}\Huge\bfseries \HocxProtocolTitle\par}
\vspace{0.75cm}
{\Large \HocxProtocolNumber\par}
\vspace{1.5cm}
\begin{tabular}{@{}p{0.26\textwidth}p{0.62\textwidth}@{}}
\textbf{Datum} & \HocxProtocolDate \\
\textbf{Status} & \HocxProtocolStatus \\
\end{tabular}
\vfill
\noindent\color{hocxPrimary}\rule{\textwidth}{1.2pt}
\vspace{0.3cm}
\noindent\color{hocxSecondary}\rule{\textwidth}{0.6pt}
\end{titlepage}
"""
        if slot == "header_footer":
            return r"""\pagestyle{fancy}
\fancyhf{}
\fancyhead[L]{\color{hocxSecondary}\small \HocxProtocolNumber}
\fancyhead[R]{\color{hocxSecondary}\small \HocxProtocolDate}
\fancyfoot[L]{\color{hocxSecondary}\small \HocxProtocolStatus}
\fancyfoot[R]{\color{hocxSecondary}\small Seite \thepage}
\renewcommand{\headrulewidth}{0.4pt}
\renewcommand{\footrulewidth}{0.4pt}
"""
        if slot == "toc":
            return r"""\tableofcontents
\clearpage
"""
        if slot == "element_text":
            return "{{ block_heading_markup }}\n{{ block_content }}\n"
        if slot == "element_todo":
            return r"""{{ block_heading_markup }}
\begin{flushleft}
{{ block_content }}
\end{flushleft}
"""
        if slot == "element_image":
            return r"""{{ block_heading_markup }}
{{ block_content }}
"""
        if slot == "element_static_text":
            return "{{ block_content }}\n"
        if slot == "element_form":
            return r"""{{ block_heading_markup }}
{{ block_content }}
"""
        if slot == "element_events":
            return r"""{{ block_heading_markup }}
{{ block_content }}
"""
        if slot == "element_bullet_list":
            return r"""{{ block_heading_markup }}
{{ block_content }}
"""
        if slot == "element_attendance":
            return r"""{{ block_heading_markup }}
{{ block_content }}
"""
        if slot == "element_session_date":
            return r"""{{ block_heading_markup }}
{{ block_content }}
"""
        return ""

    def _build_main_tex(self, *, show_toc: bool = True) -> str:
        toc_include = "\\input{toc.tex}\n" if show_toc else ""
        return f"""\\documentclass{{article}}
\\input{{styles/theme.tex}}
\\input{{preamble.tex}}
\\input{{macros.tex}}
\\begin{{document}}
\\input{{header_footer.tex}}
\\input{{title_page.tex}}
{toc_include}\\input{{protocol_body.tex}}
\\end{{document}}
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
        return [*PART_SLOT_FILES.keys(), *FONT_SLOT_TARGETS.keys()]

    def slot_choices(self) -> list[str]:
        return [*PART_SLOT_FILES.keys(), *FONT_SLOT_TARGETS.keys()]

    def _build_theme_tex(self, theme: dict, options: dict, font_files: dict[str, str] | None = None) -> str:
        primary = str(theme.get("primary_color", "A83F2F")).replace("#", "")
        secondary = str(theme.get("secondary_color", "6F675D")).replace("#", "")
        font_size = str(theme.get("font_size", "11pt"))
        font_family = theme.get("font_family", "arial")
        show_toc = bool(options.get("show_toc", True))
        numbering = options.get("numbering_mode", "sections")
        font_files = font_files or {}

        font_setup = ""
        if font_family in {"arial", "helvet"}:
            font_setup = "\\usepackage[scaled=0.98]{helvet}\n\\renewcommand{\\familydefault}{\\sfdefault}\n"
        elif font_family == "palatino":
            font_setup = "\\usepackage{mathpazo}\n"
        elif font_family in {"century_gothic", "uploaded"}:
            if font_files.get("font_regular"):
                from pathlib import PurePosixPath as _P
                def _stem(p: str) -> str:
                    return _P(p).stem
                def _dir(p: str) -> str:
                    d = _P(p).parent.as_posix()
                    return d + "/" if d and d != "." else "./"
                def _ext(p: str) -> str:
                    return _P(p).suffix or ".ttf"
                regular = font_files["font_regular"]
                bold = font_files.get("font_bold", regular)
                italic = font_files.get("font_italic", regular)
                bold_italic = font_files.get("font_bold_italic", bold if bold != regular else italic)
                font_path = _dir(regular)
                font_ext = _ext(regular)
                r, b, i, bi = _stem(regular), _stem(bold), _stem(italic), _stem(bold_italic)
                font_opts = (
                    f"Path={font_path},Extension={font_ext},"
                    f"BoldFont={b},ItalicFont={i},BoldItalicFont={bi}"
                )
                font_setup = (
                    "\\usepackage{iftex}\n"
                    "\\ifPDFTeX\n"
                    "\\usepackage[scaled=0.98]{helvet}\n"
                    "\\renewcommand{\\familydefault}{\\sfdefault}\n"
                    "\\else\n"
                    "\\usepackage{fontspec}\n"
                    "\\defaultfontfeatures{Ligatures=TeX}\n"
                    f"\\setmainfont[{font_opts}]{{{r}}}\n"
                    f"\\setsansfont[{font_opts}]{{{r}}}\n"
                    "\\fi\n"
                )
            else:
                font_setup = "\\usepackage[scaled=0.98]{helvet}\n\\renewcommand{\\familydefault}{\\sfdefault}\n"

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
