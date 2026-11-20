"use client";

import { Dispatch, FormEvent, ReactNode, SetStateAction, useEffect, useId, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { useEventFieldConfig } from "@/lib/hooks/use-event-field-config";
import { browserApiFetch } from "@/lib/api/client";

import { Badge } from "@/components/ui/badge";
import { DateInput } from "@/components/ui/date-input";
import { HelpPopover } from "@/components/ui/help-popover";
import { Modal, ModalSaveForm } from "@/components/ui/modal";
import { ActionIcon } from "@/components/ui/action-icons";
import { NavIcon } from "@/components/ui/nav-icons";
import { NumberStepper } from "@/components/ui/number-stepper";
import { SearchableMultiSelect, SearchableSelect } from "@/components/ui/searchable-select";
import { SegmentedControl, useRadioGroupKeys } from "@/components/ui/segmented-control";
import { Switch } from "@/components/ui/switch";
import { TagInput } from "@/components/ui/tag-input";
import type { TagConfig } from "@/lib/hooks/use-tag-config";
import { CYCLE_OFFSET_OPTIONS, cycleOffsetLabel } from "@/lib/utils/cycle-offsets";
import { formatDate, formatDateInputValue, formatShortWeekdayDate } from "@/lib/utils/format";
import {
  CycleConfigSummary,
  StructuredListDefinition,
  SubmissionAssignment,
  SubmissionAutoClose,
  SubmissionFileVisibility,
  SubmissionLink,
  SubmissionManualElement,
  SubmissionReviewerCandidate,
  SubmissionSortOrder,
  SubmissionSourceType,
} from "@/types/api";

/** Element einer Einzelabgabe im Formular (Migration 0198). `id` = gespeichertes Element, sonst neu. */
export type ManualElementForm = {
  /** Nur für React-Listen (stabil auch für neue Elemente ohne `id`) */
  key: string;
  id: string | null;
  name: string;
  window_start: string;
  window_end: string;
  responsible_participant_ids: string[];
};

/** Wählbare Person für die Verantwortlichen eines Elements (Teilnehmende des Mandanten). */
export type ResponsibleCandidate = { id: string; display_name: string; is_active?: boolean };

let manualElementCounter = 0;

export function newManualElement(name = "", values: Partial<ManualElementForm> = {}): ManualElementForm {
  manualElementCounter += 1;
  return { key: `new-${manualElementCounter}`, id: null, name, window_start: "", window_end: "", responsible_participant_ids: [], ...values };
}

function manualElementFromApi(element: SubmissionManualElement): ManualElementForm {
  return {
    key: element.id,
    id: element.id,
    name: element.name,
    window_start: element.window_start ?? "",
    window_end: element.window_end ?? "",
    responsible_participant_ids: element.responsible_participant_ids,
  };
}

/** Eine Einzelabgabe hat immer mindestens ein Element: fehlt es, eines mit dem Titel anlegen. */
export function withManualElement(form: FormState): FormState {
  return form.manual_elements.length > 0 ? form : { ...form, manual_elements: [newManualElement(form.title.trim())] };
}

export type FormState = {
  title: string;
  description: string;
  public_slug: string;
  source_type: SubmissionSourceType;
  tag_filter: string;
  offset_days_before: number | "";
  offset_days_after: number | "";
  cycle_config_id: string | "";
  cycle_offsets: number[];
  list_definition_id: string | "";
  deadline: string;
  allowed_file_types: string[];
  max_files_per_element: number | "";
  max_file_size_mb: number;
  sort_order: SubmissionSortOrder;
  auto_close: SubmissionAutoClose;
  /** Nach dem Enddatum offen halten, bis auto_close oder Schliessen von Hand (Migration 0173). */
  keep_open_after_end: boolean;
  responsible_participant_source: string;
  owner_access: "off" | "view" | "manage";
  owner_access_days: number | "";
  owner_resubmit_only_personal: boolean;
  link_ids: string[];
  /** Prüfer (Konten mit Login, Migration 0195) */
  reviewer_ids: string[];
  /** Wer darf eingereichte Dateien sehen? «default» = Standard der Organisation (Migration 0196) */
  file_visibility: "default" | SubmissionFileVisibility["audience"];
  file_visibility_filter: SubmissionFileVisibility["file_filter"];
  /** Elemente einer Einzelabgabe (Migration 0198), bei anderen Quellen ungenutzt */
  manual_elements: ManualElementForm[];
  /** Tags für jede Pendenz der Abgabe (Migration 0202) */
  todo_tags: string[];
  /** «Abgabe-Tag erstellen»: zusätzlich ein Tag mit dem Titel der Abgabe (Standard aus) */
  todo_own_tag: boolean;
};

export const initialForm: FormState = {
  title: "",
  description: "",
  public_slug: "",
  source_type: "events",
  tag_filter: "",
  offset_days_before: "",
  offset_days_after: "",
  cycle_config_id: "",
  cycle_offsets: [],
  list_definition_id: "",
  deadline: "",
  allowed_file_types: [],
  max_files_per_element: 5,
  max_file_size_mb: 20,
  sort_order: "date",
  auto_close: "never",
  keep_open_after_end: false,
  responsible_participant_source: "",
  // Neue Abgaben: Verantwortliche verwalten ihre Abgabe über den persönlichen Link
  owner_access: "manage",
  owner_access_days: 30,
  owner_resubmit_only_personal: false,
  link_ids: [],
  reviewer_ids: [],
  file_visibility: "default",
  file_visibility_filter: "images",
  manual_elements: [],
  todo_tags: [],
  todo_own_tag: false,
};

type TFunc = (key: string, values?: Record<string, string | number | Date>) => string;

export function sortOrderLabel(t: TFunc): Record<SubmissionSortOrder, string> {
  return {
    alphabetical: t("sortAlphabetical"),
    date: t("sortByDate"),
    proximity: t("sortProximity"),
  };
}

// Alle Personenfelder eines Termins, die als "verantwortliche Person" einer Termin-Abgabe in Frage
// kommen (Backend: EVENT_RESPONSIBLE_FIELDS in submission_service.py).
function singleParticipantEventFields(t: TFunc): { value: string; label: string }[] {
  return [
    { value: "organizer_ids", label: t("fieldOrganizers") },
    { value: "leadership_ids", label: t("fieldLeadership") },
    { value: "participant_ids", label: t("fieldParticipants") },
    { value: "spezial1_ids", label: t("special1") },
    { value: "spezial2_ids", label: t("special2") },
    { value: "spezial3_ids", label: t("special3") },
  ];
}

export { CYCLE_OFFSET_OPTIONS, cycleOffsetLabel };

function fileTypeGroups(t: TFunc) {
  return [
    { label: "PDF", types: ["pdf"] },
    { label: t("fileGroupOffice"), types: ["doc", "docx", "xls", "xlsx", "ppt", "pptx"] },
    { label: t("fileGroupImages"), types: ["jpg", "jpeg", "png", "gif", "webp"] },
    { label: t("fileGroupApple"), types: ["pages", "key", "numbers", "heic", "heif"] },
  ];
}

function autoCloseOptions(t: TFunc): { value: SubmissionAutoClose; label: string }[] {
  return [
    { value: "never", label: t("autoCloseNever") },
    { value: "first_upload", label: t("fields.autoCloseFirstUpload") },
    { value: "max_files", label: t("fields.autoCloseMaxFiles") },
  ];
}

function sourceOptions(t: TFunc): { value: SubmissionSourceType; title: string; description: string }[] {
  return [
    { value: "events", title: t("sourceEvents"), description: t("sourceEventsDescription") },
    { value: "list", title: t("sourceList"), description: t("sourceListDescription") },
    { value: "manual", title: t("sourceManual"), description: t("sourceManualDescription") },
  ];
}

export function slugify(title: string): string {
  return title
    .toLowerCase()
    .replace(/ä/g, "ae").replace(/ö/g, "oe").replace(/ü/g, "ue").replace(/ß/g, "ss")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

export function formFromAssignment(assignment: SubmissionAssignment): FormState {
  return {
    title: assignment.title,
    description: assignment.description ?? "",
    public_slug: assignment.public_slug,
    source_type: assignment.source_type,
    tag_filter: assignment.tag_filter ?? "",
    offset_days_before: assignment.offset_days_before ?? "",
    offset_days_after: assignment.offset_days_after ?? "",
    cycle_config_id: assignment.cycle_config_id ?? "",
    cycle_offsets: assignment.cycle_offsets,
    list_definition_id: assignment.list_definition_id ?? "",
    deadline: assignment.deadline ?? "",
    allowed_file_types: assignment.allowed_file_types,
    max_files_per_element: assignment.max_files_per_element ?? "",
    max_file_size_mb: assignment.max_file_size_mb,
    sort_order: assignment.sort_order,
    auto_close: assignment.auto_close ?? "never",
    keep_open_after_end: assignment.keep_open_after_end ?? false,
    responsible_participant_source: assignment.responsible_participant_source ?? "",
    owner_access: assignment.owner_access ?? "off",
    owner_access_days: assignment.owner_access_days ?? 30,
    owner_resubmit_only_personal: assignment.owner_resubmit_only_personal ?? false,
    link_ids: assignment.link_ids,
    reviewer_ids: assignment.reviewer_ids ?? [],
    file_visibility: assignment.file_visibility?.mode === "custom" ? assignment.file_visibility.audience : "default",
    file_visibility_filter: assignment.file_visibility?.mode === "custom" ? assignment.file_visibility.file_filter : "images",
    manual_elements:
      assignment.source_type !== "manual"
        ? []
        : assignment.manual_elements && assignment.manual_elements.length > 0
          ? assignment.manual_elements.map(manualElementFromApi)
          : [newManualElement(assignment.title, { window_end: assignment.deadline ?? "" })],
    todo_tags: assignment.todo_tags ?? [],
    todo_own_tag: assignment.todo_own_tag ?? false,
  };
}

/** Grund, warum das Formular noch nicht gespeichert werden kann (null = gültig). */
/** POST/PATCH-Body aus dem Formular - gemeinsam fuer Desktop-Manager und Mobile-Ansicht.
 * Nur was zur gewaehlten Verknuepfung gehoert, wird gesendet - der Rest wird beim Wechsel geleert. */
export function assignmentPayload(form: FormState) {
  const isEvents = form.source_type === "events";
  const isManual = form.source_type === "manual";
  return {
    title: form.title.trim(),
    description: form.description || null,
    public_slug: form.public_slug,
    source_type: form.source_type,
    tag_filter: isEvents ? form.tag_filter : null,
    offset_days_before: isEvents && form.offset_days_before !== "" ? Number(form.offset_days_before) : null,
    offset_days_after: isEvents && form.offset_days_after !== "" ? Number(form.offset_days_after) : null,
    cycle_config_id: isEvents ? form.cycle_config_id || null : null,
    cycle_offsets: isEvents && form.cycle_config_id ? form.cycle_offsets : [],
    list_definition_id: form.source_type === "list" ? form.list_definition_id || null : null,
    // Einzelabgaben: Zeitfenster je Element (Migration 0198)
    deadline: isEvents || isManual ? null : form.deadline || null,
    allowed_file_types: form.allowed_file_types,
    max_files_per_element: form.max_files_per_element === "" ? null : Number(form.max_files_per_element),
    max_file_size_mb: Number(form.max_file_size_mb),
    sort_order: form.sort_order,
    auto_close: form.auto_close,
    keep_open_after_end: hasEnd(form) && form.keep_open_after_end,
    responsible_participant_source: form.source_type === "manual" ? null : form.responsible_participant_source || null,
    owner_access: form.owner_access,
    owner_access_days: form.owner_access_days === "" ? 30 : Math.min(90, Math.max(1, Math.round(Number(form.owner_access_days)))),
    owner_resubmit_only_personal: form.owner_access === "manage" && form.owner_resubmit_only_personal,
    link_ids: form.link_ids,
    reviewer_ids: form.reviewer_ids,
    todo_tags: form.todo_tags,
    todo_own_tag: form.todo_own_tag,
    file_visibility: form.file_visibility === "default"
      ? { mode: "default" as const }
      : { mode: "custom" as const, audience: form.file_visibility, file_filter: form.file_visibility_filter },
    ...(isManual
      ? {
          manual_elements: form.manual_elements.map((element) => ({
            id: element.id,
            name: element.name.trim(),
            window_start: element.window_start || null,
            window_end: element.window_end || null,
            responsible_participant_ids: element.responsible_participant_ids,
          })),
        }
      : {}),
  };
}

/** Grösstes Zeitfenster in Tagen vor/nach dem Termin (Backend: schemas/submission.py OFFSET_DAYS_MAX). */
export const OFFSET_DAYS_MAX = 3650;

function offsetOutOfRange(value: number | ""): boolean {
  return value !== "" && (!Number.isInteger(value) || value < 0 || value > OFFSET_DAYS_MAX);
}

export function formProblem(form: FormState, t: TFunc): string | null {
  if (!form.title.trim()) return t("titleMissing");
  if (form.source_type === "events") {
    if (!form.tag_filter) return t("tagFilterMissing");
    if (form.cycle_config_id && form.cycle_offsets.length === 0) return t("cycleSelectionMissing");
    if (offsetOutOfRange(form.offset_days_before) || offsetOutOfRange(form.offset_days_after)) return t("offsetOutOfRange", { max: OFFSET_DAYS_MAX });
  }
  if (form.source_type === "list" && !form.list_definition_id) return t("listMissing");
  if (form.source_type === "manual") {
    if (form.manual_elements.length === 0) return t("wizard.manual.elementsMissing");
    if (form.manual_elements.some((element) => !element.name.trim())) return t("wizard.manual.nameMissing");
    if (form.manual_elements.some(manualWindowInvalid)) return t("wizard.manual.windowInvalid");
  }
  return null;
}

function manualWindowInvalid(element: ManualElementForm): boolean {
  return Boolean(element.window_start && element.window_end && element.window_start > element.window_end);
}

/** Welches Feld den Fehler aus formProblem hat (für die Markierung). */
function problemFieldOf(form: FormState): "title" | "tag" | "cycle" | "window" | "list" | "elements" | null {
  if (!form.title.trim()) return "title";
  if (form.source_type === "events") {
    if (!form.tag_filter) return "tag";
    if (form.cycle_config_id && form.cycle_offsets.length === 0) return "cycle";
    if (offsetOutOfRange(form.offset_days_before) || offsetOutOfRange(form.offset_days_after)) return "window";
  }
  if (form.source_type === "list" && !form.list_definition_id) return "list";
  if (form.source_type === "manual" && (form.manual_elements.length === 0 || form.manual_elements.some((e) => !e.name.trim() || manualWindowInvalid(e)))) {
    return "elements";
  }
  return null;
}

export type ExampleEvent = { title: string; event_date: string; event_end_date: string | null };

function addDays(iso: string, days: number): string {
  const [year, month, day] = iso.split("-").map(Number);
  const date = new Date(Date.UTC(year, month - 1, day + days));
  return date.toISOString().slice(0, 10);
}

/** Nächster (sonst letzter) Termin mit dem gewählten Tag als Beispiel fürs Zeitfenster. */
export function pickExampleEvent(events: (ExampleEvent & { tag: string | null })[], tag: string, today = new Date().toISOString().slice(0, 10)): ExampleEvent | null {
  const tagged = events
    .filter((event) => event.tag === tag)
    .sort((a, b) => a.event_date.localeCompare(b.event_date));
  return tagged.find((event) => (event.event_end_date ?? event.event_date) >= today) ?? tagged[tagged.length - 1] ?? null;
}

/** Zeitfenster an einem konkreten Termin erklärt (wie Backend: Ende ab dem letzten Tag des Termins). */
export function windowExample(form: FormState, event: ExampleEvent | null, t: TFunc): string {
  const eventDate = event?.event_date ?? new Date().toISOString().slice(0, 10);
  const lastDay = event?.event_end_date ?? eventDate;
  const start = form.offset_days_before === "" ? null : formatDate(addDays(eventDate, -Number(form.offset_days_before)));
  const end = form.offset_days_after === "" ? null : formatDate(addDays(lastDay, Number(form.offset_days_after)));
  const range =
    start && end ? t("windowExampleRange", { start, end })
      : start ? t("windowExampleFrom", { start })
        : end ? t("windowExampleUntil", { end })
          : t("windowExampleOpen");
  return event
    ? t("windowExample", { title: event.title, date: formatDate(eventDate), range })
    : t("windowExampleNoEvent", { date: formatDate(eventDate), range });
}

type AssignmentTemplate = { key: string; title: string; description: string; apply: (form: FormState) => FormState };

/** Schnellstart: füllt Quelle, Zeitraum und Dateiregeln vor; Titel und Links bleiben. */
export function assignmentTemplates(t: TFunc): AssignmentTemplate[] {
  return [
    {
      key: "event-reports",
      title: t("templateEventReportsTitle"),
      description: t("templateEventReportsDescription"),
      apply: (c) => ({
        ...c, source_type: "events", offset_days_before: 0, offset_days_after: 7, deadline: "",
        allowed_file_types: ["pdf", "doc", "docx"], max_files_per_element: 3, auto_close: "never", list_definition_id: "",
      }),
    },
    {
      key: "form-deadline",
      title: t("templateFormTitle"),
      description: t("templateFormDescription"),
      apply: (c) => withManualElement({
        ...c, source_type: "manual", tag_filter: "", offset_days_before: "", offset_days_after: "", cycle_config_id: "", cycle_offsets: [],
        list_definition_id: "", allowed_file_types: ["pdf"], max_files_per_element: 1, auto_close: "first_upload", responsible_participant_source: "",
      }),
    },
    {
      key: "event-photos",
      title: t("templatePhotosTitle"),
      description: t("templatePhotosDescription"),
      apply: (c) => ({
        ...c, source_type: "events", offset_days_before: 0, offset_days_after: 14, deadline: "", list_definition_id: "",
        allowed_file_types: ["jpg", "jpeg", "png", "heic", "heif"], max_files_per_element: "", auto_close: "never",
      }),
    },
  ];
}

function deadlineSentence(deadline: string, t: TFunc): string {
  return deadline
    ? t("deadlineSentence", { date: formatDateInputValue(deadline) })
    : t("noDeadlineSentence");
}

function windowSentence(before: number | "", after: number | "", t: TFunc): string {
  if (before !== "" && after !== "") return t("windowBothSentence", { before, after });
  if (before !== "") return t("windowBeforeOnlySentence", { before });
  if (after !== "") return t("windowAfterOnlySentence", { after });
  return t("windowNoneSentence");
}

/** Hat die Abgabe ein Ende (Tage danach bzw. Stichtag)? Nur dann gibt es «offen halten». */
export function hasEnd(form: FormState): boolean {
  if (form.source_type === "manual") return form.manual_elements.some((element) => Boolean(element.window_end));
  return form.source_type === "events" ? form.offset_days_after !== "" : Boolean(form.deadline);
}

/** Frühester Stichtag der Elemente einer Einzelabgabe (ISO) oder null. */
function nextManualDeadline(form: FormState): string | null {
  const ends = form.manual_elements.map((element) => element.window_end).filter(Boolean).sort();
  return ends[0] ?? null;
}

/** Elemente mit mindestens einer verantwortlichen Person. */
function manualResponsibleCount(form: FormState): number {
  return form.manual_elements.filter((element) => element.responsible_participant_ids.length > 0).length;
}

function autoCloseSentence(form: FormState, t: TFunc): string | null {
  if (form.auto_close === "first_upload") return t("autoCloseFirstUploadSentence");
  if (form.auto_close === "max_files" && form.max_files_per_element !== "") {
    return t("autoCloseMaxFilesSentence", { count: form.max_files_per_element });
  }
  return null;
}

function describeBase(form: FormState, listName: string | null, t: TFunc): string {
  if (form.source_type === "events") {
    const subject = form.tag_filter
      ? t("eventsSubjectTagged", { tag: form.tag_filter })
      : t("eventsSubjectUntagged");
    return `${subject} ${windowSentence(form.offset_days_before, form.offset_days_after, t)}`;
  }
  if (form.source_type === "list") {
    const subject = listName
      ? t("listSubjectNamed", { name: listName })
      : t("listSubjectUnnamed");
    return `${subject} ${deadlineSentence(form.deadline, t)}`;
  }
  const next = nextManualDeadline(form);
  return [
    t("manualSubject", { count: form.manual_elements.length }),
    next ? t("manualNextDeadlineSentence", { date: formatDateInputValue(next) }) : t("manualNoDeadlineSentence"),
    manualResponsibleCount(form) > 0 ? t("manualTodoSentence", { count: manualResponsibleCount(form) }) : null,
  ].filter(Boolean).join(" ");
}

/** Erklärt in einem Satz, wie sich die Abgabe mit den aktuellen Einstellungen verhält. */
export function describeAssignment(form: FormState, listName: string | null, t: TFunc): string {
  const base = describeBase(form, listName, t);
  const parts = [base, autoCloseSentence(form, t), hasEnd(form) && form.keep_open_after_end ? t("keepOpenSentence") : null];
  return parts.filter(Boolean).join(" ");
}

/** Öffentliche Adresse ohne Protokoll, aufgeteilt in feste Basis und den Slug der Abgabe. */
export function publicUrlParts(link: SubmissionLink | null, slug: string): { base: string; slug: string } | null {
  if (!link) return null;
  return { base: `${link.url.replace(/^https?:\/\//, "").replace(/\/+$/, "")}/`, slug: slug || "…" };
}

/** Abschnitte des Dialogs (Design «hocX Abgaben v4»): beim Anlegen fünf Schritte, beim Bearbeiten
 * fünf Karten mit Zusammenfassung, die sich einzeln öffnen lassen. */
export const SECTION_KEYS = ["basics", "window", "responsible", "files", "access"] as const;
export type SectionKey = (typeof SECTION_KEYS)[number];

export type SectionSummary = { label: string; value: string; detail: string; warn: boolean };

type SummaryContext = {
  listName: string | null;
  cycleName: string | null;
  responsibleLabel: string | null;
  hasResponsibleOptions: boolean;
  linkNames: string[];
  exampleEvent?: ExampleEvent | null;
};

/** Zusammenfassung je Abschnitt für die Karten beim Bearbeiten (rein, getestet). */
export function sectionSummaries(form: FormState, context: SummaryContext, t: TFunc): Record<SectionKey, SectionSummary> {
  const isEvents = form.source_type === "events";
  const isList = form.source_type === "list";
  const isManual = form.source_type === "manual";
  const basics: SectionSummary = isEvents
    ? form.tag_filter
      ? { label: t("linkTypeLabel"), value: t("wizard.summary.eventsTagged", { tag: form.tag_filter }), detail: t("wizard.summary.eventsDetail"), warn: false }
      : { label: t("linkTypeLabel"), value: t("wizard.summary.eventsNoTag"), detail: t("wizard.summary.eventsMissing"), warn: true }
    : isList
      ? context.listName
        ? { label: t("linkTypeLabel"), value: t("wizard.summary.listNamed", { name: context.listName }), detail: t("wizard.summary.listDetail"), warn: false }
        : { label: t("linkTypeLabel"), value: t("wizard.summary.listNoName"), detail: t("wizard.summary.listMissing"), warn: true }
      : { label: t("linkTypeLabel"), value: t("sourceManual"), detail: t("wizard.summary.manualDetail"), warn: false };

  const windowParts = [
    form.offset_days_before !== "" ? t("wizard.summary.before", { count: Number(form.offset_days_before) }) : null,
    form.offset_days_after !== "" ? t("wizard.summary.after", { count: Number(form.offset_days_after) }) : null,
  ].filter(Boolean);
  const nextDeadline = nextManualDeadline(form);
  const window: SectionSummary = isManual
    ? {
        label: t("wizard.manual.elementsLabel"),
        value: t("wizard.summary.manualElements", { count: form.manual_elements.length }),
        detail: [
          form.manual_elements.map((element) => element.name.trim()).filter(Boolean).join(", "),
          nextDeadline ? t("wizard.summary.manualNextDeadline", { date: formatDateInputValue(nextDeadline) }) : t("wizard.summary.noDeadline"),
        ].filter(Boolean).join(" · "),
        warn: form.manual_elements.length === 0 || form.manual_elements.some((element) => !element.name.trim()),
      }
    : isEvents
    ? {
        label: t("windowLabel"),
        value: `${windowParts.length ? windowParts.join(", ") : t("wizard.summary.openUntilClosed")}${context.cycleName ? ` · ${context.cycleName}` : ""}`,
        detail: windowExample(form, context.exampleEvent ?? null, t),
        warn: false,
      }
    : {
        label: t("deadlineLabel"),
        value: form.deadline ? formatDateInputValue(form.deadline) : t("wizard.summary.noDeadline"),
        detail: form.deadline ? t("wizard.summary.deadlineDetail") : t("wizard.summary.noDeadlineDetail"),
        warn: false,
      };

  const ownerMode = t(`wizard.ownerShort.${form.owner_access}`);
  const manualResponsible = manualResponsibleCount(form);
  const responsible: SectionSummary = isManual
    ? manualResponsible > 0
      ? {
          label: t("wizard.steps.responsible"),
          value: t("wizard.summary.manualResponsibleValue", { count: manualResponsible, mode: ownerMode }),
          detail: [
            t("wizard.summary.todoPerElement"),
            form.owner_access !== "off" ? t("wizard.summary.ownerDays", { days: form.owner_access_days === "" ? 30 : Number(form.owner_access_days) }) : null,
          ].filter(Boolean).join(" · "),
          warn: false,
        }
      : { label: t("wizard.steps.responsible"), value: t("noAssignment"), detail: t("wizard.summary.nobodyGetsTodo"), warn: false }
    : !context.hasResponsibleOptions
    ? { label: t("wizard.steps.responsible"), value: "—", detail: t("wizard.summary.responsibleNoColumn"), warn: false }
    : form.responsible_participant_source
      ? {
          label: t("wizard.steps.responsible"),
          value: t("wizard.summary.responsibleValue", { name: context.responsibleLabel ?? "", mode: ownerMode }),
          detail: [
            isEvents ? t("wizard.summary.todoPerEvent") : t("wizard.summary.todoPerEntry"),
            form.owner_access !== "off" ? t("wizard.summary.ownerDays", { days: form.owner_access_days === "" ? 30 : Number(form.owner_access_days) }) : null,
          ].filter(Boolean).join(" · "),
          warn: false,
        }
      : { label: t("wizard.steps.responsible"), value: t("noAssignment"), detail: t("wizard.summary.nobodyGetsTodo"), warn: false };

  const typeCount = form.allowed_file_types.length;
  const files: SectionSummary = {
    label: t("wizard.steps.files"),
    value: [
      typeCount === 0 ? t("allFileTypes") : t("fileTypeCount", { count: typeCount }),
      form.max_files_per_element === "" ? t("unlimitedFiles") : t("maxFilesCount", { count: Number(form.max_files_per_element) }),
      t("maxSizeMb", { size: form.max_file_size_mb }),
    ].join(" · "),
    detail: [
      t(`wizard.summary.autoClose.${form.auto_close}`),
      hasEnd(form) && form.keep_open_after_end ? t("wizard.summary.keepOpen") : null,
      form.source_type !== "manual" ? t("wizard.summary.sort", { sort: sortOrderLabel(t)[form.sort_order] }) : null,
    ].filter(Boolean).join(" · "),
    warn: false,
  };

  const access: SectionSummary = {
    label: t("wizard.steps.access"),
    value: `${context.linkNames.length ? context.linkNames.join(", ") : t("wizard.summary.noLink")} · ${t("wizard.summary.reviewers", { count: form.reviewer_ids.length })}`,
    detail: context.linkNames.length ? t("wizard.summary.visibility", { who: t(`wizard.visibilityShort.${form.file_visibility}`) }) : t("wizard.summary.unreachable"),
    warn: context.linkNames.length === 0,
  };

  return { basics, window, responsible, files, access };
}

// Bis zu so vielen Einträgen als Chips (wie im Design), darüber mit Suche
const MAX_CHIPS = 12;
// Höchstzahl Dateien je Abgabefeld (Backend: schemas/submission.py MAX_FILES_PER_ELEMENT)
export const MAX_FILES_PER_ELEMENT = 999;
// Grösste Datei in MB (Backend: max_file_size_mb le=100)
export const MAX_FILE_SIZE_MB = 100;
// Gültigkeit des persönlichen Links (Backend: owner_access_days 1–90)
export const OWNER_ACCESS_DAYS_MAX = 90;
// Vorschläge «+ tag» unter dem Tag-Feld der Pendenzen
const TODO_TAG_QUICK_SUGGESTIONS = 6;

/** Satz für die Fusszeile: Verhalten der Abgabe plus Dateiregeln (Design «summary»). */
export function footerSummary(form: FormState, listName: string | null, t: TFunc): string {
  const typeCount = form.allowed_file_types.length;
  const files = t("fields.footerFiles", {
    types: typeCount === 0 ? t("allFileTypes") : t("fileTypeCount", { count: typeCount }),
    files: form.max_files_per_element === "" ? t("unlimitedFiles") : t("maxFilesCount", { count: Number(form.max_files_per_element) }),
    size: form.max_file_size_mb,
  });
  return `${describeAssignment(form, listName, t)} ${files}`;
}

/** Beispiel ohne Vorsatz «Beispiel:» für die Zeile unter dem Zeitfenster. */
function windowExampleBody(form: FormState, event: ExampleEvent | null, t: TFunc): string {
  const eventDate = event?.event_date ?? new Date().toISOString().slice(0, 10);
  const lastDay = event?.event_end_date ?? eventDate;
  const start = form.offset_days_before === "" ? null : formatDate(addDays(eventDate, -Number(form.offset_days_before)));
  const end = form.offset_days_after === "" ? null : formatDate(addDays(lastDay, Number(form.offset_days_after)));
  const range =
    start && end ? t("windowExampleRange", { start, end })
      : start ? t("windowExampleFrom", { start })
        : end ? t("windowExampleUntil", { end })
          : t("windowExampleOpen");
  return event
    ? t("fields.windowExampleBody", { title: event.title, date: formatDate(eventDate), range })
    : t("fields.windowExampleBodyNoEvent", { date: formatDate(eventDate), range });
}

/** Initialen für einen Avatar («Lea Britschgi» → «LB», «Lea» → «LE»). */
export function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

const SECTION_ICONS: Record<SectionKey, ReactNode> = {
  basics: <ActionIcon name="link" />,
  window: <NavIcon name="events" />,
  responsible: <NavIcon name="participants" />,
  files: <NavIcon name="files" />,
  access: <ActionIcon name="lock" />,
};

/** Feldzeile (Design v6, «Label links»): Label und Hilfetext links, Feld rechts, Trennlinie oben;
 * unter 640 px untereinander. */
function FieldRow({
  label,
  labelId,
  htmlFor,
  help,
  helpId,
  popover,
  extra,
  invalid,
  wide,
  children,
}: {
  label: ReactNode;
  labelId?: string;
  htmlFor?: string;
  help?: ReactNode;
  helpId?: string;
  popover?: ReactNode;
  extra?: ReactNode;
  invalid?: boolean;
  /** Feld über die ganze Breite unter dem Label (z. B. Tabelle der Elemente) */
  wide?: boolean;
  children: ReactNode;
}) {
  const className = ["subm-field-row", wide ? "subm-field-row-wide" : null, invalid ? "subm-edit-invalid" : null].filter(Boolean).join(" ");
  return (
    <div className={className}>
      <div className="subm-field-row-head">
        <span className="subm-field-row-title">
          {htmlFor ? (
            <label id={labelId} htmlFor={htmlFor} className="subm-field-row-label">{label}</label>
          ) : (
            <span id={labelId} className="subm-field-row-label">{label}</span>
          )}
          {popover}
        </span>
        {help ? <span className="subm-field-row-help" id={helpId}>{help}</span> : null}
        {extra}
      </div>
      <div className="subm-field-row-control">{children}</div>
    </div>
  );
}

/** Chips als Einfachauswahl (Tag der Termine, Liste) mit Tastatur wie eine Radio-Gruppe. */
function ChipRadioGroup({
  options,
  value,
  onChange,
  labelledBy,
}: {
  options: { value: string; label: string; count?: number; ariaLabel?: string }[];
  value: string;
  onChange: (value: string) => void;
  labelledBy: string;
}) {
  const itemProps = useRadioGroupKeys(options.length, options.findIndex((option) => option.value === value), (index) => onChange(options[index].value));
  return (
    <div className="subm-edit-chips" role="radiogroup" aria-labelledby={labelledBy}>
      {options.map((option, index) => {
        const { ref, ...keys } = itemProps(index);
        return (
          <button
            key={option.value}
            ref={ref}
            type="button"
            role="radio"
            className="subm-edit-chip"
            aria-checked={option.value === value}
            aria-label={option.ariaLabel}
            onClick={() => onChange(option.value)}
            {...keys}
          >
            {option.label}
            {option.count !== undefined ? <span className="subm-edit-chip-count" aria-hidden="true">{option.count}</span> : null}
          </button>
        );
      })}
    </div>
  );
}

type Props = {
  open: boolean;
  editing: boolean;
  tenantName: string | null;
  form: FormState;
  setForm: Dispatch<SetStateAction<FormState>>;
  links: SubmissionLink[];
  availableLists: StructuredListDefinition[];
  availableTags: string[];
  availableCycleConfigs: CycleConfigSummary[];
  /** Termine für das Beispiel zum Zeitfenster und die Anzahl je Tag (optional). */
  availableEvents?: (ExampleEvent & { tag: string | null })[];
  /** Wählbare Prüfer (aktive Konten mit Login, Migration 0195) */
  availableReviewers?: SubmissionReviewerCandidate[];
  /** Personen des Mandanten für die Verantwortlichen der Elemente einer Einzelabgabe (0198) */
  availableParticipants?: ResponsibleCandidate[];
  /** Tags des Vereins (Farben aus /api/tag-config) als Vorschläge für die Pendenzen-Tags */
  todoTagConfig?: TagConfig;
  /** Rückfrage vor dem Entfernen eines gespeicherten Elements (seine Dateien werden gelöscht). Ohne: sofort */
  confirmRemoveElement?: (name: string) => Promise<boolean>;
  onSubmit: () => void | Promise<void>;
  onClose: () => void;
  onManageLinks: () => void;
};

export function SubmissionAssignmentFormModal({
  open,
  editing,
  tenantName,
  form,
  setForm,
  links,
  availableLists,
  availableTags,
  availableCycleConfigs,
  availableEvents = [],
  availableReviewers = [],
  availableParticipants = [],
  todoTagConfig = {},
  confirmRemoveElement,
  onSubmit,
  onClose,
  onManageLinks,
}: Props) {
  const t = useTranslations("submissionAssignments");
  const locale = useLocale();
  const eventFields = useEventFieldConfig();
  const uid = useId();
  const ids = (name: string) => `${uid}-${name}`;
  // Vorschläge für «Tags für die Pendenzen»: die Tags, die Pendenzen tragen (nicht die Termin-Tags)
  const [todoTagSuggestions, setTodoTagSuggestions] = useState<string[]>([]);
  useEffect(() => {
    let active = true;
    browserApiFetch<string[]>("/api/todos/tags")
      .then((tags) => {
        if (active) setTodoTagSuggestions(tags ?? []);
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, []);
  const problem = formProblem(form, t);
  const problemField = problemFieldOf(form);
  const exampleEvent = form.tag_filter ? pickExampleEvent(availableEvents, form.tag_filter) : null;
  // Anlegen: Schritt 0..4; Bearbeiten: höchstens eine offene Karte. Bei jedem Öffnen von vorn.
  const [step, setStep] = useState(0);
  const [openSection, setOpenSection] = useState<SectionKey | null>(null);
  useEffect(() => {
    if (open) {
      setStep(0);
      setOpenSection(null);
    }
  }, [open]);
  const selectedList = availableLists.find((list) => list.id === form.list_definition_id) ?? null;
  const selectedLinks = links.filter((link) => form.link_ids.includes(link.id));
  const lastStep = SECTION_KEYS.length - 1;
  const tagsAsChips = availableTags.length > 0 && availableTags.length <= MAX_CHIPS; // i18n-ok: Vergleich, kein UI-Text
  const listsAsChips = availableLists.length > 0 && availableLists.length <= MAX_CHIPS; // i18n-ok: Vergleich, kein UI-Text
  const noLinkChosen = links.length > 0 && form.link_ids.length === 0;
  // Anzahl Termine je Tag für die Chips, nur wenn die Termine geladen sind
  const eventsPerTag = new Map<string, number>();
  for (const event of availableEvents) {
    if (event.tag) eventsPerTag.set(event.tag, (eventsPerTag.get(event.tag) ?? 0) + 1);
  }

  const responsibleOptions =
    form.source_type === "events"
      ? singleParticipantEventFields(t)
          // Alias aus den Mandant-Einstellungen; ausgeblendete Felder nur, wenn schon gewählt
          .filter((option) => !eventFields.hidden(option.value) || option.value === form.responsible_participant_source)
          .map((option) => ({ ...option, label: eventFields.label(option.value, option.label) }))
      : form.source_type === "list" && selectedList
        ? [...selectedList.columns]
            // Jede Personen-Spalte der Liste kann die Verantwortlichen liefern (Wert = Spalten-Key)
            .sort((left, right) => left.sort_index - right.sort_index)
            .filter((column) => column.value_type === "participant" || column.value_type === "participants")
            .map((column) => ({ value: column.id, label: column.title }))
        : [];

  const summaries = sectionSummaries(
    form,
    {
      listName: selectedList?.name ?? null,
      cycleName: availableCycleConfigs.find((cycle) => cycle.id === form.cycle_config_id)?.name ?? null,
      responsibleLabel: responsibleOptions.find((option) => option.value === form.responsible_participant_source)?.label ?? null,
      hasResponsibleOptions: responsibleOptions.length > 0,
      linkNames: selectedLinks.map((link) => link.name),
      exampleEvent,
    },
    t
  );

  function toggleLink(linkId: string) {
    setForm((c) => ({
      ...c,
      link_ids: c.link_ids.includes(linkId) ? c.link_ids.filter((id) => id !== linkId) : [...c.link_ids, linkId],
    }));
  }

  function toggleCycleOffset(offset: number) {
    setForm((c) => ({
      ...c,
      cycle_offsets: c.cycle_offsets.includes(offset) ? c.cycle_offsets.filter((o) => o !== offset) : [...c.cycle_offsets, offset],
    }));
  }

  function toggleFileType(type: string) {
    setForm((c) => ({
      ...c,
      allowed_file_types: c.allowed_file_types.includes(type)
        ? c.allowed_file_types.filter((t) => t !== type)
        : [...c.allowed_file_types, type],
    }));
  }

  function toggleFileGroup(types: string[], allSelected: boolean) {
    setForm((c) => ({
      ...c,
      allowed_file_types: [...c.allowed_file_types.filter((t) => !types.includes(t)), ...(allSelected ? [] : types)],
    }));
  }

  function setMaxFiles(value: number | "") {
    // Ohne Maximum gibt es nichts zu erreichen: «Bei Höchstzahl» fällt auf «Nie» zurück.
    setForm((c) => ({ ...c, max_files_per_element: value, auto_close: value === "" && c.auto_close === "max_files" ? "never" : c.auto_close }));
  }

  const isManual = form.source_type === "manual";
  const isEvents = form.source_type === "events";
  // Aktive Personen; bereits gewählte bleiben wählbar (sonst verschwänden sie aus der Auswahl)
  const chosenResponsible = new Set(form.manual_elements.flatMap((element) => element.responsible_participant_ids));
  const responsibleCandidates = availableParticipants.filter((person) => person.is_active !== false || chosenResponsible.has(person.id));
  const hasResponsible = isManual ? manualResponsibleCount(form) > 0 : Boolean(form.responsible_participant_source) && responsibleOptions.length > 0;

  function stepLabel(key: SectionKey): string {
    return isManual && key === "window" ? t("wizard.steps.windowManual") : t(`wizard.steps.${key}`);
  }

  function updateElement(key: string, values: Partial<ManualElementForm>) {
    setForm((c) => ({ ...c, manual_elements: c.manual_elements.map((element) => (element.key === key ? { ...element, ...values } : element)) }));
  }

  function addElement() {
    setForm((c) => ({ ...c, manual_elements: [...c.manual_elements, newManualElement()] }));
  }

  async function removeElement(element: ManualElementForm) {
    // Gespeicherte Elemente können Einreichungen haben: nur nach Rückfrage entfernen
    if (element.id !== null && confirmRemoveElement && !(await confirmRemoveElement(element.name.trim() || t("wizard.manual.unnamed")))) return;
    setForm((c) => ({ ...c, manual_elements: c.manual_elements.filter((item) => item.key !== element.key) }));
  }

  function toggleReviewer(id: string) {
    setForm((c) => ({ ...c, reviewer_ids: c.reviewer_ids.includes(id) ? c.reviewer_ids.filter((x) => x !== id) : [...c.reviewer_ids, id] }));
  }

  function selectSource(value: SubmissionSourceType) {
    setForm((c) => {
      const next = { ...c, source_type: value, responsible_participant_source: "" };
      return value === "manual" ? withManualElement(next) : next;
    });
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    // Enter im Assistenten geht zum nächsten Schritt; erstellt wird erst im letzten
    if (!editing && step < lastStep) {
      setStep((current) => Math.min(lastStep, current + 1));
      return;
    }
    if (problem === null) return onSubmit();
  }

  const sources = sourceOptions(t);
  const sourceKeys = useRadioGroupKeys(sources.length, sources.findIndex((option) => option.value === form.source_type), (index) => selectSource(sources[index].value));
  const summaryText = footerSummary(form, selectedList?.name ?? null, t);
  const help = (anchor: string) => ({ page: "abgabebox" as const, anchor });
  const titleInvalid = problemField === "title" && (editing || step === lastStep);

  function sectionBody(key: SectionKey): ReactNode {
    switch (key) {
      case "basics":
        return (
          <>
            {!editing ? (
              <FieldRow label={t("templatesLabel")} labelId={ids("templates")} help={t("fields.templatesHelp")}>
                <div className="subm-edit-chips" role="group" aria-labelledby={ids("templates")}>
                  {assignmentTemplates(t).map((template) => (
                    <button key={template.key} type="button" className="subm-edit-template-chip" title={template.description} onClick={() => setForm((c) => template.apply(c))}>
                      {template.title}
                    </button>
                  ))}
                </div>
              </FieldRow>
            ) : null}

            <FieldRow label={t("descriptionLabel")} htmlFor={ids("description")} help={t("fields.descriptionHelp")}>
              <textarea
                id={ids("description")}
                rows={2}
                value={form.description}
                placeholder={t("descriptionPlaceholder")}
                onChange={(e) => setForm((c) => ({ ...c, description: e.target.value }))}
              />
            </FieldRow>

            <FieldRow
              label={t("linkTypeLabel")}
              labelId={ids("source")}
              help={t("fields.sourceHelp")}
              popover={<HelpPopover topic={t("linkTypeLabel")} docs={help("quelle")}>{t("helpSource")}</HelpPopover>}
            >
              <div className="subm-edit-sources" role="radiogroup" aria-labelledby={ids("source")}>
                {sources.map((option, index) => {
                  const { ref, ...keys } = sourceKeys(index);
                  return (
                    <button
                      key={option.value}
                      ref={ref}
                      type="button"
                      role="radio"
                      aria-checked={form.source_type === option.value}
                      className="subm-edit-source-card"
                      onClick={() => selectSource(option.value)}
                      {...keys}
                    >
                      <span className="subm-edit-source-title">
                        <span className="subm-radio-dot" aria-hidden="true" />
                        <strong>{option.title}</strong>
                      </span>
                      <small>{option.description}</small>
                    </button>
                  );
                })}
              </div>
            </FieldRow>

            {isEvents ? (
              <FieldRow label={t("fields.eventTagLabel")} labelId={ids("tag")} help={t("fields.eventTagHelp")} invalid={problemField === "tag"}>
                {tagsAsChips ? (
                  <ChipRadioGroup
                    labelledBy={ids("tag")}
                    value={form.tag_filter}
                    onChange={(tag) => setForm((c) => ({ ...c, tag_filter: tag }))}
                    options={availableTags.map((tag) => {
                      const count = eventsPerTag.get(tag);
                      return { value: tag, label: tag, count, ariaLabel: count !== undefined ? t("fields.tagWithCount", { tag, count }) : undefined };
                    })}
                  />
                ) : (
                  <SearchableSelect
                    options={availableTags}
                    getId={(tag) => tag}
                    getLabel={(tag) => tag}
                    value={form.tag_filter || null}
                    onChange={(tag) => setForm((c) => ({ ...c, tag_filter: tag ?? "" }))}
                    placeholder={t("chooseTagPlaceholder")}
                    searchPlaceholder={t("searchTagPlaceholder")}
                    emptyLabel={t("noTagsFound")}
                    triggerProps={{ "aria-labelledby": ids("tag") }}
                  />
                )}
              </FieldRow>
            ) : null}

            {form.source_type === "list" ? (
              <FieldRow label={t("listLabel")} labelId={ids("list")} help={t("fields.listHelp")} invalid={problemField === "list"}>
                {listsAsChips ? (
                  <ChipRadioGroup
                    labelledBy={ids("list")}
                    value={form.list_definition_id}
                    onChange={(id) => setForm((c) => ({ ...c, list_definition_id: id, responsible_participant_source: "" }))}
                    options={availableLists.map((list) => ({ value: list.id, label: list.name }))}
                  />
                ) : (
                  <SearchableSelect
                    options={availableLists}
                    getId={(list) => list.id}
                    getLabel={(list) => list.name}
                    value={form.list_definition_id || null}
                    onChange={(list) => setForm((c) => ({ ...c, list_definition_id: list ? list.id : "", responsible_participant_source: "" }))}
                    placeholder={t("chooseListPlaceholder")}
                    searchPlaceholder={t("searchListPlaceholder")}
                    emptyLabel={t("noListsFound")}
                    triggerProps={{ "aria-labelledby": ids("list") }}
                  />
                )}
              </FieldRow>
            ) : null}
          </>
        );

      case "window":
        if (isManual) {
          return (
            <FieldRow
              wide
              label={t("wizard.manual.elementsLabel")}
              labelId={ids("elements")}
              help={t("wizard.manual.windowHelp")}
              invalid={problemField === "elements"}
              popover={<HelpPopover topic={t("wizard.manual.elementsLabel")} docs={help("stichtag")}>{t("wizard.manual.help")}</HelpPopover>}
            >
              <div className="subm-elements">
                <div className="subm-elements-head" aria-hidden="true">
                  <span>{t("fields.elementColumn")}</span>
                  <span>{t("wizard.manual.startLabel")}</span>
                  <span>{t("wizard.manual.endLabel")}</span>
                  <span>{t("wizard.steps.responsible")}</span>
                  <span />
                </div>
                <ul className="subm-elements-list" aria-labelledby={ids("elements")}>
                  {form.manual_elements.map((element, index) => {
                    const name = element.name.trim() || t("wizard.manual.unnamed");
                    return (
                      <li key={element.key} className="subm-element-row">
                        <label className="subm-element-cell subm-element-name">
                          <span className="subm-element-cell-label">{t("wizard.manual.nameLabel")}</span>
                          <input
                            value={element.name}
                            aria-invalid={!element.name.trim() ? true : undefined}
                            placeholder={t("wizard.manual.namePlaceholder")}
                            onChange={(event) => updateElement(element.key, { name: event.target.value })}
                          />
                        </label>
                        <label className="subm-element-cell">
                          <span className="subm-element-cell-label">{t("wizard.manual.startLabel")}</span>
                          <DateInput
                            value={element.window_start}
                            max={element.window_end || undefined}
                            onChange={(value) => updateElement(element.key, { window_start: value })}
                            aria-label={t("wizard.manual.startAria", { index: index + 1 })}
                          />
                        </label>
                        <label className="subm-element-cell">
                          <span className="subm-element-cell-label">{t("wizard.manual.endLabel")}</span>
                          <DateInput
                            value={element.window_end}
                            min={element.window_start || undefined}
                            onChange={(value) => updateElement(element.key, { window_end: value })}
                            aria-label={t("wizard.manual.endAria", { index: index + 1 })}
                          />
                        </label>
                        <div className="subm-element-cell subm-element-responsible">
                          <span className="subm-element-cell-label" aria-hidden="true">{t("wizard.steps.responsible")}</span>
                          <SearchableMultiSelect
                            options={responsibleCandidates}
                            getId={(person) => person.id}
                            getLabel={(person) => person.display_name}
                            values={element.responsible_participant_ids}
                            onChange={(selected) => updateElement(element.key, { responsible_participant_ids: selected })}
                            emptySelectionLabel={t("wizard.manual.responsibleNone")}
                            emptyLabel={t("wizard.manual.noParticipants")}
                            triggerProps={{ "aria-label": t("wizard.manual.responsibleAria", { name }) }}
                          />
                        </div>
                        <button
                          type="button"
                          className="button-icon-soft button-icon-soft-danger subm-element-remove"
                          aria-label={t("wizard.manual.removeElement", { name })}
                          title={t("wizard.manual.removeElement", { name })}
                          disabled={form.manual_elements.length === 1}
                          onClick={() => void removeElement(element)}
                        >
                          <ActionIcon name="delete" />
                        </button>
                      </li>
                    );
                  })}
                </ul>
                <div className="subm-elements-foot">
                  <button type="button" className="subm-add-element" onClick={addElement}>{t("wizard.manual.addElement")}</button>
                </div>
              </div>
            </FieldRow>
          );
        }
        return isEvents ? (
          <>
            <FieldRow
              label={t("windowLabel")}
              labelId={ids("window")}
              help={t("fields.windowHelp")}
              invalid={problemField === "window"}
              popover={<HelpPopover topic={t("windowLabel")} docs={help("zeitfenster")}>{t("helpWindow")}</HelpPopover>}
            >
              <div className="subm-window" role="group" aria-labelledby={ids("window")}>
                <div className="subm-window-grid">
                  <div className="subm-window-side">
                    <span className="subm-window-caption">{t("opens")}</span>
                    <div className="subm-window-control">
                      <NumberStepper
                        value={form.offset_days_before}
                        onChange={(value) => setForm((c) => ({ ...c, offset_days_before: value }))}
                        min={0}
                        max={OFFSET_DAYS_MAX}
                        allowEmpty
                        emptyLabel={t("fields.immediately")}
                        label={t("daysBeforeEvent")}
                      />
                      <span>{t("fields.daysBefore")}</span>
                    </div>
                  </div>
                  <div className="subm-window-event">
                    <span className="subm-window-caption">{t("fields.event")}</span>
                    <span className="subm-window-event-date">{formatShortWeekdayDate(exampleEvent?.event_date ?? new Date().toISOString().slice(0, 10), locale)}</span>
                  </div>
                  <div className="subm-window-side subm-window-side-end">
                    <span className="subm-window-caption">{t("fields.closes")}</span>
                    <div className="subm-window-control">
                      <NumberStepper
                        value={form.offset_days_after}
                        onChange={(value) => setForm((c) => ({ ...c, offset_days_after: value }))}
                        min={0}
                        max={OFFSET_DAYS_MAX}
                        allowEmpty
                        emptyLabel={t("fields.never")}
                        label={t("daysAfterEvent")}
                      />
                      <span>{t("fields.daysAfter")}</span>
                    </div>
                  </div>
                </div>
                <div className="subm-window-bar" aria-hidden="true">
                  <span className={form.offset_days_before === "" ? "subm-window-track subm-window-track-open" : "subm-window-track"} />
                  <span className="subm-window-dot" />
                  <span className={form.offset_days_after === "" ? "subm-window-track subm-window-track-open" : "subm-window-track"} />
                </div>
                <p className="subm-window-example" aria-live="polite">
                  <strong>{t("fields.exampleLabel")}</strong>
                  <span>{windowExampleBody(form, exampleEvent, t)}</span>
                </p>
              </div>
            </FieldRow>
            {availableCycleConfigs.length > 0 ? (
              <FieldRow
                label={t("cycleLabel")}
                labelId={ids("cycle")}
                help={t("fields.cycleHelp")}
                invalid={problemField === "cycle"}
                popover={<HelpPopover topic={t("cycleLabel")} docs={help("zyklus")}>{t("cycleHelp")}</HelpPopover>}
              >
                <div className="subm-field-stack">
                  <SegmentedControl
                    aria-labelledby={ids("cycle")}
                    value={form.cycle_config_id}
                    // Beim Aktivieren des Filters ist der aktuelle Zyklus vorausgewählt.
                    onChange={(id) => setForm((c) => ({ ...c, cycle_config_id: id, cycle_offsets: id ? (c.cycle_offsets.length > 0 ? c.cycle_offsets : [0]) : [] }))}
                    options={[{ value: "", label: t("fields.allCycles") }, ...availableCycleConfigs.map((cycle) => ({ value: cycle.id, label: cycle.name }))]}
                  />
                  {form.cycle_config_id ? (
                    <div className="subm-edit-chips" role="group" aria-label={t("fields.cycleOffsetsLabel")}>
                      {CYCLE_OFFSET_OPTIONS.map((offset) => (
                        <button key={offset} type="button" className="subm-edit-chip subm-edit-chip-check" aria-pressed={form.cycle_offsets.includes(offset)} onClick={() => toggleCycleOffset(offset)}>
                          <span className="subm-check" aria-hidden="true" />
                          {cycleOffsetLabel(offset, t)}
                        </button>
                      ))}
                    </div>
                  ) : null}
                </div>
              </FieldRow>
            ) : null}
          </>
        ) : (
          <FieldRow
            label={t("deadlineLabel")}
            labelId={ids("deadline")}
            help={form.deadline ? t("wizard.deadlineHelp") : t("wizard.summary.noDeadlineDetail")}
            popover={<HelpPopover topic={t("deadlineLabel")} docs={help("stichtag")}>{t("helpDeadline")}</HelpPopover>}
          >
            <div className="subm-field-inline">
              <SegmentedControl
                aria-labelledby={ids("deadline")}
                value={form.deadline ? "with" : "open"}
                // Vorschlag: in zwei Wochen; lässt sich daneben ändern
                onChange={(mode) => setForm((c) => ({ ...c, deadline: mode === "with" ? c.deadline || addDays(new Date().toISOString().slice(0, 10), 14) : "" }))}
                options={[
                  { value: "with", label: t("wizard.withDeadline") },
                  { value: "open", label: t("wizard.openUntilClosed") },
                ]}
              />
              {form.deadline ? (
                <div className="subm-deadline-input">
                  <DateInput value={form.deadline} onChange={(deadline) => setForm((c) => ({ ...c, deadline }))} aria-label={t("deadlineLabel")} />
                </div>
              ) : null}
            </div>
          </FieldRow>
        );

      case "responsible":
        return (
          <>
            {isManual ? (
              <p className="subm-field-note">
                {manualResponsibleCount(form) > 0
                  ? t("fields.manualResponsibleSome", { count: manualResponsibleCount(form), total: form.manual_elements.length })
                  : t("fields.manualResponsibleNone")}
              </p>
            ) : responsibleOptions.length === 0 ? (
              <p className="subm-field-note">{t("wizard.noResponsibleList")}</p>
            ) : (
              <FieldRow
                label={t("responsiblePersonLabel")}
                labelId={ids("responsible")}
                help={isEvents ? t("responsiblePersonHelpEvents") : t("responsiblePersonHelpList")}
                popover={<HelpPopover topic={t("responsiblePersonLabel")} docs={help("verantwortliche")}>{t("helpResponsible")}</HelpPopover>}
              >
                <SegmentedControl
                  aria-labelledby={ids("responsible")}
                  value={form.responsible_participant_source}
                  onChange={(value) => setForm((c) => ({ ...c, responsible_participant_source: value }))}
                  options={[{ value: "", label: t("noAssignment") }, ...responsibleOptions]}
                />
              </FieldRow>
            )}
            {hasResponsible ? (
              <>
                <FieldRow label={t("todoTagsLabel")} labelId={ids("todo-tags")} help={t("todoTagsHelp")}>
                  <div className="subm-field-stack">
                    <TagInput
                      value={form.todo_tags.join(",")}
                      onChange={(value) => setForm((c) => ({ ...c, todo_tags: value.split(",").map((tag) => tag.trim()).filter(Boolean) }))}
                      suggestions={todoTagSuggestions}
                      tagConfig={todoTagConfig}
                      quickSuggestions={TODO_TAG_QUICK_SUGGESTIONS}
                      extraChips={
                        form.todo_own_tag && form.title.trim() ? (
                          <span className="subm-auto-tag">
                            {form.title.trim()}
                            <small>{t("fields.autoChip")}</small>
                          </span>
                        ) : null
                      }
                    />
                    <Switch
                      checked={form.todo_own_tag}
                      onChange={(checked) => setForm((c) => ({ ...c, todo_own_tag: checked }))}
                      label={t("todoOwnTagLabel")}
                      help={t("todoOwnTagHelp", { tag: form.title.trim() || t("todoOwnTagUntitled") })}
                    />
                  </div>
                </FieldRow>
                <FieldRow
                  label={t("fields.ownerLabel")}
                  labelId={ids("owner")}
                  help={t("fields.ownerHelp")}
                  popover={<HelpPopover topic={t("ownerAccessLabel")} docs={help("persoenlicher-link")}>{t("helpOwnerAccess")}</HelpPopover>}
                >
                  <div className="subm-field-stack">
                    <SegmentedControl
                      aria-labelledby={ids("owner")}
                      value={form.owner_access}
                      onChange={(mode) => setForm((c) => ({ ...c, owner_access: mode }))}
                      options={(["manage", "view", "off"] as const).map((mode) => ({ value: mode, label: t(`fields.ownerSegment.${mode}`) }))}
                    />
                    <p className="subm-field-description">{t(`fields.ownerDescription.${form.owner_access}`)}</p>
                    {form.owner_access !== "off" ? (
                      <div className="subm-field-panel">
                        <div className="subm-field-inline">
                          <span id={ids("owner-days")}>{t("fields.ownerValidFor")}</span>
                          <NumberStepper
                            value={form.owner_access_days}
                            onChange={(value) => setForm((c) => ({ ...c, owner_access_days: value }))}
                            min={1}
                            max={OWNER_ACCESS_DAYS_MAX}
                            label={t("ownerAccessDaysLabel")}
                          />
                          <span>{t("fields.ownerDaysSuffix", { max: OWNER_ACCESS_DAYS_MAX })}</span>
                        </div>
                        {form.owner_access === "manage" ? (
                          <Switch
                            checked={form.owner_resubmit_only_personal}
                            onChange={(checked) => setForm((c) => ({ ...c, owner_resubmit_only_personal: checked }))}
                            label={t("fields.onlyPersonalLabel")}
                            help={t("ownerResubmitOnlyPersonalHelp")}
                          />
                        ) : null}
                      </div>
                    ) : null}
                  </div>
                </FieldRow>
              </>
            ) : null}
          </>
        );

      case "files":
        return (
          <>
            <FieldRow
              label={t("allowedFileTypesLabel")}
              labelId={ids("types")}
              help={t("fields.fileTypesHelp")}
              popover={<HelpPopover topic={t("allowedFileTypesLabel")} docs={help("dateien")}>{t("helpFileTypes")}</HelpPopover>}
            >
              <div className="subm-type-cards" role="group" aria-labelledby={ids("types")}>
                {fileTypeGroups(t).map((group) => {
                  const chosen = group.types.filter((type) => form.allowed_file_types.includes(type)).length;
                  const allSelected = chosen === group.types.length;
                  const state = allSelected ? "on" : chosen > 0 ? "mixed" : "off";
                  return (
                    <div key={group.label} className="subm-type-card" data-state={state}>
                      <button
                        type="button"
                        className="subm-type-card-toggle"
                        aria-pressed={allSelected ? true : chosen > 0 ? "mixed" : false}
                        onClick={() => toggleFileGroup(group.types, allSelected)}
                      >
                        <span className="subm-check" data-state={state} aria-hidden="true" />
                        <span>{group.label}</span>
                      </button>
                      <span className="subm-type-card-exts">
                        {group.types.map((type) => (
                          <button key={type} type="button" className="subm-type-ext" aria-pressed={form.allowed_file_types.includes(type)} aria-label={`.${type}`} onClick={() => toggleFileType(type)}>
                            {type}
                          </button>
                        ))}
                      </span>
                    </div>
                  );
                })}
              </div>
            </FieldRow>

            <FieldRow label={t("fields.amountsLabel")} help={t("fields.amountsHelp")}>
              <div className="subm-amounts">
                <div className="subm-amount">
                  <span className="subm-window-caption" id={ids("max-files")}>{t("fields.maxFilesLabel")}</span>
                  <div className="subm-field-inline">
                    <NumberStepper
                      value={form.max_files_per_element}
                      onChange={setMaxFiles}
                      min={1}
                      max={MAX_FILES_PER_ELEMENT}
                      allowEmpty
                      decrementToEmpty={false}
                      emptyLabel={t("unlimited")}
                      emptyPlaceholder={t("fields.unlimitedSymbol")}
                      label={t("fields.maxFilesLabel")}
                    />
                    <button
                      type="button"
                      className="subm-edit-chip"
                      aria-pressed={form.max_files_per_element === ""}
                      onClick={() => setMaxFiles(form.max_files_per_element === "" ? initialForm.max_files_per_element : "")}
                    >
                      {t("unlimited")}
                    </button>
                  </div>
                </div>
                <div className="subm-amount">
                  <span className="subm-window-caption">{t("fields.maxSizeLabel")}</span>
                  <div className="subm-field-inline">
                    <NumberStepper
                      value={form.max_file_size_mb}
                      onChange={(value) => setForm((c) => ({ ...c, max_file_size_mb: value === "" ? c.max_file_size_mb : value }))}
                      min={1}
                      max={MAX_FILE_SIZE_MB}
                      label={t("fields.maxSizeLabel")}
                    />
                    <span>{t("fields.mb")}</span>
                  </div>
                </div>
              </div>
            </FieldRow>

            <FieldRow
              label={t("autoCloseLabel")}
              labelId={ids("auto-close")}
              help={form.max_files_per_element === "" ? t("autoCloseHelpUnlimited") : t("autoCloseHelp")}
              helpId={ids("auto-close-help")}
              popover={<HelpPopover topic={t("autoCloseLabel")} docs={help("automatisch-schliessen")}>{t("helpAutoClose")}</HelpPopover>}
            >
              <div className="subm-field-stack">
                <SegmentedControl
                  aria-labelledby={ids("auto-close")}
                  value={form.auto_close}
                  onChange={(value) => setForm((c) => ({ ...c, auto_close: value }))}
                  options={autoCloseOptions(t).map((option) => ({
                    ...option,
                    disabled: option.value === "max_files" && form.max_files_per_element === "",
                    describedBy: option.value === "max_files" ? ids("auto-close-help") : undefined,
                  }))}
                />
                {hasEnd(form) ? (
                  <Switch
                    checked={form.keep_open_after_end}
                    onChange={(checked) => setForm((c) => ({ ...c, keep_open_after_end: checked }))}
                    label={t("keepOpenLabel")}
                    help={t("keepOpenHelp")}
                  />
                ) : null}
              </div>
            </FieldRow>

            {!isManual ? (
              <FieldRow label={t("sortOrderLabel")} labelId={ids("sort")} help={t("fields.sortHelp")}>
                <SegmentedControl
                  aria-labelledby={ids("sort")}
                  value={form.sort_order}
                  onChange={(value) => setForm((c) => ({ ...c, sort_order: value }))}
                  options={(["date", "proximity", "alphabetical"] as const).map((value) => ({ value, label: sortOrderLabel(t)[value] }))}
                />
              </FieldRow>
            ) : null}
          </>
        );

      case "access":
        return (
          <>
            <FieldRow
              label={t("reachableViaLabel")}
              labelId={ids("links")}
              help={t("fields.linksHelp")}
              popover={<HelpPopover topic={t("publicLinkLabel")} docs={help("links")}>{t("helpLinks")}</HelpPopover>}
              extra={<button type="button" className="subm-field-row-link" onClick={onManageLinks}>{t("fields.manageLinks")}</button>}
            >
              {links.length === 0 ? (
                <p className="subm-field-note">{t("noLinkYetHelp")}</p>
              ) : (
                <div className="subm-link-cards" role="group" aria-labelledby={ids("links")}>
                  {links.map((link) => {
                    const url = publicUrlParts(link, form.public_slug);
                    const chosen = form.link_ids.includes(link.id);
                    return (
                      <button key={link.id} type="button" className="subm-link-card" aria-pressed={chosen} onClick={() => toggleLink(link.id)}>
                        <span className="subm-check" data-state={chosen ? "on" : "off"} aria-hidden="true" />
                        <span className="subm-link-card-text">
                          <span className="subm-link-card-name">
                            <span>{link.name}</span>
                            {link.is_default ? <Badge variant="neutral">{t("defaultLabel")}</Badge> : null}
                          </span>
                          {url ? <code className="subm-link-card-url">{url.base}<strong>{url.slug}</strong></code> : null}
                        </span>
                      </button>
                    );
                  })}
                  {noLinkChosen ? <span className="subm-edit-warn">{t("noLinkSelectedHelp")}</span> : null}
                </div>
              )}
            </FieldRow>

            <FieldRow label={t("reviewers.label")} labelId={ids("reviewers")} help={t("reviewers.help")}>
              {availableReviewers.length === 0 ? (
                <p className="subm-field-note">{t("reviewers.noCandidates")}</p>
              ) : availableReviewers.length <= MAX_CHIPS ? (
                <div className="subm-edit-chips" role="group" aria-labelledby={ids("reviewers")}>
                  {availableReviewers.map((reviewer) => (
                    <button key={reviewer.id} type="button" className="subm-edit-chip subm-edit-chip-person" aria-pressed={form.reviewer_ids.includes(reviewer.id)} onClick={() => toggleReviewer(reviewer.id)}>
                      <span className="subm-chip-avatar" aria-hidden="true">{initials(reviewer.display_name)}</span>
                      {reviewer.display_name}
                    </button>
                  ))}
                </div>
              ) : (
                <SearchableMultiSelect
                  options={availableReviewers}
                  getId={(reviewer) => reviewer.id}
                  getLabel={(reviewer) => reviewer.display_name}
                  values={form.reviewer_ids}
                  onChange={(selected) => setForm((c) => ({ ...c, reviewer_ids: selected }))}
                  emptySelectionLabel={t("reviewers.none")}
                  emptyLabel={t("reviewers.noCandidates")}
                  triggerProps={{ "aria-labelledby": ids("reviewers") }}
                />
              )}
            </FieldRow>

            <FieldRow label={t("fields.visibilityLabel")} labelId={ids("visibility")} help={t("fields.visibilityHelp")}>
              <div className="subm-field-stack">
                <SegmentedControl
                  aria-labelledby={ids("visibility")}
                  value={form.file_visibility}
                  onChange={(mode) => setForm((c) => ({ ...c, file_visibility: mode }))}
                  options={(["default", "role_only", "all_participants", "own_submissions"] as const).map((mode) => ({ value: mode, label: t(`wizard.visibilityChip.${mode}`) }))}
                />
                <p className="subm-field-description">{t(`fileVisibility.help.${form.file_visibility}`)}</p>
                {form.file_visibility === "all_participants" || form.file_visibility === "own_submissions" ? (
                  <div className="subm-field-inline">
                    <span id={ids("visibility-filter")}>{t("fields.visibilityFilterLabel")}</span>
                    <SegmentedControl
                      aria-labelledby={ids("visibility-filter")}
                      value={form.file_visibility_filter}
                      onChange={(filter) => setForm((c) => ({ ...c, file_visibility_filter: filter }))}
                      options={(["images", "all"] as const).map((filter) => ({ value: filter, label: t(`fileVisibility.filter.${filter}`) }))}
                    />
                  </div>
                ) : null}
              </div>
            </FieldRow>
          </>
        );
    }
  }

  const currentKey = SECTION_KEYS[step];

  return (
    <Modal open={open} title={editing ? t("editAssignment") : t("createAssignment")} className={editing ? "subm-edit-modal" : "subm-edit-modal subm-edit-modal-wizard"} hideCloseButton onClose={onClose}>
      <ModalSaveForm className="subm-edit-form" onSubmit={handleSubmit}>
        <header className="subm-edit-heading">
          <div className="subm-edit-eyebrow">
            {editing ? t("editAssignment") : t("newAssignment")}
            {tenantName ? <><span aria-hidden="true">·</span><span>{tenantName}</span></> : null}
          </div>
          <input
            aria-label={t("titleLabel")}
            aria-invalid={titleInvalid ? true : undefined}
            className="subm-edit-title"
            placeholder={t("titlePlaceholder")}
            value={form.title}
            autoFocus={!editing}
            onChange={(e) => {
              const title = e.target.value;
              setForm((c) =>
                editing
                  ? { ...c, title }
                  : {
                      ...c,
                      title,
                      public_slug: slugify(title),
                      // Elemente, die bisher wie die Abgabe hiessen, ziehen mit
                      manual_elements: c.manual_elements.map((element) => (element.id === null && element.name === c.title.trim() ? { ...element, name: title.trim() } : element)),
                    }
              );
            }}
          />
          <button type="button" className="subm-edit-close" title={t("close")} aria-label={t("close")} onClick={onClose}><ActionIcon name="close" /></button>
        </header>

        <div className="subm-edit-main">
          {editing ? (
            SECTION_KEYS.map((key) => {
              const summary = summaries[key];
              const isOpen = openSection === key;
              return (
                <section key={key} className={isOpen ? "subm-edit-section subm-edit-section-open" : "subm-edit-section"}>
                  <button
                    type="button"
                    className="subm-edit-section-toggle"
                    aria-expanded={isOpen}
                    aria-controls={ids(`section-${key}`)}
                    onClick={() => setOpenSection(isOpen ? null : key)}
                  >
                    <span className="subm-edit-section-icon" aria-hidden="true">{SECTION_ICONS[key]}</span>
                    <span className="subm-edit-section-text">
                      <span className="subm-edit-section-label">
                        {stepLabel(key)}
                        {summary.warn ? <span className="subm-edit-warn-dot" aria-hidden="true" /> : null}
                      </span>
                      <span className="subm-edit-section-value">{summary.value}</span>
                      <span className={summary.warn ? "subm-edit-section-detail subm-edit-warn" : "subm-edit-section-detail"}>{summary.detail}</span>
                    </span>
                    <span className="subm-edit-section-action">{isOpen ? t("wizard.done") : t("wizard.change")}</span>
                  </button>
                  {isOpen ? (
                    <div id={ids(`section-${key}`)} className="subm-edit-section-body subm-edit-reveal">
                      {sectionBody(key)}
                    </div>
                  ) : null}
                </section>
              );
            })
          ) : (
            <>
              <ol className="subm-edit-steps">
                {SECTION_KEYS.map((key, index) => (
                  <li key={key}>
                    <button
                      type="button"
                      className="subm-edit-step"
                      aria-label={`${index + 1}. ${stepLabel(key)}`}
                      aria-current={index === step ? "step" : undefined}
                      data-done={index < step ? "true" : undefined}
                      onClick={() => setStep(index)}
                    >
                      <span className="subm-edit-step-bar" aria-hidden="true" />
                      <span>{index + 1}. {stepLabel(key)}</span>
                    </button>
                  </li>
                ))}
              </ol>
              <div className="subm-edit-step-body subm-edit-reveal" key={currentKey}>
                <div className="subm-edit-step-heading">
                  <h3 className="subm-edit-question">{stepLabel(currentKey)}</h3>
                  <span>{isManual && currentKey === "window" ? t("wizard.questions.windowManual") : t(`wizard.questions.${currentKey}`)}</span>
                </div>
                {sectionBody(currentKey)}
              </div>
            </>
          )}
        </div>

        <footer className="subm-edit-footer">
          <p key={summaryText} className="subm-edit-footer-summary">{summaryText}</p>
          <div className="subm-edit-actions">
            {(editing || step === lastStep) && problem !== null ? <span className="subm-edit-problem" role="status">{t("saveBlockedHint", { problem })}</span> : null}
            {editing ? (
              <>
                <button type="button" className="button-secondary" onClick={onClose}>{t("cancel")}</button>
                <button data-modal-save type="submit" className="button-primary" disabled={problem !== null}>{t("saveAssignment")}</button>
              </>
            ) : (
              <>
                <button type="button" className="button-secondary" onClick={step === 0 ? onClose : () => setStep(step - 1)}>
                  {step === 0 ? t("cancel") : t("wizard.back")}
                </button>
                {/* Eigene keys: sonst macht React aus demselben Knopf beim Klick auf «Weiter» einen
                    Submit-Knopf, und der Browser sendet das Formular noch im selben Klick ab
                    (der letzte Schritt würde übersprungen). */}
                {step < lastStep ? (
                  <button key="wizard-next" type="button" className="button-primary" onClick={() => setStep(step + 1)}>{t("wizard.next")}</button>
                ) : (
                  <button key="wizard-create" data-modal-save type="submit" className="button-primary" disabled={problem !== null}>{t("saveAssignment")}</button>
                )}
              </>
            )}
          </div>
        </footer>
      </ModalSaveForm>
    </Modal>
  );
}
