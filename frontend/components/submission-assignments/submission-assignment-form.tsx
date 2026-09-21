"use client";

import { Dispatch, FormEvent, SetStateAction } from "react";

import { DateInput } from "@/components/ui/date-input";
import { Modal } from "@/components/ui/modal";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { formatDateInputValue } from "@/lib/utils/format";
import {
  CycleConfigSummary,
  StructuredListDefinition,
  SubmissionAssignment,
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
  responsible_participant_source: "",
  link_ids: [],
};

export const SORT_ORDER_LABEL: Record<SubmissionSortOrder, string> = {
  alphabetical: "Alphabetisch",
  date: "Nach Datum",
  proximity: "Nähe zu heute",
};

// Termin-Felder, die als "verantwortliche Person" einer Termin-Abgabe in Frage kommen.
const SINGLE_PARTICIPANT_EVENT_FIELDS: { value: string; label: string }[] = [
  { value: "spezial1_ids", label: "Spezial 1" },
  { value: "spezial2_ids", label: "Spezial 2" },
  { value: "spezial3_ids", label: "Spezial 3" },
];

// Zyklen, die ausgewählt werden können: 0 = aktueller Zyklus, -1 = vorheriger usw.
const CYCLE_OFFSET_OPTIONS = [0, -1, -2, -3];

export function cycleOffsetLabel(offset: number): string {
  return offset === 0 ? "Aktueller Zyklus" : offset === -1 ? "Vorheriger Zyklus (−1)" : `Zyklus −${Math.abs(offset)}`;
}

const FILE_TYPE_GROUPS = [
  { label: "PDF", types: ["pdf"] },
  { label: "Office-Dateien", types: ["doc", "docx", "xls", "xlsx", "ppt", "pptx"] },
  { label: "Bilddateien", types: ["jpg", "jpeg", "png", "gif", "webp"] },
];

const SOURCE_OPTIONS: { value: SubmissionSourceType; title: string; description: string }[] = [
  { value: "events", title: "Termine", description: "Ein Abgabefeld pro Termin mit dem gewählten Tag, rollendes Zeitfenster." },
  { value: "list", title: "Liste", description: "Ein Abgabefeld pro Listeneintrag, ein gemeinsamer Stichtag." },
  { value: "manual", title: "Manuell", description: "Ein einzelnes Abgabefeld, unabhängig von Terminen und Listen." },
];

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
    responsible_participant_source: assignment.responsible_participant_source ?? "",
    link_ids: assignment.link_ids,
  };
}

/** Grund, warum das Formular noch nicht gespeichert werden kann (null = gültig). */
export function formProblem(form: FormState): string | null {
  if (!form.title.trim()) return "Titel fehlt";
  if (form.source_type === "events") {
    if (!form.tag_filter) return "Tag-Filter fehlt";
    if (form.cycle_config_id && form.cycle_offsets.length === 0) return "Bitte mindestens einen Zyklus auswählen oder den Zyklus-Filter entfernen";
  }
  if (form.source_type === "list" && !form.list_definition_id) return "Liste fehlt";
  return null;
}

function deadlineSentence(deadline: string): string {
  return deadline
    ? `Abgaben sind bis ${formatDateInputValue(deadline)} möglich.`
    : "Es gibt keinen Stichtag, die Abgabe bleibt offen, bis sie manuell geschlossen wird.";
}

function windowSentence(before: number | "", after: number | ""): string {
  if (before !== "" && after !== "") return `Es öffnet ${before} Tage vor dem Termin und schliesst ${after} Tage danach.`;
  if (before !== "") return `Es öffnet ${before} Tage vor dem Termin und bleibt danach offen, bis es manuell geschlossen wird.`;
  if (after !== "") return `Es ist sofort offen und schliesst ${after} Tage nach dem Termin.`;
  return "Es bleibt offen, bis es manuell geschlossen wird.";
}

/** Erklärt in einem Satz, wie sich die Abgabe mit den aktuellen Einstellungen verhält. */
export function describeAssignment(form: FormState, listName: string | null): string {
  if (form.source_type === "events") {
    const subject = form.tag_filter
      ? `Jeder Termin mit dem Tag «${form.tag_filter}» bekommt ein eigenes Abgabefeld.`
      : "Jeder Termin mit dem gewählten Tag bekommt ein eigenes Abgabefeld.";
    return `${subject} ${windowSentence(form.offset_days_before, form.offset_days_after)}`;
  }
  if (form.source_type === "list") {
    const subject = listName
      ? `Jeder Eintrag der Liste «${listName}» bekommt ein eigenes Abgabefeld.`
      : "Jeder Eintrag der gewählten Liste bekommt ein eigenes Abgabefeld.";
    return `${subject} ${deadlineSentence(form.deadline)}`;
  }
  return `Diese Abgabe hat ein einziges Abgabefeld, unabhängig von Terminen und Listen. ${deadlineSentence(form.deadline)}`;
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
  onSubmit: () => void;
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
  const problem = formProblem(form);
  const selectedList = availableLists.find((list) => list.id === form.list_definition_id) ?? null;
  const selectedLinks = links.filter((link) => form.link_ids.includes(link.id));
  const previewLink = selectedLinks.find((link) => link.is_default) ?? selectedLinks[0] ?? null;
  const url = publicUrlParts(previewLink, form.public_slug);

  const responsibleOptions =
    form.source_type === "events"
      ? SINGLE_PARTICIPANT_EVENT_FIELDS
      : form.source_type === "list" && selectedList
        ? ([
            selectedList.column_one_value_type === "participant"
              ? { value: "column_one", label: selectedList.column_one_title || "Spalte 1" }
              : null,
            selectedList.column_two_value_type === "participant"
              ? { value: "column_two", label: selectedList.column_two_title || "Spalte 2" }
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
    if (problem === null) onSubmit();
  }

  const fileTypeCount = form.allowed_file_types.length;
  const maxFilesLabel = form.max_files_per_element === "" ? "unbegrenzt viele Dateien" : `max. ${form.max_files_per_element} ${form.max_files_per_element === 1 ? "Datei" : "Dateien"}`;

  return (
    <Modal open={open} title={editing ? "Abgabe bearbeiten" : "Abgabe erstellen"} className="subm-edit-modal" hideCloseButton onClose={onClose}>
      <form className="subm-edit-form" onSubmit={handleSubmit}>
        <header className="subm-edit-heading">
          <div className="subm-edit-eyebrow">
            {editing ? "Abgabe bearbeiten" : "Neue Abgabe"}
            {tenantName ? <><span aria-hidden="true">·</span><span>{tenantName}</span></> : null}
          </div>
          <input
            aria-label="Titel"
            className="subm-edit-title"
            placeholder="Titel der Abgabe"
            value={form.title}
            autoFocus={!editing}
            onChange={(e) => {
              const title = e.target.value;
              setForm((c) => ({ ...c, title, ...(editing ? {} : { public_slug: slugify(title) }) }));
            }}
          />
          <button type="button" className="subm-edit-close" aria-label="Schliessen" onClick={onClose}>×</button>
        </header>

        <div className="subm-edit-body">
          <div className="subm-edit-main grid">
            <div className="field-stack">
              <span className="field-label" id="subm-source-label">Verknüpfung</span>
              <div className="subm-edit-sources" role="radiogroup" aria-labelledby="subm-source-label">
                {SOURCE_OPTIONS.map((option) => (
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
                    <span className="field-label">Tag-Filter</span>
                    <SearchableSelect
                      options={availableTags}
                      getId={(tag) => tag}
                      getLabel={(tag) => tag}
                      value={form.tag_filter || null}
                      onChange={(tag) => setForm((c) => ({ ...c, tag_filter: tag ?? "" }))}
                      placeholder="Tag wählen…"
                      searchPlaceholder="Tag suchen…"
                      emptyLabel="Keine Tags gefunden"
                    />
                  </div>

                  <div className="field-stack">
                    <span className="field-label">Zeitfenster</span>
                    <div className="subm-edit-window">
                      <span>Öffnet</span>
                      <input
                        type="number"
                        min={0}
                        aria-label="Tage vor dem Termin"
                        placeholder="∞"
                        value={form.offset_days_before}
                        onChange={(e) => setForm((c) => ({ ...c, offset_days_before: e.target.value === "" ? "" : Number(e.target.value) }))}
                      />
                      <span>Tage vor dem Termin und schliesst</span>
                      <input
                        type="number"
                        min={0}
                        aria-label="Tage nach dem Termin"
                        placeholder="∞"
                        value={form.offset_days_after}
                        onChange={(e) => setForm((c) => ({ ...c, offset_days_after: e.target.value === "" ? "" : Number(e.target.value) }))}
                      />
                      <span>Tage danach.</span>
                    </div>
                    <span className="field-help">
                      Feld leer lassen = auf dieser Seite unbegrenzt. Ohne beide Werte bleibt die Abgabe offen, bis sie manuell geschlossen wird.
                    </span>
                  </div>

                  <div className="field-stack">
                    <span className="field-label">Zyklus</span>
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
                      nullLabel="Alle Zyklen (kein Filter)"
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
                            {cycleOffsetLabel(offset)}
                          </button>
                        ))}
                      </div>
                    ) : null}
                    <span className="field-help">
                      Nur Termine berücksichtigen, die dem gewählten Zyklus (bzw. den gewählten Zyklen) zugeordnet sind. Der aktuelle Zyklus richtet sich nach dem heutigen Datum und wechselt automatisch. Ohne Auswahl werden alle Termine mit dem Tag berücksichtigt.
                    </span>
                  </div>
                </>
              ) : (
                <>
                  {form.source_type === "list" ? (
                    <div className="field-stack">
                      <span className="field-label">Liste</span>
                      <SearchableSelect
                        options={availableLists}
                        getId={(list) => list.id}
                        getLabel={(list) => list.name}
                        value={form.list_definition_id || null}
                        onChange={(list) => setForm((c) => ({ ...c, list_definition_id: list ? list.id : "", responsible_participant_source: "" }))}
                        placeholder="Liste wählen…"
                        searchPlaceholder="Liste suchen…"
                        emptyLabel="Keine Listen gefunden"
                      />
                    </div>
                  ) : null}
                  <div className="field-stack">
                    <span className="field-label">Stichtag</span>
                    <DateInput value={form.deadline} onChange={(deadline) => setForm((c) => ({ ...c, deadline }))} aria-label="Stichtag" />
                    <span className="field-help">Leer lassen = kein Stichtag, die Abgabe bleibt offen, bis sie manuell geschlossen wird.</span>
                  </div>
                </>
              )}
            </div>

            <label className="field-stack">
              <span className="field-label">Beschreibung</span>
              <textarea
                rows={2}
                value={form.description}
                placeholder="Optional – erscheint für die Abgebenden über dem Upload-Feld."
                onChange={(e) => setForm((c) => ({ ...c, description: e.target.value }))}
              />
            </label>

            <div className="field-stack">
              <div className="subm-edit-label-row">
                <span className="field-label">Erlaubte Dateitypen</span>
                <span className="subm-edit-count">{fileTypeCount === 0 ? "alle erlaubt" : `${fileTypeCount} ausgewählt`}</span>
              </div>
              <div className="subm-edit-types">
                {FILE_TYPE_GROUPS.map((group) => {
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
                        {allSelected ? "Keine" : "Alle"}
                      </button>
                    </div>
                  );
                })}
              </div>
              <span className="field-help">Ohne Auswahl sind alle Dateitypen erlaubt.</span>
            </div>

            <div className={form.source_type === "manual" ? "subm-edit-grid subm-edit-grid-2" : "subm-edit-grid"}>
              <label className="field-stack">
                <span className="field-label">Max. Dateien</span>
                <input
                  type="number"
                  min={1}
                  placeholder="unbegrenzt"
                  value={form.max_files_per_element}
                  onChange={(e) => setForm((c) => ({ ...c, max_files_per_element: e.target.value === "" ? "" : Number(e.target.value) }))}
                />
              </label>
              <label className="field-stack">
                <span className="field-label">Max. Grösse (MB)</span>
                <input
                  type="number"
                  min={1}
                  value={form.max_file_size_mb}
                  onChange={(e) => setForm((c) => ({ ...c, max_file_size_mb: Number(e.target.value) }))}
                />
              </label>
              {form.source_type !== "manual" ? (
                <label className="field-stack">
                  <span className="field-label">Sortierung</span>
                  <select value={form.sort_order} onChange={(e) => setForm((c) => ({ ...c, sort_order: e.target.value as SubmissionSortOrder }))}>
                    {(Object.keys(SORT_ORDER_LABEL) as SubmissionSortOrder[]).map((value) => (
                      <option key={value} value={value}>{SORT_ORDER_LABEL[value]}</option>
                    ))}
                  </select>
                </label>
              ) : null}
            </div>

            {responsibleOptions.length > 0 ? (
              <div className="field-stack">
                <span className="field-label">Verantwortliche Person</span>
                <SearchableSelect
                  options={responsibleOptions}
                  getId={(option) => option.value}
                  getLabel={(option) => option.label}
                  value={form.responsible_participant_source || null}
                  onChange={(option) => setForm((c) => ({ ...c, responsible_participant_source: option ? option.value : "" }))}
                  nullLabel="Keine Zuweisung"
                />
                <span className="field-help">
                  {form.source_type === "events"
                    ? "Terminfeld, dessen Person als zuständig für die Abgabe gilt."
                    : "Listenspalte, deren Person als zuständig für die Abgabe gilt."}
                </span>
              </div>
            ) : null}
          </div>

          <aside className="subm-edit-sidebar">
            <div className="field-stack">
              <span className="field-label">Öffentlicher Link</span>
              {url ? (
                <code className="subm-edit-url">{url.base}<strong>{url.slug}</strong></code>
              ) : (
                <span className="field-help">Noch kein Link ausgewählt.</span>
              )}
            </div>

            <div className="field-stack">
              <span className="field-label">Erreichbar über</span>
              {links.length === 0 ? (
                <span className="field-help">
                  Es gibt noch keinen Link – lege zuerst unter «Abgabe-Links verwalten» einen an, sonst ist diese Abgabe nicht erreichbar.
                </span>
              ) : (
                <>
                  <div className="subm-edit-links">
                    {links.map((link) => (
                      <label key={link.id} className="subm-edit-link-option">
                        <input type="checkbox" checked={form.link_ids.includes(link.id)} onChange={() => toggleLink(link.id)} />
                        <span>{link.name}</span>
                        {link.is_default ? <small>Standard</small> : null}
                      </label>
                    ))}
                  </div>
                  {form.link_ids.length === 0 ? (
                    <span className="field-help">Kein Link ausgewählt – die Abgabe ist so über die Abgabebox nicht erreichbar.</span>
                  ) : null}
                </>
              )}
            </div>

            <div className="field-stack">
              <span className="field-label">So verhält sich die Abgabe</span>
              <div className="subm-edit-summary">
                <p>{describeAssignment(form, selectedList?.name ?? null)}</p>
              </div>
              <div className="subm-edit-chips">
                <span className="subm-edit-tag">{maxFilesLabel}</span>
                <span className="subm-edit-tag">max. {form.max_file_size_mb} MB</span>
                <span className="subm-edit-tag">{fileTypeCount === 0 ? "alle Dateitypen" : `${fileTypeCount} ${fileTypeCount === 1 ? "Dateityp" : "Dateitypen"}`}</span>
              </div>
              <p className="subm-edit-scan">
                <span className="subm-edit-scan-dot" aria-hidden="true" />
                Jede Datei wird vor der Freigabe per ClamAV geprüft.
              </p>
            </div>
          </aside>
        </div>

        <footer className="subm-edit-footer">
          <button type="button" className="subm-edit-manage" onClick={onManageLinks}>Abgabe-Links verwalten</button>
          <div className="subm-edit-actions">
            <button type="button" className="button-secondary" onClick={onClose}>Abbrechen</button>
            <button type="submit" className="button-primary" disabled={problem !== null} title={problem ?? undefined}>
              {editing ? "Abgabe speichern" : "Abgabe erstellen"}
            </button>
          </div>
        </footer>
      </form>
    </Modal>
  );
}
