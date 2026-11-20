"use client";

import { Dispatch, FormEvent, ReactNode, SetStateAction, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { useEventFieldConfig } from "@/lib/hooks/use-event-field-config";

import { DateInput } from "@/components/ui/date-input";
import { HelpPopover } from "@/components/ui/help-popover";
import { Modal, ModalSaveForm } from "@/components/ui/modal";
import { ActionIcon } from "@/components/ui/action-icons";
import { NavIcon } from "@/components/ui/nav-icons";
import { SearchableMultiSelect, SearchableSelect } from "@/components/ui/searchable-select";
import { TagInput } from "@/components/ui/tag-input";
import type { TagConfig } from "@/lib/hooks/use-tag-config";
import { formatDate, formatDateInputValue } from "@/lib/utils/format";
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

// Termin-Felder, die als "verantwortliche Person" einer Termin-Abgabe in Frage kommen.
function singleParticipantEventFields(t: TFunc): { value: string; label: string }[] {
  return [
    { value: "spezial1_ids", label: t("special1") },
    { value: "spezial2_ids", label: t("special2") },
    { value: "spezial3_ids", label: t("special3") },
  ];
}

// Zyklen, die ausgewählt werden können: 0 = aktueller Zyklus, -1 = vorheriger usw.
export const CYCLE_OFFSET_OPTIONS = [0, -1, -2, -3];

export function cycleOffsetLabel(offset: number, t: TFunc): string {
  return offset === 0 ? t("currentCycle") : offset === -1 ? t("previousCycle") : t("cycleOffsetNamed", { offset: Math.abs(offset) });
}

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
    { value: "first_upload", label: t("autoCloseFirstUpload") },
    { value: "max_files", label: t("autoCloseMaxFiles") },
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

const SECTION_ICONS: Record<SectionKey, ReactNode> = {
  basics: <ActionIcon name="link" />,
  window: <NavIcon name="events" />,
  responsible: <NavIcon name="participants" />,
  files: <NavIcon name="files" />,
  access: <ActionIcon name="lock" />,
};

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
  /** Termine für das Beispiel zum Zeitfenster (optional). */
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
  const eventFields = useEventFieldConfig();
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
  const previewLink = selectedLinks.find((link) => link.is_default) ?? selectedLinks[0] ?? null;
  const url = publicUrlParts(previewLink, form.public_slug);
  const lastStep = SECTION_KEYS.length - 1;
  const tagsAsChips = availableTags.length > 0 && availableTags.length <= MAX_CHIPS; // i18n-ok: Vergleich, kein UI-Text
  const listsAsChips = availableLists.length > 0 && availableLists.length <= MAX_CHIPS; // i18n-ok: Vergleich, kein UI-Text
  const noLinkChosen = links.length > 0 && form.link_ids.length === 0;

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

  const isManual = form.source_type === "manual";
  // Aktive Personen; bereits gewählte bleiben wählbar (sonst verschwänden sie aus der Auswahl)
  const chosenResponsible = new Set(form.manual_elements.flatMap((element) => element.responsible_participant_ids));
  const responsibleCandidates = availableParticipants.filter((person) => person.is_active !== false || chosenResponsible.has(person.id));

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

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    // Enter im Assistenten geht zum nächsten Schritt; erstellt wird erst im letzten
    if (!editing && step < lastStep) {
      setStep((current) => Math.min(lastStep, current + 1));
      return;
    }
    if (problem === null) return onSubmit();
  }

  const fileTypeCount = form.allowed_file_types.length;
  const maxFilesLabel = form.max_files_per_element === "" ? t("unlimitedFiles") : t("maxFilesCount", { count: form.max_files_per_element });
  const summaryText = describeAssignment(form, selectedList?.name ?? null, t);
  const help = (anchor: string) => ({ page: "abgabebox" as const, anchor });

  function sectionBody(key: SectionKey): ReactNode {
    switch (key) {
      case "basics":
        return (
          <>
            {!editing ? (
              <div className="subm-edit-basics">
                <label className={problemField === "title" && step === lastStep ? "field-stack subm-edit-invalid" : "field-stack"}>
                  <span className="field-label">{t("titleLabel")}</span>
                  <input
                    value={form.title}
                    placeholder={t("titlePlaceholder")}
                    autoFocus
                    onChange={(e) => {
                      const title = e.target.value;
                      setForm((c) => ({
                        ...c,
                        title,
                        public_slug: slugify(title),
                        // Elemente, die bisher wie die Abgabe hiessen, ziehen mit
                        manual_elements: c.manual_elements.map((element) => (element.id === null && element.name === c.title.trim() ? { ...element, name: title.trim() } : element)),
                      }));
                    }}
                  />
                </label>
                <div className="subm-edit-quickstart" role="group" aria-label={t("templatesLabel")}>
                  <span>{t("wizard.quickStart")}</span>
                  {assignmentTemplates(t).map((template) => (
                    <button key={template.key} type="button" className="subm-edit-template-chip" title={template.description} onClick={() => setForm((c) => template.apply(c))}>
                      {template.title}
                    </button>
                  ))}
                </div>
              </div>
            ) : null}

            <div className="field-stack">
              <span className="field-label">
                <span id="subm-source-label">{t("wizard.sourceQuestion")}</span>
                <HelpPopover topic={t("linkTypeLabel")} docs={help("quelle")}>{t("helpSource")}</HelpPopover>
              </span>
              <div className="subm-edit-sources" role="radiogroup" aria-labelledby="subm-source-label">
                {sourceOptions(t).map((option) => (
                  <button
                    key={option.value}
                    type="button"
                    role="radio"
                    aria-checked={form.source_type === option.value}
                    className="subm-edit-source-card"
                    onClick={() => setForm((c) => {
                      const next = { ...c, source_type: option.value, responsible_participant_source: "" };
                      return option.value === "manual" ? withManualElement(next) : next;
                    })}
                  >
                    <strong>{option.title}</strong>
                    <small>{option.description}</small>
                  </button>
                ))}
              </div>
            </div>

            {form.source_type === "events" ? (
              <div className={problemField === "tag" ? "field-stack subm-edit-invalid" : "field-stack"}>
                <span className="field-label" id="subm-tag-label">{t("tagFilterLabel")}</span>
                {tagsAsChips ? (
                  <div className="subm-edit-chips" role="radiogroup" aria-labelledby="subm-tag-label">
                    {availableTags.map((tag) => (
                      <button key={tag} type="button" role="radio" className="subm-edit-chip" aria-checked={form.tag_filter === tag} onClick={() => setForm((c) => ({ ...c, tag_filter: tag }))}>
                        {tag}
                      </button>
                    ))}
                  </div>
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
                  />
                )}
              </div>
            ) : null}

            {form.source_type === "list" ? (
              <div className={problemField === "list" ? "field-stack subm-edit-invalid" : "field-stack"}>
                <span className="field-label" id="subm-list-label">{t("listLabel")}</span>
                {listsAsChips ? (
                  <div className="subm-edit-chips" role="radiogroup" aria-labelledby="subm-list-label">
                    {availableLists.map((list) => (
                      <button
                        key={list.id}
                        type="button"
                        role="radio"
                        className="subm-edit-chip"
                        aria-checked={form.list_definition_id === list.id}
                        onClick={() => setForm((c) => ({ ...c, list_definition_id: list.id, responsible_participant_source: "" }))}
                      >
                        {list.name}
                      </button>
                    ))}
                  </div>
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
                  />
                )}
              </div>
            ) : null}
          </>
        );

      case "window":
        if (isManual) {
          return (
            <div className={problemField === "elements" ? "field-stack subm-edit-invalid" : "field-stack"}>
              <span className="field-label">
                <span id="subm-elements-label">{t("wizard.manual.elementsLabel")}</span>
                <HelpPopover topic={t("wizard.manual.elementsLabel")} docs={help("stichtag")}>{t("wizard.manual.help")}</HelpPopover>
              </span>
              <ul className="subm-edit-elements" aria-labelledby="subm-elements-label">
                {form.manual_elements.map((element, index) => (
                  <li key={element.key} className="subm-edit-element-row">
                    <label className="field-stack subm-edit-element-name">
                      <span className="field-label">{t("wizard.manual.nameLabel")}</span>
                      <input
                        value={element.name}
                        aria-invalid={!element.name.trim() ? true : undefined}
                        placeholder={t("wizard.manual.namePlaceholder")}
                        onChange={(event) => updateElement(element.key, { name: event.target.value })}
                      />
                    </label>
                    <label className="field-stack">
                      <span className="field-label">{t("wizard.manual.startLabel")}</span>
                      <DateInput
                        value={element.window_start}
                        max={element.window_end || undefined}
                        onChange={(value) => updateElement(element.key, { window_start: value })}
                        aria-label={t("wizard.manual.startAria", { index: index + 1 })}
                      />
                    </label>
                    <label className="field-stack">
                      <span className="field-label">{t("wizard.manual.endLabel")}</span>
                      <DateInput
                        value={element.window_end}
                        min={element.window_start || undefined}
                        onChange={(value) => updateElement(element.key, { window_end: value })}
                        aria-label={t("wizard.manual.endAria", { index: index + 1 })}
                      />
                    </label>
                    <button
                      type="button"
                      className="button-icon-soft button-icon-soft-danger subm-edit-element-remove"
                      aria-label={t("wizard.manual.removeElement", { name: element.name.trim() || t("wizard.manual.unnamed") })}
                      title={t("wizard.manual.removeElement", { name: element.name.trim() || t("wizard.manual.unnamed") })}
                      disabled={form.manual_elements.length === 1}
                      onClick={() => void removeElement(element)}
                    >
                      <ActionIcon name="delete" />
                    </button>
                  </li>
                ))}
              </ul>
              <div>
                <button type="button" className="button-secondary" onClick={addElement}>{t("wizard.manual.addElement")}</button>
              </div>
              <span className="field-help">{t("wizard.manual.windowHelp")}</span>
            </div>
          );
        }
        return form.source_type === "events" ? (
          <>
            <div className={problemField === "window" ? "field-stack subm-edit-invalid" : "field-stack"}>
              <span className="field-label">
                {t("windowLabel")}
                <HelpPopover topic={t("windowLabel")} docs={help("zeitfenster")}>{t("helpWindow")}</HelpPopover>
              </span>
              <div className="subm-edit-window">
                <span>{t("opens")}</span>
                <input
                  type="number"
                  min={0}
                  max={OFFSET_DAYS_MAX}
                  aria-label={t("daysBeforeEvent")}
                  placeholder={t("noLimitPlaceholder")}
                  value={form.offset_days_before}
                  onChange={(e) => setForm((c) => ({ ...c, offset_days_before: e.target.value === "" ? "" : Number(e.target.value) }))}
                />
                <span>{t("daysBeforeEventAndCloses")}</span>
                <input
                  type="number"
                  min={0}
                  max={OFFSET_DAYS_MAX}
                  aria-label={t("daysAfterEvent")}
                  placeholder={t("noLimitPlaceholder")}
                  value={form.offset_days_after}
                  onChange={(e) => setForm((c) => ({ ...c, offset_days_after: e.target.value === "" ? "" : Number(e.target.value) }))}
                />
                <span>{t("daysAfterSuffix")}</span>
              </div>
              <p className="subm-edit-example" aria-live="polite">{windowExample(form, exampleEvent, t)}</p>
              <span className="field-help">{t("windowHelp")}</span>
            </div>
            {availableCycleConfigs.length > 0 ? (
              <div className={problemField === "cycle" ? "field-stack subm-edit-invalid" : "field-stack"}>
                <span className="field-label">
                  <span id="subm-cycle-label">{t("cycleLabel")}</span>
                  <HelpPopover topic={t("cycleLabel")} docs={help("zyklus")}>{t("cycleHelp")}</HelpPopover>
                </span>
                <div className="subm-edit-chips" role="radiogroup" aria-labelledby="subm-cycle-label">
                  <button type="button" role="radio" className="subm-edit-chip" aria-checked={!form.cycle_config_id} onClick={() => setForm((c) => ({ ...c, cycle_config_id: "", cycle_offsets: [] }))}>
                    {t("allCyclesNoFilter")}
                  </button>
                  {availableCycleConfigs.map((cycle) => (
                    <button
                      key={cycle.id}
                      type="button"
                      role="radio"
                      className="subm-edit-chip"
                      aria-checked={form.cycle_config_id === cycle.id}
                      // Beim Aktivieren des Filters ist der aktuelle Zyklus vorausgewählt.
                      onClick={() => setForm((c) => ({ ...c, cycle_config_id: cycle.id, cycle_offsets: c.cycle_offsets.length > 0 ? c.cycle_offsets : [0] }))}
                    >
                      {cycle.name}
                    </button>
                  ))}
                </div>
                {form.cycle_config_id ? (
                  <div className="subm-edit-chips">
                    {CYCLE_OFFSET_OPTIONS.map((offset) => (
                      <button key={offset} type="button" className="subm-edit-chip" aria-pressed={form.cycle_offsets.includes(offset)} onClick={() => toggleCycleOffset(offset)}>
                        {cycleOffsetLabel(offset, t)}
                      </button>
                    ))}
                  </div>
                ) : null}
              </div>
            ) : null}
          </>
        ) : (
          <div className="field-stack">
            <span className="field-label">
              <span id="subm-deadline-label">{t("deadlineLabel")}</span>
              <HelpPopover topic={t("deadlineLabel")} docs={help("stichtag")}>{t("helpDeadline")}</HelpPopover>
            </span>
            <div className="subm-edit-segment" role="radiogroup" aria-labelledby="subm-deadline-label">
              <button
                type="button"
                role="radio"
                aria-checked={Boolean(form.deadline)}
                // Vorschlag: in zwei Wochen; lässt sich darunter ändern
                onClick={() => setForm((c) => ({ ...c, deadline: c.deadline || addDays(new Date().toISOString().slice(0, 10), 14) }))}
              >
                {t("wizard.withDeadline")}
              </button>
              <button type="button" role="radio" aria-checked={!form.deadline} onClick={() => setForm((c) => ({ ...c, deadline: "" }))}>
                {t("wizard.openUntilClosed")}
              </button>
            </div>
            {form.deadline ? <DateInput value={form.deadline} onChange={(deadline) => setForm((c) => ({ ...c, deadline }))} aria-label={t("deadlineLabel")} /> : null}
            <span className="field-help">{form.deadline ? t("wizard.deadlineHelp") : t("wizard.summary.noDeadlineDetail")}</span>
          </div>
        );

      case "responsible":
        if (!isManual && responsibleOptions.length === 0) {
          return <p className="muted">{t("wizard.noResponsibleList")}</p>;
        }
        return (
          <>
            {isManual ? (
              <div className="field-stack">
                <span className="field-label">
                  <span id="subm-element-responsible-label">{t("responsiblePersonLabel")}</span>
                  <HelpPopover topic={t("responsiblePersonLabel")} docs={help("verantwortliche")}>{t("helpResponsible")}</HelpPopover>
                </span>
                <span className="field-help">{t("wizard.manual.responsibleHelp")}</span>
                <ul className="subm-edit-elements" aria-labelledby="subm-element-responsible-label">
                  {form.manual_elements.map((element) => (
                    <li key={element.key} className="subm-edit-element-responsible">
                      <span className="subm-edit-element-title">{element.name.trim() || t("wizard.manual.unnamed")}</span>
                      <SearchableMultiSelect
                        options={responsibleCandidates}
                        getId={(person) => person.id}
                        getLabel={(person) => person.display_name}
                        values={element.responsible_participant_ids}
                        onChange={(ids) => updateElement(element.key, { responsible_participant_ids: ids })}
                        emptySelectionLabel={t("wizard.manual.responsibleNone")}
                        emptyLabel={t("wizard.manual.noParticipants")}
                        triggerProps={{ "aria-label": t("wizard.manual.responsibleAria", { name: element.name.trim() || t("wizard.manual.unnamed") }) }}
                      />
                    </li>
                  ))}
                </ul>
              </div>
            ) : (
            <div className="field-stack">
              <span className="field-label">
                <span id="subm-responsible-label">{t("responsiblePersonLabel")}</span>
                <HelpPopover topic={t("responsiblePersonLabel")} docs={help("verantwortliche")}>{t("helpResponsible")}</HelpPopover>
              </span>
              <span className="field-help">{form.source_type === "events" ? t("responsiblePersonHelpEvents") : t("responsiblePersonHelpList")}</span>
              <div className="subm-edit-chips" role="radiogroup" aria-labelledby="subm-responsible-label">
                <button type="button" role="radio" className="subm-edit-chip" aria-checked={!form.responsible_participant_source} onClick={() => setForm((c) => ({ ...c, responsible_participant_source: "" }))}>
                  {t("noAssignment")}
                </button>
                {responsibleOptions.map((option) => (
                  <button
                    key={option.value}
                    type="button"
                    role="radio"
                    className="subm-edit-chip"
                    aria-checked={form.responsible_participant_source === option.value}
                    onClick={() => setForm((c) => ({ ...c, responsible_participant_source: option.value }))}
                  >
                    {option.label}
                  </button>
                ))}
              </div>
            </div>
            )}
            {(isManual ? manualResponsibleCount(form) > 0 : form.responsible_participant_source) ? (
              <div className="field-stack">
                <span className="field-label">
                  <span id="subm-todo-tags-label">{t("todoTagsLabel")}</span>
                </span>
                <span className="field-help">{t("todoTagsHelp")}</span>
                <TagInput
                  value={form.todo_tags.join(",")}
                  onChange={(value) => setForm((c) => ({ ...c, todo_tags: value.split(",").map((tag) => tag.trim()).filter(Boolean) }))}
                  suggestions={Object.keys(todoTagConfig)}
                  tagConfig={todoTagConfig}
                />
                <label className="checkbox-row">
                  <input type="checkbox" checked={form.todo_own_tag} onChange={(event) => setForm((c) => ({ ...c, todo_own_tag: event.target.checked }))} />
                  <span>
                    {t("todoOwnTagLabel")}
                    <span className="field-help"> {t("todoOwnTagHelp", { tag: form.title.trim() || t("todoOwnTagUntitled") })}</span>
                  </span>
                </label>
              </div>
            ) : null}
            {(isManual ? manualResponsibleCount(form) > 0 : form.responsible_participant_source) ? (
              <div className="field-stack">
                <span className="field-label">
                  <span id="subm-owner-label">{t("ownerAccessLabel")}</span>
                  <HelpPopover topic={t("ownerAccessLabel")} docs={help("persoenlicher-link")}>{t("helpOwnerAccess")}</HelpPopover>
                </span>
                <div className="subm-edit-options" role="radiogroup" aria-labelledby="subm-owner-label">
                  {(["manage", "view", "off"] as const).map((mode) => (
                    <button key={mode} type="button" role="radio" className="subm-edit-option" aria-checked={form.owner_access === mode} onClick={() => setForm((c) => ({ ...c, owner_access: mode }))}>
                      <strong>{t(`ownerAccess.${mode}`)}</strong>
                      {form.owner_access === mode ? <small>{t(`ownerAccessHelp.${mode}`)}</small> : null}
                    </button>
                  ))}
                </div>
                {form.owner_access !== "off" ? (
                  <label className="subm-edit-inline">
                    <span>{t("wizard.ownerDaysBefore")}</span>
                    <input
                      type="number"
                      min={1}
                      max={90}
                      aria-label={t("ownerAccessDaysLabel")}
                      value={form.owner_access_days}
                      onChange={(event) => setForm((c) => ({ ...c, owner_access_days: event.target.value === "" ? "" : Number(event.target.value) }))}
                    />
                    <span>{t("wizard.ownerDaysAfter")}</span>
                  </label>
                ) : null}
                {form.owner_access === "manage" ? (
                  <label className="checkbox-row">
                    <input type="checkbox" checked={form.owner_resubmit_only_personal} onChange={(event) => setForm((c) => ({ ...c, owner_resubmit_only_personal: event.target.checked }))} />
                    <span>
                      {t("ownerResubmitOnlyPersonalLabel")}
                      <span className="field-help"> {t("ownerResubmitOnlyPersonalHelp")}</span>
                    </span>
                  </label>
                ) : null}
              </div>
            ) : null}
          </>
        );

      case "files":
        return (
          <>
            <div className="field-stack">
              <div className="subm-edit-label-row">
                <span className="field-label">
                  {t("allowedFileTypesLabel")}
                  <HelpPopover topic={t("allowedFileTypesLabel")} docs={help("dateien")}>{t("helpFileTypes")}</HelpPopover>
                </span>
                <span className="subm-edit-count">{fileTypeCount === 0 ? t("allAllowed") : t("countSelected", { count: fileTypeCount })}</span>
              </div>
              <div className="subm-edit-types">
                {fileTypeGroups(t).map((group) => {
                  const allSelected = group.types.every((t) => form.allowed_file_types.includes(t));
                  return (
                    <div key={group.label} className="subm-edit-type-row">
                      <strong>{group.label}</strong>
                      <div className="subm-edit-chips">
                        {group.types.map((type) => (
                          <button key={type} type="button" className="subm-edit-chip" aria-pressed={form.allowed_file_types.includes(type)} onClick={() => toggleFileType(type)}>
                            .{type}
                          </button>
                        ))}
                      </div>
                      <button type="button" className="subm-edit-type-all" onClick={() => toggleFileGroup(group.types, allSelected)}>
                        {allSelected ? t("noneAction") : t("allAction")}
                      </button>
                    </div>
                  );
                })}
              </div>
              <span className="field-help">{t("noSelectionAllTypesAllowed")}</span>
            </div>

            <div className="subm-edit-grid subm-edit-grid-2">
              <label className="field-stack">
                <span className="field-label">{t("maxFilesLabel")}</span>
                <input
                  type="number"
                  min={1}
                  placeholder={t("unlimited")}
                  value={form.max_files_per_element}
                  onChange={(e) => {
                    const value = e.target.value === "" ? "" : Number(e.target.value);
                    // Ohne Maximum gibt es nichts zu erreichen: "Sobald Höchstzahl erreicht" fällt auf "Nie" zurück.
                    setForm((c) => ({ ...c, max_files_per_element: value, auto_close: value === "" && c.auto_close === "max_files" ? "never" : c.auto_close }));
                  }}
                />
              </label>
              <label className="field-stack">
                <span className="field-label">{t("maxSizeLabel")}</span>
                <input type="number" min={1} value={form.max_file_size_mb} onChange={(e) => setForm((c) => ({ ...c, max_file_size_mb: Number(e.target.value) }))} />
              </label>
            </div>

            {form.source_type !== "manual" ? (
              <div className="field-stack">
                <span className="field-label" id="subm-sort-label">{t("sortOrderLabel")}</span>
                <div className="subm-edit-chips" role="radiogroup" aria-labelledby="subm-sort-label">
                  {(Object.keys(sortOrderLabel(t)) as SubmissionSortOrder[]).map((value) => (
                    <button key={value} type="button" role="radio" className="subm-edit-chip" aria-checked={form.sort_order === value} onClick={() => setForm((c) => ({ ...c, sort_order: value }))}>
                      {sortOrderLabel(t)[value]}
                    </button>
                  ))}
                </div>
              </div>
            ) : null}

            <div className="field-stack">
              <span className="field-label">
                <span id="subm-auto-close-label">{t("autoCloseLabel")}</span>
                <HelpPopover topic={t("autoCloseLabel")} docs={help("automatisch-schliessen")}>{t("helpAutoClose")}</HelpPopover>
              </span>
              <div className="subm-edit-chips" role="radiogroup" aria-labelledby="subm-auto-close-label">
                {autoCloseOptions(t).map((option) => (
                  <button
                    key={option.value}
                    type="button"
                    role="radio"
                    className="subm-edit-chip"
                    aria-checked={form.auto_close === option.value}
                    aria-describedby={option.value === "max_files" ? "subm-auto-close-help" : undefined}
                    disabled={option.value === "max_files" && form.max_files_per_element === ""}
                    onClick={() => setForm((c) => ({ ...c, auto_close: option.value }))}
                  >
                    {option.label}
                  </button>
                ))}
              </div>
              <span className="field-help" id="subm-auto-close-help">
                {form.max_files_per_element === "" ? t("autoCloseHelpUnlimited") : t("autoCloseHelp")}
              </span>
            </div>

            {hasEnd(form) ? (
              <label className="checkbox-row">
                <input type="checkbox" checked={form.keep_open_after_end} onChange={(event) => setForm((c) => ({ ...c, keep_open_after_end: event.target.checked }))} />
                <span>
                  {t("keepOpenLabel")}
                  <span className="field-help"> {t("keepOpenHelp")}</span>
                </span>
              </label>
            ) : null}

            <label className="field-stack">
              <span className="field-label">{t("descriptionLabel")}</span>
              <textarea rows={2} value={form.description} placeholder={t("descriptionPlaceholder")} onChange={(e) => setForm((c) => ({ ...c, description: e.target.value }))} />
            </label>
          </>
        );

      case "access":
        return (
          <>
            <div className="field-stack">
              <span className="field-label">
                {t("reachableViaLabel")}
                <HelpPopover topic={t("publicLinkLabel")} docs={help("links")}>{t("helpLinks")}</HelpPopover>
              </span>
              {links.length === 0 ? (
                <span className="field-help">{t("noLinkYetHelp")}</span>
              ) : (
                <div className="subm-edit-links">
                  {links.map((link) => (
                    <label key={link.id} className="subm-edit-link-option">
                      <input type="checkbox" checked={form.link_ids.includes(link.id)} onChange={() => toggleLink(link.id)} />
                      <span>{link.name}</span>
                      {link.is_default ? <small>{t("defaultLabel")}</small> : null}
                    </label>
                  ))}
                </div>
              )}
              {url ? <code className="subm-edit-url">{url.base}<strong>{url.slug}</strong></code> : null}
              {noLinkChosen ? <span className="subm-edit-warn">{t("noLinkSelectedHelp")}</span> : null}
            </div>

            <div className="field-stack">
              <span className="field-label" id="subm-reviewers-label">{t("reviewers.label")}</span>
              {availableReviewers.length === 0 ? (
                <span className="field-help">{t("reviewers.noCandidates")}</span>
              ) : availableReviewers.length <= MAX_CHIPS ? (
                <div className="subm-edit-chips" role="group" aria-labelledby="subm-reviewers-label">
                  {availableReviewers.map((reviewer) => (
                    <button key={reviewer.id} type="button" className="subm-edit-chip" aria-pressed={form.reviewer_ids.includes(reviewer.id)} onClick={() => toggleReviewer(reviewer.id)}>
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
                  onChange={(ids) => setForm((c) => ({ ...c, reviewer_ids: ids }))}
                  emptySelectionLabel={t("reviewers.none")}
                  emptyLabel={t("reviewers.noCandidates")}
                />
              )}
              <span className="field-help">{t("reviewers.help")}</span>
            </div>

            <div className="field-stack">
              <span className="field-label" id="subm-visibility-label">{t("fileVisibility.label")}</span>
              <div className="subm-edit-chips" role="radiogroup" aria-labelledby="subm-visibility-label">
                {(["default", "role_only", "all_participants", "own_submissions"] as const).map((mode) => (
                  <button key={mode} type="button" role="radio" className="subm-edit-chip" aria-checked={form.file_visibility === mode} onClick={() => setForm((c) => ({ ...c, file_visibility: mode }))}>
                    {t(`wizard.visibilityChip.${mode}`)}
                  </button>
                ))}
              </div>
              <span className="field-help">{t(`fileVisibility.help.${form.file_visibility}`)}</span>
              {form.file_visibility === "all_participants" || form.file_visibility === "own_submissions" ? (
                <div className="subm-edit-chips" role="radiogroup" aria-label={t("fileVisibility.filterLabel")}>
                  {(["images", "all"] as const).map((filter) => (
                    <button key={filter} type="button" role="radio" className="subm-edit-chip" aria-checked={form.file_visibility_filter === filter} onClick={() => setForm((c) => ({ ...c, file_visibility_filter: filter }))}>
                      {t(`fileVisibility.filter.${filter}`)}
                    </button>
                  ))}
                </div>
              ) : null}
            </div>
          </>
        );
    }
  }

  return (
    <Modal open={open} title={editing ? t("editAssignment") : t("createAssignment")} className={editing ? "subm-edit-modal" : "subm-edit-modal subm-edit-modal-wizard"} hideCloseButton onClose={onClose}>
      <ModalSaveForm className="subm-edit-form" onSubmit={handleSubmit}>
        <header className="subm-edit-heading">
          <div className="subm-edit-eyebrow">
            {editing ? t("editAssignment") : t("newAssignment")}
            {tenantName ? <><span aria-hidden="true">·</span><span>{tenantName}</span></> : null}
          </div>
          {editing ? (
            <input
              aria-label={t("titleLabel")}
              aria-invalid={problemField === "title" ? true : undefined}
              className="subm-edit-title"
              placeholder={t("titlePlaceholder")}
              value={form.title}
              onChange={(e) => setForm((c) => ({ ...c, title: e.target.value }))}
            />
          ) : (
            <h2 className="subm-edit-new-title">{form.title.trim() || t("newAssignment")}</h2>
          )}
          <button type="button" className="subm-edit-close" title={t("close")} aria-label={t("close")} onClick={onClose}><ActionIcon name="close" /></button>
          {!editing ? (
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
          ) : null}
        </header>

        <div className="subm-edit-body">
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
                      aria-controls={`subm-section-${key}`}
                      onClick={() => setOpenSection(isOpen ? null : key)}
                    >
                      <span className="subm-edit-section-icon" aria-hidden="true">{SECTION_ICONS[key]}</span>
                      <span className="subm-edit-section-text">
                        <span className="subm-edit-section-label">{summary.label}</span>
                        <span className="subm-edit-section-value">{summary.value}</span>
                        <span className={summary.warn ? "subm-edit-section-detail subm-edit-warn" : "subm-edit-section-detail"}>{summary.detail}</span>
                      </span>
                      <span className="subm-edit-section-action">{isOpen ? t("wizard.done") : t("wizard.change")}</span>
                    </button>
                    {isOpen ? (
                      <div id={`subm-section-${key}`} className="subm-edit-section-body subm-edit-reveal">
                        {sectionBody(key)}
                      </div>
                    ) : null}
                  </section>
                );
              })
            ) : (
              <div className="subm-edit-step-body subm-edit-reveal" key={SECTION_KEYS[step]}>
                <h3 className="subm-edit-question">
                  {isManual && SECTION_KEYS[step] === "window" ? t("wizard.questions.windowManual") : t(`wizard.questions.${SECTION_KEYS[step]}`)}
                </h3>
                {sectionBody(SECTION_KEYS[step])}
              </div>
            )}
          </div>

          <aside className="subm-edit-sidebar">
            <div className="field-stack">
              <span className="field-label">{t("behaviorSummaryLabel")}</span>
              <div className="subm-edit-summary">
                <p key={summaryText} className="subm-edit-summary-text">{summaryText}</p>
              </div>
              <div className="subm-edit-chips">
                <span className="subm-edit-tag">{maxFilesLabel}</span>
                <span className="subm-edit-tag">{t("maxSizeMb", { size: form.max_file_size_mb })}</span>
                <span className="subm-edit-tag">{fileTypeCount === 0 ? t("allFileTypes") : t("fileTypeCount", { count: fileTypeCount })}</span>
              </div>
              <p className="subm-edit-scan">
                <span className="subm-edit-scan-dot" aria-hidden="true" />
                {t("clamavScanNote")}
              </p>
            </div>
          </aside>
        </div>

        <footer className="subm-edit-footer">
          {editing ? (
            <>
              <button type="button" className="subm-edit-manage" onClick={onManageLinks}>{t("manageLinksAction")}</button>
              <div className="subm-edit-actions">
                {problem !== null ? <span className="subm-edit-problem" role="status">{t("saveBlockedHint", { problem })}</span> : null}
                <button type="button" className="button-secondary" onClick={onClose}>{t("cancel")}</button>
                <button data-modal-save type="submit" className="button-primary" disabled={problem !== null}>{t("saveAssignment")}</button>
              </div>
            </>
          ) : (
            <>
              <button type="button" className="button-secondary" onClick={step === 0 ? onClose : () => setStep(step - 1)}>
                {step === 0 ? t("cancel") : t("wizard.back")}
              </button>
              <span className="subm-edit-step-count">{t("wizard.stepOf", { step: step + 1, total: SECTION_KEYS.length })}</span>
              <div className="subm-edit-actions">
                {step === lastStep && problem !== null ? <span className="subm-edit-problem" role="status">{t("saveBlockedHint", { problem })}</span> : null}
                {step < lastStep ? (
                  <button type="button" className="button-primary" onClick={() => setStep(step + 1)}>{t("wizard.next")}</button>
                ) : (
                  <button data-modal-save type="submit" className="button-primary" disabled={problem !== null}>{t("createAssignment")}</button>
                )}
              </div>
            </>
          )}
        </footer>
      </ModalSaveForm>
    </Modal>
  );
}
