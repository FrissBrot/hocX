from __future__ import annotations

import asyncio
import re
import shutil
import subprocess
import unicodedata
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import AttendanceFine, Event, FinanceAccount, FinanceTransaction, ListDefinition, ListEntry, Participant, Protocol as ProtocolModel, ProtocolElement, ProtocolExportCache, StoredFile, Tenant
from app.repositories.export_repository import ExportRepository
from app.schemas.protocol import ProtocolExportRead


class ExportService:
    def __init__(self, repository: ExportRepository | None = None) -> None:
        self.repository = repository or ExportRepository()
        self.generator_version = "hocx-step8"

    def export_latex(self, db: Session, protocol_id: int) -> ProtocolExportRead:
        protocol, export_dir, latex_source, _body = self._build_export_context(db, protocol_id)
        main_tex_path = export_dir / "main.tex"
        main_tex_path.write_text(latex_source, encoding="utf-8")

        stored_file = self._store_generated_file(
            db,
            tenant_id=protocol.tenant_id,
            source_path=main_tex_path,
            original_name=self._export_filename(protocol, "tex"),
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

    async def export_pdf(self, db: Session, protocol_id: int) -> ProtocolExportRead:
        protocol, export_dir, latex_source, body_content = self._build_export_context(db, protocol_id)

        # Version tracking: compare body content (not main.tex — that contains a
        # unique UUID path that always differs between builds).
        prev_cache = self.repository.latest_export_cache(db, protocol_id)
        content_changed = (
            prev_cache is not None
            and prev_cache.latex_source is not None
            and prev_cache.latex_source != body_content
        )

        # Compute the new version BEFORE compiling so the PDF footer shows the
        # correct (already-bumped) version number.
        # Two independent counters:
        #   version_minor       → 0.x series (pre-abschluss)
        #   version_final_minor → 1.x series (abgeschlossen)
        # version_major is the display flag: 0 = draft, 1 = final.
        is_final = protocol.status == "abgeschlossen"
        new_major = 1 if is_final else 0
        new_minor = protocol.version_minor
        new_final_minor = protocol.version_final_minor
        if content_changed:
            if is_final:
                new_final_minor += 1
            else:
                new_minor += 1

        # Patch \HocxProtocolVersion in the LaTeX source with the new value
        display_minor = new_final_minor if is_final else new_minor
        new_version_str = f"v{new_major}.{display_minor}" if (new_major > 0 or display_minor > 0) else ""
        latex_source = re.sub(
            r"\\newcommand\{\\HocxProtocolVersion\}\{[^}]*\}",
            f"\\\\newcommand{{\\\\HocxProtocolVersion}}{{{new_version_str}}}",
            latex_source,
        )

        main_tex_path = export_dir / "main.tex"
        main_tex_path.write_text(latex_source, encoding="utf-8")
        try:
            await self._compile_pdf_async(main_tex_path)
        except Exception:
            shutil.rmtree(export_dir, ignore_errors=True)
            raise

        pdf_path = export_dir / "main.pdf"
        stored_file = self._store_generated_file(
            db,
            tenant_id=protocol.tenant_id,
            source_path=pdf_path,
            original_name=self._export_filename(protocol, "pdf"),
            mime_type="application/pdf",
        )
        # Clean up the working directory — the PDF is now in the persistent store
        shutil.rmtree(export_dir, ignore_errors=True)

        cache = self.repository.create_export_cache(
            db,
            ProtocolExportCache(
                protocol_id=protocol.id,
                export_format="pdf",
                latex_source=body_content,
                generated_file_id=stored_file.id,
                generator_version=self.generator_version,
            ),
        )

        if (new_major != protocol.version_major
                or new_minor != protocol.version_minor
                or new_final_minor != protocol.version_final_minor):
            protocol.version_major = new_major
            protocol.version_minor = new_minor
            protocol.version_final_minor = new_final_minor
            db.add(protocol)

        db.commit()
        db.refresh(protocol)

        return ProtocolExportRead(
            protocol_id=protocol.id,
            export_format="pdf",
            generated_file_id=stored_file.id,
            content_url=f"/api/stored-files/{stored_file.id}/content",
            storage_path=stored_file.storage_path,
            created_at=cache.created_at,
            status="generated",
            version_major=protocol.version_major,
            version_minor=protocol.version_final_minor if is_final else protocol.version_minor,
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

        # XeTeX resolves font paths relative to main.tex (= export_dir), not to the
        # \input'd theme.tex inside template/. Copy fonts so they're reachable.
        template_fonts_dir = template_copy_dir / "fonts"
        if template_fonts_dir.is_dir():
            shutil.copytree(template_fonts_dir, export_dir / "fonts", dirs_exist_ok=True)
            # Patch theme.tex: rewrite \setmainfont/\setsansfont to use fontspec
            # Path+Extension syntax instead of bare file paths (e.g. fonts/regular.ttf).
            # This is needed because fontspec resolves relative font paths via cwd,
            # which must point to export_dir for fonts/ to be found.
            self._patch_theme_fontspec(template_copy_dir / "styles" / "theme.tex")

        body_path = export_dir / "protocol_body.tex"
        body_content = self._render_protocol_body(db, protocol.id, export_dir)
        body_path.write_text(body_content, encoding="utf-8")

        latex_source = self._build_main_tex(protocol, template_copy_dir, body_path)
        return protocol, export_dir, latex_source, body_content

    def _build_main_tex(self, protocol, template_copy_dir: Path, body_path: Path) -> str:
        preamble = self._read_optional(template_copy_dir / "preamble.tex")
        theme = self._read_optional(template_copy_dir / "styles" / "theme.tex")
        macros = self._read_optional(template_copy_dir / "macros.tex")
        header_footer = self._read_optional(template_copy_dir / "header_footer.tex")
        title_page = self._read_optional(template_copy_dir / "title_page.tex")
        toc = self._read_optional(template_copy_dir / "toc.tex")
        protocol_number = self._escape_latex(protocol.protocol_number)
        protocol_title = self._escape_latex(protocol.title or "Untitled protocol")
        protocol_date = self._escape_latex(protocol.protocol_date.strftime("%d.%m.%Y"))
        protocol_status = self._escape_latex(protocol.status)
        protocol_version = self._escape_latex(
            f"v{protocol.version_major}.{protocol.version_minor}"
            if (protocol.version_major > 0 or protocol.version_minor > 0)
            else ""
        )
        include_toc = "\\setcounter{tocdepth}{-1}" not in theme
        # If the theme uses fontspec (XeTeX/LuaTeX), remove T1 fontenc from the preamble
        # to avoid "Corrupted NFSS tables" — fontspec handles encoding internally.
        uses_fontspec = "\\usepackage{fontspec}" in theme or "\\setmainfont" in theme
        preamble = self._normalize_preamble_tex(preamble, strip_fontenc=uses_fontspec)
        theme = self._normalize_theme_tex(theme)

        metadata_block = f"""\\section*{{Protocol Metadata}}
Protocol number: {protocol_number}\\\\
Title: {protocol_title}\\\\
Date: {protocol_date}\\\\
Status: {protocol_status}
"""

        return f"""\\documentclass{{article}}
{theme}
{preamble}
{macros}
\\newcommand{{\\HocxProtocolNumber}}{{{protocol_number}}}
\\newcommand{{\\HocxProtocolTitle}}{{{protocol_title}}}
\\newcommand{{\\HocxProtocolDate}}{{{protocol_date}}}
\\newcommand{{\\HocxProtocolStatus}}{{{protocol_status}}}
\\newcommand{{\\HocxProtocolVersion}}{{{protocol_version}}}
\\makeatletter
\\@ifpackageloaded{{microtype}}{{\\microtypesetup{{expansion=false}}}}{{}}
\\makeatother
\\setlength\\parindent{{0pt}}
\\setlength\\parskip{{0.6em}}
\\begin{{document}}
{header_footer}
{title_page}
{toc if include_toc else ""}
{metadata_block}
\\input{{{body_path.as_posix()}}}
\\end{{document}}
"""

    @staticmethod
    def _trim_section_name(name: str) -> str:
        return re.sub(r"\s*\(.*\)$", "", name).strip()

    def _render_protocol_body(self, db: Session, protocol_id: int, export_dir: Path) -> str:
        parts: list[str] = []
        image_export_dir = export_dir / "images"
        image_export_dir.mkdir(parents=True, exist_ok=True)

        for element in self.repository.list_protocol_elements(db, protocol_id):
            if not element.export_visible_snapshot:
                continue
            if self._trim_section_name(element.section_name_snapshot or "").lower() == "sitzungsnotizen":
                continue

            parts.append(f"\\section{{{self._escape_latex(element.section_name_snapshot)}}}")

            for block in self.repository.list_protocol_element_blocks(db, element.id):
                if not block.export_visible_snapshot:
                    continue

                block_heading = block.block_title_snapshot or block.display_title_snapshot or block.title_snapshot
                parts.append(self._render_block(db, block, block_heading, export_dir, image_export_dir))

            # Dynamic session todos: todos tagged with the (trimmed, lowercased) section name.
            # Skip "sitzungsnotizen" — those are internal session notes, not protocol content.
            section_tag = self._trim_section_name(element.section_name_snapshot or "").lower()
            if section_tag and section_tag != "sitzungsnotizen":
                session_todos = self.repository.list_todos_by_tag(db, protocol_id, section_tag)
                if session_todos:
                    parts.append("\\subsection*{Sitzungs-Todos}")
                    parts.append(self._render_todo_rows_latex(session_todos))

        return "\n".join(parts)

    def _render_block(self, db: Session, block, block_heading: str, export_dir: Path, image_export_dir: Path) -> str:
        content = self._default_block_content(db, block, image_export_dir)
        partial_path = self._resolve_partial_path(export_dir, block)
        if partial_path and partial_path.exists():
            template = partial_path.read_text(encoding="utf-8")
            return self._fill_block_partial(block, template, block_heading, content)

        if not str(block_heading or "").strip():
            return content

        return f"""{self._block_heading_markup(block, block_heading)}
{content}
"""

    def _resolve_partial_path(self, export_dir: Path, block) -> Path | None:
        if block.latex_template_snapshot:
            candidate = export_dir / "template" / block.latex_template_snapshot
            if candidate.exists():
                return candidate

        default_name = {
            1: "text.tex",
            2: "todo.tex",
            3: "image.tex",
            5: "static_text.tex",
            6: "form.tex",
            7: "events.tex",
            8: "bullet_list.tex",
            9: "attendance.tex",
            10: "session_date.tex",
            11: "matrix.tex",
        }.get(block.element_type_id)
        if default_name is None:
            return None
        candidate = export_dir / "template" / "elements" / default_name
        return candidate if candidate.exists() else None

    def _default_block_content(self, db: Session, block, image_export_dir: Path) -> str:
        if block.element_type_id == 1:
            text = self.repository.get_protocol_text(db, block.id)
            return self._markdown_to_latex(text.content if text else "")
        if block.element_type_id == 2:
            todo_rows = self.repository.list_protocol_todos(db, block.id)
            if not todo_rows:
                return "Keine offenen Todos."
            return self._render_todo_rows_latex(todo_rows)
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
        if block.element_type_id == 6:
            linked_list_id = int((block.configuration_snapshot_json or {}).get("linked_list_id") or 0)
            if linked_list_id:
                return self._linked_list_content(db, linked_list_id, block.configuration_snapshot_json or {})
            rows = block.configuration_snapshot_json.get("rows", []) if block.configuration_snapshot_json else []
            if not rows:
                return ""
            left_heading_raw = str((block.configuration_snapshot_json or {}).get("left_column_heading") or "").strip()
            value_heading_raw = str((block.configuration_snapshot_json or {}).get("value_column_heading") or "").strip()
            left_heading = self._escape_latex(left_heading_raw)
            value_heading = self._escape_latex(value_heading_raw)
            parts = ["\\begin{flushleft}", "\\begin{tabular}{p{0.28\\textwidth}p{0.64\\textwidth}}"]
            rendered_row_count = 0
            if left_heading_raw or value_heading_raw:
                parts.append(f"\\textbf{{{left_heading}}} & \\textbf{{{value_heading}}} \\\\")
            for row in rows:
                label = str(row.get("label") or "Feld").strip()
                value = self._form_row_value(db, row)
                if not str(value).strip():
                    continue
                parts.append(f"{self._escape_latex(label)} & {self._escape_latex(value)} \\\\")
                rendered_row_count += 1
            if rendered_row_count == 0:
                return ""
            parts.append("\\end{tabular}")
            parts.append("\\end{flushleft}")
            return "\n".join(parts)
        if block.element_type_id == 7:
            config = block.configuration_snapshot_json or {}
            protocol_element = db.get(ProtocolElement, block.protocol_element_id)
            protocol = self.repository.get_protocol(db, protocol_element.protocol_id) if protocol_element else None
            if protocol is None:
                return "No matching events."
            return self._event_list_content(db, protocol=protocol, config=config)
        if block.element_type_id == 8:
            items = block.configuration_snapshot_json.get("bullet_items", []) if block.configuration_snapshot_json else []
            if not items:
                return "No bullet points."
            lines = ["\\begin{itemize}"]
            for item in items:
                if str(item).strip():
                    lines.append(f"\\item {self._escape_latex(str(item))}")
            lines.append("\\end{itemize}")
            return "\n".join(lines)
        if block.element_type_id == 9:
            entries = block.configuration_snapshot_json.get("attendance_entries", []) if block.configuration_snapshot_json else []
            if not entries:
                return "No attendance captured."
            status_labels = {
                "present": "Anwesend",
                "late": "Verspaetet",
                "excused": "Entschuldigt",
                "absent": "Unentschuldigt",
            }
            counts: dict[str, int] = {"present": 0, "late": 0, "excused": 0, "absent": 0}
            lines = ["\\begin{flushleft}", "\\begin{tabular}{p{0.58\\textwidth}p{0.34\\textwidth}}"]
            for entry in entries:
                participant_name = entry.get("participant_name")
                if not participant_name and entry.get("participant_id"):
                    participant = db.get(Participant, int(entry["participant_id"]))
                    participant_name = participant.display_name if participant else "Unbekannt"
                raw_status = entry.get("status", "absent")
                if raw_status in counts:
                    counts[raw_status] += 1
                status = status_labels.get(raw_status, "—")
                lines.append(f"{self._escape_latex(str(participant_name or 'Teilnehmer'))} & {self._escape_latex(status)} \\\\")
            lines.append("\\end{tabular}")
            lines.append("\\end{flushleft}")
            lines.append(
                f"\\par\\smallskip\\noindent{{\\small\\color{{hocxSecondary}}"
                f"{counts['present']} Anwesend"
                f" $\\cdot$ {counts['late']} Verspaetet"
                f" $\\cdot$ {counts['excused']} Entschuldigt"
                f" $\\cdot$ {counts['absent']} Unentschuldigt"
                f"}}"
            )
            return "\n".join(lines)
        if block.element_type_id == 10:
            config = block.configuration_snapshot_json or {}
            selected_date = config.get("selected_date")
            label = config.get("session_label") or "Naechste Sitzung"
            if not selected_date:
                return self._escape_latex(f"{label}: offen")
            return self._escape_latex(f"{label}: {self._format_date_value(selected_date)}")
        if block.element_type_id == 11:
            protocol_element = db.get(ProtocolElement, block.protocol_element_id)
            protocol = self.repository.get_protocol(db, protocol_element.protocol_id) if protocol_element else None
            if protocol is None:
                return ""
            return self._matrix_block_content(db, block.configuration_snapshot_json or {}, protocol)
        if block.element_type_id == 12:
            return self._finance_balance_content(db, block.configuration_snapshot_json or {})
        if block.element_type_id == 13:
            return self._finance_transactions_content(db, block.configuration_snapshot_json or {}, block)
        if block.element_type_id == 14:
            protocol_element = db.get(ProtocolElement, block.protocol_element_id)
            if protocol_element is None:
                return "Keine Bussen."
            return self._fine_list_content(db, protocol_element.protocol_id)
        return self._escape_latex(block.description_snapshot or "")

    def _fill_block_partial(self, block, template: str, heading: str, content: str) -> str:
        heading_markup = self._block_heading_markup(block, heading)
        return (
            template.replace("\\subsection*{ {{ block_heading }} }", heading_markup)
            .replace("\\subsection{ {{ block_heading }} }", heading_markup)
            .replace("{{ block_heading_markup }}", heading_markup)
            .replace("{{ block_heading }}", self._escape_latex(heading))
            .replace("{{ block_content }}", content)
        )

    def _block_heading_markup(self, block, heading: str) -> str:
        if not str(heading or "").strip():
            return ""
        config = block.configuration_snapshot_json or {}
        title_as_subtitle = bool(config.get("title_as_subtitle", True))
        escaped_heading = self._escape_latex(heading)
        if title_as_subtitle:
            return f"\\subsection{{{escaped_heading}}}"
        return f"\\textbf{{{escaped_heading}}}\\\\"

    def _render_todo_rows_latex(self, rows) -> str:
        status_labels = {
            "open": "Offen",
            "in_progress": "Offen",
            "done": "Erledigt",
            "cancelled": "Abgebrochen",
        }
        has_assignee = any(getattr(r, "assigned_participant_name", None) for r in rows)
        has_due = any(
            getattr(r, "resolved_due_date", None) or getattr(r, "resolved_due_label", None)
            for r in rows
        )

        if has_assignee and has_due:
            col_spec = "p{0.08\\textwidth}p{0.48\\textwidth}p{0.20\\textwidth}p{0.18\\textwidth}"
            headers = ["\\textbf{Status}", "\\textbf{Aufgabe}", "\\textbf{Zugewiesen}", "\\textbf{F\\\"allig}"]
        elif has_assignee:
            col_spec = "p{0.08\\textwidth}p{0.56\\textwidth}p{0.28\\textwidth}"
            headers = ["\\textbf{Status}", "\\textbf{Aufgabe}", "\\textbf{Zugewiesen}"]
        elif has_due:
            col_spec = "p{0.08\\textwidth}p{0.58\\textwidth}p{0.28\\textwidth}"
            headers = ["\\textbf{Status}", "\\textbf{Aufgabe}", "\\textbf{F\\\"allig}"]
        else:
            col_spec = "p{0.08\\textwidth}p{0.84\\textwidth}"
            headers = ["\\textbf{Status}", "\\textbf{Aufgabe}"]

        parts = [
            "\\begin{flushleft}",
            f"\\begin{{tabular}}{{{col_spec}}}",
            " & ".join(headers) + " \\\\",
            "\\hline",
        ]
        for row in rows:
            label = status_labels.get(row.todo_status_code or "open", "Offen")
            cells = [self._escape_latex(label), self._escape_latex(row.ProtocolTodo.task)]
            if has_assignee:
                cells.append(self._escape_latex(getattr(row, "assigned_participant_name", None) or ""))
            if has_due:
                due = ""
                if getattr(row, "resolved_due_date", None):
                    due = row.resolved_due_date.strftime("%d.%m.%Y")
                    if getattr(row, "resolved_due_label", None):
                        due = f"{due} ({row.resolved_due_label})"
                elif getattr(row, "resolved_due_label", None):
                    due = str(row.resolved_due_label)
                cells.append(self._escape_latex(due))
            parts.append(" & ".join(cells) + " \\\\")
        parts += ["\\end{tabular}", "\\end{flushleft}"]
        return "\n".join(parts)

    def _event_list_columns(self, config: dict) -> dict[str, bool]:
        columns = {
            "date": config.get("event_show_date", True) is not False,
            "tag": config.get("event_show_tag", True) is not False,
            "title": config.get("event_show_title", True) is not False,
            "description": config.get("event_show_description", True) is not False,
            "participant_count": config.get("event_show_participant_count", False) is True,
        }
        if not any(columns.values()):
            columns["title"] = True
        return columns

    def _event_list_content(self, db: Session, *, protocol, config: dict, extra_tag_filter: str | None = None) -> str:
        tag_filters = [t.strip() for t in str(config.get("event_tag_filter") or "").lower().split(",") if t.strip()]
        combined_extra_tag_filters = [t.strip() for t in str(extra_tag_filter or "").lower().split(",") if t.strip()]
        only_from_protocol_date = bool(config.get("event_only_from_protocol_date", True))
        only_before_protocol_date = bool(config.get("event_only_before_protocol_date", False))
        gray_past = bool(config.get("event_gray_past", True))
        show_tag_colors = bool(config.get("event_show_tag_colors", False))
        tag_config: dict = {}
        if show_tag_colors:
            tenant = db.get(Tenant, protocol.tenant_id)
            if tenant is not None:
                tag_config = tenant.tag_config_json or {}
        columns = self._event_list_columns(config)
        events = list(
            db.scalars(
                select(Event).where(Event.tenant_id == protocol.tenant_id).order_by(Event.event_date.asc(), Event.id.asc())
            )
        )

        column_specs: list[str] = []
        headers: list[str] = []
        if columns["date"]:
            column_specs.append("p{0.28\\textwidth}")
            headers.append("Datum")
        if columns["tag"]:
            column_specs.append("p{0.10\\textwidth}")
            headers.append("Tag")
        if columns["title"]:
            column_specs.append("p{0.28\\textwidth}")
            headers.append("Titel")
        if columns["description"]:
            column_specs.append("p{0.18\\textwidth}")
            headers.append("Beschreibung")
        if columns["participant_count"]:
            column_specs.append("p{0.10\\textwidth}")
            headers.append("Teilnehmer")

        rows: list[str] = []
        for event in events:
            event_end_date = event.event_end_date or event.event_date
            event_tag_lower = (event.tag or "").lower()
            if tag_filters and not any(t in event_tag_lower for t in tag_filters):
                continue
            if combined_extra_tag_filters and not any(t in event_tag_lower for t in combined_extra_tag_filters):
                continue
            if only_before_protocol_date and protocol.protocol_date and event_end_date >= protocol.protocol_date:
                continue
            elif not only_before_protocol_date and only_from_protocol_date and protocol.protocol_date and event_end_date < protocol.protocol_date:
                continue

            cells: list[str] = []
            if columns["date"]:
                if event_end_date == event.event_date:
                    cells.append(event.event_date.strftime("%d.%m.%Y"))
                else:
                    date_range = f"{event.event_date.strftime('%d.%m.%Y')}~--~{event_end_date.strftime('%d.%m.%Y')}"
                    cells.append(f"\\mbox{{{date_range}}}")
            if columns["tag"]:
                raw_tags = [t.strip() for t in (event.tag or "").split(",") if t.strip()]
                if not raw_tags:
                    cells.append("-")
                elif not show_tag_colors:
                    cells.append(self._escape_latex(", ".join(raw_tags)))
                else:
                    parts: list[str] = []
                    for t in raw_tags:
                        escaped_t = self._escape_latex(t)
                        tag_color = (tag_config.get(t) or {}).get("color", "")
                        if tag_color and tag_color.startswith("#") and len(tag_color) == 7:
                            hex_color = tag_color[1:].upper()
                            escaped_t = f"\\textcolor[HTML]{{{hex_color}}}{{{escaped_t}}}"
                        parts.append(escaped_t)
                    cells.append(", ".join(parts))
            if columns["title"]:
                cells.append(self._escape_latex(event.title))
            if columns["description"]:
                cells.append(self._escape_latex(event.description or "-"))
            if columns["participant_count"]:
                cells.append(self._escape_latex(str(max(0, int(event.participant_count or 0)))))

            if gray_past and protocol.protocol_date and event_end_date < protocol.protocol_date:
                cells = [f"\\textcolor{{gray}}{{{cell}}}" for cell in cells]

            rows.append(" & ".join(cells) + " \\\\")

        if not rows:
            return "No matching events."

        return "\n".join(
            [
                f"\\begin{{tabular}}{{{''.join(column_specs)}}}",
                " & ".join(headers) + " \\\\",
                *rows,
                "\\end{tabular}",
            ]
        )

    def _fine_list_content(self, db: Session, protocol_id: int) -> str:
        fines = db.scalars(
            select(AttendanceFine)
            .where(AttendanceFine.protocol_id == protocol_id)
            .order_by(AttendanceFine.created_at.asc())
        ).all()
        if not fines:
            return "Keine Bussen."
        fine_type_labels = {"late": "Verspaetet", "absent": "Unentschuldigt"}
        status_labels = {"pending": "ausstehend", "collected": "kassiert"}
        lines = ["\\begin{flushleft}", "\\begin{tabular}{p{0.35\\textwidth}p{0.2\\textwidth}p{0.15\\textwidth}p{0.15\\textwidth}}"]
        lines.append("\\textbf{Teilnehmer} & \\textbf{Grund} & \\textbf{Betrag} & \\textbf{Status} \\\\")
        for fine in fines:
            account = db.get(FinanceAccount, fine.account_id)
            cur = account.currency_label if account else ""
            amount_str = f"{float(fine.amount):,.2f}".replace(",", "'")
            lines.append(
                f"{self._escape_latex(fine.participant_name_snapshot)} & "
                f"{self._escape_latex(fine_type_labels.get(fine.fine_type, fine.fine_type))} & "
                f"{self._escape_latex(amount_str + ' ' + cur)} & "
                f"{self._escape_latex(status_labels.get(fine.status, fine.status))} \\\\"
            )
        lines.append("\\end{tabular}")
        lines.append("\\end{flushleft}")
        return "\n".join(lines)

    def _finance_balance_content(self, db: Session, config: dict) -> str:
        account_id = int(config.get("finance_account_id") or 0)
        if not account_id:
            return "Kein Konto konfiguriert."
        account = db.get(FinanceAccount, account_id)
        if account is None:
            return "Konto nicht gefunden."
        from sqlalchemy import func
        result = db.execute(
            select(func.coalesce(func.sum(FinanceTransaction.amount), 0).label("balance"))
            .where(FinanceTransaction.account_id == account_id)
        ).one()
        balance = float(result.balance)
        sign = "" if balance >= 0 else "-"
        amount_str = f"{sign}{abs(balance):,.2f}".replace(",", "'")
        return self._escape_latex(f"{account.name}: {amount_str} {account.currency_label}") + "\n\n"

    def _finance_transactions_content(self, db: Session, config: dict, block) -> str:
        account_id = int(config.get("finance_account_id") or 0)
        if not account_id:
            return "Kein Konto konfiguriert."
        account = db.get(FinanceAccount, account_id)
        if account is None:
            return "Konto nicht gefunden."
        filter_type = str(config.get("finance_filter_type") or "all")
        last_n = int(config.get("finance_last_n") or 10)
        since_date = str(config.get("finance_since_date") or "")

        txs_query = select(FinanceTransaction).where(FinanceTransaction.account_id == account_id).order_by(FinanceTransaction.transaction_date.asc(), FinanceTransaction.id.asc())
        all_txs = list(db.scalars(txs_query))

        from datetime import date as date_type
        import datetime as dt_module
        this_year = dt_module.date.today().year
        filtered = []
        for tx in all_txs:
            if filter_type == "since_last_session":
                if since_date and str(tx.transaction_date) < since_date:
                    continue
            elif filter_type == "this_year":
                if tx.transaction_date.year != this_year:
                    continue
            filtered.append(tx)
        if filter_type == "last_n":
            filtered = filtered[-last_n:] if len(filtered) > last_n else filtered

        if not filtered:
            return "Keine Transaktionen."

        cur = account.currency_label
        running = 0.0
        lines = [
            "\\begin{flushleft}",
            "\\begin{tabular}{p{0.15\\textwidth}p{0.42\\textwidth}p{0.16\\textwidth}p{0.16\\textwidth}}",
            f"\\textbf{{Datum}} & \\textbf{{Beschreibung}} & \\textbf{{Betrag}} & \\textbf{{Saldo}} \\\\",
        ]
        for tx in filtered:
            running += float(tx.amount)
            date_str = tx.transaction_date.strftime("%d.%m.%Y")
            sign = "+" if float(tx.amount) >= 0 else ""
            amount_str = f"{sign}{float(tx.amount):,.2f}".replace(",", "'")
            running_str = f"{running:,.2f}".replace(",", "'")
            lines.append(
                f"{self._escape_latex(date_str)} & "
                f"{self._escape_latex(tx.description)} & "
                f"{self._escape_latex(amount_str + ' ' + cur)} & "
                f"{self._escape_latex(running_str + ' ' + cur)} \\\\"
            )
        lines.append("\\end{tabular}")
        lines.append("\\end{flushleft}")
        return "\n".join(lines)

    def _format_date_value(self, value: str | None) -> str:
        if not value:
            return ""
        try:
            return datetime.fromisoformat(value).strftime("%d.%m.%Y")
        except ValueError:
            if len(value) == 10 and value[4] == "-" and value[7] == "-":
                year, month, day = value.split("-")
                return f"{day}.{month}.{year}"
            return value

    def _form_row_value(self, db: Session, row: dict) -> str:
        value_type = row.get("value_type") or row.get("row_type") or "text"
        if value_type == "participant" and row.get("participant_id"):
            participant = db.get(Participant, int(row["participant_id"]))
            return participant.display_name if participant else ""
        if value_type == "participants" and row.get("participant_ids"):
            participants = [
                db.get(Participant, int(participant_id))
                for participant_id in row.get("participant_ids", [])
            ]
            return ", ".join(participant.display_name for participant in participants if participant)
        if value_type == "event" and row.get("event_id"):
            event = db.get(Event, int(row["event_id"]))
            if not event:
                return ""
            event_end_date = event.event_end_date or event.event_date
            date_part = (
                event.event_date.strftime("%d.%m.%Y")
                if event_end_date == event.event_date
                else f"{event.event_date.strftime('%d.%m.%Y')} - {event_end_date.strftime('%d.%m.%Y')}"
            )
            return f"{date_part} - {event.title}"
        return str(row.get("text_value") or "").strip()

    def _linked_list_value(self, db: Session, *, value_type: str, value: dict) -> str:
        return self._form_row_value(db, {"value_type": value_type, **(value or {})})

    def _linked_list_column_meta(self, definition: ListDefinition, column_key: str) -> tuple[str, str]:
        if column_key == "column_two":
            return definition.column_two_title, definition.column_two_value_type
        return definition.column_one_title, definition.column_one_value_type

    def _linked_list_entry_value(self, entry: ListEntry, column_key: str) -> dict:
        if column_key == "column_two":
            return dict(entry.column_two_value_json or {})
        return dict(entry.column_one_value_json or {})

    def _linked_list_sort_text(self, db: Session, *, value_type: str, value: dict) -> str:
        if value_type == "participant":
            participant_id = int(value.get("participant_id") or 0)
            if not participant_id:
                return ""
            participant = db.get(Participant, participant_id)
            return str(participant.display_name if participant else "").strip()
        if value_type == "participants":
            participant_ids = [int(item) for item in (value.get("participant_ids") or []) if int(item)]
            if not participant_ids:
                return ""
            participants = [
                participant
                for participant_id in participant_ids
                for participant in [db.get(Participant, participant_id)]
                if participant is not None
            ]
            participants.sort(key=lambda participant: (participant.display_name.casefold(), participant.id))
            return ", ".join(participant.display_name for participant in participants)
        if value_type == "event":
            event_id = int(value.get("event_id") or 0)
            if not event_id:
                return ""
            event = db.get(Event, event_id)
            return str(event.title if event else "").strip()
        return str(value.get("text_value") or "").strip()

    def _linked_list_sort_key(self, value: str) -> str:
        normalized = unicodedata.normalize("NFKD", str(value or "").strip())
        return "".join(character for character in normalized if not unicodedata.combining(character)).casefold()

    def _linked_list_inline_text(self, value: str | None) -> str:
        return " ".join(str(value or "").split()).strip()

    def _linked_list_content(self, db: Session, list_definition_id: int, config: dict | None = None) -> str:
        definition = db.get(ListDefinition, list_definition_id)
        if definition is None:
            return ""
        entries = list(
            db.scalars(
                select(ListEntry)
                .where(ListEntry.list_definition_id == list_definition_id)
                .order_by(ListEntry.sort_index.asc(), ListEntry.id.asc())
            )
        )
        if not entries:
            return ""

        config = config if isinstance(config, dict) else {}
        group_by = str(config.get("linked_list_group_by") or "").strip()
        if group_by not in {"column_one", "column_two"}:
            group_by = ""
        sort_by = str(config.get("linked_list_sort_by") or "").strip()
        if sort_by not in {"column_one", "column_two"}:
            sort_by = ""
        sort_direction = "desc" if str(config.get("linked_list_sort_direction") or "").strip().lower() == "desc" else "asc"

        rendered_entries: list[dict] = []
        for entry in entries:
            left_value = self._linked_list_value(
                db,
                value_type=definition.column_one_value_type,
                value=dict(entry.column_one_value_json or {}),
            )
            right_value = self._linked_list_value(
                db,
                value_type=definition.column_two_value_type,
                value=dict(entry.column_two_value_json or {}),
            )
            if not str(left_value).strip() and not str(right_value).strip():
                continue

            sort_text = ""
            if sort_by:
                _, sort_value_type = self._linked_list_column_meta(definition, sort_by)
                sort_text = self._linked_list_sort_text(
                    db,
                    value_type=sort_value_type,
                    value=self._linked_list_entry_value(entry, sort_by),
                )

            group_label = None
            if group_by:
                _, group_value_type = self._linked_list_column_meta(definition, group_by)
                group_raw_value = self._linked_list_entry_value(entry, group_by)
                group_rendered = self._linked_list_inline_text(
                    self._linked_list_value(db, value_type=group_value_type, value=group_raw_value)
                )
                group_label = group_rendered or "Ohne Wert"

            rendered_entries.append(
                {
                    "entry": entry,
                    "left_value": left_value,
                    "right_value": right_value,
                    "sort_key": self._linked_list_sort_key(sort_text),
                    "group_label": group_label,
                }
            )

        if not rendered_entries:
            return ""

        rendered_entries.sort(key=lambda item: (item["entry"].sort_index, item["entry"].id))
        if sort_by:
            filled_entries = [item for item in rendered_entries if item["sort_key"]]
            empty_entries = [item for item in rendered_entries if not item["sort_key"]]
            filled_entries.sort(key=lambda item: item["sort_key"], reverse=sort_direction == "desc")
            rendered_entries = filled_entries + empty_entries

        header_left = self._escape_latex(definition.column_one_title)
        header_right = self._escape_latex(definition.column_two_title)
        parts = ["\\begin{flushleft}", "\\begin{tabular}{p{0.46\\textwidth}p{0.46\\textwidth}}", f"\\textbf{{{header_left}}} & \\textbf{{{header_right}}} \\\\"]
        rendered_row_count = 0
        if group_by:
            grouped_rows: list[dict[str, object]] = []
            group_index: dict[str, int] = {}
            for item in rendered_entries:
                group_label = str(item["group_label"] or "Ohne Wert")
                group_key = self._linked_list_sort_key(group_label) or "__empty__"
                existing_index = group_index.get(group_key)
                if existing_index is None:
                    group_index[group_key] = len(grouped_rows)
                    grouped_rows.append(
                        {
                            "group_label": group_label,
                            "left_values": [str(item["left_value"] or "")],
                            "right_values": [str(item["right_value"] or "")],
                        }
                    )
                    continue
                grouped_rows[existing_index]["left_values"].append(str(item["left_value"] or ""))
                grouped_rows[existing_index]["right_values"].append(str(item["right_value"] or ""))

            for row in grouped_rows:
                merged_left = ", ".join(
                    value for value in (self._linked_list_inline_text(item) for item in row["left_values"]) if value
                )
                merged_right = ", ".join(
                    value for value in (self._linked_list_inline_text(item) for item in row["right_values"]) if value
                )
                left_cell = str(row["group_label"]) if group_by == "column_one" else merged_left
                right_cell = merged_right if group_by == "column_one" else str(row["group_label"])
                parts.append(f"{self._escape_latex(left_cell)} & {self._escape_latex(right_cell)} \\\\")
                rendered_row_count += 1
        else:
            for item in rendered_entries:
                parts.append(
                    f"{self._escape_latex(str(item['left_value']))} & {self._escape_latex(str(item['right_value']))} \\\\"
                )
                rendered_row_count += 1
        if rendered_row_count == 0:
            return ""
        parts.append("\\end{tabular}")
        parts.append("\\end{flushleft}")
        return "\n".join(parts)

    def _matrix_block_content(self, db: Session, config: dict, protocol) -> str:
        rows = sorted(
            (config.get("rows") or []),
            key=lambda entry: (entry.get("sort_index", 0), str(entry.get("id", ""))),
        )
        columns = config.get("columns") or []
        if not rows or not columns:
            return ""

        left_heading_raw = str(config.get("left_column_heading") or "").strip()
        left_heading = self._escape_latex(left_heading_raw)
        column_groups = [columns[i : i + 3] for i in range(0, len(columns), 3)]
        rendered_tables: list[str] = []

        for group in column_groups:
            rendered_rows: list[tuple[str, list[str]]] = []
            for row in rows:
                row_id = str(row.get("id") or "")
                values = [
                    self._matrix_row_value(
                        db,
                        row=row,
                        cell=self._matrix_cell(column, row_id),
                        protocol=protocol,
                        column=column,
                    )
                    for column in group
                ]
                if not any(str(value).strip() for value in values):
                    continue
                rendered_rows.append((self._escape_latex(str(row.get("label") or "Feld").strip()), values))

            if not rendered_rows:
                continue

            column_titles = [self._escape_latex(str(column.get("title") or "").strip()) for column in group]
            header_needed = bool(left_heading_raw or any(str(column.get("title") or "").strip() for column in group))
            left_width = 0.18
            value_width = 0.78 / max(len(group), 1)
            column_spec = "p{0.18\\textwidth}" + "".join(f"p{{{value_width:.2f}\\textwidth}}" for _ in group)
            lines = ["\\begin{flushleft}", f"\\begin{{tabular}}{{{column_spec}}}"]
            if header_needed:
                lines.append(
                    " & ".join(
                        [f"\\textbf{{{left_heading}}}" if left_heading_raw else ""]
                        + [f"\\textbf{{{title}}}" if title else "" for title in column_titles]
                    )
                    + " \\\\"
                )
            for label, values in rendered_rows:
                lines.append(f"{label} & " + " & ".join(values) + " \\\\")
            lines.append("\\end{tabular}")
            lines.append("\\end{flushleft}")
            rendered_tables.append("\n".join(lines))

        return "\n\\vspace{1em}\n".join(rendered_tables)

    def _matrix_cell(self, column: dict, row_id: str) -> dict:
        # New schema: row_values; old schema: values
        values = column.get("row_values") or column.get("values") or {}
        if not isinstance(values, dict):
            values = {}
        raw_cell = values.get(row_id)
        return raw_cell if isinstance(raw_cell, dict) else {}

    def _matrix_row_type(self, row: dict) -> str:
        """Resolve row_type from new or old schema."""
        if row.get("row_type"):
            return str(row["row_type"])
        if row.get("embedded_element_type_id"):
            return str(row["embedded_element_type_id"])
        return str(row.get("value_type") or "text")

    def _matrix_row_value(self, db: Session, *, row: dict, cell: dict, protocol, column: dict) -> str:
        embedded_block = cell.get("embedded_block")
        if isinstance(embedded_block, dict) and embedded_block.get("element_type_id"):
            return self._matrix_embedded_block_content(db, embedded_block=embedded_block, protocol=protocol, column=column)

        row_type = self._matrix_row_type(row)
        # If row_type is a numeric string it refers to an embedded block element type
        _named_types = {"text", "participant", "participants", "event", "events"}
        if row_type not in _named_types:
            try:
                embedded_type_id = int(row_type)
            except (TypeError, ValueError):
                return ""
            # Element type 7 = event list: render as newline-separated dates in cell
            if embedded_type_id == 7:
                return self._matrix_event_row_value(db, row=row, protocol=protocol, column=column)
            return ""

        primary_value = self._matrix_single_value(
            db,
            value_type=row_type,
            cell=cell,
            protocol=protocol,
            row=row,
            column=column,
            prefix="",
        )
        return primary_value

    def _matrix_event_row_value(self, db: Session, *, row: dict, protocol, column: dict) -> str:
        """Render event list row as newline-separated text for a matrix cell."""
        row_config = row.get("row_config") or {}
        events = self._matrix_events(db, row=row, protocol=protocol, column=column)
        if not events:
            return ""
        show_date = bool(row_config.get("event_show_date", True))
        show_count = bool(row_config.get("event_show_participant_count", False))
        gray_past = bool(row_config.get("event_gray_past", True))
        parts: list[str] = []
        for event in events:
            event_end_date = event.event_end_date or event.event_date
            if show_date:
                if event_end_date != event.event_date:
                    date_str = f"{event.event_date.strftime('%d.%m.%Y')} – {event_end_date.strftime('%d.%m.%Y')}"
                else:
                    date_str = event.event_date.strftime("%d.%m.%Y")
            else:
                date_str = self._escape_latex(event.title)
            if show_count and event.participant_count:
                line = f"{date_str} ({event.participant_count})"
            else:
                line = date_str
            line = line.strip()
            if not line:
                continue
            if gray_past and protocol.protocol_date and event_end_date < protocol.protocol_date:
                parts.append(f"\\textcolor{{gray}}{{{self._escape_latex(line)}}}")
            else:
                parts.append(self._escape_latex(line))
        return "\\newline ".join(parts)

    def _matrix_embedded_block_content(self, db: Session, *, embedded_block: dict, protocol, column: dict | None = None) -> str:
        try:
            element_type_id = int(embedded_block.get("element_type_id") or 0)
        except (TypeError, ValueError):
            return ""

        config = embedded_block.get("configuration_snapshot_json") if isinstance(embedded_block.get("configuration_snapshot_json"), dict) else {}

        if element_type_id in {1, 5}:
            return self._latex_multiline(str(embedded_block.get("text_content") or "").strip())

        if element_type_id == 2:
            todo_items = config.get("todo_items") if isinstance(config.get("todo_items"), list) else []
            lines = ["\\begin{itemize}"]
            rendered_count = 0
            for item in todo_items:
                if not isinstance(item, dict):
                    continue
                task = str(item.get("task") or "").strip()
                if not task:
                    continue
                prefix = "[x]" if bool(item.get("done")) else "[ ]"
                lines.append(f"\\item {self._escape_latex(f'{prefix} {task}')}")
                rendered_count += 1
            if rendered_count == 0:
                return ""
            lines.append("\\end{itemize}")
            return "\n".join(lines)

        if element_type_id == 3:
            images = config.get("images") if isinstance(config.get("images"), list) else []
            labels = []
            for item in images:
                if not isinstance(item, dict):
                    continue
                caption = str(item.get("caption") or "").strip()
                url = str(item.get("url") or "").strip()
                label = caption or url
                if label:
                    labels.append(f"Bild: {label}")
            return self._latex_multiline("\n".join(labels))

        if element_type_id == 6:
            linked_list_id = int(config.get("linked_list_id") or 0)
            if linked_list_id:
                return self._linked_list_content(db, linked_list_id, config)
            rows = config.get("rows") if isinstance(config.get("rows"), list) else []
            if not rows:
                return ""
            parts = ["\\begin{flushleft}", "\\begin{tabular}{p{0.24\\textwidth}p{0.52\\textwidth}}"]
            rendered_row_count = 0
            for row in rows:
                if not isinstance(row, dict):
                    continue
                value = self._form_row_value(db, row)
                if not str(value).strip():
                    continue
                label = self._escape_latex(str(row.get("label") or "Feld").strip())
                parts.append(f"{label} & {self._escape_latex(value)} \\\\")
                rendered_row_count += 1
            if rendered_row_count == 0:
                return ""
            parts.append("\\end{tabular}")
            parts.append("\\end{flushleft}")
            return "\n".join(parts)

        if element_type_id == 7:
            column_tag_filter = None
            if bool(config.get("event_use_column_tag_filter", False)) and isinstance(column, dict):
                column_tag_filter = str(column.get("event_tag_filter") or column.get("title") or "").strip() or None
            return self._event_list_content(db, protocol=protocol, config=config, extra_tag_filter=column_tag_filter)

        if element_type_id == 8:
            bullet_items = config.get("bullet_items") if isinstance(config.get("bullet_items"), list) else []
            lines = ["\\begin{itemize}"]
            rendered_count = 0
            for item in bullet_items:
                text = str(item or "").strip()
                if not text:
                    continue
                lines.append(f"\\item {self._escape_latex(text)}")
                rendered_count += 1
            if rendered_count == 0:
                return ""
            lines.append("\\end{itemize}")
            return "\n".join(lines)

        if element_type_id == 9:
            entries = config.get("attendance_entries") if isinstance(config.get("attendance_entries"), list) else []
            if not entries:
                return ""
            status_labels = {
                "present": "Anwesend",
                "late": "Anwesend (verspaetet)",
                "excused": "Entschuldigt",
                "absent": "Unentschuldigt",
            }
            lines = ["\\begin{flushleft}", "\\begin{tabular}{p{0.44\\textwidth}p{0.32\\textwidth}}"]
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                participant_name = entry.get("participant_name")
                if not participant_name and entry.get("participant_id"):
                    participant = db.get(Participant, int(entry["participant_id"]))
                    participant_name = participant.display_name if participant else "Unbekannt"
                status = status_labels.get(entry.get("status"), "—")
                lines.append(f"{self._escape_latex(str(participant_name or 'Teilnehmer'))} & {self._escape_latex(status)} \\\\")
            lines.append("\\end{tabular}")
            lines.append("\\end{flushleft}")
            return "\n".join(lines)

        if element_type_id == 10:
            selected_date = config.get("selected_date")
            label = config.get("session_label") or "Naechste Sitzung"
            if not selected_date:
                return self._escape_latex(f"{label}: offen")
            return self._escape_latex(f"{label}: {self._format_date_value(str(selected_date))}")

        return ""

    def _matrix_single_value(self, db: Session, *, value_type: str, cell: dict, protocol, row: dict, column: dict, prefix: str) -> str:
        if value_type == "participant":
            participant_id = cell.get(f"{prefix}participant_id") or row.get("template_participant_id")
            if not participant_id:
                return ""
            participant = db.get(Participant, int(participant_id))
            return self._latex_multiline(participant.display_name if participant else "")
        if value_type == "participants":
            participant_ids = cell.get(f"{prefix}participant_ids") or row.get("template_participant_ids") or []
            if not participant_ids:
                return ""
            participants = [db.get(Participant, int(participant_id)) for participant_id in participant_ids]
            return self._latex_multiline(", ".join(participant.display_name for participant in participants if participant))
        if value_type == "event":
            event_id = cell.get(f"{prefix}event_id") or row.get("template_event_id")
            if not event_id:
                return ""
            event = db.get(Event, int(event_id))
            if not event:
                return ""
            return self._latex_multiline(self._event_inline_label(event))
        if value_type == "events":
            events = self._matrix_events(db, row=row, protocol=protocol, column=column)
            if not events:
                return ""
            return "\\newline ".join(self._escape_latex(self._event_inline_label(event)) for event in events)
        return self._latex_multiline(str(cell.get(f"{prefix}text_value") or row.get("template_value") or "").strip())

    def _matrix_events(self, db: Session, *, row: dict, protocol, column: dict) -> list[Event]:
        # New schema: event filters live in row_config; old schema: directly on row
        _row_config = row.get("row_config") or {}
        tag_filter_raw = str(row.get("event_tag_filter") or _row_config.get("event_tag_filter") or "").strip().lower()
        tag_filters_matrix = [t.strip() for t in tag_filter_raw.split(",") if t.strip()]
        title_filter = str(row.get("event_title_filter") or _row_config.get("event_title_filter") or "").strip().lower()
        # hide_past_events / event_only_from_protocol_date are the same concept under different names
        hide_past_events = bool(
            row.get("hide_past_events",
            _row_config.get("hide_past_events",
            _row_config.get("event_only_from_protocol_date", True)))
        )
        # Column tag: prefer explicit event_tag_filter on the column, fall back to column title
        use_col_tag = bool(
            row.get("event_use_column_tag_filter")
            or _row_config.get("event_use_column_tag_filter")
            or row.get("use_column_title_as_tag", _row_config.get("use_column_title_as_tag", True))
        )
        column_tag_filter = ""
        if use_col_tag:
            column_tag_filter = str(column.get("event_tag_filter") or column.get("title") or "").strip().lower()
        events = list(
            db.scalars(
                select(Event)
                .where(Event.tenant_id == protocol.tenant_id)
                .order_by(Event.event_date.asc(), Event.id.asc())
            )
        )
        filtered: list[Event] = []
        for event in events:
            effective_end_date = event.event_end_date or event.event_date
            if hide_past_events and effective_end_date < protocol.protocol_date:
                continue
            event_tag_lower_m = (event.tag or "").lower()
            if tag_filters_matrix and not any(t in event_tag_lower_m for t in tag_filters_matrix):
                continue
            if column_tag_filter and column_tag_filter not in event_tag_lower_m:
                continue
            if title_filter and title_filter not in event.title.lower():
                continue
            filtered.append(event)
        return filtered

    def _event_inline_label(self, event: Event) -> str:
        if event.event_end_date and event.event_end_date != event.event_date:
            label = f"{event.event_date.strftime('%d.%m.%Y')} - {event.event_end_date.strftime('%d.%m.%Y')}"
        else:
            label = event.event_date.strftime("%d.%m.%Y")
        if event.description:
            label += f" ({event.description})"
        return label

    def _latex_multiline(self, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        return "\\newline ".join(self._escape_latex(line) for line in text.splitlines() if line.strip()) or self._escape_latex(text)

    def _export_filename(self, protocol, extension: str) -> str:
        base_name = (protocol.title or protocol.protocol_number or f"protocol-{protocol.id}").strip()
        sanitized = re.sub(r"[^A-Za-z0-9._ -]+", "-", base_name).strip(" .-_")
        if not sanitized:
            sanitized = f"protocol-{protocol.id}"
        return f"{sanitized}.{extension}"

    def _normalize_preamble_tex(self, content: str, strip_fontenc: bool = False) -> str:
        if "\\usepackage{microtype}" in content:
            content = content.replace(
                "\\usepackage{microtype}",
                "\\usepackage[protrusion=true,expansion=false]{microtype}",
            )
        if strip_fontenc:
            # fontspec (XeTeX/LuaTeX) handles encoding itself; T1 fontenc conflicts with it
            for _pkg in (
                "\\usepackage[T1]{fontenc}",
                "\\usepackage[T1]{fontenc}\n\\IfFileExists{lmodern.sty}{\\usepackage{lmodern}}{}",
                "\\usepackage{lmodern}",
                "\\IfFileExists{lmodern.sty}{\\usepackage{lmodern}}{}",
            ):
                content = content.replace(_pkg, "")
        elif (
            "\\usepackage[T1]{fontenc}" in content
            and "\\usepackage{lmodern}" not in content
            and "\\IfFileExists{lmodern.sty}{\\usepackage{lmodern}}{}" not in content
        ):
            content = content.replace(
                "\\usepackage[T1]{fontenc}",
                "\\usepackage[T1]{fontenc}\n\\IfFileExists{lmodern.sty}{\\usepackage{lmodern}}{}",
                1,
            )
        return content

    def _patch_theme_fontspec(self, theme_path: Path) -> None:
        """Rewrite bare-path \\setmainfont{fonts/x.ttf}[...] to Path+Extension syntax."""
        import re as _re
        if not theme_path.exists():
            return
        text = theme_path.read_text(encoding="utf-8")
        # Match: \setmainfont{path/stem.ext}[...] or \setsansfont{...}[...]
        pattern = _re.compile(
            r'(\\(?:setmainfont|setsansfont))\{([^}]+)\}(\[[^\]]*\])?'
        )
        def _rewrite(m: _re.Match) -> str:
            cmd = m.group(1)
            font_path_str = m.group(2)
            rest = m.group(3) or ""
            p = Path(font_path_str)
            stem = p.stem
            ext = p.suffix or ".ttf"
            directory = p.parent.as_posix()
            font_dir = (directory + "/") if directory and directory != "." else "./"
            # Parse existing options, strip Path/Extension, simplify font file refs
            opts_str = rest.strip("[]")
            simplified = []
            for o in opts_str.split(","):
                o = o.strip()
                if not o or o.startswith("Path=") or o.startswith("Extension="):
                    continue
                # Simplify BoldFont={path/stem.ext} → BoldFont=stem
                simplified_opt = _re.sub(
                    r'(BoldFont|ItalicFont|BoldItalicFont)=\{?([^,}\]]+)\}?',
                    lambda mo: f"{mo.group(1)}={Path(mo.group(2).strip()).stem}",
                    o,
                )
                simplified.append(simplified_opt)
            opts = [f"Path={font_dir}", f"Extension={ext}"] + simplified
            return f"{cmd}[{','.join(opts)}]{{{stem}}}"
        patched = pattern.sub(_rewrite, text)
        if patched != text:
            theme_path.write_text(patched, encoding="utf-8")

    def _normalize_theme_tex(self, content: str) -> str:
        if "\\setcounter{secnumdepth}" not in content:
            content += "\n\\setcounter{secnumdepth}{2}\n"
        if "\\setcounter{tocdepth}" not in content:
            content += "\n\\setcounter{tocdepth}{2}\n"
        return content

    def _read_optional(self, path: Path) -> str:
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def _resolve_compiler(self, main_tex_path: Path) -> str:
        source = main_tex_path.read_text(encoding="utf-8")
        if "\\usepackage{fontspec}" in source or "\\setmainfont" in source:
            if shutil.which("xelatex"):
                return "xelatex"
            if shutil.which("lualatex"):
                return "lualatex"
            raise RuntimeError(
                "Custom fonts require xelatex or lualatex in the backend container. "
                "Rebuild the backend image after updating the Dockerfile."
            )
        return "pdflatex"

    async def _compile_pdf_async(self, main_tex_path: Path) -> None:
        compiler = self._resolve_compiler(main_tex_path)
        command = [
            compiler,
            "-interaction=nonstopmode",
            "-halt-on-error",
            f"-output-directory={main_tex_path.parent.as_posix()}",
            main_tex_path.as_posix(),
        ]
        result = None
        # Run twice: first pass writes .toc/.aux, second pass uses them for TOC/refs.
        for _ in range(2):
            proc = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=main_tex_path.parent,
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.communicate()
                raise RuntimeError("PDF compilation timed out after 120s")
            result = proc
            result.stdout_text = stdout.decode(errors="replace")
            result.stderr_text = stderr.decode(errors="replace")
        if result is not None and result.returncode != 0:
            raise RuntimeError(f"pdflatex failed: {result.stderr_text or result.stdout_text}")

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
        # Single-pass per-character replacement to avoid double-escaping
        # (sequential str.replace would re-escape the {} in \textbackslash{})
        _MAP = {
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
        return "".join(_MAP.get(c, c) for c in str(value))

    def _escape_latex_text(self, value: str) -> str:
        """Escape LaTeX special chars except * and _ (handled by markdown parser)."""
        _MAP = {
            "\\": "\\textbackslash{}",
            "&": "\\&",
            "%": "\\%",
            "$": "\\$",
            "#": "\\#",
            "{": "\\{",
            "}": "\\}",
            "~": "\\textasciitilde{}",
            "^": "\\textasciicircum{}",
        }
        return "".join(_MAP.get(c, c) for c in str(value))

    def _inline_markdown_to_latex(self, text: str) -> str:
        """Convert inline markdown (bold/italic) to LaTeX with proper escaping."""
        parts: list[str] = []
        i = 0
        while i < len(text):
            # Markdown backslash escape: \* \_ \\ etc. → literal character
            if text[i] == "\\" and i + 1 < len(text) and text[i + 1] in ("*", "_", "\\", "{", "}", "`"):
                parts.append(self._escape_latex_text(text[i + 1]))
                i += 2
                continue
            if text[i:i+2] == "**":
                end = text.find("**", i + 2)
                if end != -1:
                    parts.append(f"\\textbf{{{self._inline_markdown_to_latex(text[i+2:end])}}}")
                    i = end + 2
                    continue
            if text[i] == "*":
                end = text.find("*", i + 1)
                if end != -1 and end > i + 1:
                    parts.append(f"\\textit{{{self._inline_markdown_to_latex(text[i+1:end])}}}")
                    i = end + 1
                    continue
            if text[i] == "_":
                end = text.find("_", i + 1)
                if end != -1 and end > i + 1:
                    parts.append(f"\\textit{{{self._inline_markdown_to_latex(text[i+1:end])}}}")
                    i = end + 1
                    continue
            # Collect plain text up to next markdown marker
            j = i + 1
            while j < len(text) and text[j] not in ("*", "_", "\\"):
                j += 1
            parts.append(self._escape_latex_text(text[i:j]))
            i = j
        return "".join(parts)

    def _markdown_to_latex(self, text: str) -> str:
        """Convert simple markdown text to LaTeX."""
        lines = text.split("\n")
        result: list[str] = []
        in_itemize = False
        in_enumerate = False
        pending: list[str] = []

        def flush_para() -> None:
            if pending:
                result.append(" ".join(pending))
                pending.clear()

        def close_list() -> None:
            nonlocal in_itemize, in_enumerate
            flush_para()
            if in_itemize:
                result.append(r"\end{itemize}")
                in_itemize = False
            if in_enumerate:
                result.append(r"\end{enumerate}")
                in_enumerate = False

        for line in lines:
            ul_m = re.match(r"^- (.+)", line)
            ol_m = re.match(r"^\d+\. (.+)", line)
            if ul_m:
                flush_para()
                if in_enumerate:
                    result.append(r"\end{enumerate}")
                    in_enumerate = False
                if not in_itemize:
                    result.append(r"\begin{itemize}")
                    in_itemize = True
                result.append(r"\item " + self._inline_markdown_to_latex(ul_m.group(1)))
            elif ol_m:
                flush_para()
                if in_itemize:
                    result.append(r"\end{itemize}")
                    in_itemize = False
                if not in_enumerate:
                    result.append(r"\begin{enumerate}")
                    in_enumerate = True
                result.append(r"\item " + self._inline_markdown_to_latex(ol_m.group(1)))
            elif line.strip() == "":
                flush_para()
                close_list()
                if result and result[-1] != "":
                    result.append("")
            else:
                if in_itemize or in_enumerate:
                    close_list()
                pending.append(self._inline_markdown_to_latex(line))

        close_list()
        flush_para()
        return "\n".join(result)
