"use client";

import { DragEvent, FormEvent, KeyboardEvent, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { DataTable, DataToolbar } from "@/components/ui/data-table";
import { Modal } from "@/components/ui/modal";
import { browserApiFetch } from "@/lib/api/client";
import { useToast } from "@/contexts/toast-context";
import { formatDateRange } from "@/lib/utils/format";
import {
  DocumentTemplate,
  ElementDefinition,
  EventSummary,
  ParticipantSummary,
  StructuredListDefinition,
  StructuredListEntry,
  TemplateElement,
  TemplateSummary,
} from "@/types/api";

type TemplateBuilderProps = {
  initialTemplates: TemplateSummary[];
};

type TemplateEditorProps = {
  initialTemplate: TemplateSummary;
  initialElements: TemplateElement[];
  initialDefinitions: ElementDefinition[];
  availableEvents: EventSummary[];
  availableParticipants: ParticipantSummary[];
  availableLists: StructuredListDefinition[];
  initialAssignedParticipants: ParticipantSummary[];
  availableDocumentTemplates: DocumentTemplate[];
};

type TemplateCreateState = {
  name: string;
  description: string;
  next_event_id: string;
  last_event_id: string;
  protocol_number_pattern: string;
  title_pattern: string;
  auto_create_next_protocol: boolean;
  cycle_reset_month: string;
  cycle_reset_day: string;
};

type TemplateItemForm = {
  element_definition_ids: string[];
};

type TemplateParticipantAssignmentState = {
  participant_id: number;
  exclude_from_attendance: boolean;
};

type ResponsibleNameMode = "display_name" | "first_name" | "last_name";

type ResponsibilityAssignment = {
  participant_id: number;
  list_definition_id: number | null;
  list_entry_id: number | null;
  locked: boolean;
};

type ResponsibilityConfig = {
  name_display_mode: ResponsibleNameMode;
  assignments: ResponsibilityAssignment[];
};

type ResponsibilityDisplayGroup = {
  key: string;
  participantIds: number[];
  listDefinitionId: number | null;
  listEntryId: number | null;
  locked: boolean;
};

type EligibleResponsibleList = {
  definition: StructuredListDefinition;
  textColumn: "column_one" | "column_two";
  participantColumn: "column_one" | "column_two";
  participantValueType: "participant" | "participants";
};

const initialTemplateCreate: TemplateCreateState = {
  name: "",
  description: "",
  next_event_id: "",
  last_event_id: "",
  protocol_number_pattern: "",
  title_pattern: "",
  auto_create_next_protocol: false,
  cycle_reset_month: "7",
  cycle_reset_day: "31"
};

const initialTemplateItemForm: TemplateItemForm = {
  element_definition_ids: []
};

function normalizeTemplateParticipantAssignments(participants: ParticipantSummary[]): TemplateParticipantAssignmentState[] {
  return Array.from(
    new Map(
      participants.map((participant) => [
        participant.id,
        {
          participant_id: participant.id,
          exclude_from_attendance: Boolean(participant.exclude_from_attendance),
        } satisfies TemplateParticipantAssignmentState,
      ])
    ).values()
  );
}

function resequenceTemplateElements(items: TemplateElement[]) {
  return items.map((item, index) => ({ ...item, sort_index: (index + 1) * 10 }));
}

function nextTemplateElementSortIndex(items: TemplateElement[]) {
  const maxSortIndex = items.reduce((max, item) => Math.max(max, item.sort_index), 0);
  return maxSortIndex + 10;
}

function definitionTypeSummary(definition: ElementDefinition) {
  const labels = Array.from(
    new Set(
      definition.blocks
        .map((block) => String(block.configuration_json?.block_type_code ?? block.title ?? "").trim())
        .filter(Boolean)
    )
  );
  return labels.length ? labels.join(", ") : `${definition.blocks.length} Block${definition.blocks.length === 1 ? "" : "e"}`;
}

function normalizeMatchText(value: string) {
  return value.trim().replace(/\s+/g, " ").toLowerCase();
}

function eligibleResponsibleList(definition: StructuredListDefinition): EligibleResponsibleList | null {
  const firstIsText = definition.column_one_value_type === "text";
  const secondIsText = definition.column_two_value_type === "text";
  const firstIsParticipants = definition.column_one_value_type === "participant" || definition.column_one_value_type === "participants";
  const secondIsParticipants = definition.column_two_value_type === "participant" || definition.column_two_value_type === "participants";

  if (firstIsText && secondIsParticipants) {
    return {
      definition,
      textColumn: "column_one",
      participantColumn: "column_two",
      participantValueType: definition.column_two_value_type === "participant" ? "participant" : "participants",
    };
  }
  if (secondIsText && firstIsParticipants) {
    return {
      definition,
      textColumn: "column_two",
      participantColumn: "column_one",
      participantValueType: definition.column_one_value_type === "participant" ? "participant" : "participants",
    };
  }
  return null;
}

function parseResponsibilityConfig(configurationJson: Record<string, unknown> | null | undefined): ResponsibilityConfig {
  const responsibility = configurationJson?.responsibility;
  const raw = responsibility && typeof responsibility === "object" ? (responsibility as Record<string, unknown>) : {};
  const rawAssignments = Array.isArray(raw.assignments) ? raw.assignments : [];
  const assignments = rawAssignments
    .map((item) => {
      if (!item || typeof item !== "object") {
        return null;
      }
      const entry = item as Record<string, unknown>;
      const participantId = Number(entry.participant_id ?? 0);
      const listDefinitionId = Number(entry.list_definition_id ?? 0);
      const listEntryId = Number(entry.list_entry_id ?? 0);
      if (!participantId) {
        return null;
      }
      return {
        participant_id: participantId,
        list_definition_id: listDefinitionId || null,
        list_entry_id: listEntryId || null,
        locked: Boolean(entry.locked ?? false),
      } satisfies ResponsibilityAssignment;
    })
    .filter((assignment): assignment is ResponsibilityAssignment => Boolean(assignment));
  const dedupedAssignments: ResponsibilityAssignment[] = [];
  const seenParticipantIds = new Set<number>();
  for (const assignment of assignments) {
    if (seenParticipantIds.has(assignment.participant_id)) {
      continue;
    }
    dedupedAssignments.push(assignment);
    seenParticipantIds.add(assignment.participant_id);
  }
  return {
    name_display_mode:
      raw.name_display_mode === "first_name" || raw.name_display_mode === "last_name" ? raw.name_display_mode : "display_name",
    assignments: dedupedAssignments,
  };
}

function buildResponsibilityConfig(
  currentConfigurationJson: Record<string, unknown>,
  responsibility: ResponsibilityConfig
) {
  return {
    ...currentConfigurationJson,
    responsibility: {
      name_display_mode: responsibility.name_display_mode,
      assignments: responsibility.assignments.map((assignment) => ({
        participant_id: assignment.participant_id,
        list_definition_id: assignment.list_definition_id,
        list_entry_id: assignment.list_entry_id,
        locked: assignment.locked,
      })),
    },
  };
}

function responsibilityConfigsEqual(left: ResponsibilityConfig, right: ResponsibilityConfig) {
  return JSON.stringify(left) === JSON.stringify(right);
}

function participantName(participant: ParticipantSummary | undefined, mode: ResponsibleNameMode, fallbackId?: number) {
  if (!participant) {
    return fallbackId ? `Teilnehmer ${fallbackId}` : "Unbekannt";
  }
  if (mode === "first_name") {
    return participant.first_name?.trim() || participant.display_name;
  }
  if (mode === "last_name") {
    return participant.last_name?.trim() || participant.display_name;
  }
  return participant.display_name;
}

function titleWithResponsibility(
  item: TemplateElement,
  participantsById: Map<number, ParticipantSummary>,
  fallbackMode: ResponsibleNameMode
) {
  const responsibility = parseResponsibilityConfig(item.configuration_json);
  const mode = responsibility.name_display_mode || fallbackMode;
  const names = responsibility.assignments
    .map((assignment) => participantName(participantsById.get(assignment.participant_id), mode, assignment.participant_id))
    .filter(Boolean);
  return names.length ? `${item.title} (${names.join(", ")})` : item.title;
}

function listTextValue(entry: StructuredListEntry, column: "column_one" | "column_two") {
  const value = column === "column_one" ? entry.column_one_value : entry.column_two_value;
  return String(value?.text_value ?? "").trim();
}

function listParticipantIds(
  entry: StructuredListEntry,
  column: "column_one" | "column_two",
  valueType: "participant" | "participants"
) {
  const value = column === "column_one" ? entry.column_one_value : entry.column_two_value;
  if (valueType === "participant") {
    const participantId = Number(value?.participant_id ?? 0);
    return participantId ? [participantId] : [];
  }
  return Array.isArray(value?.participant_ids) ? value.participant_ids.map(Number).filter(Boolean) : [];
}

function rowOptionLabel(
  entry: StructuredListEntry,
  meta: EligibleResponsibleList,
  participantsById: Map<number, ParticipantSummary>,
  mode: ResponsibleNameMode
) {
  const text = listTextValue(entry, meta.textColumn) || `Zeile ${entry.id}`;
  const names = listParticipantIds(entry, meta.participantColumn, meta.participantValueType)
    .map((participantId) => participantName(participantsById.get(participantId), mode, participantId))
    .filter(Boolean);
  return names.length ? `${text} -> ${names.join(", ")}` : text;
}

function ResponsibilityLockIcon({ locked }: { locked: boolean }) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      {locked ? (
        <>
          <path d="M8 10V7.5a4 4 0 1 1 8 0V10" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
          <rect x="5.5" y="10" width="13" height="10" rx="2.5" fill="none" stroke="currentColor" strokeWidth="1.8" />
          <circle cx="12" cy="15" r="1.2" fill="currentColor" />
        </>
      ) : (
        <>
          <path d="M8 10V7.5a4 4 0 1 1 7 2.65" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
          <path d="M14.5 12.5 18 9" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
          <rect x="5.5" y="10" width="13" height="10" rx="2.5" fill="none" stroke="currentColor" strokeWidth="1.8" />
          <circle cx="12" cy="15" r="1.2" fill="currentColor" />
        </>
      )}
    </svg>
  );
}

export function TemplateBuilder({ initialTemplates }: TemplateBuilderProps) {
  const router = useRouter();
  const showToast = useToast();
  const [templates, setTemplates] = useState(initialTemplates);
  const [form, setForm] = useState(initialTemplateCreate);
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [search, setSearch] = useState("");

  const filteredTemplates = useMemo(
    () =>
      templates.filter((template) => {
        const haystack = `${template.name} ${template.description ?? ""}`.toLowerCase();
        return !search || haystack.includes(search.toLowerCase());
      }),
    [templates, search]
  );

  async function createTemplate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    try {
      const created = await browserApiFetch<TemplateSummary>("/api/templates", {
        method: "POST",
        body: JSON.stringify({
          name: form.name,
          description: form.description || null,
          protocol_number_pattern: form.protocol_number_pattern || null,
          title_pattern: form.title_pattern || null,
          auto_create_next_protocol: form.auto_create_next_protocol,
          cycle_reset_month: Number(form.cycle_reset_month),
          cycle_reset_day: Number(form.cycle_reset_day),
          version: 1,
          status: "active",
          created_by: null
        })
      });
      setTemplates((current) => [created, ...current]);
      setForm(initialTemplateCreate);
      setShowCreateForm(false);
      showToast(`Created template #${created.id}`, "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Template creation failed", "error");
    }
  }

  async function deleteTemplate(templateId: number) {
    try {
      await browserApiFetch(`/api/templates/${templateId}`, { method: "DELETE" });
      setTemplates((current) => current.filter((template) => template.id !== templateId));
      showToast(`Deleted template #${templateId}`, "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Template deletion failed", "error");
    }
  }

  return (
    <div className="grid">
      <DataToolbar
        title="Templates"
        description="Templates are slim containers: they select finished elements and decide order only."
        actions={
          <button type="button" className="button-inline" onClick={() => setShowCreateForm((current) => !current)}>
            {showCreateForm ? "Close create form" : "New template"}
          </button>
        }
      />

      <Modal
        open={showCreateForm}
        onClose={() => setShowCreateForm(false)}
        title="Create template"
        description="Create a fresh template shell, then assign reusable elements to it."
      >
        <form className="grid" onSubmit={createTemplate}>
          <label className="field-stack">
            <span className="field-label">Template name</span>
            <input value={form.name} onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))} placeholder="Template name" required />
          </label>
          <label className="field-stack">
            <span className="field-label">Description</span>
            <textarea rows={4} value={form.description} onChange={(event) => setForm((current) => ({ ...current, description: event.target.value }))} placeholder="Description" />
          </label>
          <div className="two-col">
            <label className="field-stack">
              <span className="field-label">Protocol number pattern</span>
              <input value={form.protocol_number_pattern} onChange={(event) => setForm((current) => ({ ...current, protocol_number_pattern: event.target.value }))} placeholder="e.g. Sitzung {n}" />
              <span className="field-help">Beispiele: Sitzung [n], Sitzung [mm].[n_month], J[yy]-[n_year], V[n_cycle]. Eckige und geschweifte Klammern funktionieren beide.</span>
            </label>
            <label className="field-stack">
              <span className="field-label">Title pattern</span>
              <input value={form.title_pattern} onChange={(event) => setForm((current) => ({ ...current, title_pattern: event.target.value }))} placeholder="e.g. Sitzung {n} - {date:DD.MM.YYYY}" />
              <span className="field-help">The date token always uses the selected protocol date, not the current day.</span>
            </label>
          </div>
          <div className="two-col">
            <label className="field-stack">
              <span className="field-label">Cycle reset month</span>
              <input value={form.cycle_reset_month} onChange={(event) => setForm((current) => ({ ...current, cycle_reset_month: event.target.value }))} type="number" min={1} max={12} />
            </label>
            <label className="field-stack">
              <span className="field-label">Cycle reset day</span>
              <input value={form.cycle_reset_day} onChange={(event) => setForm((current) => ({ ...current, cycle_reset_day: event.target.value }))} type="number" min={1} max={31} />
            </label>
          </div>
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={form.auto_create_next_protocol}
              onChange={(event) => setForm((current) => ({ ...current, auto_create_next_protocol: event.target.checked }))}
            />
            <span>Naechstes Protokoll automatisch erstellen, wenn dieses spaeter auf Abgeschlossen gesetzt wird.</span>
          </label>
          <div className="info-note">
            Tokens: {"{n}"} = alle Protokolle, {"{n_year}"} = in diesem Jahr, {"{n_month}"} = in diesem Monat, {"{n_cycle}"} = im eigenen Zyklus. Datums-Tokens: {"{date}"}, {"{date:DD.MM.YYYY}"}, {"{dd}"}, {"{mm}"}, {"{yyyy}"}.
          </div>
          <div className="table-toolbar-actions">
            <button type="submit" className="button-inline">Create template</button>
          </div>
        </form>
      </Modal>

      <article className="card">
        <div className="two-col">
          <label className="field-stack">
            <span className="field-label">Search</span>
            <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search templates" />
          </label>
          <div className="card">
            <div className="eyebrow">Overview</div>
            <div className="status-row">
              <span className="pill">{filteredTemplates.length} visible</span>
              <span className="pill">{templates.length} total</span>
            </div>
          </div>
        </div>
      </article>

      <DataTable columns={["Template", "Description", "Version", "Actions"]}>
        {filteredTemplates.map((template) => (
          <tr key={template.id} className="table-row-clickable" onClick={() => router.push(`/templates/${template.id}`)}>
            <td>
              <strong>{template.name}</strong>
              <div className="muted">{template.status === "archived" ? "Archiviert" : "Aktiv"}</div>
            </td>
            <td>{template.description ?? "No description"}</td>
            <td>{template.version}</td>
            <td>
              <div className="table-actions">
                <button type="button" className="button-inline button-danger" onClick={(event) => {
                  event.stopPropagation();
                  void deleteTemplate(template.id);
                }}>Delete</button>
              </div>
            </td>
          </tr>
        ))}
      </DataTable>
    </div>
  );
}

export function TemplateEditor({
  initialTemplate,
  initialElements,
  initialDefinitions,
  availableEvents,
  availableParticipants,
  availableLists,
  initialAssignedParticipants,
  availableDocumentTemplates,
}: TemplateEditorProps) {
  const router = useRouter();
  const showToast = useToast();
  const [template, setTemplate] = useState(initialTemplate);
  const [elements, setElements] = useState(initialElements);
  const [templateMeta, setTemplateMeta] = useState({
    name: initialTemplate.name,
    description: initialTemplate.description ?? "",
    status: initialTemplate.status,
    next_event_id: initialTemplate.next_event_id ? String(initialTemplate.next_event_id) : "",
    last_event_id: initialTemplate.last_event_id ? String(initialTemplate.last_event_id) : "",
    todo_due_event_tag: initialTemplate.todo_due_event_tag ?? "",
    protocol_number_pattern: initialTemplate.protocol_number_pattern ?? "",
    title_pattern: initialTemplate.title_pattern ?? "",
    auto_create_next_protocol: Boolean(initialTemplate.auto_create_next_protocol),
    cycle_reset_month: String(initialTemplate.cycle_reset_month ?? 7),
    cycle_reset_day: String(initialTemplate.cycle_reset_day ?? 31),
    document_template_id: initialTemplate.document_template_id ? String(initialTemplate.document_template_id) : "",
  });
  const [newItemForm, setNewItemForm] = useState<TemplateItemForm>({
    ...initialTemplateItemForm
  });
  const [showCreateItem, setShowCreateItem] = useState(false);
  const [showParticipantModal, setShowParticipantModal] = useState(false);
  const [showResponsibilityModalFor, setShowResponsibilityModalFor] = useState<number | null>(null);
  const [draggedTemplateElementId, setDraggedTemplateElementId] = useState<number | null>(null);
  const [activeTemplateDropIndex, setActiveTemplateDropIndex] = useState<number | null>(null);
  const [expandedTemplateDropIndex, setExpandedTemplateDropIndex] = useState<number | null>(null);
  const [positionDrafts, setPositionDrafts] = useState<Record<number, string>>({});
  const [responsibilityAutoListId, setResponsibilityAutoListId] = useState("");
  const [responsibilityNameMode, setResponsibilityNameMode] = useState<ResponsibleNameMode>(() => {
    const firstConfiguredElement = initialElements.find((item) => Array.isArray((item.configuration_json?.responsibility as { assignments?: unknown } | undefined)?.assignments));
    return parseResponsibilityConfig(firstConfiguredElement?.configuration_json ?? {}).name_display_mode;
  });
  const [listEntriesByListId, setListEntriesByListId] = useState<Record<number, StructuredListEntry[]>>({});
  const [loadingResponsibleListId, setLoadingResponsibleListId] = useState<number | null>(null);
  const [responsibilitySearch, setResponsibilitySearch] = useState("");
  const [manualLinkListId, setManualLinkListId] = useState("");
  const [manualLinkEntryId, setManualLinkEntryId] = useState("");
  const [participantAssignments, setParticipantAssignments] = useState<TemplateParticipantAssignmentState[]>(
    () => normalizeTemplateParticipantAssignments(initialAssignedParticipants)
  );

  const participantsById = useMemo(
    () => new Map(availableParticipants.map((participant) => [participant.id, participant])),
    [availableParticipants]
  );
  const allParticipantIds = useMemo(
    () => availableParticipants.filter((participant) => participant.is_active).map((participant) => participant.id),
    [availableParticipants]
  );
  const participantAssignmentsById = useMemo(
    () => new Map(participantAssignments.map((assignment) => [assignment.participant_id, assignment])),
    [participantAssignments]
  );
  const assignedParticipantIds = useMemo(
    () => participantAssignments.map((assignment) => assignment.participant_id),
    [participantAssignments]
  );
  const excludedAttendanceCount = useMemo(
    () => participantAssignments.filter((assignment) => assignment.exclude_from_attendance).length,
    [participantAssignments]
  );
  const eligibleResponsibleLists = useMemo(
    () =>
      availableLists
        .map((definition) => eligibleResponsibleList(definition))
        .filter((definition): definition is EligibleResponsibleList => Boolean(definition)),
    [availableLists]
  );
  const orderedElements = useMemo(
    () => [...elements].sort((left, right) => left.sort_index - right.sort_index),
    [elements]
  );
  const responsibilityModalElement = useMemo(
    () => orderedElements.find((item) => item.id === showResponsibilityModalFor) ?? null,
    [orderedElements, showResponsibilityModalFor]
  );
  const templateDropExpandTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const templateDragPreviewRef = useRef<HTMLElement | null>(null);
  const filteredResponsibilityParticipants = useMemo(() => {
    const query = responsibilitySearch.trim().toLowerCase();
    return [...availableParticipants]
      .sort((left, right) => left.display_name.localeCompare(right.display_name, "de", { sensitivity: "base" }))
      .filter((participant) => {
        if (!query) {
          return true;
        }
        const haystack = [
          participant.display_name,
          participant.first_name ?? "",
          participant.last_name ?? "",
          participant.email ?? "",
        ]
          .join(" ")
          .toLowerCase();
        return haystack.includes(query);
      });
  }, [availableParticipants, responsibilitySearch]);
  const manualLinkListMeta = useMemo(
    () => eligibleResponsibleLists.find((item) => String(item.definition.id) === manualLinkListId) ?? null,
    [eligibleResponsibleLists, manualLinkListId]
  );

  useEffect(() => {
    setPositionDrafts(
      Object.fromEntries(orderedElements.map((item, index) => [item.id, String(index + 1)]))
    );
  }, [orderedElements]);

  useEffect(
    () => () => {
      if (templateDropExpandTimerRef.current) {
        clearTimeout(templateDropExpandTimerRef.current);
      }
      if (templateDragPreviewRef.current) {
        templateDragPreviewRef.current.remove();
        templateDragPreviewRef.current = null;
      }
    },
    []
  );

  useEffect(() => {
    if (!showResponsibilityModalFor || !responsibilityModalElement) {
      setResponsibilitySearch("");
      setManualLinkListId("");
      setManualLinkEntryId("");
      return;
    }
    const firstLinkedListId =
      parseResponsibilityConfig(responsibilityModalElement.configuration_json).assignments.find((assignment) => assignment.list_definition_id)?.list_definition_id
      ?? (responsibilityAutoListId ? Number(responsibilityAutoListId) : null)
      ?? eligibleResponsibleLists[0]?.definition.id
      ?? null;
    setManualLinkListId(firstLinkedListId ? String(firstLinkedListId) : "");
    setManualLinkEntryId("");
    setResponsibilitySearch("");
  }, [showResponsibilityModalFor, responsibilityAutoListId, eligibleResponsibleLists]);

  useEffect(() => {
    if (!manualLinkListId) {
      setManualLinkEntryId("");
      return;
    }
    const listDefinitionId = Number(manualLinkListId);
    if (!Number.isFinite(listDefinitionId) || listDefinitionId <= 0) {
      setManualLinkEntryId("");
      return;
    }
    void ensureResponsibleListEntries(listDefinitionId);
    setManualLinkEntryId("");
  }, [manualLinkListId]);

  useEffect(() => {
    if (!responsibilityModalElement) {
      return;
    }
    const listDefinitionIds = Array.from(
      new Set(
        parseResponsibilityConfig(responsibilityModalElement.configuration_json).assignments
          .map((assignment) => assignment.list_definition_id)
          .filter((value): value is number => Number(value) > 0)
      )
    );
    listDefinitionIds.forEach((listDefinitionId) => {
      void ensureResponsibleListEntries(listDefinitionId);
    });
  }, [responsibilityModalElement]);

  async function ensureResponsibleListEntries(listDefinitionId: number) {
    if (listEntriesByListId[listDefinitionId]) {
      return listEntriesByListId[listDefinitionId];
    }
    setLoadingResponsibleListId(listDefinitionId);
    try {
      const entries = await browserApiFetch<StructuredListEntry[]>(`/api/lists/${listDefinitionId}/entries`);
      setListEntriesByListId((current) => ({ ...current, [listDefinitionId]: entries ?? [] }));
      return entries ?? [];
    } finally {
      setLoadingResponsibleListId((current) => (current === listDefinitionId ? null : current));
    }
  }

  async function patchTemplateElementConfiguration(templateElementId: number, configurationJson: Record<string, unknown>) {
    const updated = await browserApiFetch<TemplateElement>(`/api/template-elements/${templateElementId}`, {
      method: "PATCH",
      body: JSON.stringify({ configuration_json: configurationJson }),
    });
    setElements((current) => current.map((item) => (item.id === updated.id ? updated : item)));
    return updated;
  }

  async function saveElementResponsibility(
    templateElementId: number,
    updater: (current: ResponsibilityConfig) => ResponsibilityConfig
  ) {
    const templateElement = orderedElements.find((item) => item.id === templateElementId);
    if (!templateElement) {
      return null;
    }
    const currentResponsibility = parseResponsibilityConfig(templateElement.configuration_json);
    const nextResponsibility = updater(currentResponsibility);
    if (responsibilityConfigsEqual(currentResponsibility, nextResponsibility)) {
      return templateElement;
    }
    return patchTemplateElementConfiguration(
      templateElementId,
      buildResponsibilityConfig(templateElement.configuration_json, nextResponsibility)
    );
  }

  function currentResponsibilityTitle(item: TemplateElement) {
    return titleWithResponsibility(item, participantsById, responsibilityNameMode);
  }

  async function applyResponsibilityNameMode(nextMode: ResponsibleNameMode) {
    setResponsibilityNameMode(nextMode);
    const itemsToUpdate = orderedElements.filter((item) => {
      const currentResponsibility = parseResponsibilityConfig(item.configuration_json);
      return currentResponsibility.assignments.length > 0 || "responsibility" in item.configuration_json;
    });
    if (!itemsToUpdate.length) {
      showToast("Namensformat für Verantwortliche gesetzt", "success");
      return;
    }
    try {
      for (const item of itemsToUpdate) {
        await saveElementResponsibility(item.id, (current) => ({
          ...current,
          name_display_mode: nextMode,
        }));
      }
      showToast("Namensformat für Verantwortliche gespeichert", "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Namensformat konnte nicht gespeichert werden", "error");
    }
  }

  async function autoAssignResponsiblesFromList(listDefinitionId: number, targetItems: TemplateElement[] = orderedElements) {
    const listMeta = eligibleResponsibleLists.find((item) => item.definition.id === listDefinitionId);
    if (!listMeta) {
      return;
    }
    setResponsibilityAutoListId(String(listDefinitionId));
    try {
      const entries = await ensureResponsibleListEntries(listDefinitionId);
      let matchedElementCount = 0;
      for (const item of targetItems) {
        const matchedAssignments = entries
          .filter((entry) => normalizeMatchText(listTextValue(entry, listMeta.textColumn)) === normalizeMatchText(item.title))
          .flatMap((entry) =>
            listParticipantIds(entry, listMeta.participantColumn, listMeta.participantValueType).map((participantId) => ({
              participant_id: participantId,
              list_definition_id: listDefinitionId,
              list_entry_id: entry.id,
              locked: false,
            }))
          );
        if (matchedAssignments.length > 0) {
          matchedElementCount += 1;
        }
        const dedupedMatches: ResponsibilityAssignment[] = [];
        const matchedParticipantIds = new Set<number>();
        for (const assignment of matchedAssignments) {
          if (matchedParticipantIds.has(assignment.participant_id)) {
            continue;
          }
          dedupedMatches.push(assignment);
          matchedParticipantIds.add(assignment.participant_id);
        }
        await saveElementResponsibility(item.id, (current) => {
          const preservedAssignments = current.assignments.filter((assignment) => {
            if (assignment.locked) {
              return true;
            }
            if (assignment.list_definition_id === listDefinitionId) {
              return false;
            }
            return true;
          });
          const existingParticipantIds = new Set(preservedAssignments.map((assignment) => assignment.participant_id));
          const nextAssignments = [...preservedAssignments];
          for (const assignment of dedupedMatches) {
            if (existingParticipantIds.has(assignment.participant_id)) {
              continue;
            }
            nextAssignments.push(assignment);
            existingParticipantIds.add(assignment.participant_id);
          }
          return {
            name_display_mode: responsibilityNameMode,
            assignments: nextAssignments,
          };
        });
      }
      if (matchedElementCount) {
        showToast(`${matchedElementCount} Element${matchedElementCount === 1 ? "" : "e"} wurden automatisch zugeordnet`, "success");
      }
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Automatische Zuordnung konnte nicht gespeichert werden", "error");
    }
  }

  async function toggleResponsibleParticipant(templateElementId: number, participantId: number, enabled: boolean) {
    try {
      await saveElementResponsibility(templateElementId, (current) => {
        const nextAssignments = current.assignments.filter((assignment) => assignment.participant_id !== participantId);
        if (enabled) {
          nextAssignments.push({
            participant_id: participantId,
            list_definition_id: null,
            list_entry_id: null,
            locked: false,
          });
        }
        return {
          name_display_mode: responsibilityNameMode,
          assignments: nextAssignments,
        };
      });
      showToast(enabled ? "Verantwortliche Person zugewiesen" : "Verantwortliche Person entfernt", "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Verantwortliche Person konnte nicht aktualisiert werden", "error");
    }
  }

  async function toggleResponsibilityLock(templateElementId: number, participantId: number) {
    try {
      await saveElementResponsibility(templateElementId, (current) => ({
        name_display_mode: responsibilityNameMode,
        assignments: current.assignments.map((assignment) =>
          assignment.participant_id === participantId && assignment.list_definition_id && assignment.list_entry_id
            ? { ...assignment, locked: !assignment.locked }
            : assignment
        ),
      }));
      showToast("Tabellen-Verknüpfung aktualisiert", "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Tabellen-Verknüpfung konnte nicht aktualisiert werden", "error");
    }
  }

  async function toggleResponsibilityRowLock(templateElementId: number, listDefinitionId: number, listEntryId: number) {
    try {
      await saveElementResponsibility(templateElementId, (current) => {
        const matchingAssignments = current.assignments.filter(
          (assignment) => assignment.list_definition_id === listDefinitionId && assignment.list_entry_id === listEntryId
        );
        if (!matchingAssignments.length) {
          return current;
        }
        const nextLocked = !matchingAssignments.every((assignment) => assignment.locked);
        return {
          name_display_mode: responsibilityNameMode,
          assignments: current.assignments.map((assignment) =>
            assignment.list_definition_id === listDefinitionId && assignment.list_entry_id === listEntryId
              ? { ...assignment, locked: nextLocked }
              : assignment
          ),
        };
      });
      showToast("Tabellen-Verknüpfung aktualisiert", "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Tabellen-Verknüpfung konnte nicht aktualisiert werden", "error");
    }
  }

  async function linkElementToResponsibleRow() {
    if (!responsibilityModalElement || !manualLinkListMeta || !manualLinkEntryId) {
      return;
    }
    const entryId = Number(manualLinkEntryId);
    const listDefinitionId = manualLinkListMeta.definition.id;
    try {
      const entries = await ensureResponsibleListEntries(listDefinitionId);
      const selectedEntry = entries.find((entry) => entry.id === entryId);
      if (!selectedEntry) {
        showToast("Die gewählte Tabellenzeile wurde nicht gefunden", "error");
        return;
      }
      const participantIds = listParticipantIds(selectedEntry, manualLinkListMeta.participantColumn, manualLinkListMeta.participantValueType);
      if (!participantIds.length) {
        showToast("Die gewählte Tabellenzeile enthält keine Teilnehmenden", "error");
        return;
      }
      await saveElementResponsibility(responsibilityModalElement.id, (current) => {
        const nextAssignmentsByParticipant = new Map<number, ResponsibilityAssignment>();
        for (const assignment of current.assignments) {
          if (assignment.list_definition_id === listDefinitionId) {
            continue;
          }
          nextAssignmentsByParticipant.set(assignment.participant_id, assignment);
        }
        for (const participantId of participantIds) {
          nextAssignmentsByParticipant.set(participantId, {
            participant_id: participantId,
            list_definition_id: listDefinitionId,
            list_entry_id: entryId,
            locked: true,
          });
        }
        return {
          name_display_mode: responsibilityNameMode,
          assignments: [...nextAssignmentsByParticipant.values()],
        };
      });
      showToast("Element mit Tabellenzeile verknüpft", "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Tabellenzeilen-Verknüpfung konnte nicht gespeichert werden", "error");
    }
  }

  function responsibilityLinkTooltip(assignment: ResponsibilityAssignment) {
    if (!assignment.list_definition_id || !assignment.list_entry_id) {
      return "";
    }
    const listMeta = eligibleResponsibleLists.find((item) => item.definition.id === assignment.list_definition_id);
    const listName = listMeta?.definition.name ?? `Liste ${assignment.list_definition_id}`;
    const linkedEntry = listEntriesByListId[assignment.list_definition_id]?.find((entry) => entry.id === assignment.list_entry_id);
    const rowLabel = linkedEntry && listMeta
      ? listTextValue(linkedEntry, listMeta.textColumn) || `Zeile ${assignment.list_entry_id}`
      : `Zeile ${assignment.list_entry_id}`;
    return `${listName} · ${rowLabel}`;
  }

  function responsibilityDisplayGroups(templateElement: TemplateElement) {
    const responsibility = parseResponsibilityConfig(templateElement.configuration_json);
    const groups: ResponsibilityDisplayGroup[] = [];
    const groupIndexes = new Map<string, number>();
    for (const assignment of responsibility.assignments) {
      const groupKey =
        assignment.list_definition_id && assignment.list_entry_id
          ? `linked:${assignment.list_definition_id}:${assignment.list_entry_id}`
          : `manual:${assignment.participant_id}`;
      const existingIndex = groupIndexes.get(groupKey);
      if (existingIndex === undefined) {
        groupIndexes.set(groupKey, groups.length);
        groups.push({
          key: groupKey,
          participantIds: [assignment.participant_id],
          listDefinitionId: assignment.list_definition_id,
          listEntryId: assignment.list_entry_id,
          locked: assignment.locked,
        });
        continue;
      }
      groups[existingIndex] = {
        ...groups[existingIndex],
        participantIds: [...groups[existingIndex].participantIds, assignment.participant_id],
        locked: groups[existingIndex].locked && assignment.locked,
      };
    }
    return groups.map((group) => ({
      ...group,
      names: group.participantIds
        .map((participantId) =>
          participantName(
            participantsById.get(participantId),
            responsibility.name_display_mode || responsibilityNameMode,
            participantId
          )
        )
        .filter(Boolean)
        .join(", "),
      tooltip:
        group.listDefinitionId && group.listEntryId
          ? responsibilityLinkTooltip({
              participant_id: group.participantIds[0] ?? 0,
              list_definition_id: group.listDefinitionId,
              list_entry_id: group.listEntryId,
              locked: group.locked,
            })
          : "",
    }));
  }

  function isParticipantResponsible(templateElement: TemplateElement, participantId: number) {
    return parseResponsibilityConfig(templateElement.configuration_json).assignments.some(
      (assignment) => assignment.participant_id === participantId
    );
  }
  async function saveTemplate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      const updated = await browserApiFetch<TemplateSummary>(`/api/templates/${template.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          name: templateMeta.name,
          description: templateMeta.description || null,
          status: templateMeta.status,
          next_event_id: templateMeta.next_event_id ? Number(templateMeta.next_event_id) : null,
          last_event_id: templateMeta.last_event_id ? Number(templateMeta.last_event_id) : null,
          todo_due_event_tag: templateMeta.todo_due_event_tag || null,
          protocol_number_pattern: templateMeta.protocol_number_pattern || null,
          title_pattern: templateMeta.title_pattern || null,
          auto_create_next_protocol: templateMeta.auto_create_next_protocol,
          cycle_reset_month: Number(templateMeta.cycle_reset_month),
          cycle_reset_day: Number(templateMeta.cycle_reset_day),
          document_template_id: templateMeta.document_template_id ? Number(templateMeta.document_template_id) : null,
        })
      });
      setTemplate(updated);
      showToast("Template saved", "success");
      router.refresh();
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Template save failed", "error");
    }
  }

  async function saveTemplateParticipants(closeAfter = false) {
    try {
      await browserApiFetch(`/api/templates/${template.id}/participants`, {
        method: "PUT",
        body: JSON.stringify({
          participants: participantAssignments.map((assignment) => ({
            participant_id: assignment.participant_id,
            exclude_from_attendance: assignment.exclude_from_attendance,
          })),
        }),
      });
      showToast("Participant assignments saved", "success");
      router.refresh();
      if (closeAfter) {
        setShowParticipantModal(false);
      }
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Participant assignments could not be saved", "error");
    }
  }

  async function addElementToTemplate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      const createdItems = await Promise.all(
        newItemForm.element_definition_ids.map((elementDefinitionId, index) =>
          browserApiFetch<TemplateElement>(`/api/templates/${template.id}/elements`, {
            method: "POST",
            body: JSON.stringify({
              element_definition_id: Number(elementDefinitionId),
              sort_index: nextTemplateElementSortIndex(elements) + index * 10
            })
          })
        )
      );
      setElements((current) => [...current, ...createdItems].sort((left, right) => left.sort_index - right.sort_index));
      setNewItemForm(initialTemplateItemForm);
      setShowCreateItem(false);
      showToast(`${createdItems.length} Element${createdItems.length === 1 ? "" : "e"} hinzugefuegt`, "success");
      router.refresh();
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Template element creation failed", "error");
    }
  }

  async function persistTemplateOrder(nextOrdered: TemplateElement[], successMessage: string) {
    try {
      const resequenced = resequenceTemplateElements(nextOrdered);
      const temporaryItems = resequenced.map((item, index) => ({
        ...item,
        sort_index: -1000 - index,
      }));
      for (const item of temporaryItems) {
        await browserApiFetch<TemplateElement>(`/api/template-elements/${item.id}`, {
          method: "PATCH",
          body: JSON.stringify({ sort_index: item.sort_index })
        });
      }
      const updatedItems: TemplateElement[] = [];
      for (const item of resequenced) {
        const updated = await browserApiFetch<TemplateElement>(`/api/template-elements/${item.id}`, {
          method: "PATCH",
          body: JSON.stringify({ sort_index: item.sort_index })
        });
        updatedItems.push(updated);
      }
      setElements(updatedItems.sort((left, right) => left.sort_index - right.sort_index));
      showToast(successMessage, "success");
      router.refresh();
      return true;
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Template-Reihenfolge konnte nicht gespeichert werden", "error");
      return false;
    }
  }

  async function reorderTemplateItems(sourceId: number, targetId: number) {
    if (sourceId === targetId) {
      return;
    }
    const sourceIndex = orderedElements.findIndex((item) => item.id === sourceId);
    const targetIndex = orderedElements.findIndex((item) => item.id === targetId);
    if (sourceIndex === -1 || targetIndex === -1) {
      return;
    }
    const nextOrdered = [...orderedElements];
    const [moved] = nextOrdered.splice(sourceIndex, 1);
    nextOrdered.splice(targetIndex, 0, moved);
    await persistTemplateOrder(nextOrdered, "Template-Reihenfolge gespeichert");
  }

  async function moveTemplateItemToPosition(templateElementId: number, requestedPosition: number) {
    const currentIndex = orderedElements.findIndex((item) => item.id === templateElementId);
    if (currentIndex === -1) {
      return;
    }
    const clampedIndex = Math.min(Math.max(requestedPosition - 1, 0), orderedElements.length - 1);
    setPositionDrafts((current) => ({ ...current, [templateElementId]: String(clampedIndex + 1) }));
    if (currentIndex === clampedIndex) {
      return;
    }
    const nextOrdered = [...orderedElements];
    const [moved] = nextOrdered.splice(currentIndex, 1);
    nextOrdered.splice(clampedIndex, 0, moved);
    await persistTemplateOrder(nextOrdered, `Element auf Position ${clampedIndex + 1} verschoben`);
  }

  function handlePositionSubmit(templateElementId: number, rawValue: string) {
    const parsed = Number(rawValue);
    if (!Number.isFinite(parsed) || parsed < 1) {
      const currentIndex = orderedElements.findIndex((item) => item.id === templateElementId);
      setPositionDrafts((current) => ({
        ...current,
        [templateElementId]: String(currentIndex >= 0 ? currentIndex + 1 : 1),
      }));
      return;
    }
    void moveTemplateItemToPosition(templateElementId, Math.trunc(parsed));
  }

  function clearTemplateDropExpansionTimer() {
    if (templateDropExpandTimerRef.current) {
      clearTimeout(templateDropExpandTimerRef.current);
      templateDropExpandTimerRef.current = null;
    }
  }

  function clearTemplateDragPreview() {
    if (templateDragPreviewRef.current) {
      templateDragPreviewRef.current.remove();
      templateDragPreviewRef.current = null;
    }
  }

  function resetTemplateDragState() {
    clearTemplateDropExpansionTimer();
    clearTemplateDragPreview();
    setDraggedTemplateElementId(null);
    setActiveTemplateDropIndex(null);
    setExpandedTemplateDropIndex(null);
  }

  function scheduleTemplateDropExpansion(dropIndex: number) {
    clearTemplateDropExpansionTimer();
    templateDropExpandTimerRef.current = setTimeout(() => {
      setExpandedTemplateDropIndex(dropIndex);
    }, 180);
  }

  function handleTemplateDragStart(event: DragEvent<HTMLElement>, templateElementId: number) {
    setDraggedTemplateElementId(templateElementId);
    setActiveTemplateDropIndex(null);
    setExpandedTemplateDropIndex(null);
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/template-element", String(templateElementId));
    const rowElement = event.currentTarget.closest(".template-element-row");
    if (rowElement instanceof HTMLElement) {
      clearTemplateDragPreview();
      const preview = rowElement.cloneNode(true) as HTMLElement;
      preview.style.position = "fixed";
      preview.style.top = "-1000px";
      preview.style.left = "-1000px";
      preview.style.width = `${rowElement.offsetWidth}px`;
      preview.style.pointerEvents = "none";
      preview.style.transform = "rotate(-1deg)";
      preview.style.boxShadow = "0 16px 34px rgba(15, 23, 42, 0.28)";
      preview.style.opacity = "0.96";
      preview.classList.add("template-element-drag-preview");
      document.body.appendChild(preview);
      templateDragPreviewRef.current = preview;
      event.dataTransfer.setDragImage(preview, 28, 24);
    }
  }

  function handleTemplateDragEnd() {
    resetTemplateDragState();
  }

  function templateDropIndexForRow(event: DragEvent<HTMLElement>, rowIndex: number) {
    const bounds = event.currentTarget.getBoundingClientRect();
    const midpoint = bounds.top + bounds.height / 2;
    return event.clientY >= midpoint ? rowIndex + 1 : rowIndex;
  }

  function handleTemplateDropSlotDragOver(event: DragEvent<HTMLElement>, dropIndex: number) {
    event.preventDefault();
    if (!draggedTemplateElementId) {
      return;
    }
    event.dataTransfer.dropEffect = "move";
    const isSameDropTarget = activeTemplateDropIndex === dropIndex;
    setActiveTemplateDropIndex((current) => (current === dropIndex ? current : dropIndex));
    if (!isSameDropTarget) {
      scheduleTemplateDropExpansion(dropIndex);
      return;
    }
    if (expandedTemplateDropIndex !== dropIndex && !templateDropExpandTimerRef.current) {
      scheduleTemplateDropExpansion(dropIndex);
    }
  }

  function handleTemplateRowDragOver(event: DragEvent<HTMLElement>, rowIndex: number) {
    if (!draggedTemplateElementId) {
      return;
    }
    handleTemplateDropSlotDragOver(event, templateDropIndexForRow(event, rowIndex));
  }

  async function handleTemplateDropAtIndex(event: DragEvent<HTMLElement>, dropIndex: number) {
    event.preventDefault();
    const transferValue = event.dataTransfer.getData("text/template-element");
    const sourceId = transferValue ? Number(transferValue) : draggedTemplateElementId;
    if (!sourceId || Number.isNaN(sourceId)) {
      resetTemplateDragState();
      return;
    }
    const movedItem = orderedElements.find((item) => item.id === sourceId);
    const sourceIndex = orderedElements.findIndex((item) => item.id === sourceId);
    resetTemplateDragState();
    if (!movedItem) {
      return;
    }
    if (sourceIndex === -1) {
      return;
    }
    const nextOrdered = orderedElements.filter((item) => item.id !== sourceId);
    const rawIndex = Math.min(Math.max(dropIndex, 0), orderedElements.length);
    const targetIndex = rawIndex > sourceIndex ? rawIndex - 1 : rawIndex;
    if (targetIndex === sourceIndex) {
      return;
    }
    nextOrdered.splice(targetIndex, 0, movedItem);
    await persistTemplateOrder(nextOrdered, `Element auf Position ${targetIndex + 1} verschoben`);
  }

  async function handleTemplateRowDrop(event: DragEvent<HTMLElement>, rowIndex: number) {
    await handleTemplateDropAtIndex(event, templateDropIndexForRow(event, rowIndex));
  }

  async function deleteTemplateItem(templateElementId: number) {
    try {
      await browserApiFetch(`/api/template-elements/${templateElementId}`, { method: "DELETE" });
      setElements((current) => current.filter((item) => item.id !== templateElementId));
      showToast("Element removed from template", "success");
      router.refresh();
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Template element deletion failed", "error");
    }
  }

  return (
    <div className="grid">
      <article className="card">
        <DataToolbar title="Template settings" description="General information about this template and the document layout it uses." />
        <form className="grid" onSubmit={saveTemplate}>
          <label className="field-stack">
            <span className="field-label">Template name</span>
            <input value={templateMeta.name} onChange={(event) => setTemplateMeta((current) => ({ ...current, name: event.target.value }))} />
          </label>
          <label className="field-stack">
            <span className="field-label">Description</span>
            <textarea rows={4} value={templateMeta.description} onChange={(event) => setTemplateMeta((current) => ({ ...current, description: event.target.value }))} />
          </label>
          <div className="two-col">
            <label className="field-stack">
              <span className="field-label">Protocol number pattern</span>
              <input value={templateMeta.protocol_number_pattern} onChange={(event) => setTemplateMeta((current) => ({ ...current, protocol_number_pattern: event.target.value }))} placeholder="e.g. Sitzung {n}" />
              <span className="field-help">Beispiele: Sitzung [n], Sitzung [mm].[n_month], J[yy]-[n_year], V[n_cycle]. Eckige und geschweifte Klammern funktionieren beide.</span>
            </label>
            <label className="field-stack">
              <span className="field-label">Title pattern</span>
              <input value={templateMeta.title_pattern} onChange={(event) => setTemplateMeta((current) => ({ ...current, title_pattern: event.target.value }))} placeholder="e.g. Sitzung {n} - {date:DD.MM.YYYY}" />
              <span className="field-help">Used automatically when a new protocol is created and the title field is left empty.</span>
            </label>
          </div>
          <div className="two-col">
            <label className="field-stack">
              <span className="field-label">Cycle reset month</span>
              <input value={templateMeta.cycle_reset_month} onChange={(event) => setTemplateMeta((current) => ({ ...current, cycle_reset_month: event.target.value }))} type="number" min={1} max={12} />
            </label>
            <label className="field-stack">
              <span className="field-label">Cycle reset day</span>
              <input value={templateMeta.cycle_reset_day} onChange={(event) => setTemplateMeta((current) => ({ ...current, cycle_reset_day: event.target.value }))} type="number" min={1} max={31} />
              <span className="field-help">Example: 31.07 means the cycle resets after 31 July, so the next cycle starts on 01 August.</span>
            </label>
          </div>
          <div className="two-col">
            <label className="field-stack">
              <span className="field-label">Naechste Sitzung</span>
              <select value={templateMeta.next_event_id} onChange={(event) => setTemplateMeta((current) => ({ ...current, next_event_id: event.target.value }))}>
                <option value="">Nicht gesetzt</option>
                {availableEvents.map((event) => (
                  <option key={event.id} value={event.id}>
                    {formatDateRange(event.event_date, event.event_end_date)} - {event.title}
                  </option>
                ))}
              </select>
              <span className="field-help">Kann in Todos und spaeteren Blöcken als Marker verwendet werden.</span>
            </label>
            <label className="field-stack">
              <span className="field-label">Letzte Sitzung</span>
              <select value={templateMeta.last_event_id} onChange={(event) => setTemplateMeta((current) => ({ ...current, last_event_id: event.target.value }))}>
                <option value="">Nicht gesetzt</option>
                {availableEvents.map((event) => (
                  <option key={event.id} value={event.id}>
                    {formatDateRange(event.event_date, event.event_end_date)} - {event.title}
                  </option>
                ))}
              </select>
              <span className="field-help">Bleibt als Template-Kontext erhalten und ist nicht auf das heutige Datum bezogen.</span>
            </label>
          </div>
          <label className="field-stack">
            <span className="field-label">Todo-Termin-Tag</span>
            <select
              value={templateMeta.todo_due_event_tag}
              onChange={(event) => setTemplateMeta((current) => ({ ...current, todo_due_event_tag: event.target.value }))}
            >
              <option value="">Alle Termine</option>
              {Array.from(new Set(availableEvents.map((e) => e.tag).filter(Boolean))).sort().map((tag) => (
                <option key={tag} value={tag!}>{tag}</option>
              ))}
            </select>
            <span className="field-help">Nur Termine mit diesem Tag werden in der Todo-Fällig-Auswahl angezeigt. Leer = alle Termine.</span>
          </label>
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={templateMeta.auto_create_next_protocol}
              onChange={(event) =>
                setTemplateMeta((current) => ({ ...current, auto_create_next_protocol: event.target.checked }))
              }
            />
            <span>Naechstes Protokoll automatisch erstellen, sobald dieses Protokoll spaeter auf Abgeschlossen gesetzt wird.</span>
          </label>
          <div className="info-note">
            Kurzinfo: [n] zaehlt alle Protokolle, [n_year] pro Kalenderjahr, [n_month] pro Monat und [n_cycle] im eigenen Zyklus. Du kannst frei kombinieren, z. B. Sitzung [mm].[n_month] oder Protokoll [n_cycle]/[cycle_yyyy_end].
          </div>
          <div className="two-col">
            <label className="field-stack">
              <span className="field-label">PDF-Layout</span>
              <select
                value={templateMeta.document_template_id}
                onChange={(event) => setTemplateMeta((current) => ({ ...current, document_template_id: event.target.value }))}
              >
                <option value="">Kein Layout zugewiesen</option>
                {availableDocumentTemplates.filter((dt) => dt.is_active).map((dt) => (
                  <option key={dt.id} value={dt.id}>
                    {dt.name}{dt.is_default ? " (Standard)" : ""}
                  </option>
                ))}
              </select>
              <span className="field-help">Wird beim PDF-Export verwendet. Kann in den Einstellungen → Dokumentlayouts konfiguriert werden.</span>
            </label>
            <label className="field-stack">
              <span className="field-label">Template status</span>
              <select value={templateMeta.status} onChange={(event) => setTemplateMeta((current) => ({ ...current, status: event.target.value }))}>
                <option value="active">Active</option>
                <option value="archived">Archived</option>
              </select>
            </label>
          </div>
          <div className="table-toolbar-actions">
            <button type="submit" className="button-inline">Save template</button>
          </div>
        </form>
      </article>

      <article className="card">
        <div className="eyebrow">How templates work now</div>
        <p className="muted">Templates no longer build blocks themselves. They only choose ready-made elements from the Elements area and place them in order.</p>
      </article>

      <article className="card">
        <DataToolbar
          title="Teilnehmer im Template"
          description="Nur diese Teilnehmer sind spaeter im Protokoll auswählbar. Pro Person kannst du zusaetzlich festlegen, ob sie in der Anwesenheitskontrolle erscheinen soll."
          actions={
            <div className="table-toolbar-actions">
              <button type="button" className="button-inline" onClick={() => setShowParticipantModal(true)}>
                Teilnehmer waehlen
              </button>
            </div>
          }
        />
        <div className="status-row">
          <span className="pill">{assignedParticipantIds.length} ausgewaehlt</span>
          <span className="pill">{excludedAttendanceCount} ohne Anwesenheitskontrolle</span>
          <span className="pill">{availableParticipants.length} verfuegbar</span>
        </div>

        <Modal
          open={showParticipantModal}
          onClose={() => setShowParticipantModal(false)}
          title="Teilnehmer waehlen"
          description="Mit Haken legst du fest, wer in diesem Template im Protokoll auswählbar ist. Für ausgewählte Teilnehmer kannst du sie hier direkt aus der Anwesenheitskontrolle entfernen."
          size="fullscreen"
        >
          <div className="grid">
            <div className="table-toolbar-actions">
              <button
                type="button"
                className="button-ghost button-inline"
                onClick={() =>
                  setParticipantAssignments((current) => {
                    const currentAssignmentsById = new Map(current.map((assignment) => [assignment.participant_id, assignment]));
                    return allParticipantIds.map((participantId) => ({
                      participant_id: participantId,
                      exclude_from_attendance: currentAssignmentsById.get(participantId)?.exclude_from_attendance ?? false,
                    }));
                  })
                }
              >
                Alle auswaehlen
              </button>
            </div>
            <div className="selection-list">
              {availableParticipants.map((participant) => {
                const assignment = participantAssignmentsById.get(participant.id);
                const checked = Boolean(assignment);
                return (
                  <div key={participant.id} className={`selection-card selection-card-checkbox${checked ? " selection-card-active" : ""}`}>
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={(event) =>
                        setParticipantAssignments((current) =>
                          event.target.checked
                            ? current.some((entry) => entry.participant_id === participant.id)
                              ? current
                              : [...current, { participant_id: participant.id, exclude_from_attendance: false }]
                            : current.filter((entry) => entry.participant_id !== participant.id)
                        )
                      }
                    />
                    <div className="grid">
                      <strong>{participant.display_name}</strong>
                      <div className="muted">
                        {[participant.first_name, participant.last_name].filter(Boolean).join(" ") || participant.email || "Teilnehmer"}
                      </div>
                      {checked ? (
                        <label className="checkbox-row">
                          <input
                            type="checkbox"
                            checked={assignment?.exclude_from_attendance ?? false}
                            onChange={(event) =>
                              setParticipantAssignments((current) =>
                                current.map((entry) =>
                                  entry.participant_id === participant.id
                                    ? { ...entry, exclude_from_attendance: event.target.checked }
                                    : entry
                                )
                              )
                            }
                          />
                          <span>Aus Anwesenheitskontrolle entfernen</span>
                        </label>
                      ) : null}
                    </div>
                  </div>
                );
              })}
            </div>
            <div className="table-toolbar-actions table-actions-end">
              <button type="button" className="button-inline" onClick={() => void saveTemplateParticipants(true)}>
                Auswahl speichern
              </button>
            </div>
          </div>
        </Modal>
      </article>

      <article className="card">
        <DataToolbar
          title="Template elements"
          description="Templates only collect finished elements. Wiederholungen und Filter werden direkt in den Blöcken des Elements gepflegt."
          actions={
            <button type="button" className="button-inline" onClick={() => setShowCreateItem((current) => !current)}>
              {showCreateItem ? "Close create form" : "Add element"}
            </button>
          }
        />

        <div className="grid">
          <div className="three-col">
            <label className="field-stack">
              <span className="field-label">Namensanzeige</span>
              <select
                value={responsibilityNameMode}
                onChange={(event) => void applyResponsibilityNameMode(event.target.value as ResponsibleNameMode)}
              >
                <option value="display_name">Anzeigename</option>
                <option value="first_name">Vorname</option>
                <option value="last_name">Nachname</option>
              </select>
              <span className="field-help">Dieses Format wird für die Anzeige der Verantwortlichen hinter dem Elementtitel verwendet.</span>
            </label>
            <label className="field-stack">
              <span className="field-label">Initiale Zuordnung aus Liste</span>
              <select
                value={responsibilityAutoListId}
                onChange={(event) => {
                  const nextValue = event.target.value;
                  setResponsibilityAutoListId(nextValue);
                  if (nextValue) {
                    void autoAssignResponsiblesFromList(Number(nextValue));
                  }
                }}
              >
                <option value="">Keine Liste ausgewählt</option>
                {eligibleResponsibleLists.map((item) => (
                  <option key={item.definition.id} value={item.definition.id}>
                    {item.definition.name}
                  </option>
                ))}
              </select>
              <span className="field-help">Es werden nur Listen mit genau einer Textspalte und einer Teilnehmer-Spalte angeboten.</span>
            </label>
            <div className="table-toolbar-actions align-end">
              <button
                type="button"
                className="button-ghost button-inline"
                disabled={!responsibilityAutoListId}
                onClick={() => responsibilityAutoListId && void autoAssignResponsiblesFromList(Number(responsibilityAutoListId))}
              >
                Erneut abgleichen
              </button>
            </div>
          </div>
          <div className="info-note">
            Beim Listenabgleich wird der Freitext der Liste mit dem Elementtitel verglichen. Gefundene Teilnehmende werden einmalig übernommen. Mit dem Schloss fixierst du danach bei Bedarf die Verknüpfung auf eine konkrete Tabellenzeile.
          </div>
          <div className="status-row">
            <span className="pill">
              {orderedElements.filter((item) => parseResponsibilityConfig(item.configuration_json).assignments.length > 0).length} mit Verantwortlichen
            </span>
            <span className="pill">{eligibleResponsibleLists.length} passende Listen</span>
            {responsibilityAutoListId ? (
              <span className="pill">
                Auto-Liste: {eligibleResponsibleLists.find((item) => String(item.definition.id) === responsibilityAutoListId)?.definition.name ?? responsibilityAutoListId}
              </span>
            ) : null}
          </div>
        </div>

        <Modal
          open={showCreateItem}
          onClose={() => setShowCreateItem(false)}
          title="Add element to template"
          description="Waehle ein oder mehrere fertige Elemente aus und fuege sie gesammelt zum Template hinzu."
        >
          <form className="grid" onSubmit={addElementToTemplate}>
            <DataTable columns={["", "Element", "Typen", "Beschreibung", "Bloecke"]}>
              {initialDefinitions.map((definition) => {
                const checked = newItemForm.element_definition_ids.includes(String(definition.id));
                return (
                  <tr
                    key={definition.id}
                    className="table-row-clickable"
                    onClick={() =>
                      setNewItemForm((current) => ({
                        ...current,
                        element_definition_ids: checked
                          ? current.element_definition_ids.filter((id) => id !== String(definition.id))
                          : [...current.element_definition_ids, String(definition.id)],
                      }))
                    }
                  >
                    <td>
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => undefined}
                        aria-label={`Element ${definition.title} auswaehlen`}
                      />
                    </td>
                    <td>
                      <strong>{definition.title}</strong>
                    </td>
                    <td>{definitionTypeSummary(definition)}</td>
                    <td>{definition.description ?? "Keine Beschreibung"}</td>
                    <td>{definition.blocks.length}</td>
                  </tr>
                );
              })}
            </DataTable>
            <span className="field-help">Neue Elemente werden automatisch hinten angehaengt. Die Reihenfolge kannst du danach per Drag and Drop oder direkt ueber die Positionszahl anpassen.</span>
            <div className="table-toolbar-actions">
              <button type="submit" className="button-inline" disabled={newItemForm.element_definition_ids.length === 0}>Ausgewaehlte Elemente hinzufuegen</button>
            </div>
          </form>
        </Modal>

        <Modal
          open={!!responsibilityModalElement}
          onClose={() => setShowResponsibilityModalFor(null)}
          title={responsibilityModalElement ? `Verantwortliche für ${responsibilityModalElement.title}` : "Verantwortliche"}
          description="Weise diesem Element Teilnehmende zu, verknüpfe sie optional mit einer Listenzeile und fixiere Verbindungen bei Bedarf mit dem Schloss."
          size="fullscreen"
        >
          {responsibilityModalElement ? (() => {
            const responsibility = parseResponsibilityConfig(responsibilityModalElement.configuration_json);
            const assignments = responsibility.assignments;
            const availableManualEntries = manualLinkListMeta ? (listEntriesByListId[manualLinkListMeta.definition.id] ?? []) : [];
            return (
              <div className="grid section-stack">
                <article className="card">
                  <div className="eyebrow">Titelvorschau</div>
                  <h3>{currentResponsibilityTitle(responsibilityModalElement)}</h3>
                  <p className="muted">Wenn Verantwortliche gesetzt sind, werden sie später im Protokoll direkt hinter dem Elementtitel angezeigt.</p>
                  <div className="status-row">
                    <span className="pill">{assignments.length} zugewiesen</span>
                    <span className="pill">
                      Anzeige: {responsibilityNameMode === "display_name" ? "Anzeigename" : responsibilityNameMode === "first_name" ? "Vorname" : "Nachname"}
                    </span>
                  </div>
                </article>

                <article className="card">
                  <div className="eyebrow">Aktuelle Verantwortliche</div>
                  {assignments.length ? (
                    <div className="responsibility-list">
                      {assignments.map((assignment) => {
                        const participant = participantsById.get(assignment.participant_id);
                        const sourceLabel = assignment.list_definition_id
                          ? assignment.locked
                            ? "Fix mit Tabellenzeile verknüpft"
                            : "Aus Liste erkannt"
                          : "Manuell zugewiesen";
                        const lockTitle = responsibilityLinkTooltip(assignment);
                        return (
                          <div className="responsibility-card" key={`responsibility-${responsibilityModalElement.id}-${assignment.participant_id}`}>
                            <div className="responsibility-card-head">
                              <div>
                                <strong>{participantName(participant, responsibilityNameMode, assignment.participant_id)}</strong>
                                <div className="muted">{sourceLabel}</div>
                              </div>
                              <div className="responsibility-card-actions">
                                {assignment.list_definition_id && assignment.list_entry_id ? (
                                  <button
                                    type="button"
                                    className={`responsibility-lock-button${assignment.locked ? " responsibility-lock-button-active" : ""}`}
                                    title={lockTitle}
                                    onClick={() => void toggleResponsibilityLock(responsibilityModalElement.id, assignment.participant_id)}
                                  >
                                    {assignment.locked ? "🔒" : "🔓"}
                                  </button>
                                ) : null}
                                <button
                                  type="button"
                                  className="button-ghost button-inline"
                                  onClick={() => void toggleResponsibleParticipant(responsibilityModalElement.id, assignment.participant_id, false)}
                                >
                                  Entfernen
                                </button>
                              </div>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  ) : (
                    <div className="responsibility-empty">Noch keine Verantwortlichen gesetzt.</div>
                  )}
                </article>

                <article className="card">
                  <div className="eyebrow">Mit Tabellenzeile verknüpfen</div>
                  <div className="two-col">
                    <label className="field-stack">
                      <span className="field-label">Liste</span>
                      <select value={manualLinkListId} onChange={(event) => setManualLinkListId(event.target.value)}>
                        <option value="">Liste wählen</option>
                        {eligibleResponsibleLists.map((item) => (
                          <option key={`responsibility-list-${item.definition.id}`} value={item.definition.id}>
                            {item.definition.name}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className="field-stack">
                      <span className="field-label">Zeile</span>
                      <select
                        value={manualLinkEntryId}
                        onChange={(event) => setManualLinkEntryId(event.target.value)}
                        disabled={!manualLinkListMeta || loadingResponsibleListId === manualLinkListMeta.definition.id}
                      >
                        <option value="">
                          {!manualLinkListMeta
                            ? "Zuerst Liste wählen"
                            : loadingResponsibleListId === manualLinkListMeta.definition.id
                            ? "Zeilen werden geladen..."
                            : "Zeile wählen"}
                        </option>
                        {manualLinkListMeta
                          ? availableManualEntries.map((entry) => (
                              <option key={`responsibility-entry-${entry.id}`} value={entry.id}>
                                {rowOptionLabel(entry, manualLinkListMeta, participantsById, responsibilityNameMode)}
                              </option>
                            ))
                          : null}
                      </select>
                    </label>
                  </div>
                  <div className="table-toolbar-actions">
                    <button
                      type="button"
                      className="button-inline"
                      disabled={!manualLinkEntryId}
                      onClick={() => void linkElementToResponsibleRow()}
                    >
                      Zeile verknüpfen
                    </button>
                  </div>
                  <span className="field-help">Diese Aktion setzt die Teilnehmenden der gewählten Zeile für dieses Element und fixiert die Verbindung direkt über die Tabellenzeilen-ID.</span>
                </article>

                <article className="card">
                  <div className="eyebrow">Teilnehmende manuell zuweisen</div>
                  <label className="field-stack">
                    <span className="field-label">Suchen</span>
                    <input
                      value={responsibilitySearch}
                      onChange={(event) => setResponsibilitySearch(event.target.value)}
                      placeholder="Teilnehmer suchen"
                    />
                  </label>
                  <div className="selection-list selection-grid">
                    {filteredResponsibilityParticipants.map((participant) => {
                      const checked = isParticipantResponsible(responsibilityModalElement, participant.id);
                      const linkedAssignment = assignments.find((assignment) => assignment.participant_id === participant.id);
                      return (
                        <label
                          key={`responsibility-participant-${participant.id}`}
                          className={`selection-card selection-card-checkbox${checked ? " selection-card-active" : ""}`}
                        >
                          <input
                            type="checkbox"
                            checked={checked}
                            onChange={(event) => void toggleResponsibleParticipant(responsibilityModalElement.id, participant.id, event.target.checked)}
                          />
                          <div>
                            <strong>{participantName(participant, responsibilityNameMode, participant.id)}</strong>
                            <div className="muted">{participant.display_name}</div>
                            {linkedAssignment?.list_definition_id ? (
                              <div className="muted">{responsibilityLinkTooltip(linkedAssignment)}</div>
                            ) : null}
                          </div>
                        </label>
                      );
                    })}
                  </div>
                  {filteredResponsibilityParticipants.length === 0 ? (
                    <div className="responsibility-empty">Keine Teilnehmenden für den aktuellen Suchbegriff gefunden.</div>
                  ) : null}
                </article>
              </div>
            );
          })() : null}
        </Modal>

        <div
          className={`template-element-list${draggedTemplateElementId ? " template-element-list-dragging" : ""}`}
          onDragOver={(event) => event.preventDefault()}
        >
          {orderedElements.length === 0 && !draggedTemplateElementId ? (
            <div className="template-element-empty">Noch keine Elemente im Template.</div>
          ) : null}

          {orderedElements.map((item, index) => {
            const responsibility = parseResponsibilityConfig(item.configuration_json);
            const responsibilityCount = responsibility.assignments.length;
            const currentPosition = orderedElements.findIndex((entry) => entry.id === item.id) + 1;
            const displayGroups = responsibilityDisplayGroups(item);
            return (
              <div className="template-element-list-item" key={item.id}>
                <div
                  className={`template-element-drop-slot${activeTemplateDropIndex === index ? " template-element-drop-slot-active" : ""}${expandedTemplateDropIndex === index ? " template-element-drop-slot-expanded" : ""}`}
                  onDragOver={(event) => handleTemplateDropSlotDragOver(event, index)}
                  onDrop={(event) => void handleTemplateDropAtIndex(event, index)}
                />

                <div
                  className={`template-element-row${draggedTemplateElementId === item.id ? " template-element-row-dragging" : ""}`}
                  onDragOver={(event) => handleTemplateRowDragOver(event, index)}
                  onDrop={(event) => void handleTemplateRowDrop(event, index)}
                >
                  <button
                    type="button"
                    draggable
                    className="template-element-drag-handle"
                    onDragStart={(event) => handleTemplateDragStart(event, item.id)}
                    onDragEnd={handleTemplateDragEnd}
                    title="Ziehen zum Umordnen"
                    aria-label={`Element ${item.title} ziehen`}
                  >
                    ⋮⋮
                  </button>

                  <div className="template-element-row-copy">
                    <div className="template-element-row-copy-main">
                      <div className="template-element-title-line">
                        <strong>{item.title}</strong>
                        {displayGroups.length ? (
                          <span className="template-element-inline-responsibility">
                            (
                            {displayGroups.map((group, groupIndex) => (
                              <span className="template-element-inline-responsibility-group" key={`template-element-row-group-${item.id}-${group.key}`}>
                                {groupIndex > 0 ? <span className="template-element-inline-responsibility-separator">, </span> : null}
                                <span className="template-element-inline-responsibility-text">{group.names}</span>
                              </span>
                            ))}
                            )
                          </span>
                        ) : null}
                        {displayGroups.some((group) => group.listDefinitionId && group.listEntryId) ? (
                          <span className="template-element-inline-locks">
                            {displayGroups
                              .filter((group) => group.listDefinitionId && group.listEntryId)
                              .map((group) => (
                                <button
                                  key={`template-element-row-lock-${item.id}-${group.key}`}
                                  type="button"
                                  className={`template-element-inline-lock${group.locked ? " template-element-inline-lock-locked" : " template-element-inline-lock-unlocked"}`}
                                  title={group.tooltip}
                                  onClick={() => void toggleResponsibilityRowLock(item.id, group.listDefinitionId!, group.listEntryId!)}
                                >
                                  <ResponsibilityLockIcon locked={group.locked} />
                                </button>
                              ))}
                          </span>
                        ) : null}
                      </div>
                      {item.description ? <span className="muted">{item.description}</span> : null}
                    </div>
                  </div>

                  <div className="template-element-row-meta">
                    <span className="pill">{item.blocks.length} {item.blocks.length === 1 ? "Block" : "Blöcke"}</span>
                    {responsibilityCount ? <span className="pill">{responsibilityCount} Verantwortliche</span> : null}
                  </div>

                  <label className="table-order-field template-element-position-field">
                    <span className="muted">Pos.</span>
                    <input
                      type="number"
                      min={1}
                      max={orderedElements.length}
                      value={positionDrafts[item.id] ?? String(currentPosition)}
                      onChange={(event) =>
                        setPositionDrafts((current) => ({ ...current, [item.id]: event.target.value }))
                      }
                      onBlur={(event) => handlePositionSubmit(item.id, event.target.value)}
                      onKeyDown={(event: KeyboardEvent<HTMLInputElement>) => {
                        if (event.key === "Enter") {
                          event.preventDefault();
                          event.currentTarget.blur();
                        }
                        if (event.key === "Escape") {
                          event.preventDefault();
                          setPositionDrafts((current) => ({ ...current, [item.id]: String(currentPosition) }));
                        }
                      }}
                      aria-label={`Position für ${item.title}`}
                    />
                  </label>

                  <div className="template-element-row-actions">
                    <button
                      type="button"
                      className="button-inline button-ghost"
                      onClick={() => setShowResponsibilityModalFor(item.id)}
                    >
                      Verantwortliche
                    </button>
                    <button type="button" className="button-inline button-danger" onClick={() => void deleteTemplateItem(item.id)}>
                      Entfernen
                    </button>
                  </div>
                </div>
              </div>
            );
          })}

          {orderedElements.length > 0 ? (
            <div
              className={`template-element-drop-slot${activeTemplateDropIndex === orderedElements.length ? " template-element-drop-slot-active" : ""}${expandedTemplateDropIndex === orderedElements.length ? " template-element-drop-slot-expanded" : ""}`}
              onDragOver={(event) => handleTemplateDropSlotDragOver(event, orderedElements.length)}
              onDrop={(event) => void handleTemplateDropAtIndex(event, orderedElements.length)}
            />
          ) : null}
        </div>
      </article>
    </div>
  );
}
