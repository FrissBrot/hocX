"use client";

import { Dispatch, FormEvent, SetStateAction } from "react";
import { useTranslations } from "next-intl";

import { DateInput } from "@/components/ui/date-input";
import { Modal, ModalSaveForm } from "@/components/ui/modal";
import { ActionIcon } from "@/components/ui/action-icons";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { formatDateInputValue } from "@/lib/utils/format";
import {
  CycleConfigSummary,
  StructuredListDefinition,
  SubmissionAssignment,
  SubmissionAutoClose,
  SubmissionLink,
  SubmissionSortOrder,
  SubmissionSourceType,
} from "@/types/api";

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
  responsible_participant_source: string;
  link_ids: string[];
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
  responsible_participant_source: "",
  link_ids: [],
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
    responsible_participant_source: assignment.responsible_participant_source ?? "",
    link_ids: assignment.link_ids,
  };
}

/** Grund, warum das Formular noch nicht gespeichert werden kann (null = gültig). */
/** POST/PATCH-Body aus dem Formular - gemeinsam fuer Desktop-Manager und Mobile-Ansicht.
 * Nur was zur gewaehlten Verknuepfung gehoert, wird gesendet - der Rest wird beim Wechsel geleert. */
export function assignmentPayload(form: FormState) {
  const isEvents = form.source_type === "events";
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
    deadline: isEvents ? null : form.deadline || null,
    allowed_file_types: form.allowed_file_types,
    max_files_per_element: form.max_files_per_element === "" ? null : Number(form.max_files_per_element),
    max_file_size_mb: Number(form.max_file_size_mb),
    sort_order: form.sort_order,
    auto_close: form.auto_close,
    responsible_participant_source: form.source_type === "manual" ? null : form.responsible_participant_source || null,
    link_ids: form.link_ids,
  };
}

export function formProblem(form: FormState, t: TFunc): string | null {
  if (!form.title.trim()) return t("titleMissing");
  if (form.source_type === "events") {
    if (!form.tag_filter) return t("tagFilterMissing");
    if (form.cycle_config_id && form.cycle_offsets.length === 0) return t("cycleSelectionMissing");
  }
  if (form.source_type === "list" && !form.list_definition_id) return t("listMissing");
  return null;
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
  return `${t("manualSubject")} ${deadlineSentence(form.deadline, t)}`;
}

/** Erklärt in einem Satz, wie sich die Abgabe mit den aktuellen Einstellungen verhält. */
export function describeAssignment(form: FormState, listName: string | null, t: TFunc): string {
  const base = describeBase(form, listName, t);
  const autoClose = autoCloseSentence(form, t);
  return autoClose ? `${base} ${autoClose}` : base;
}

/** Öffentliche Adresse ohne Protokoll, aufgeteilt in feste Basis und den Slug der Abgabe. */
export function publicUrlParts(link: SubmissionLink | null, slug: string): { base: string; slug: string } | null {
  if (!link) return null;
  return { base: `${link.url.replace(/^https?:\/\//, "").replace(/\/+$/, "")}/`, slug: slug || "…" };
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
  onSubmit,
  onClose,
  onManageLinks,
}: Props) {
  const t = useTranslations("submissionAssignments");
  const problem = formProblem(form, t);
  const selectedList = availableLists.find((list) => list.id === form.list_definition_id) ?? null;
  const selectedLinks = links.filter((link) => form.link_ids.includes(link.id));
  const previewLink = selectedLinks.find((link) => link.is_default) ?? selectedLinks[0] ?? null;
  const url = publicUrlParts(previewLink, form.public_slug);

  const responsibleOptions =
    form.source_type === "events"
      ? singleParticipantEventFields(t)
      : form.source_type === "list" && selectedList
        ? ([
            selectedList.column_one_value_type === "participant"
              ? { value: "column_one", label: selectedList.column_one_title || t("column1") }
              : null,
            selectedList.column_two_value_type === "participant"
              ? { value: "column_two", label: selectedList.column_two_title || t("column2") }
              : null,
          ].filter((option): option is { value: string; label: string } => option !== null))
        : [];

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

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (problem === null) return onSubmit();
  }

  const fileTypeCount = form.allowed_file_types.length;
  const maxFilesLabel = form.max_files_per_element === "" ? t("unlimitedFiles") : t("maxFilesCount", { count: form.max_files_per_element });

  return (
    <Modal open={open} title={editing ? t("editAssignment") : t("createAssignment")} className="subm-edit-modal" hideCloseButton onClose={onClose}>
      <ModalSaveForm className="subm-edit-form" onSubmit={handleSubmit}>
        <header className="subm-edit-heading">
          <div className="subm-edit-eyebrow">
            {editing ? t("editAssignment") : t("newAssignment")}
            {tenantName ? <><span aria-hidden="true">·</span><span>{tenantName}</span></> : null}
          </div>
          <input
            aria-label={t("titleLabel")}
            className="subm-edit-title"
            placeholder={t("titlePlaceholder")}
            value={form.title}
            autoFocus={!editing}
            onChange={(e) => {
              const title = e.target.value;
              setForm((c) => ({ ...c, title, ...(editing ? {} : { public_slug: slugify(title) }) }));
            }}
          />
          <button type="button" className="subm-edit-close" title={t("close")} aria-label={t("close")} onClick={onClose}><ActionIcon name="close" /></button>
        </header>

        <div className="subm-edit-body">
          <div className="subm-edit-main grid">
            <div className="field-stack">
              <span className="field-label" id="subm-source-label">{t("linkTypeLabel")}</span>
              <div className="subm-edit-sources" role="radiogroup" aria-labelledby="subm-source-label">
                {sourceOptions(t).map((option) => (
                  <button
                    key={option.value}
                    type="button"
                    role="radio"
                    aria-checked={form.source_type === option.value}
                    className="subm-edit-source-card"
                    onClick={() => setForm((c) => ({ ...c, source_type: option.value, responsible_participant_source: "" }))}
                  >
                    <strong>{option.title}</strong>
                    <small>{option.description}</small>
                  </button>
                ))}
              </div>
            </div>

            <div className="subm-edit-panel">
              {form.source_type === "events" ? (
                <>
                  <div className="field-stack">
                    <span className="field-label">{t("tagFilterLabel")}</span>
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
                  </div>

                  <div className="field-stack">
                    <span className="field-label">{t("windowLabel")}</span>
                    <div className="subm-edit-window">
                      <span>{t("opens")}</span>
                      <input
                        type="number"
                        min={0}
                        aria-label={t("daysBeforeEvent")}
                        placeholder="∞"
                        value={form.offset_days_before}
                        onChange={(e) => setForm((c) => ({ ...c, offset_days_before: e.target.value === "" ? "" : Number(e.target.value) }))}
                      />
                      <span>{t("daysBeforeEventAndCloses")}</span>
                      <input
                        type="number"
                        min={0}
                        aria-label={t("daysAfterEvent")}
                        placeholder="∞"
                        value={form.offset_days_after}
                        onChange={(e) => setForm((c) => ({ ...c, offset_days_after: e.target.value === "" ? "" : Number(e.target.value) }))}
                      />
                      <span>{t("daysAfterSuffix")}</span>
                    </div>
                    <span className="field-help">
                      {t("windowHelp")}
                    </span>
                  </div>

                  <div className="field-stack">
                    <span className="field-label">{t("cycleLabel")}</span>
                    <SearchableSelect
                      options={availableCycleConfigs}
                      getId={(cfg) => cfg.id}
                      getLabel={(cfg) => cfg.name}
                      value={form.cycle_config_id || null}
                      onChange={(cfg) =>
                        setForm((c) => ({
                          ...c,
                          cycle_config_id: cfg ? cfg.id : "",
                          // Beim Aktivieren des Filters ist der aktuelle Zyklus vorausgewählt.
                          cycle_offsets: cfg ? (c.cycle_offsets.length > 0 ? c.cycle_offsets : [0]) : [],
                        }))
                      }
                      nullLabel={t("allCyclesNoFilter")}
                    />
                    {form.cycle_config_id ? (
                      <div className="subm-edit-chips">
                        {CYCLE_OFFSET_OPTIONS.map((offset) => (
                          <button
                            key={offset}
                            type="button"
                            className="subm-edit-chip"
                            aria-pressed={form.cycle_offsets.includes(offset)}
                            onClick={() => toggleCycleOffset(offset)}
                          >
                            {cycleOffsetLabel(offset, t)}
                          </button>
                        ))}
                      </div>
                    ) : null}
                    <span className="field-help">
                      {t("cycleHelp")}
                    </span>
                  </div>
                </>
              ) : (
                <>
                  {form.source_type === "list" ? (
                    <div className="field-stack">
                      <span className="field-label">{t("listLabel")}</span>
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
                    </div>
                  ) : null}
                  <div className="field-stack">
                    <span className="field-label">{t("deadlineLabel")}</span>
                    <DateInput value={form.deadline} onChange={(deadline) => setForm((c) => ({ ...c, deadline }))} aria-label={t("deadlineLabel")} />
                    <span className="field-help">{t("deadlineHelp")}</span>
                  </div>
                </>
              )}
            </div>

            <label className="field-stack">
              <span className="field-label">{t("descriptionLabel")}</span>
              <textarea
                rows={2}
                value={form.description}
                placeholder={t("descriptionPlaceholder")}
                onChange={(e) => setForm((c) => ({ ...c, description: e.target.value }))}
              />
            </label>

            <div className="field-stack">
              <div className="subm-edit-label-row">
                <span className="field-label">{t("allowedFileTypesLabel")}</span>
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
                          <button
                            key={type}
                            type="button"
                            className="subm-edit-chip"
                            aria-pressed={form.allowed_file_types.includes(type)}
                            onClick={() => toggleFileType(type)}
                          >
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

            <div className={form.source_type === "manual" ? "subm-edit-grid subm-edit-grid-2" : "subm-edit-grid"}>
              <label className="field-stack">
                <span className="field-label">{t("maxFilesLabel")}</span>
                <input
                  type="number"
                  min={1}
                  placeholder={t("unlimited")}
                  value={form.max_files_per_element}
                  onChange={(e) => {
                    const value = e.target.value === "" ? "" : Number(e.target.value);
                    // Ohne Maximum gibt es nichts zu erreichen: "Sobald Maximum erreicht" fällt auf "Nie" zurück.
                    setForm((c) => ({ ...c, max_files_per_element: value, auto_close: value === "" && c.auto_close === "max_files" ? "never" : c.auto_close }));
                  }}
                />
              </label>
              <label className="field-stack">
                <span className="field-label">{t("maxSizeLabel")}</span>
                <input
                  type="number"
                  min={1}
                  value={form.max_file_size_mb}
                  onChange={(e) => setForm((c) => ({ ...c, max_file_size_mb: Number(e.target.value) }))}
                />
              </label>
              {form.source_type !== "manual" ? (
                <label className="field-stack">
                  <span className="field-label">{t("sortOrderLabel")}</span>
                  <select value={form.sort_order} onChange={(e) => setForm((c) => ({ ...c, sort_order: e.target.value as SubmissionSortOrder }))}>
                    {(Object.keys(sortOrderLabel(t)) as SubmissionSortOrder[]).map((value) => (
                      <option key={value} value={value}>{sortOrderLabel(t)[value]}</option>
                    ))}
                  </select>
                </label>
              ) : null}
            </div>

            <div className="field-stack">
              <span className="field-label" id="subm-auto-close-label">{t("autoCloseLabel")}</span>
              <div className="subm-edit-chips" role="radiogroup" aria-labelledby="subm-auto-close-label">
                {autoCloseOptions(t).map((option) => (
                  <button
                    key={option.value}
                    type="button"
                    role="radio"
                    className="subm-edit-chip"
                    aria-checked={form.auto_close === option.value}
                    disabled={option.value === "max_files" && form.max_files_per_element === ""}
                    onClick={() => setForm((c) => ({ ...c, auto_close: option.value }))}
                  >
                    {option.label}
                  </button>
                ))}
              </div>
              <span className="field-help">
                {form.max_files_per_element === "" ? t("autoCloseHelpUnlimited") : t("autoCloseHelp")}
              </span>
            </div>

            {responsibleOptions.length > 0 ? (
              <div className="field-stack">
                <span className="field-label">{t("responsiblePersonLabel")}</span>
                <SearchableSelect
                  options={responsibleOptions}
                  getId={(option) => option.value}
                  getLabel={(option) => option.label}
                  value={form.responsible_participant_source || null}
                  onChange={(option) => setForm((c) => ({ ...c, responsible_participant_source: option ? option.value : "" }))}
                  nullLabel={t("noAssignment")}
                />
                <span className="field-help">
                  {form.source_type === "events"
                    ? t("responsiblePersonHelpEvents")
                    : t("responsiblePersonHelpList")}
                </span>
              </div>
            ) : null}
          </div>

          <aside className="subm-edit-sidebar">
            <div className="field-stack">
              <span className="field-label">{t("publicLinkLabel")}</span>
              {url ? (
                <code className="subm-edit-url">{url.base}<strong>{url.slug}</strong></code>
              ) : (
                <span className="field-help">{t("noLinkSelectedYet")}</span>
              )}
            </div>

            <div className="field-stack">
              <span className="field-label">{t("reachableViaLabel")}</span>
              {links.length === 0 ? (
                <span className="field-help">
                  {t("noLinkYetHelp")}
                </span>
              ) : (
                <>
                  <div className="subm-edit-links">
                    {links.map((link) => (
                      <label key={link.id} className="subm-edit-link-option">
                        <input type="checkbox" checked={form.link_ids.includes(link.id)} onChange={() => toggleLink(link.id)} />
                        <span>{link.name}</span>
                        {link.is_default ? <small>{t("defaultLabel")}</small> : null}
                      </label>
                    ))}
                  </div>
                  {form.link_ids.length === 0 ? (
                    <span className="field-help">{t("noLinkSelectedHelp")}</span>
                  ) : null}
                </>
              )}
            </div>

            <div className="field-stack">
              <span className="field-label">{t("behaviorSummaryLabel")}</span>
              <div className="subm-edit-summary">
                <p>{describeAssignment(form, selectedList?.name ?? null, t)}</p>
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
          <button type="button" className="subm-edit-manage" onClick={onManageLinks}>{t("manageLinksAction")}</button>
          <div className="subm-edit-actions">
            <button type="button" className="button-secondary" onClick={onClose}>{t("cancel")}</button>
            <button data-modal-save type="submit" className="button-primary" disabled={problem !== null} title={problem ?? undefined}>
              {editing ? t("saveAssignment") : t("createAssignment")}
            </button>
          </div>
        </footer>
      </ModalSaveForm>
    </Modal>
  );
}
