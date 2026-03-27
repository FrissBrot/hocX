from __future__ import annotations

import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import ProtocolExportCache, StoredFile
from app.repositories.export_repository import ExportRepository
from app.schemas.protocol import ProtocolExportRead


class ExportService:
    def __init__(self, repository: ExportRepository | None = None) -> None:
        self.repository = repository or ExportRepository()
        self.generator_version = "hocx-step8"

    def export_latex(self, db: Session, protocol_id: int) -> ProtocolExportRead:
        protocol, export_dir, latex_source = self._build_export_context(db, protocol_id)
        main_tex_path = export_dir / "main.tex"
        main_tex_path.write_text(latex_source, encoding="utf-8")

        stored_file = self._store_generated_file(
            db,
            tenant_id=protocol.tenant_id,
            source_path=main_tex_path,
            original_name=f"{protocol.protocol_number}.tex",
            mime_type="application/x-tex",
        )
        cache = self.repository.create_export_cache(
            db,
            ProtocolExportCache(
                protocol_id=protocol.id,
                export_format="latex",
                latex_source=latex_source,
                generated_file_id=stored_file.id,
                generator_version=self.generator_version,
            ),
        )
        db.commit()

        return ProtocolExportRead(
            protocol_id=protocol.id,
            export_format="latex",
            generated_file_id=stored_file.id,
            content_url=f"/api/stored-files/{stored_file.id}/content",
            storage_path=stored_file.storage_path,
            created_at=cache.created_at,
            status="generated",
        )

    def export_pdf(self, db: Session, protocol_id: int) -> ProtocolExportRead:
        protocol, export_dir, latex_source = self._build_export_context(db, protocol_id)
        main_tex_path = export_dir / "main.tex"
        main_tex_path.write_text(latex_source, encoding="utf-8")
        self._compile_pdf(main_tex_path)

        pdf_path = export_dir / "main.pdf"
        stored_file = self._store_generated_file(
            db,
            tenant_id=protocol.tenant_id,
            source_path=pdf_path,
            original_name=f"{protocol.protocol_number}.pdf",
            mime_type="application/pdf",
        )
        cache = self.repository.create_export_cache(
            db,
            ProtocolExportCache(
                protocol_id=protocol.id,
                export_format="pdf",
                latex_source=latex_source,
                generated_file_id=stored_file.id,
                generator_version=self.generator_version,
            ),
        )
        db.commit()

        return ProtocolExportRead(
            protocol_id=protocol.id,
            export_format="pdf",
            generated_file_id=stored_file.id,
            content_url=f"/api/stored-files/{stored_file.id}/content",
            storage_path=stored_file.storage_path,
            created_at=cache.created_at,
            status="generated",
        )

    def latest_export_metadata(self, db: Session, protocol_id: int) -> ProtocolExportRead:
        cache = self.repository.latest_export_cache(db, protocol_id)
        if cache is None:
            return ProtocolExportRead(protocol_id=protocol_id, export_format="none", status="missing")

        stored_file = self.repository.get_stored_file(db, cache.generated_file_id)
        return ProtocolExportRead(
            protocol_id=protocol_id,
            export_format=cache.export_format,
            generated_file_id=cache.generated_file_id,
            content_url=f"/api/stored-files/{stored_file.id}/content" if stored_file else None,
            storage_path=stored_file.storage_path if stored_file else None,
            created_at=cache.created_at,
            status="generated",
        )

    def _build_export_context(self, db: Session, protocol_id: int):
        protocol = self.repository.get_protocol(db, protocol_id)
        if protocol is None:
            raise ValueError("Protocol not found")

        template_path = Path(protocol.document_template_path_snapshot or "")
        if not template_path.exists():
            raise ValueError("Document template snapshot path not found")

        export_dir = (
            Path(settings.export_root)
            / f"protocol-{protocol.id}"
            / f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:8]}"
        )
        export_dir.mkdir(parents=True, exist_ok=True)
        template_copy_dir = export_dir / "template"
        shutil.copytree(template_path, template_copy_dir)

        body_path = export_dir / "protocol_body.tex"
        body_path.write_text(self._render_protocol_body(db, protocol.id, export_dir), encoding="utf-8")

        latex_source = self._build_main_tex(protocol, template_copy_dir, body_path)
        return protocol, export_dir, latex_source

    def _build_main_tex(self, protocol, template_copy_dir: Path, body_path: Path) -> str:
        preamble = self._read_optional(template_copy_dir / "preamble.tex")
        theme = self._read_optional(template_copy_dir / "styles" / "theme.tex")
        macros = self._read_optional(template_copy_dir / "macros.tex")
        header_footer = self._read_optional(template_copy_dir / "header_footer.tex")
        title_page = self._read_optional(template_copy_dir / "title_page.tex")
        toc = self._read_optional(template_copy_dir / "toc.tex")

        metadata_block = f"""\\section*{{Protocol Metadata}}
Protocol number: {self._escape_latex(protocol.protocol_number)}\\\\
Title: {self._escape_latex(protocol.title or "Untitled protocol")}\\\\
Date: {self._escape_latex(str(protocol.protocol_date))}\\\\
Status: {self._escape_latex(protocol.status)}
"""

        return f"""\\documentclass{{article}}
{theme}
{preamble}
{macros}
\\setlength\\parindent{{0pt}}
\\setlength\\parskip{{0.6em}}
\\begin{{document}}
{header_footer}
{title_page}
{toc}
{metadata_block}
\\input{{{body_path.as_posix()}}}
\\end{{document}}
"""

    def _render_protocol_body(self, db: Session, protocol_id: int, export_dir: Path) -> str:
        parts: list[str] = []
        image_export_dir = export_dir / "images"
        image_export_dir.mkdir(parents=True, exist_ok=True)

        for element in self.repository.list_protocol_elements(db, protocol_id):
            if not element.export_visible_snapshot:
                continue

            parts.append(f"\\section*{{{self._escape_latex(element.section_name_snapshot)}}}")

            for block in self.repository.list_protocol_element_blocks(db, element.id):
                if not block.export_visible_snapshot:
                    continue

                block_heading = block.block_title_snapshot or block.display_title_snapshot or block.title_snapshot
                parts.append(self._render_block(db, block, block_heading, export_dir, image_export_dir))

        return "\n".join(parts)

    def _render_block(self, db: Session, block, block_heading: str, export_dir: Path, image_export_dir: Path) -> str:
        content = self._default_block_content(db, block, image_export_dir)
        partial_path = None
        if block.latex_template_snapshot:
            partial_path = export_dir / "template" / block.latex_template_snapshot
        if partial_path and partial_path.exists():
            template = partial_path.read_text(encoding="utf-8")
            return self._fill_block_partial(template, block_heading, content)

        return f"""\\subsection*{{{self._escape_latex(block_heading)}}}
{content}
"""

    def _default_block_content(self, db: Session, block, image_export_dir: Path) -> str:
        if block.element_type_id == 1:
            text = self.repository.get_protocol_text(db, block.id)
            return self._escape_latex(text.content if text else "")
        if block.element_type_id == 2:
            todo_rows = self.repository.list_protocol_todos(db, block.id)
            if not todo_rows:
                return "No open items."
            lines = ["\\begin{itemize}"]
            for row in todo_rows:
                label = row.todo_status_code or "unknown"
                lines.append(f"\\item [{self._escape_latex(label)}] {self._escape_latex(row.ProtocolTodo.task)}")
            lines.append("\\end{itemize}")
            return "\n".join(lines)
        if block.element_type_id == 3:
            image_rows = self.repository.list_protocol_images(db, block.id)
            if not image_rows:
                return "No images uploaded."
            parts: list[str] = []
            for index, row in enumerate(image_rows, start=1):
                source_path = Path(settings.storage_root) / row.StoredFile.storage_path
                if not source_path.exists():
                    parts.append(f"Missing image file: {self._escape_latex(row.StoredFile.original_name)}")
                    continue
                copied_path = image_export_dir / f"block-{block.id}-{index}{source_path.suffix}"
                shutil.copy2(source_path, copied_path)
                caption = row.ProtocolImage.caption or row.ProtocolImage.title or row.StoredFile.original_name
                parts.extend(
                    [
                        "\\begin{figure}[H]",
                        "\\centering",
                        f"\\includegraphics[width=0.82\\textwidth]{{{copied_path.as_posix()}}}",
                        f"\\caption*{{{self._escape_latex(caption)}}}",
                        "\\end{figure}",
                    ]
                )
            return "\n".join(parts)
        return self._escape_latex(block.description_snapshot or "No snapshot text available.")

    def _fill_block_partial(self, template: str, heading: str, content: str) -> str:
        return (
            template.replace("{{ block_heading }}", self._escape_latex(heading))
            .replace("{{ block_content }}", content)
        )

    def _read_optional(self, path: Path) -> str:
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def _compile_pdf(self, main_tex_path: Path) -> None:
        command = [
            "pdflatex",
            "-interaction=nonstopmode",
            "-halt-on-error",
            f"-output-directory={main_tex_path.parent.as_posix()}",
            main_tex_path.as_posix(),
        ]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(f"pdflatex failed: {result.stderr or result.stdout}")

    def _store_generated_file(self, db: Session, *, tenant_id: int, source_path: Path, original_name: str, mime_type: str):
        target_dir = Path(settings.export_root) / "generated"
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / f"{uuid4().hex}-{source_path.name}"
        shutil.copy2(source_path, target_path)
        relative_path = target_path.relative_to(settings.storage_root)
        stored_file = StoredFile(
            tenant_id=tenant_id,
            original_name=original_name,
            mime_type=mime_type,
            storage_path=str(relative_path),
            latex_path=None,
            file_size_bytes=target_path.stat().st_size,
            checksum_sha256=None,
            created_by=None,
        )
        return self.repository.create_stored_file(db, stored_file)

    def _escape_latex(self, value: str) -> str:
        replacements = {
            "\\": "\\textbackslash{}",
            "&": "\\&",
            "%": "\\%",
            "$": "\\$",
            "#": "\\#",
            "_": "\\_",
            "{": "\\{",
            "}": "\\}",
            "~": "\\textasciitilde{}",
            "^": "\\textasciicircum{}",
        }
        escaped = value
        for old, new in replacements.items():
            escaped = escaped.replace(old, new)
        return escaped
