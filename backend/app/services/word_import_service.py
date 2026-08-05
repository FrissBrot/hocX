from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from difflib import SequenceMatcher
from io import BytesIO

from docx import Document
from docx.oxml.ns import qn
from docx.table import Table as DocxTable
from docx.text.paragraph import Paragraph as DocxParagraph
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.cycle_utils import get_cycle_year
from app.repositories.participant_repository import participant_eligible_on
from app.models import (
    CycleConfig,
    ElementDefinition,
    ElementType,
    Event,
    ListDefinition,
    ListEntry,
    Participant,
    Protocol,
    ProtocolElement,
    ProtocolElementBlock,
    ProtocolText,
    Template,
    TemplateElement,
    TemplateParticipant,
    WordImportProfile,
)
from app.schemas.event import CycleAssignment, EventCreate, EventUpdate
from app.schemas.participant import ParticipantCreate
from app.schemas.protocol import ProtocolCreateFromTemplate, ProtocolUpdate
from app.schemas.word_import import (
    TablePreview,
    WordImportAnalysis,
    WordImportAttendanceMapping,
    WordImportCommit,
    WordImportEventCandidate,
    WordImportEventMapping,
    WordImportFormFieldValue,
    WordImportFormRow,
    WordImportListDefinitionOption,
    WordImportListEntryCandidate,
    WordImportListRowCommit,
    WordImportListRowMapping,
    WordImportNameResolution,
    WordImportTextMapping,
    WordImportTextTarget,
)
from app.services.event_service import EventService
from app.services.participant_service import ParticipantService
from app.services.protocol_service import ProtocolService

_GERMAN_MONTHS = {
    "januar": 1, "februar": 2, "märz": 3, "maerz": 3, "april": 4, "mai": 5, "juni": 6,
    "juli": 7, "august": 8, "september": 9, "oktober": 10, "november": 11, "dezember": 12,
}
_EXCUSED_KEYWORDS = ("entschuldigt", "excused")
_ABSENT_KEYWORDS = ("abwesend", "unentschuldigt", "absent")
_LATE_KEYWORDS = ("verspätet", "verspaetet", "spät", "late")
_ATTENDANCE_TABLE_KEYWORDS = ("name", "teilnehmer", "mitglied", "anwesend")
_EVENT_TABLE_KEYWORDS = ("datum", "termin", "anlass", "sitzung")
_NAME_SPLIT_PATTERN = re.compile(r"[,/&]| und ")

_DATE_PATTERN = re.compile(r"(\d{1,2})\.\s?(\d{1,2})\.\s?(\d{2,4})")
_DATE_TEXT_PATTERN = re.compile(r"(\d{1,2})\.?\s+(" + "|".join(_GERMAN_MONTHS) + r")\s+(\d{4})", re.IGNORECASE)

_EVENT_MATCH_THRESHOLD = 0.8
_EVENT_CHANGE_THRESHOLD = 0.45
_LIST_NAME_MATCH_THRESHOLD = 0.5
_PARTICIPANT_MATCH_THRESHOLD = 0.6
_CANDIDATE_LIMIT = 5
_LIST_ENTRY_CANDIDATE_MIN_SCORE = 0.3


@dataclass
class ParsedSection:
    heading: str
    text: str


@dataclass
class ParsedTable:
    index: int
    header_cells: list[str]
    rows: list[list[str]]
    preceding_heading: str | None
    known_role: str | None = None


@dataclass
class ParsedDocx:
    protocol_date: date | None
    title_hint: str | None
    sections: list[ParsedSection] = field(default_factory=list)
    tables: list[ParsedTable] = field(default_factory=list)


_UMLAUT_FOLD = str.maketrans({"ä": "a", "ö": "o", "ü": "u", "ß": "ss"})


def _fold_umlauts(text: str) -> str:
    return text.translate(_UMLAUT_FOLD)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", _fold_umlauts(text.strip().lower()))


def _extract_date(text: str) -> date | None:
    candidate = _strip_leading_ordinal(text)
    match = _DATE_PATTERN.search(candidate)
    if match:
        day, month, year = match.groups()
        year_int = int(year) if len(year) == 4 else 2000 + int(year)
        try:
            return date(year_int, int(month), int(day))
        except ValueError:
            return None
    match = _DATE_TEXT_PATTERN.search(candidate.lower())
    if match:
        day, month_name, year = match.groups()
        try:
            return date(int(year), _GERMAN_MONTHS[month_name], int(day))
        except ValueError:
            return None
    return None


# Requires at least one space after the ordinal ("4. 25.09.2024" -> list item) so a
# tightly-written real date's day component ("13.09.2025", no space before the month)
# is never mistaken for a leading list number and mangled.
_LEADING_ORDINAL_PATTERN = re.compile(r"^\d{1,2}[.\)]\s+")


def _strip_leading_ordinal(text: str) -> str:
    return _LEADING_ORDINAL_PATTERN.sub("", text.strip(), count=1)


def _starts_with_date(text: str) -> bool:
    """Word templates sometimes reuse the same numbered Heading style for a
    dated sub-list inside a section (e.g. a holiday-calendar list numbered
    4-15 right in between real section headings "3." and "16."). A real
    section title in this document type never starts with a calendar date,
    so this overrides any style/bold signal that would otherwise misclassify
    those list rows as new sections."""
    remainder = _strip_leading_ordinal(text)
    return _DATE_PATTERN.match(remainder) is not None


def _is_heading(paragraph: DocxParagraph) -> bool:
    """Only a real Word heading style starts a new section - bold/large body text
    (e.g. an inline label like "Module:" within a section) must never split a
    section on its own, only genuine "Heading N"/"Überschrift N" paragraphs do."""
    text = paragraph.text.strip()
    if not text or len(text) > 120:
        return False
    if _starts_with_date(text):
        return False
    style_name = (paragraph.style.name if paragraph.style else "") or ""
    return style_name.lower().startswith(("heading", "überschrift", "ueberschrift", "titel"))


def _classify_status(marker: str) -> str | None:
    lowered = marker.strip().lower()
    if not lowered:
        return None
    if any(keyword in lowered for keyword in _EXCUSED_KEYWORDS):
        return "excused"
    if any(keyword in lowered for keyword in _ABSENT_KEYWORDS):
        return "absent"
    if any(keyword in lowered for keyword in _LATE_KEYWORDS):
        return "late"
    return None


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, _fold_umlauts(a.lower().strip()), _fold_umlauts(b.lower().strip())).ratio()


def _iter_block_items(document):
    for child in document.element.body.iterchildren():
        if child.tag == qn("w:p"):
            yield DocxParagraph(child, document)
        elif child.tag == qn("w:tbl"):
            yield DocxTable(child, document)


def parse_docx(raw_bytes: bytes) -> ParsedDocx:
    """Heuristic extraction tailored to a single, consistent legacy Word template.

    Walks the document body in true reading order (not `document.paragraphs`/
    `document.tables` separately) so each table can be associated with whatever
    heading immediately precedes it, even when there's no paragraph text between
    them (e.g. a heading followed directly by a table, as in "2. Ämtli").
    """
    document = Document(BytesIO(raw_bytes))
    items = list(_iter_block_items(document))

    non_empty_paragraph_texts = [item.text.strip() for item in items if isinstance(item, DocxParagraph) and item.text.strip()]
    title_hint = non_empty_paragraph_texts[0] if non_empty_paragraph_texts else None
    protocol_date = None
    for text in non_empty_paragraph_texts[:15]:
        protocol_date = _extract_date(text)
        if protocol_date:
            break

    sections: list[ParsedSection] = []
    tables: list[ParsedTable] = []
    current_heading: str | None = None
    current_lines: list[str] = []
    table_index = 0
    for item in items:
        if isinstance(item, DocxParagraph):
            text = item.text.strip()
            if not text:
                continue
            if _is_heading(item):
                if current_heading is not None and current_lines:
                    sections.append(ParsedSection(heading=current_heading, text="\n".join(current_lines)))
                current_heading = text
                current_lines = []
            elif current_heading is not None:
                current_lines.append(text)
        else:
            raw_rows = [[cell.text.strip() for cell in row.cells] for row in item.rows]
            if raw_rows:
                header_cells, *data_rows = raw_rows
                tables.append(
                    ParsedTable(
                        index=table_index,
                        header_cells=header_cells,
                        rows=[row for row in data_rows if any(row)],
                        preceding_heading=current_heading,
                    )
                )
                table_index += 1
    if current_heading is not None and current_lines:
        sections.append(ParsedSection(heading=current_heading, text="\n".join(current_lines)))

    kept_sections: list[ParsedSection] = []
    for section in sections:
        lines = [line.strip() for line in section.text.split("\n") if line.strip()]
        kind = _classify_section_kind(lines)
        if kind == "text":
            kept_sections.append(section)
            continue
        if kind == "events":
            rows = [[line] for line in lines]
        else:
            rows = [list(pair) for pair in (_split_two_columns(line) for line in lines) if pair is not None]
        tables.append(
            ParsedTable(
                index=table_index,
                header_cells=[section.heading],
                rows=rows,
                preceding_heading=section.heading,
                known_role=kind,
            )
        )
        table_index += 1
    sections = kept_sections

    return ParsedDocx(protocol_date=protocol_date, title_hint=title_hint, sections=sections, tables=tables)


def _resolve_table_role(
    table: ParsedTable,
    overrides: dict[int, dict],
    profile_table_roles: dict[str, dict],
    list_definitions: list[tuple[int, str]],
) -> tuple[str, int | None, bool]:
    """Third return value is True when the role came from an explicit source (this
    call's manual override, or a learned profile signature match) rather than a
    heuristic guess - see the "first table defaults to attendance" fallback below,
    which must never clobber an explicit source just because it happens to sit at
    index 0."""
    if table.index in overrides:
        entry = overrides[table.index]
        return entry.get("role", "ignore"), entry.get("list_definition_id"), True
    signature = _normalize(" | ".join(table.header_cells))
    if signature in profile_table_roles:
        entry = profile_table_roles[signature]
        return entry.get("role", "ignore"), entry.get("list_definition_id"), True

    role = table.known_role
    if role is None:
        if any(keyword in signature for keyword in _ATTENDANCE_TABLE_KEYWORDS):
            role = "attendance"
        elif any(keyword in signature for keyword in _EVENT_TABLE_KEYWORDS):
            role = "events"

    if role in (None, "list") and table.preceding_heading and list_definitions:
        best_id: int | None = None
        best_score = 0.0
        for list_id, name in list_definitions:
            score = _similarity(table.preceding_heading, name)
            if score > best_score:
                best_score = score
                best_id = list_id
        if best_id is not None and best_score >= _LIST_NAME_MATCH_THRESHOLD:
            return "list", best_id, False
        if role == "list":
            return "list", None, False

    if role is not None:
        return role, None, False
    if len(table.header_cells) == 2:
        # A plausible two-column role/assignment table (like "Amt" / "Person") even
        # without a confident name match against an existing List - surfaced as
        # "list" with no target yet, rather than silently "ignore", so it's visible
        # in the review step and the user only has to pick which List it belongs to.
        return "list", None, False
    return "ignore", None, False


_DATE_RANGE_PATTERN = re.compile(
    r"\d{1,2}\.\s?\d{1,2}\.\s?\d{2,4}\s*[-–]\s*\d{1,2}\.\s?\d{1,2}\.\s?\d{2,4}"
)


def _extract_event_row(cells: list[str]) -> tuple[str, date | None]:
    for raw_cell in cells:
        # Strip a leading list ordinal ("14. ") first and consistently reuse that
        # stripped text for both date detection and remainder/title-building below -
        # otherwise the ordinal can fuse with the date itself ("4. 25.09.2024" being
        # misread as day=4/month=25) and derail everything downstream.
        cell = _strip_leading_ordinal(raw_cell)
        candidate_date = _extract_date(cell)
        if candidate_date is None:
            continue
        range_match = _DATE_RANGE_PATTERN.search(cell)
        if range_match:
            # "14.05.2026 – 17.05.2026 Auffahrt" - strip the whole range as one unit so
            # the end date doesn't linger in the title (a plain global sub would also
            # eat unrelated later dates in the same cell, which we don't want here).
            remainder = (cell[: range_match.start()] + cell[range_match.end() :]).strip(" -–:\t")
        else:
            remainder = _DATE_PATTERN.sub("", cell, count=1)
            remainder = _DATE_TEXT_PATTERN.sub("", remainder, count=1)
            remainder = remainder.strip(" -–:\t")
        if remainder:
            return remainder, candidate_date
        for other in cells:
            if other is raw_cell or not other.strip():
                continue
            if _extract_date(other) is None:
                return other.strip(), candidate_date
        return "", candidate_date
    for cell in cells:
        if cell.strip():
            return cell.strip(), None
    return "", None


def _split_two_columns(line: str) -> tuple[str, str] | None:
    if "\t" in line:
        parts = [part.strip() for part in line.split("\t") if part.strip()]
    else:
        parts = [part.strip() for part in re.split(r"\s{2,}", line) if part.strip()]
    if len(parts) == 2:
        return parts[0], parts[1]
    return None


def _classify_section_kind(lines: list[str]) -> str:
    """Some legacy templates lay out a Termine list or a role/person list as plain
    tab-aligned paragraph text instead of a real Word table - this lets such a
    section be treated like a table (offered as "events"/"list") instead of only
    ever being importable as opaque free text."""
    if len(lines) < 2:
        return "text"
    dated = sum(1 for line in lines if _starts_with_date(line))
    if dated / len(lines) >= 0.6:
        return "events"
    two_col = sum(1 for line in lines if _split_two_columns(line) is not None)
    if two_col / len(lines) >= 0.6:
        return "list"
    return "text"


_EVENT_REPEAT_MATCH_THRESHOLD = 0.5


def _strip_title_prefix(heading: str, element_title: str) -> str:
    """A "Rückblick"-style section's heading is normally "<Elementtitel> <Anlassname>"
    (e.g. "Rückblick Elternabend" for element title "Rückblick") - stripping the known
    element title isolates the Anlass name for the event-candidate search below. Falls
    back to the full heading if the title isn't actually a prefix of it (still a usable,
    if noisier, search string rather than no match at all)."""
    normalized_heading = _normalize(heading)
    normalized_title = _normalize(element_title)
    if normalized_title and normalized_heading.startswith(normalized_title):
        return heading[len(element_title):].strip(" :-–")
    return heading


def _score_event_candidate(title: str, raw_date: date | None, event: Event) -> float:
    title_score = _similarity(title, event.title)
    if raw_date is None:
        return 0.2 * title_score
    day_diff = abs((event.event_date - raw_date).days)
    if day_diff == 0:
        return 0.5 + 0.5 * title_score
    if day_diff <= 3:
        return 0.3 * max(0.0, 1 - day_diff / 3) + 0.4 * title_score
    return 0.2 * title_score


def _match_names(
    raw_text: str, participants: list[Participant], name_overrides: dict[str, int] | None = None
) -> list[WordImportNameResolution]:
    overrides = name_overrides or {}
    names = [part.strip() for part in _NAME_SPLIT_PATTERN.split(raw_text) if part.strip()]
    resolutions: list[WordImportNameResolution] = []
    for name in names:
        override_id = overrides.get(_normalize(name))
        if override_id is not None:
            resolutions.append(WordImportNameResolution(raw_name=name, participant_id=override_id))
            continue
        scored = sorted(
            ((_similarity(name, participant.display_name), participant.id) for participant in participants),
            key=lambda entry: entry[0],
            reverse=True,
        )
        participant_id = scored[0][1] if scored and scored[0][0] >= _PARTICIPANT_MATCH_THRESHOLD else None
        resolutions.append(WordImportNameResolution(raw_name=name, participant_id=participant_id))
    return resolutions


def _build_column_value(
    value_type: str,
    raw_text: str,
    participants: list[Participant],
    name_overrides: dict[str, int] | None = None,
) -> tuple[dict, list[WordImportNameResolution]]:
    if value_type == "text":
        text_value = raw_text.strip()
        return ({"text_value": text_value} if text_value else {}), []
    if value_type in ("participant", "participants"):
        resolutions = _match_names(raw_text, participants, name_overrides)
        matched_ids = [resolution.participant_id for resolution in resolutions if resolution.participant_id is not None]
        if value_type == "participant":
            return ({"participant_id": matched_ids[0]} if matched_ids else {}), resolutions
        return ({"participant_ids": matched_ids} if matched_ids else {}), resolutions
    return {}, []


_FORM_FIELD_LINE_PATTERN = re.compile(r"^(.+?):\s*(.*)$")
_FORM_FIELD_MATCH_THRESHOLD = 0.5


def _parse_form_fields(text: str, rows: list[dict]) -> dict[str, str]:
    """Extracts "Label: Value" lines from a section's raw text and fuzzy-matches each
    label against a form block's configured row labels (e.g. "Treffpunkt: Vor der
    Kirche" -> the "Treffpunkt" row) - the same "Label:" convention this app's own
    event-repeat text blocks already use by default (e.g. "Positiv:"/"Negativ:" in a
    Rückblick block), just split across dedicated form rows instead of one text blob.
    Only ':' is treated as a separator (not '-'/'–') to avoid misreading ordinary prose
    containing a dash as a field line. First matching line wins per row."""
    values: dict[str, str] = {}
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        match = _FORM_FIELD_LINE_PATTERN.match(line)
        if not match:
            continue
        raw_label, raw_value = match.groups()
        best_row_id: str | None = None
        best_score = 0.0
        for row in rows:
            score = _similarity(raw_label, str(row.get("label") or ""))
            if score > best_score:
                best_score = score
                best_row_id = str(row.get("id"))
        if best_row_id is not None and best_score >= _FORM_FIELD_MATCH_THRESHOLD and best_row_id not in values:
            values[best_row_id] = raw_value.strip()
    return values


def _resolved_value_json(value_type: str, raw_text: str, names: list) -> dict:
    """Turns an already name-resolved value (raw_text + a list of objects exposing
    .raw_name/.participant_id, e.g. WordImportNameResolution/WordImportFormFieldValue
    entries) into the {"text_value"|"participant_id"|"participant_ids": ...} shape stored
    on a list entry or form-block row - shared by the list-row commit path and the
    form-block text commit path below, which both resolve names the same way in the
    wizard before commit() runs."""
    if value_type in ("participant", "participants"):
        ids = [name.participant_id for name in names if name.participant_id is not None]
        if value_type == "participant":
            return {"participant_id": ids[0]} if ids else {}
        return {"participant_ids": ids} if ids else {}
    if value_type == "text":
        text_value = raw_text.strip()
        return {"text_value": text_value} if text_value else {}
    return {}


def _display_value(value_type: str, value_json: dict, participants_by_id: dict[int, Participant]) -> str:
    if value_type == "text":
        return str(value_json.get("text_value", ""))
    if value_type == "participant":
        participant_id = value_json.get("participant_id")
        participant = participants_by_id.get(participant_id) if participant_id is not None else None
        return participant.display_name if participant else ""
    if value_type == "participants":
        ids = value_json.get("participant_ids") or []
        return ", ".join(participants_by_id[pid].display_name for pid in ids if pid in participants_by_id)
    return ""


def _nearest_previous_protocol_id(db: Session, *, tenant_id: int, template_id: int, protocol_date: date) -> int | None:
    return db.scalar(
        select(Protocol.id)
        .where(
            Protocol.tenant_id == tenant_id,
            Protocol.template_id == template_id,
            Protocol.protocol_date < protocol_date,
        )
        .order_by(Protocol.protocol_date.desc(), Protocol.id.desc())
        .limit(1)
    )


def _list_snapshot_entries_by_id(db: Session, *, protocol_id: int, list_definition_id: int) -> dict[int, dict]:
    """entry_id -> frozen {"column_one_value", "column_two_value"} from a previous
    protocol's whole-list "form" block for this list, or {} if it has none. Used as the
    diff baseline for matched/changed instead of today's live value, since an old
    document should be compared against what was true back then, not today's data."""
    configs = db.execute(
        select(ProtocolElementBlock.configuration_snapshot_json)
        .join(ProtocolElement, ProtocolElement.id == ProtocolElementBlock.protocol_element_id)
        .where(ProtocolElement.protocol_id == protocol_id)
    ).scalars()
    for config in configs:
        if not config or config.get("linked_list_id") != list_definition_id:
            continue
        entries = (config.get("list_snapshot") or {}).get("entries") or []
        return {entry["id"]: entry for entry in entries if isinstance(entry, dict) and entry.get("id") is not None}
    return {}


def _template_linked_list_ids(db: Session, *, template_id: int, form_type_id: int | None) -> set[int]:
    """List ids the template already has a whole-list "form" block for - the only lists
    a word-import can write a snapshot into (see WordImportListRowMapping)."""
    if form_type_id is None:
        return set()
    ids: set[int] = set()
    definitions = db.execute(
        select(ElementDefinition)
        .join(TemplateElement, TemplateElement.element_definition_id == ElementDefinition.id)
        .where(TemplateElement.template_id == template_id)
    ).scalars()
    for definition in definitions:
        for block in (definition.configuration_json or {}).get("blocks", []):
            if block.get("element_type_id") != form_type_id:
                continue
            linked_list_id = (block.get("configuration_json") or {}).get("linked_list_id")
            if linked_list_id:
                ids.add(int(linked_list_id))
    return ids


def _value_key(value_type: str, value_json: dict) -> str:
    if value_type == "text":
        return _normalize(str(value_json.get("text_value", "")))
    if value_type == "participant":
        return str(value_json.get("participant_id", ""))
    if value_type == "participants":
        return ",".join(str(pid) for pid in sorted(value_json.get("participant_ids", []) or []))
    if value_type == "event":
        return str(value_json.get("event_id", ""))
    return ""


class WordImportService:
    def analyze(
        self,
        db: Session,
        *,
        tenant_id: int,
        template_id: int,
        protocol_date_hint: date | None,
        raw_bytes: bytes,
        table_role_overrides: dict[int, dict] | None = None,
    ) -> WordImportAnalysis:
        parsed = parse_docx(raw_bytes)
        protocol_date = protocol_date_hint or parsed.protocol_date
        warnings: list[str] = []

        profile = db.execute(
            select(WordImportProfile).where(
                WordImportProfile.tenant_id == tenant_id, WordImportProfile.template_id == template_id
            )
        ).scalar_one_or_none()
        profile_config = profile.mapping_config_json if profile else {}
        heading_to_target = profile_config.get("heading_to_target", {})
        table_roles_by_signature = profile_config.get("table_roles_by_signature", {})
        participant_name_overrides = profile_config.get("participant_name_overrides", {})
        profile_applied = bool(heading_to_target or table_roles_by_signature or participant_name_overrides)

        list_definition_rows = list(
            db.execute(
                select(ListDefinition).where(ListDefinition.tenant_id == tenant_id, ListDefinition.is_active.is_(True))
            ).scalars()
        )
        list_definitions_for_matching = [(item.id, item.name) for item in list_definition_rows]
        list_definitions_by_id = {item.id: item for item in list_definition_rows}

        table_roles: dict[int, str] = {}
        table_list_definitions: dict[int, int | None] = {}
        table_role_explicit: dict[int, bool] = {}
        for table in parsed.tables:
            role, list_definition_id, explicit = _resolve_table_role(
                table, table_role_overrides or {}, table_roles_by_signature, list_definitions_for_matching
            )
            table_roles[table.index] = role
            table_list_definitions[table.index] = list_definition_id
            table_role_explicit[table.index] = explicit
        # Last-resort default when nothing in the document was recognized as the
        # attendance table at all: assume the first table is it. Must never override
        # table 0's role if that role came from an explicit source (this call's manual
        # override, or a signature learned from a previous import) - otherwise a
        # learned "table 0 is actually the Ämtli list, not attendance" mapping would
        # get silently clobbered back to "attendance" on every later import where the
        # real attendance table's heuristic match happens to miss.
        if (
            parsed.tables
            and not any(role == "attendance" for role in table_roles.values())
            and not table_role_explicit.get(parsed.tables[0].index, False)
        ):
            table_roles[parsed.tables[0].index] = "attendance"

        form_type_id = db.scalar(select(ElementType.id).where(ElementType.code == "form"))
        template_linked_list_ids = _template_linked_list_ids(db, template_id=template_id, form_type_id=form_type_id)

        tables_preview = [
            TablePreview(
                index=table.index,
                header_cells=table.header_cells,
                sample_rows=table.rows[:3],
                role=table_roles.get(table.index, "ignore"),
                list_definition_id=table_list_definitions.get(table.index),
                has_snapshot_target=(
                    table_list_definitions.get(table.index) in template_linked_list_ids
                    if table_roles.get(table.index) == "list"
                    else True
                ),
            )
            for table in parsed.tables
        ]

        text_type_id = db.scalar(select(ElementType.id).where(ElementType.code == "text"))
        static_text_type_id = db.scalar(select(ElementType.id).where(ElementType.code == "static_text"))
        text_capable_ids = {value for value in (text_type_id, static_text_type_id) if value is not None}
        # "form" blocks (fixed labeled rows, e.g. Organisation/Wer geht/Treffpunkt on a
        # Scharanlässe-style element) are offered as text targets too, alongside plain
        # text/static_text blocks - see is_form_block/form_rows below.
        content_capable_ids = text_capable_ids | ({form_type_id} if form_type_id is not None else set())

        template_rows = db.execute(
            select(TemplateElement, ElementDefinition)
            .join(ElementDefinition, ElementDefinition.id == TemplateElement.element_definition_id)
            .where(TemplateElement.template_id == template_id)
            .order_by(TemplateElement.sort_index.asc())
        ).all()

        text_targets: list[WordImportTextTarget] = []
        element_targets: dict[int, list[tuple[int, str]]] = {}
        element_titles: dict[int, str] = {}
        # Blocks whose repeat_source is "event" get one live instance per matching
        # Event (ProtocolService.add_event_block_to_element), not a fixed slot in the
        # template - a (template_element_id, block_sort_index) target alone can't tell
        # which instance/Event a section belongs to, so these keys are flagged here and
        # resolved to a specific Event further below, after the ordinary target
        # resolution (profile / title-similarity / manual) has picked the block exactly
        # like for any other element.
        event_repeat_block_keys: set[tuple[int, int]] = set()
        # (template_element_id, block_sort_index) -> that form block's raw configured rows
        # (id/label/row_type, straight from ElementDefinition), used below both to build
        # WordImportTextTarget.form_rows and, once a section is matched to such a target,
        # to extract per-row values out of its raw text via _parse_form_fields.
        form_rows_by_key: dict[tuple[int, int], list[dict]] = {}
        for template_element, definition in template_rows:
            blocks = sorted(
                (definition.configuration_json or {}).get("blocks", []),
                key=lambda entry: entry.get("sort_index", 0),
            )
            content_blocks = [block for block in blocks if block.get("element_type_id") in content_capable_ids]
            if not content_blocks:
                continue
            element_titles[template_element.id] = definition.title
            legacy_repeat_config = template_element.configuration_json or {}
            targets_for_element: list[tuple[int, str]] = []
            for block in content_blocks:
                sort_index = block["sort_index"]
                block_config = dict(block.get("configuration_json") or {})
                effective_repeat = (
                    {**legacy_repeat_config, **block_config}
                    if not block_config.get("repeat_source") and legacy_repeat_config.get("repeat_source")
                    else block_config
                )
                is_event_repeat_block = str(effective_repeat.get("repeat_source") or "") == "event"
                if is_event_repeat_block:
                    event_repeat_block_keys.add((template_element.id, sort_index))
                is_form_block = block.get("element_type_id") == form_type_id
                form_rows: list[dict] = []
                if is_form_block:
                    form_rows = sorted(block_config.get("rows") or [], key=lambda entry: entry.get("sort_index", 0))
                    form_rows_by_key[(template_element.id, sort_index)] = form_rows
                label = definition.title if len(content_blocks) == 1 else f'{definition.title} – {block.get("title") or f"Block {sort_index}"}'
                text_targets.append(
                    WordImportTextTarget(
                        template_element_id=template_element.id,
                        block_sort_index=sort_index,
                        label=label,
                        is_event_repeat=is_event_repeat_block,
                        is_form_block=is_form_block,
                        form_rows=[
                            WordImportFormRow(
                                row_id=str(row.get("id")),
                                label=str(row.get("label") or row.get("title") or "Feld"),
                                row_type=str(row.get("row_type") or row.get("value_type") or "text"),
                            )
                            for row in form_rows
                        ],
                    )
                )
                targets_for_element.append((sort_index, label))
            if targets_for_element:
                element_targets[template_element.id] = targets_for_element

        all_events = list(db.execute(select(Event).where(Event.tenant_id == tenant_id)).scalars())
        # Event-repeat blocks (e.g. "Rückblick", "Scharanlässe") must be linked to a real
        # Termin from the same Zyklus-Periode as the protocol being imported (the template's
        # configured CycleConfig, cycle year computed from protocol_date) - not just any
        # tenant event. Falls back to all tenant events if the template has no cycle
        # configured or no protocol_date could be determined yet.
        template = db.get(Template, template_id)
        cycle_cfg = db.get(CycleConfig, template.cycle_config_id) if template and template.cycle_config_id else None
        if cycle_cfg is not None and protocol_date is not None:
            target_cycle_year = get_cycle_year(protocol_date, cycle_cfg.reset_month, cycle_cfg.reset_day)
            period_events = [
                event
                for event in all_events
                if get_cycle_year(event.event_date, cycle_cfg.reset_month, cycle_cfg.reset_day) == target_cycle_year
            ]
        else:
            period_events = all_events
        participants = list(
            db.execute(
                select(Participant).where(Participant.tenant_id == tenant_id, Participant.is_active.is_(True))
            ).scalars()
        )

        text_mappings: list[WordImportTextMapping] = []
        for section in parsed.sections:
            normalized_heading = _normalize(section.heading)
            saved_target = heading_to_target.get(normalized_heading)
            if saved_target:
                template_element_id = saved_target.get("template_element_id")
                block_sort_index = saved_target.get("block_sort_index")
                confidence = 1.0
            else:
                best_element_id: int | None = None
                best_score = 0.0
                for candidate_element_id, title in element_titles.items():
                    if not element_targets.get(candidate_element_id):
                        continue
                    score = _similarity(section.heading, title)
                    if score > best_score:
                        best_score = score
                        best_element_id = candidate_element_id
                if best_element_id is not None and best_score >= 0.35:
                    template_element_id = best_element_id
                    block_sort_index = min(sort_index for sort_index, _ in element_targets[best_element_id])
                    confidence = round(best_score, 2)
                else:
                    template_element_id = None
                    block_sort_index = None
                    confidence = round(best_score, 2)
                    warnings.append(f'Kein passendes Element für Abschnitt "{section.heading}" gefunden – bitte manuell zuweisen.')

            is_event_repeat = (
                template_element_id is not None
                and block_sort_index is not None
                and (template_element_id, block_sort_index) in event_repeat_block_keys
            )
            # Computed unconditionally (not gated on is_event_repeat) so that manually
            # switching a section's target to a DIFFERENT event-repeat block later in the
            # wizard - after this initial auto-match - still has a full, non-empty
            # candidate list to show instead of the empty [] a mapping starts with. Since
            # this list is period-scoped (not per-block tag/window-filtered), it's valid
            # for every event-repeat target in this protocol, not just the auto-matched one.
            search_text = _strip_title_prefix(
                section.heading, element_titles.get(template_element_id, "") if template_element_id is not None else ""
            )
            scored_events = sorted(
                ((_similarity(search_text, event.title), event) for event in period_events),
                key=lambda entry: entry[0],
                reverse=True,
            )
            event_candidates = [
                WordImportEventCandidate(event_id=event.id, title=event.title, event_date=event.event_date, score=round(score, 3))
                for score, event in scored_events
            ]
            matched_event_id: int | None = None
            if is_event_repeat:
                best_event_score, best_event = (scored_events[0] if scored_events else (0.0, None))
                matched_event_id = best_event.id if best_event is not None and best_event_score >= _EVENT_REPEAT_MATCH_THRESHOLD else None
                if matched_event_id is None:
                    warnings.append(f'Rückblick "{section.heading}" konnte keinem Anlass zugeordnet werden – bitte manuell wählen.')

            is_form_block = (
                template_element_id is not None
                and block_sort_index is not None
                and (template_element_id, block_sort_index) in form_rows_by_key
            )
            # Parsed against EVERY form-block target (not just the one currently matched
            # above) so that manually switching a section's target later in the wizard -
            # e.g. because the initial title-similarity match missed and
            # template_element_id started out None - still has real parsed values to show
            # instead of silently falling back to blank fields. Same reasoning as
            # event_candidates being computed unconditionally further up.
            form_fields_by_target: dict[str, list[WordImportFormFieldValue]] = {}
            for form_key, rows in form_rows_by_key.items():
                parsed_field_values = _parse_form_fields(section.text, rows)
                fields_for_target: list[WordImportFormFieldValue] = []
                for row in rows:
                    row_id = str(row.get("id"))
                    row_type = str(row.get("row_type") or row.get("value_type") or "text")
                    raw_value = parsed_field_values.get(row_id, "")
                    names: list[WordImportNameResolution] = []
                    if row_type in ("participant", "participants") and raw_value:
                        names = _match_names(raw_value, participants, participant_name_overrides)
                    fields_for_target.append(
                        WordImportFormFieldValue(
                            row_id=row_id,
                            label=str(row.get("label") or "Feld"),
                            row_type=row_type,
                            raw_value=raw_value,
                            names=names,
                        )
                    )
                form_fields_by_target[f"{form_key[0]}:{form_key[1]}"] = fields_for_target
                if is_form_block and form_key == (template_element_id, block_sort_index) and not parsed_field_values:
                    warnings.append(f'Für "{section.heading}" konnten keine Felder erkannt werden – bitte manuell ausfüllen.')
            form_fields = (
                form_fields_by_target.get(f"{template_element_id}:{block_sort_index}", []) if is_form_block else []
            )

            text_mappings.append(
                WordImportTextMapping(
                    extracted_heading=section.heading,
                    extracted_text=section.text,
                    template_element_id=template_element_id,
                    block_sort_index=block_sort_index,
                    confidence=confidence,
                    is_event_repeat=is_event_repeat,
                    matched_event_id=matched_event_id,
                    event_candidates=event_candidates,
                    is_form_block=is_form_block,
                    form_fields=form_fields,
                    form_fields_by_target=form_fields_by_target,
                )
            )

        attendance_mappings: list[WordImportAttendanceMapping] = []
        for table in parsed.tables:
            if table_roles.get(table.index) != "attendance":
                continue
            for cells in table.rows:
                if not cells or not cells[0]:
                    continue
                status = "present"
                for marker in cells[1:]:
                    classified = _classify_status(marker)
                    if classified:
                        status = classified
                        break
                raw_name = cells[0]
                override_id = participant_name_overrides.get(_normalize(raw_name))
                if override_id is not None:
                    suggested = override_id
                    candidates = [override_id]
                else:
                    scored = sorted(
                        ((_similarity(raw_name, participant.display_name), participant.id) for participant in participants),
                        key=lambda entry: entry[0],
                        reverse=True,
                    )
                    candidates = [participant_id for score, participant_id in scored[:3] if score >= 0.4]
                    suggested = candidates[0] if candidates and scored[0][0] >= 0.6 else None
                if suggested is None:
                    warnings.append(f'Kein passender Teilnehmer für "{raw_name}" gefunden.')
                attendance_mappings.append(
                    WordImportAttendanceMapping(
                        raw_name=raw_name, status=status, suggested_participant_id=suggested, candidates=candidates
                    )
                )

        # Participants who belong to this template's attendance roster (same query
        # ProtocolService.create_from_template uses to build attendance_entries) but were
        # never mentioned by name anywhere in the document must still show up in the
        # review step - otherwise they'd silently default to "absent" with no visible row,
        # looking like missing data instead of an explicit, editable default.
        already_matched_participant_ids = {
            mapping.suggested_participant_id for mapping in attendance_mappings if mapping.suggested_participant_id is not None
        }
        roster_filters = [
            TemplateParticipant.template_id == template_id,
            TemplateParticipant.exclude_from_attendance.is_(False),
        ]
        if protocol_date is not None:
            roster_filters.append(participant_eligible_on(protocol_date))
        template_roster = list(
            db.execute(
                select(Participant)
                .join(TemplateParticipant, TemplateParticipant.participant_id == Participant.id)
                .where(*roster_filters)
                .order_by(Participant.display_name.asc(), Participant.id.asc())
            ).scalars()
        )
        for participant in template_roster:
            if participant.id in already_matched_participant_ids:
                continue
            attendance_mappings.append(
                WordImportAttendanceMapping(
                    raw_name="", status="absent", suggested_participant_id=participant.id, candidates=[participant.id]
                )
            )

        event_mappings: list[WordImportEventMapping] = []
        row_index = 0
        for table in parsed.tables:
            if table_roles.get(table.index) != "events":
                continue
            for cells in table.rows:
                title, raw_date = _extract_event_row(cells)
                if not title:
                    continue
                scored_events = sorted(
                    ((_score_event_candidate(title, raw_date, event), event) for event in all_events),
                    key=lambda entry: entry[0],
                    reverse=True,
                )
                candidates = [
                    WordImportEventCandidate(event_id=event.id, title=event.title, event_date=event.event_date, score=round(score, 3))
                    for score, event in scored_events[:_CANDIDATE_LIMIT]
                ]
                best_score, best_event = (scored_events[0] if scored_events else (0.0, None))
                if best_event is not None and raw_date == best_event.event_date and _similarity(title, best_event.title) >= _EVENT_MATCH_THRESHOLD:
                    status: str = "matched"
                elif best_event is not None and best_score >= _EVENT_CHANGE_THRESHOLD:
                    status = "changed"
                else:
                    status = "new"
                    best_event = None
                event_mappings.append(
                    WordImportEventMapping(
                        row_index=row_index,
                        raw_title=title,
                        raw_date=raw_date,
                        status=status,
                        matched_event_id=best_event.id if best_event else None,
                        matched_event_title=best_event.title if best_event else None,
                        matched_event_date=best_event.event_date if best_event else None,
                        candidates=candidates,
                    )
                )
                row_index += 1
        if any(mapping.status != "matched" for mapping in event_mappings):
            warnings.append("Neue oder abweichende Termine gefunden – bitte prüfen und übernehmen oder ablehnen.")

        participants_by_id = {participant.id: participant for participant in participants}
        previous_protocol_id = (
            _nearest_previous_protocol_id(db, tenant_id=tenant_id, template_id=template_id, protocol_date=protocol_date)
            if protocol_date is not None
            else None
        )
        previous_entries_by_list: dict[int, dict[int, dict]] = {}

        list_mappings: list[WordImportListRowMapping] = []
        for table in parsed.tables:
            if table_roles.get(table.index) != "list":
                continue
            list_definition_id = table_list_definitions.get(table.index)
            if list_definition_id is None or list_definition_id not in list_definitions_by_id:
                warnings.append(f"Tabelle #{table.index + 1}: keine passende Liste gefunden – bitte manuell auswählen.")
                continue
            has_snapshot_target = list_definition_id in template_linked_list_ids
            if not has_snapshot_target:
                warnings.append(
                    f'Vorlage hat keinen Block für Liste "{list_definitions_by_id[list_definition_id].name}" – '
                    "Tabelle wird nicht importiert."
                )
            definition = list_definitions_by_id[list_definition_id]
            existing_entries = list(
                db.execute(select(ListEntry).where(ListEntry.list_definition_id == list_definition_id)).scalars()
            )
            existing_by_key = {
                _value_key(definition.column_one_value_type, entry.column_one_value_json or {}): entry
                for entry in existing_entries
            }
            if list_definition_id not in previous_entries_by_list:
                previous_entries_by_list[list_definition_id] = (
                    _list_snapshot_entries_by_id(db, protocol_id=previous_protocol_id, list_definition_id=list_definition_id)
                    if previous_protocol_id is not None
                    else {}
                )
            previous_entries = previous_entries_by_list[list_definition_id]
            for list_row_index, cells in enumerate(table.rows):
                column_one_raw = cells[0] if len(cells) > 0 else ""
                column_two_raw = cells[1] if len(cells) > 1 else ""
                if not column_one_raw:
                    continue
                col1_value, col1_names = _build_column_value(
                    definition.column_one_value_type, column_one_raw, participants, participant_name_overrides
                )
                col2_value, col2_names = _build_column_value(
                    definition.column_two_value_type, column_two_raw, participants, participant_name_overrides
                )
                key = _value_key(definition.column_one_value_type, col1_value)
                existing = existing_by_key.get(key)
                scored_entries = sorted(
                    (
                        (
                            _similarity(
                                column_one_raw,
                                _display_value(definition.column_one_value_type, entry.column_one_value_json or {}, participants_by_id),
                            ),
                            entry,
                        )
                        for entry in existing_entries
                    ),
                    key=lambda item: item[0],
                    reverse=True,
                )
                candidates = [
                    WordImportListEntryCandidate(
                        entry_id=entry.id,
                        column_one_display=_display_value(definition.column_one_value_type, entry.column_one_value_json or {}, participants_by_id),
                        column_two_display=_display_value(definition.column_two_value_type, entry.column_two_value_json or {}, participants_by_id),
                        score=round(score, 3),
                    )
                    for score, entry in scored_entries
                    if score >= _LIST_ENTRY_CANDIDATE_MIN_SCORE
                ][:_CANDIDATE_LIMIT]
                if existing is not None and not any(candidate.entry_id == existing.id for candidate in candidates):
                    candidates.insert(
                        0,
                        WordImportListEntryCandidate(
                            entry_id=existing.id,
                            column_one_display=_display_value(definition.column_one_value_type, existing.column_one_value_json or {}, participants_by_id),
                            column_two_display=_display_value(definition.column_two_value_type, existing.column_two_value_json or {}, participants_by_id),
                            score=1.0,
                        ),
                    )
                if existing is None:
                    status = "new"
                    matched_entry_id = None
                else:
                    # Diff against the nearest earlier protocol's frozen snapshot value for
                    # this same entry when available (a list drifts over time - comparing an
                    # old document to *today's* live value would show spurious "changed"
                    # rows for entries nothing actually changed about back then), otherwise
                    # fall back to the live value.
                    baseline_col2 = (previous_entries.get(existing.id) or {}).get("column_two_value")
                    if baseline_col2 is None:
                        baseline_col2 = existing.column_two_value_json or {}
                    baseline_col2_key = _value_key(definition.column_two_value_type, baseline_col2)
                    new_col2_key = _value_key(definition.column_two_value_type, col2_value)
                    status = "matched" if baseline_col2_key == new_col2_key else "changed"
                    matched_entry_id = existing.id
                unmatched_names = [
                    resolution.raw_name for resolution in (col1_names + col2_names) if resolution.participant_id is None
                ]
                if unmatched_names:
                    warnings.append(f'Nicht gefundene Teilnehmer in Liste "{definition.name}": {", ".join(unmatched_names)}')
                list_mappings.append(
                    WordImportListRowMapping(
                        table_index=table.index,
                        row_index=list_row_index,
                        column_one_raw=column_one_raw,
                        column_two_raw=column_two_raw,
                        column_one_type=definition.column_one_value_type,
                        column_two_type=definition.column_two_value_type,
                        status=status,
                        matched_entry_id=matched_entry_id,
                        column_one_names=col1_names,
                        column_two_names=col2_names,
                        candidates=candidates,
                        has_snapshot_target=has_snapshot_target,
                    )
                )

        if protocol_date is None:
            warnings.append("Kein Datum im Dokument erkannt – bitte manuell angeben.")

        return WordImportAnalysis(
            protocol_date=protocol_date,
            tables=tables_preview,
            text_mappings=text_mappings,
            text_targets=text_targets,
            attendance_mappings=attendance_mappings,
            event_mappings=event_mappings,
            list_definitions=[WordImportListDefinitionOption(id=item.id, name=item.name) for item in list_definition_rows],
            list_mappings=list_mappings,
            profile_applied=profile_applied,
            warnings=warnings,
        )

    def commit(self, db: Session, *, tenant_id: int, user_id: int | None, payload: WordImportCommit) -> int:
        protocol_service = ProtocolService()
        event_service = EventService()
        participant_service = ParticipantService()

        # Any existing participant this import actually references (attendance or list
        # rows) must be eligible on protocol_date, or they'd silently vanish from this
        # protocol's roster despite being explicitly named in the imported document -
        # widen (never narrow) their joined_at/left_at window to include it. A None side
        # already means "unbounded" there, so it's left untouched.
        participant_cache: dict[int, Participant] = {}

        def _get_cached_participant(participant_id: int) -> Participant | None:
            if participant_id not in participant_cache:
                participant_cache[participant_id] = db.get(Participant, participant_id)
            return participant_cache[participant_id]

        def _widen_participant_window(participant_id: int, target_date: date) -> None:
            participant = _get_cached_participant(participant_id)
            if participant is None:
                return
            if participant.joined_at is not None and target_date < participant.joined_at:
                participant.joined_at = target_date
                db.add(participant)
            if participant.left_at is not None and target_date > participant.left_at:
                participant.left_at = target_date
                db.add(participant)

        template = db.get(Template, payload.template_id)
        cycle_assignments: list[CycleAssignment] | None = None
        if template is not None and template.cycle_config_id is not None:
            cycle_cfg = db.get(CycleConfig, template.cycle_config_id)
            if cycle_cfg is not None:
                cycle_year = get_cycle_year(payload.protocol_date, cycle_cfg.reset_month, cycle_cfg.reset_day)
                cycle_assignments = [CycleAssignment(cycle_config_id=cycle_cfg.id, cycle_year=cycle_year)]

        protocol_id = protocol_service.create_from_template(
            db,
            ProtocolCreateFromTemplate(
                template_id=payload.template_id,
                protocol_date=payload.protocol_date,
                event_id=None,
            ),
            tenant_id=tenant_id,
            created_by=user_id,
        )

        rows = list(
            db.execute(
                select(ProtocolElementBlock, ProtocolElement.template_element_id, ProtocolElement.id)
                .join(ProtocolElement, ProtocolElement.id == ProtocolElementBlock.protocol_element_id)
                .where(ProtocolElement.protocol_id == protocol_id)
            ).all()
        )
        block_by_key: dict[tuple[int, int], ProtocolElementBlock] = {}
        # (template_element_id, event_id) -> the event-repeat block instance already
        # auto-generated for that Event by create_from_template's own repeat logic
        # above (only events currently within its window get one there) - reused
        # instead of creating a duplicate block for the same Event.
        event_block_by_key: dict[tuple[int, int], ProtocolElementBlock] = {}
        protocol_element_id_by_template_element_id: dict[int, int] = {}
        attendance_blocks: list[ProtocolElementBlock] = []
        for block, template_element_id, protocol_element_id in rows:
            config = block.configuration_snapshot_json or {}
            source_sort_index = config.get("source_sort_index")
            if template_element_id is not None and source_sort_index is not None:
                block_by_key[(template_element_id, source_sort_index)] = block
            if template_element_id is not None:
                protocol_element_id_by_template_element_id[template_element_id] = protocol_element_id
                if config.get("repeat_source_type") == "event" and config.get("repeat_source_id") is not None:
                    event_block_by_key[(template_element_id, int(config["repeat_source_id"]))] = block
            if config and "attendance_entries" in config:
                attendance_blocks.append(block)

        def _get_or_create_event_repeat_block(template_element_id: int, event_id: int) -> ProtocolElementBlock | None:
            key = (template_element_id, event_id)
            block = event_block_by_key.get(key)
            if block is not None:
                return block
            protocol_element_id = protocol_element_id_by_template_element_id.get(template_element_id)
            if protocol_element_id is None:
                return None
            try:
                block = protocol_service.add_event_block_to_element(
                    db, protocol_element_id=protocol_element_id, event_id=event_id
                )
            except ValueError:
                return None
            event_block_by_key[key] = block
            return block

        # Same shape/purpose as attendance_name_updates/list_name_updates below - learned
        # from form-block participant(s) rows (e.g. "Organisation"/"Wer geht" on a
        # Scharanlässe-style block) so a repeated import of similarly-worded old
        # protocols reuses the same name resolution without re-asking.
        form_name_updates: dict[str, int] = {}
        # normalized raw_name -> newly created Participant.id, deduplicates a name typed
        # as "create new" appearing in more than one form-field row within this same
        # commit (e.g. the same person listed under both "Organisation" and "Wer geht").
        created_form_participants: dict[str, int] = {}
        for text_commit in payload.texts:
            if text_commit.template_element_id is None:
                continue
            if text_commit.is_event_repeat:
                if text_commit.linked_event_id is None:
                    # No Anlass chosen for this Rückblick-style section - never falls
                    # back to block_sort_index, which would silently write into an
                    # arbitrary other Event's block (see event_block_by_key above).
                    continue
                block = _get_or_create_event_repeat_block(text_commit.template_element_id, text_commit.linked_event_id)
            elif text_commit.block_sort_index is not None:
                block = block_by_key.get((text_commit.template_element_id, text_commit.block_sort_index))
            else:
                continue
            if block is None:
                continue
            if text_commit.is_form_block:
                config = dict(block.configuration_snapshot_json or {})
                fields_by_row_id = {field.row_id: field for field in text_commit.form_fields}
                updated_rows = []
                for row in config.get("rows") or []:
                    row_id = str(row.get("id"))
                    field = fields_by_row_id.get(row_id)
                    if field is None:
                        updated_rows.append(row)
                        continue
                    resolved_names = []
                    for name in field.names:
                        participant_id = name.participant_id
                        if participant_id is None and name.create_new:
                            cache_key = _normalize(name.raw_name)
                            participant_id = created_form_participants.get(cache_key)
                            if participant_id is None:
                                new_participant = participant_service.create_participant(
                                    db,
                                    ParticipantCreate(
                                        display_name=name.raw_name.strip(),
                                        # Scoped to exactly this protocol's date, same as a
                                        # newly created attendance participant above.
                                        joined_at=payload.protocol_date,
                                        left_at=payload.protocol_date,
                                    ),
                                    tenant_id=tenant_id,
                                )
                                db.flush()
                                participant_id = new_participant.id
                                created_form_participants[cache_key] = participant_id
                                db.add(TemplateParticipant(template_id=payload.template_id, participant_id=participant_id, exclude_from_attendance=False))
                        resolved_names.append(name.model_copy(update={"participant_id": participant_id}))
                        if participant_id is not None:
                            form_name_updates[_normalize(name.raw_name)] = participant_id
                            _widen_participant_window(participant_id, payload.protocol_date)
                    updated_rows.append({**row, **_resolved_value_json(field.row_type, field.raw_value, resolved_names)})
                config["rows"] = updated_rows
                block.configuration_snapshot_json = config
                db.add(block)
            else:
                protocol_text = db.execute(
                    select(ProtocolText).where(ProtocolText.protocol_element_block_id == block.id)
                ).scalar_one_or_none()
                if protocol_text is not None:
                    protocol_text.content = text_commit.content

        # Learned here (not straight from payload.attendance) so create_new rows contribute
        # their newly-created participant_id, and roster-only rows (raw_name == "", added in
        # analyze() for template participants missing from the document) don't pollute the
        # profile with a bogus ""-key override.
        attendance_name_updates: dict[str, int] = {}
        if payload.attendance and attendance_blocks:
            status_by_participant: dict[int, str] = {}
            created_participants: dict[int, str] = {}
            for entry in payload.attendance:
                participant_id = entry.participant_id
                if participant_id is None and entry.create_new:
                    new_participant = participant_service.create_participant(
                        db,
                        ParticipantCreate(
                            display_name=(entry.participant_name or entry.raw_name).strip(),
                            # Scoped to exactly this protocol's date, so the person shows up
                            # only here and not in other protocols' rosters until someone
                            # widens their membership window by hand.
                            joined_at=payload.protocol_date,
                            left_at=payload.protocol_date,
                        ),
                        tenant_id=tenant_id,
                    )
                    participant_id = new_participant.id
                    created_participants[participant_id] = new_participant.display_name
                    # Also add to the template's roster so future protocols/imports for this
                    # template already list them, not just this one-off protocol.
                    db.add(TemplateParticipant(template_id=payload.template_id, participant_id=participant_id, exclude_from_attendance=False))
                if participant_id is None:
                    continue
                if participant_id not in created_participants:
                    _widen_participant_window(participant_id, payload.protocol_date)
                status_by_participant[participant_id] = entry.status
                if entry.raw_name:
                    attendance_name_updates[_normalize(entry.raw_name)] = participant_id
            if created_participants:
                db.flush()
            for attendance_block in attendance_blocks:
                entries = attendance_block.configuration_snapshot_json.get("attendance_entries", [])
                present_ids = {entry.get("participant_id") for entry in entries}
                for entry in entries:
                    if entry.get("participant_id") in status_by_participant:
                        entry["status"] = status_by_participant[entry["participant_id"]]
                for missing_id, status in status_by_participant.items():
                    if missing_id in present_ids:
                        continue
                    # create_from_template built attendance_entries from the roster query
                    # BEFORE this method ran (and that query filters by participant_eligible_on)
                    # - so this participant is missing here either because they were just
                    # created above, or because their old joined_at/left_at window excluded
                    # protocol_date and only got widened to include it a few lines up. Either
                    # way: append instead of status-patch.
                    display_name = created_participants.get(missing_id)
                    if display_name is None:
                        existing_participant = _get_cached_participant(missing_id)
                        display_name = existing_participant.display_name if existing_participant else ""
                    entries.append({"participant_id": missing_id, "participant_name": display_name, "status": status})
                attendance_block.configuration_snapshot_json = {
                    **attendance_block.configuration_snapshot_json,
                    "attendance_entries": entries,
                }

        for event_commit in payload.events:
            if not event_commit.approved:
                continue
            if event_commit.linked_event_id is None:
                event_service.create_event(
                    db,
                    EventCreate(title=event_commit.final_title, event_date=event_commit.final_date, cycle_assignments=cycle_assignments),
                    tenant_id=tenant_id,
                )
            else:
                event_service.update_event(
                    db,
                    event_commit.linked_event_id,
                    EventUpdate(title=event_commit.final_title, event_date=event_commit.final_date, cycle_assignments=cycle_assignments),
                )

        # Lists are never written to the live ListEntry table (see WordImportListRowMapping
        # / WordImportListRowCommit docstrings) - collect the approved rows here and only
        # patch the protocol's own block snapshot(s) further below, *after* the status
        # transition to "abgeschlossen" has run its live-refreshing freeze step (otherwise
        # that freeze would immediately overwrite these historical values with today's data).
        list_name_updates: dict[str, int] = {}
        approved_list_commits: list[WordImportListRowCommit] = []
        definitions_cache: dict[int, ListDefinition] = {}
        for list_commit in payload.lists:
            if not list_commit.approved:
                continue
            definition = definitions_cache.get(list_commit.list_definition_id)
            if definition is None:
                definition = db.get(ListDefinition, list_commit.list_definition_id)
                if definition is None:
                    continue
                definitions_cache[list_commit.list_definition_id] = definition
            approved_list_commits.append(list_commit)
            for name_resolution in list_commit.column_one_names + list_commit.column_two_names:
                if name_resolution.participant_id is not None:
                    list_name_updates[_normalize(name_resolution.raw_name)] = name_resolution.participant_id
                    _widen_participant_window(name_resolution.participant_id, payload.protocol_date)

        heading_updates = {
            _normalize(tc.extracted_heading): {
                "template_element_id": tc.template_element_id,
                "block_sort_index": tc.block_sort_index,
            }
            for tc in payload.texts
            # Event-repeat headings (e.g. "Rückblick Elternabend") name a specific
            # Anlass, not a stable structural target - memoizing them would make a
            # differently-named Rückblick heading next time wrongly short-circuit
            # straight past _match_event_repeat_section in analyze().
            if tc.template_element_id is not None and tc.block_sort_index is not None and not tc.is_event_repeat
        }
        table_role_updates = {
            tc.header_signature: {"role": tc.role, "list_definition_id": tc.list_definition_id} for tc in payload.tables
        }
        name_updates: dict[str, int] = {**attendance_name_updates, **list_name_updates, **form_name_updates}
        if heading_updates or table_role_updates or name_updates:
            profile = db.execute(
                select(WordImportProfile).where(
                    WordImportProfile.tenant_id == tenant_id, WordImportProfile.template_id == payload.template_id
                )
            ).scalar_one_or_none()
            if profile is None:
                profile = WordImportProfile(tenant_id=tenant_id, template_id=payload.template_id, mapping_config_json={})
                db.add(profile)
                db.flush()
            config = dict(profile.mapping_config_json or {})
            heading_map = dict(config.get("heading_to_target", {}))
            heading_map.update(heading_updates)
            table_map = dict(config.get("table_roles_by_signature", {}))
            table_map.update(table_role_updates)
            name_map = dict(config.get("participant_name_overrides", {}))
            name_map.update(name_updates)
            profile.mapping_config_json = {
                "heading_to_target": heading_map,
                "table_roles_by_signature": table_map,
                "participant_name_overrides": name_map,
            }

        protocol_service.update_protocol(db, protocol_id, ProtocolUpdate(status="abgeschlossen"))

        if approved_list_commits:
            blocks_by_list_id: dict[int, list[ProtocolElementBlock]] = {}
            for block in db.execute(
                select(ProtocolElementBlock)
                .join(ProtocolElement, ProtocolElement.id == ProtocolElementBlock.protocol_element_id)
                .where(ProtocolElement.protocol_id == protocol_id)
            ).scalars():
                linked_list_id = (block.configuration_snapshot_json or {}).get("linked_list_id")
                if linked_list_id:
                    blocks_by_list_id.setdefault(int(linked_list_id), []).append(block)

            synthetic_id = 0
            for list_commit in approved_list_commits:
                target_blocks = blocks_by_list_id.get(list_commit.list_definition_id)
                if not target_blocks:
                    # Chosen template has no block linked to this list - no snapshot slot
                    # exists in this protocol, so nothing is written (never falls back to
                    # live, see WordImportListRowMapping.has_snapshot_target).
                    continue
                definition = definitions_cache[list_commit.list_definition_id]
                col1_value = _resolved_value_json(definition.column_one_value_type, list_commit.column_one_raw, list_commit.column_one_names)
                col2_value = _resolved_value_json(definition.column_two_value_type, list_commit.column_two_raw, list_commit.column_two_names)
                for block in target_blocks:
                    config = dict(block.configuration_snapshot_json or {})
                    list_snapshot = dict(config.get("list_snapshot") or {})
                    entries = list(list_snapshot.get("entries") or [])
                    target_index = (
                        next(
                            (i for i, entry in enumerate(entries) if isinstance(entry, dict) and entry.get("id") == list_commit.linked_entry_id),
                            None,
                        )
                        if list_commit.linked_entry_id is not None
                        else None
                    )
                    if target_index is not None:
                        entries[target_index] = {**entries[target_index], "column_one_value": col1_value, "column_two_value": col2_value}
                    else:
                        # No live counterpart (or it wasn't found in this block's frozen
                        # entries) - append a snapshot-only row with a synthetic negative id,
                        # never a real ListEntry id, so it can never collide with one.
                        synthetic_id -= 1
                        entries.append(
                            {
                                "id": list_commit.linked_entry_id if list_commit.linked_entry_id is not None else synthetic_id,
                                "sort_index": len(entries),
                                "column_one_value": col1_value,
                                "column_two_value": col2_value,
                            }
                        )
                    list_snapshot["entries"] = entries
                    config["list_snapshot"] = list_snapshot
                    block.configuration_snapshot_json = config
                    db.add(block)

        db.commit()
        return protocol_id
