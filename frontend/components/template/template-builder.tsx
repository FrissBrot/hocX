"use client";

import { useParticipantSelectable } from "@/contexts/participant-date-context";

import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { flushSync } from "react-dom";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";

import { DataTable } from "@/components/ui/data-table";
import { Modal, ModalSaveForm } from "@/components/ui/modal";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { SearchInput } from "@/components/ui/search-input";
import { browserApiFetch } from "@/lib/api/client";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { TemplateFineTariffModal } from "@/components/template/template-fine-tariff-modal";
import { SessionDesignView } from "@/components/template/session-design-view";
import { SessionTemplateWorkspace } from "@/components/template/session-template-studio";
import type { BlockEditorData } from "@/components/template/element-editor/block-editor";
import { Tabs } from "@/components/ui/tabs";
import { useTagConfig } from "@/lib/hooks/use-tag-config";
import { EligibleResponsibleList, eligibleResponsibleList, listParticipantIds, listTextValue } from "@/lib/utils/responsible-lists";
import {
  CycleConfigSummary,
  EventSummary,
  FinanceAccount,
  ParticipantSummary,
  StructuredListDefinition,
  StructuredListEntry,
  TemplateElement,
  TemplateSummary,
} from "@/types/api";

type TemplateBuilderProps = {
  initialTemplates: TemplateSummary[];
  availableCycleConfigs: CycleConfigSummary[];
  // Anlegen, Duplizieren, Archivieren und Löschen: nur Admins (Schreibende passen Vorlagen an)
  canManage?: boolean;
};

type TemplateEditorProps = {
  initialTemplate: TemplateSummary;
  initialElements: TemplateElement[];
  availableEvents: EventSummary[];
  availableParticipants: ParticipantSummary[];
  availableLists: StructuredListDefinition[];
  initialAssignedParticipants: ParticipantSummary[];
  availableCycleConfigs: CycleConfigSummary[];
  // Nur mit gebuchten Finanzen (sonst kein Bussentarif, siehe require_feature im Backend).
  financeAccounts?: FinanceAccount[] | null;
  // Einstellungen, Teilnehmende und Bussentarif: nur Admins; Traktanden und Gestaltung auch Schreibende
  canManage?: boolean;
  knownEventTags?: string[];
};

type StudioView = "editor" | "pdf" | "invitation";

type TFunc = (key: string, values?: Record<string, string | number | Date>) => string;

type TemplateCreateState = {
  name: string;
  description: string;
  next_event_id: string;
  last_event_id: string;
  protocol_number_pattern: string;
  title_pattern: string;
  auto_create_next_protocol: boolean;
  cycle_config_id: string;
};

type TemplateParticipantAssignmentState = {
  participant_id: string;
  exclude_from_attendance: boolean;
};

type ResponsibleNameMode = "display_name" | "first_name" | "last_name";

type ResponsibilityAssignment = {
  participant_id: string;
  list_definition_id: string | null;
  list_entry_id: string | null;
  locked: boolean;
};

type ResponsibilityConfig = {
  name_display_mode: ResponsibleNameMode;
  assignments: ResponsibilityAssignment[];
};

const initialTemplateCreate: TemplateCreateState = {
  name: "",
  description: "",
  next_event_id: "",
  last_event_id: "",
  protocol_number_pattern: "",
  title_pattern: "",
  auto_create_next_protocol: false,
  cycle_config_id: "",
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

function normalizeMatchText(value: string) {
  return value.trim().replace(/\s+/g, " ").toLowerCase();
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
      const participantId = typeof entry.participant_id === "string" ? entry.participant_id : null;
      const listDefinitionId = typeof entry.list_definition_id === "string" ? entry.list_definition_id : null;
      const listEntryId = typeof entry.list_entry_id === "string" ? entry.list_entry_id : null;
      if (!participantId) {
        return null;
      }
      return {
        participant_id: participantId,
        list_definition_id: listDefinitionId,
        list_entry_id: listEntryId,
        locked: Boolean(entry.locked ?? false),
      } satisfies ResponsibilityAssignment;
    })
    .filter((assignment): assignment is ResponsibilityAssignment => Boolean(assignment));
  const dedupedAssignments: ResponsibilityAssignment[] = [];
  const seenParticipantIds = new Set<string>();
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

function participantName(participant: ParticipantSummary | undefined, mode: ResponsibleNameMode, t: TFunc) {
  if (!participant) {
    return t("unknownParticipant");
  }
  if (mode === "first_name") {
    return participant.first_name?.trim() || participant.display_name;
  }
  if (mode === "last_name") {
    return participant.last_name?.trim() || participant.display_name;
  }
  return participant.display_name;
}

// Verantwortliche wie im Backend (responsible_label_service._resolve_ids_for_assignments):
// Zuweisungen mit Tabellenzeile lesen den aktuellen Wert der Zeile, sobald deren Einträge geladen
// sind; sonst (oder ohne Zeile) gilt die beim Zuweisen gespeicherte Person.
function liveResponsibleParticipantIds(
  assignments: ResponsibilityAssignment[],
  eligibleLists: EligibleResponsibleList[],
  listEntriesByListId: Record<string, StructuredListEntry[]>
) {
  const ids: string[] = [];
  for (const assignment of assignments) {
    let resolved = [assignment.participant_id];
    if (assignment.list_definition_id && assignment.list_entry_id) {
      const meta = eligibleLists.find((item) => item.definition.id === assignment.list_definition_id);
      const entry = listEntriesByListId[assignment.list_definition_id]?.find((item) => item.id === assignment.list_entry_id);
      if (meta && entry) {
        resolved = listParticipantIds(entry, meta.participantColumn, meta.participantValueType);
      }
    }
    for (const id of resolved) {
      if (!ids.includes(id)) ids.push(id);
    }
  }
  return ids;
}

function titleWithResponsibility(
  item: TemplateElement,
  participantsById: Map<string, ParticipantSummary>,
  fallbackMode: ResponsibleNameMode,
  eligibleLists: EligibleResponsibleList[],
  listEntriesByListId: Record<string, StructuredListEntry[]>,
  t: TFunc
) {
  const responsibility = parseResponsibilityConfig(item.configuration_json);
  const mode = responsibility.name_display_mode || fallbackMode;
  const names = liveResponsibleParticipantIds(responsibility.assignments, eligibleLists, listEntriesByListId)
    .map((participantId) => participantName(participantsById.get(participantId), mode, t))
    .filter(Boolean);
  return names.length ? `${item.title} (${names.join(", ")})` : item.title;
}

function rowOptionLabel(
  entry: StructuredListEntry,
  meta: EligibleResponsibleList,
  participantsById: Map<string, ParticipantSummary>,
  mode: ResponsibleNameMode,
  t: TFunc
) {
  const text = listTextValue(entry, meta.textColumn) || t("emptyRow");
  const names = listParticipantIds(entry, meta.participantColumn, meta.participantValueType)
    .map((participantId) => participantName(participantsById.get(participantId), mode, t))
    .filter(Boolean);
  return names.length ? `${text} -> ${names.join(", ")}` : text;
}

export function TemplateBuilder({ initialTemplates, availableCycleConfigs, canManage = true }: TemplateBuilderProps) {
  const router = useRouter();
  const t = useTranslations("templates.builder");
  const showToast = useToast();
  const confirm = useConfirm();
  const [templates, setTemplates] = useState(initialTemplates);
  const [form, setForm] = useState(initialTemplateCreate);
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [search, setSearch] = useState("");
  const [duplicateTarget, setDuplicateTarget] = useState<TemplateSummary | null>(null);
  const [duplicateName, setDuplicateName] = useState("");
  const [duplicateBusy, setDuplicateBusy] = useState(false);

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
          cycle_config_id: form.cycle_config_id ? form.cycle_config_id : null,
          version: 1,
          status: "active",
          created_by: null
        })
      });
      setTemplates((current) => [created, ...current]);
      setForm(initialTemplateCreate);
      setShowCreateForm(false);
      showToast(t("createdToast", { name: created.name }), "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("createFailedToast"), "error");
    }
  }

  async function deleteTemplate(templateId: string) {
    const ok = await confirm({
      message: t("deleteConfirm"),
      tone: "danger",
      confirmLabel: t("delete")
    });
    if (!ok) return;
    try {
      const deletedName = templates.find((template) => template.id === templateId)?.name ?? t("unnamed");
      await browserApiFetch(`/api/templates/${templateId}`, { method: "DELETE" });
      setTemplates((current) => current.filter((template) => template.id !== templateId));
      showToast(t("deletedToast", { name: deletedName }), "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("deleteFailedToast"), "error");
    }
  }

  async function toggleTemplateArchived(template: TemplateSummary) {
    const nextStatus = template.status === "archived" ? "active" : "archived";
    try {
      const updated = await browserApiFetch<TemplateSummary>(`/api/templates/${template.id}`, {
        method: "PATCH",
        body: JSON.stringify({ status: nextStatus }),
      });
      setTemplates((current) => current.map((item) => (item.id === updated.id ? updated : item)));
      showToast(nextStatus === "archived" ? t("archivedToast") : t("unarchivedToast"), "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("statusChangeFailedToast"), "error");
    }
  }

  function openDuplicate(template: TemplateSummary) {
    setDuplicateTarget(template);
    setDuplicateName(t("duplicateNameSuggestion", { name: template.name }));
  }

  async function submitDuplicate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!duplicateTarget) return;
    setDuplicateBusy(true);
    try {
      const created = await browserApiFetch<TemplateSummary>(`/api/templates/${duplicateTarget.id}/duplicate`, {
        method: "POST",
        body: JSON.stringify({ name: duplicateName }),
      });
      setTemplates((current) => [created, ...current]);
      setDuplicateTarget(null);
      showToast(t("duplicatedToast", { name: created.name }), "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("duplicateFailedToast"), "error");
    } finally {
      setDuplicateBusy(false);
    }
  }

  return (
    <div className="grid">
      <div className="page-header">
        <div>
          <h1 className="page-title">{t("pageTitle")}</h1>
          <p className="muted">{t("pageIntro")}</p>
        </div>
        {canManage ? (
          <button type="button" className={showCreateForm ? "button-ghost" : "button-primary"} onClick={() => setShowCreateForm((current) => !current)}>
            {showCreateForm ? t("cancel") : t("newTemplateButton")}
          </button>
        ) : null}
      </div>

      <Modal
        open={showCreateForm}
        onClose={() => setShowCreateForm(false)}
        title={t("createTitle")}
        description={t("createDescription")}
      >
        <ModalSaveForm className="grid" onSubmit={createTemplate}>
          <label className="field-stack">
            <span className="field-label">{t("nameLabel")}</span>
            <input value={form.name} onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))} placeholder={t("nameLabel")} required />
          </label>
          <label className="field-stack">
            <span className="field-label">{t("descriptionLabel")}</span>
            <textarea rows={4} value={form.description} onChange={(event) => setForm((current) => ({ ...current, description: event.target.value }))} placeholder={t("descriptionLabel")} />
          </label>
          <div className="two-col">
            <label className="field-stack">
              <span className="field-label">{t("protocolNumberPatternLabel")}</span>
              <input value={form.protocol_number_pattern} onChange={(event) => setForm((current) => ({ ...current, protocol_number_pattern: event.target.value }))} placeholder={t("protocolNumberPatternPlaceholder")} />
              <span className="field-help">{t("protocolNumberPatternHelp")}</span>
            </label>
            <label className="field-stack">
              <span className="field-label">{t("titlePatternLabel")}</span>
              <input value={form.title_pattern} onChange={(event) => setForm((current) => ({ ...current, title_pattern: event.target.value }))} placeholder={t("titlePatternPlaceholder")} />
              <span className="field-help">{t("titlePatternHelp")}</span>
            </label>
          </div>
          <label className="field-stack">
            <span className="field-label">{t("cycleLabel")}</span>
            <SearchableSelect
              options={availableCycleConfigs}
              getId={(cc) => cc.id}
              getLabel={(cc) => cc.name}
              value={form.cycle_config_id || null}
              onChange={(cc) => setForm((current) => ({ ...current, cycle_config_id: cc ? String(cc.id) : "" }))}
              nullLabel={t("noCycle")}
            />
            <span className="field-help">{t("cycleHelp")}</span>
          </label>
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={form.auto_create_next_protocol}
              onChange={(event) => setForm((current) => ({ ...current, auto_create_next_protocol: event.target.checked }))}
            />
            <span>{t("autoCreateNextProtocolLabel")}</span>
          </label>
          <div className="info-note">
            {t("patternTokensHelp")}
          </div>
          <div className="table-toolbar-actions">
            <button data-modal-save type="submit" className="button-secondary">{t("createSubmit")}</button>
          </div>
        </ModalSaveForm>
      </Modal>

      <div className="list-filter-row">
        <div />
        <div className="list-filter-search">
          <SearchInput value={search} onChange={setSearch} placeholder={t("searchPlaceholder")} />
        </div>
      </div>

      <DataTable className="data-table-lg" columns={canManage ? [t("colTemplate"), t("colDescription"), t("colVersion"), t("colActions")] : [t("colTemplate"), t("colDescription"), t("colVersion")]}>
        {filteredTemplates.map((template) => (
          <tr key={template.id} className="table-row-clickable" onClick={() => router.push(`/templates/${template.id}`)}>
            <td>
              <strong>{template.name}</strong>
              <div className="muted">{template.status === "archived" ? t("archived") : t("active")}</div>
            </td>
            <td className="table-cell-wrap">{template.description ?? t("noDescription")}</td>
            <td>{template.version}</td>
            {canManage ? (
            <td>
              <div className="table-actions">
                <button
                  type="button"
                  className="button-secondary button-ghost"
                  onClick={(event) => {
                    event.stopPropagation();
                    openDuplicate(template);
                  }}
                >
                  {t("duplicate")}
                </button>
                <button
                  type="button"
                  className="button-secondary button-ghost"
                  onClick={(event) => {
                    event.stopPropagation();
                    void toggleTemplateArchived(template);
                  }}
                >
                  {template.status === "archived" ? t("unarchive") : t("archive")}
                </button>
                <button type="button" className="button-secondary button-danger" onClick={(event) => {
                  event.stopPropagation();
                  void deleteTemplate(template.id);
                }}>{t("delete")}</button>
              </div>
            </td>
            ) : null}
          </tr>
        ))}
      </DataTable>

      <Modal
        open={duplicateTarget !== null}
        onClose={() => setDuplicateTarget(null)}
        title={duplicateTarget ? t("duplicateTitleNamed", { name: duplicateTarget.name }) : t("duplicateTitle")}
        description={t("duplicateDescription")}
      >
        <ModalSaveForm className="grid" onSubmit={submitDuplicate}>
          <label className="field-stack">
            <span className="field-label">{t("newNameLabel")}</span>
            <input value={duplicateName} onChange={(event) => setDuplicateName(event.target.value)} required />
          </label>
          <div className="table-toolbar-actions">
            <button data-modal-save type="submit" className="button-secondary" disabled={duplicateBusy}>
              {duplicateBusy ? t("duplicating") : t("duplicate")}
            </button>
          </div>
        </ModalSaveForm>
      </Modal>
    </div>
  );
}

export function TemplateEditor({
  initialTemplate,
  initialElements,
  availableEvents,
  availableParticipants,
  availableLists,
  initialAssignedParticipants,
  availableCycleConfigs,
  financeAccounts = null,
  canManage = true,
  knownEventTags = [],
}: TemplateEditorProps) {
  const router = useRouter();
  const isParticipantSelectable = useParticipantSelectable();
  const t = useTranslations("templates.editor");
  const tStudio = useTranslations("templates.studio");
  const showToast = useToast();
  const { tagConfig } = useTagConfig();
  const [view, setView] = useState<StudioView>("editor");
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
    cycle_config_id: initialTemplate.cycle_config_id ? String(initialTemplate.cycle_config_id) : "",
  });
  const [showParticipantModal, setShowParticipantModal] = useState(false);
  const [participantPickerSearch, setParticipantPickerSearch] = useState("");
  const [showSettingsModal, setShowSettingsModal] = useState(false);
  const [showFineTariffModal, setShowFineTariffModal] = useState(false);
  const [showAutoAssignModal, setShowAutoAssignModal] = useState(false);
  const [showResponsibilityModalFor, setShowResponsibilityModalFor] = useState<string | null>(null);
  const [responsibilityAutoListId, setResponsibilityAutoListId] = useState("");
  const [responsibilityNameMode, setResponsibilityNameMode] = useState<ResponsibleNameMode>(() => {
    const firstConfiguredElement = initialElements.find((item) => Array.isArray((item.configuration_json?.responsibility as { assignments?: unknown } | undefined)?.assignments));
    return parseResponsibilityConfig(firstConfiguredElement?.configuration_json ?? {}).name_display_mode;
  });
  const [listEntriesByListId, setListEntriesByListId] = useState<Record<string, StructuredListEntry[]>>({});
  const [loadingResponsibleListId, setLoadingResponsibleListId] = useState<string | null>(null);
  const [responsibilitySearch, setResponsibilitySearch] = useState("");
  const [manualLinkListId, setManualLinkListId] = useState("");
  const [manualLinkEntryId, setManualLinkEntryId] = useState("");
  // Guards applyResponsibilityNameMode/autoAssignResponsiblesFromList, both of which await a
  // sequential per-element PATCH loop - without this, a second click while the first sequence
  // is still running could interleave two overlapping save sequences against the same elements.
  const [bulkAssignBusy, setBulkAssignBusy] = useState(false);
  const [participantAssignments, setParticipantAssignments] = useState<TemplateParticipantAssignmentState[]>(
    () => normalizeTemplateParticipantAssignments(initialAssignedParticipants)
  );

  const participantsById = useMemo(
    () => new Map(availableParticipants.map((participant) => [participant.id, participant])),
    [availableParticipants]
  );
  const allParticipantIds = useMemo(
    () => availableParticipants.filter((participant) => participant.is_active && isParticipantSelectable(participant)).map((participant) => participant.id),
    [availableParticipants, isParticipantSelectable]
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
  const filteredPickerParticipants = useMemo(() => {
    const query = participantPickerSearch.trim().toLowerCase();
    if (!query) {
      return availableParticipants.filter(isParticipantSelectable);
    }
    return availableParticipants.filter(isParticipantSelectable).filter((participant) => {
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
  }, [availableParticipants, participantPickerSearch, isParticipantSelectable]);
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
  // Monotonic sequence guard for persistTemplateOrder: fast repeated drag/drop or position
  // edits can start a new reorder before an in-flight one's PATCH requests resolve. Only the
  // response belonging to the most-recently-started call is allowed to commit `elements`, so a
  // slow, now-stale response can never clobber a newer order that already landed.
  const templateOrderSeqRef = useRef(0);
  const filteredResponsibilityParticipants = useMemo(() => {
    const query = responsibilitySearch.trim().toLowerCase();
    return availableParticipants.filter(isParticipantSelectable)
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
  }, [availableParticipants, responsibilitySearch, isParticipantSelectable]);
  const manualLinkListMeta = useMemo(
    () => eligibleResponsibleLists.find((item) => String(item.definition.id) === manualLinkListId) ?? null,
    [eligibleResponsibleLists, manualLinkListId]
  );
  // Daten für den Baustein-Dialog (Spalten, Zeilen, Terminfilter, Listen)
  const blockEditorData: BlockEditorData = {
    participants: availableParticipants,
    events: availableEvents,
    lists: availableLists,
    listEntries: listEntriesByListId,
    ensureListEntries: (listId: string) => void ensureResponsibleListEntries(listId),
    knownEventTags,
    tagConfig,
    accounts: financeAccounts ?? [],
    cycleConfigs: availableCycleConfigs,
  };

  useEffect(() => {
    if (!showResponsibilityModalFor || !responsibilityModalElement) {
      setResponsibilitySearch("");
      setManualLinkListId("");
      setManualLinkEntryId("");
      return;
    }
    const firstLinkedListId =
      parseResponsibilityConfig(responsibilityModalElement.configuration_json).assignments.find((assignment) => assignment.list_definition_id)?.list_definition_id
      ?? (responsibilityAutoListId || null)
      ?? eligibleResponsibleLists[0]?.definition.id
      ?? null;
    setManualLinkListId(firstLinkedListId ?? "");
    setManualLinkEntryId("");
    setResponsibilitySearch("");
  }, [showResponsibilityModalFor, responsibilityAutoListId, eligibleResponsibleLists]);

  useEffect(() => {
    if (!manualLinkListId) {
      setManualLinkEntryId("");
      return;
    }
    const listDefinitionId = manualLinkListId;
    if (!listDefinitionId) {
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
          .filter((value): value is string => Boolean(value))
      )
    );
    listDefinitionIds.forEach((listDefinitionId) => {
      void ensureResponsibleListEntries(listDefinitionId);
    });
  }, [responsibilityModalElement]);

  // Tabellen hinter den Verantwortlichen aller Traktanden: beim Öffnen und bei jeder Rückkehr in
  // den Tab frisch laden, damit die Namen Änderungen an der Tabelle folgen (wie im Protokoll).
  const responsibleListIdsKey = useMemo(
    () =>
      Array.from(
        new Set(
          elements.flatMap((item) =>
            parseResponsibilityConfig(item.configuration_json).assignments
              .filter((assignment) => assignment.list_definition_id && assignment.list_entry_id)
              .map((assignment) => assignment.list_definition_id as string)
          )
        )
      )
        .sort()
        .join(","),
    [elements]
  );

  useEffect(() => {
    const listIds = responsibleListIdsKey ? responsibleListIdsKey.split(",") : [];
    if (listIds.length === 0) return;
    let cancelled = false;
    async function reload() {
      const loaded = await Promise.all(
        listIds.map((listId) =>
          browserApiFetch<StructuredListEntry[]>(`/api/lists/${listId}/entries`)
            .then((entries) => [listId, entries ?? []] as const)
            .catch(() => null) // best-effort: bis zum nächsten Laden gilt die gespeicherte Person
        )
      );
      if (cancelled) return;
      setListEntriesByListId((current) => {
        const next = { ...current };
        for (const item of loaded) if (item) next[item[0]] = item[1];
        return next;
      });
    }
    function onVisibility() {
      if (document.visibilityState === "visible") void reload();
    }
    void reload();
    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener("focus", onVisibility);
    return () => {
      cancelled = true;
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("focus", onVisibility);
    };
  }, [responsibleListIdsKey]);

  async function ensureResponsibleListEntries(listDefinitionId: string) {
    if (listEntriesByListId[listDefinitionId]) {
      return listEntriesByListId[listDefinitionId];
    }
    setLoadingResponsibleListId(listDefinitionId);
    try {
      const entries = await browserApiFetch<StructuredListEntry[]>(`/api/lists/${listDefinitionId}/entries`);
      setListEntriesByListId((current) => ({ ...current, [listDefinitionId]: entries ?? [] }));
      return entries ?? [];
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("listEntriesLoadFailed"), "error");
      return [];
    } finally {
      setLoadingResponsibleListId((current) => (current === listDefinitionId ? null : current));
    }
  }

  async function patchTemplateElementConfiguration(templateElementId: string, configurationJson: Record<string, unknown>) {
    const updated = await browserApiFetch<TemplateElement>(`/api/template-elements/${templateElementId}`, {
      method: "PATCH",
      body: JSON.stringify({ configuration_json: configurationJson }),
    });
    setElements((current) => current.map((item) => (item.id === updated.id ? updated : item)));
    return updated;
  }

  async function saveElementResponsibility(
    templateElementId: string,
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
    return titleWithResponsibility(item, participantsById, responsibilityNameMode, eligibleResponsibleLists, listEntriesByListId, t);
  }

  async function applyResponsibilityNameMode(nextMode: ResponsibleNameMode) {
    if (bulkAssignBusy) return;
    setResponsibilityNameMode(nextMode);
    const itemsToUpdate = orderedElements.filter((item) => {
      const currentResponsibility = parseResponsibilityConfig(item.configuration_json);
      return currentResponsibility.assignments.length > 0 || "responsibility" in item.configuration_json;
    });
    if (!itemsToUpdate.length) {
      showToast(t("nameFormatSetToast"), "success");
      return;
    }
    setBulkAssignBusy(true);
    try {
      for (const item of itemsToUpdate) {
        await saveElementResponsibility(item.id, (current) => ({
          ...current,
          name_display_mode: nextMode,
        }));
      }
      showToast(t("nameFormatSavedToast"), "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("nameFormatSaveFailed"), "error");
    } finally {
      setBulkAssignBusy(false);
    }
  }

  async function autoAssignResponsiblesFromList(listDefinitionId: string, targetItems: TemplateElement[] = orderedElements) {
    if (bulkAssignBusy) return;
    const listMeta = eligibleResponsibleLists.find((item) => item.definition.id === listDefinitionId);
    if (!listMeta) {
      return;
    }
    setResponsibilityAutoListId(String(listDefinitionId));
    setBulkAssignBusy(true);
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
        const matchedParticipantIds = new Set<string>();
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
        showToast(t("autoAssignedToast", { count: matchedElementCount }), "success");
      }
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("autoAssignmentSaveFailed"), "error");
    } finally {
      setBulkAssignBusy(false);
    }
  }

  async function toggleResponsibleParticipant(templateElementId: string, participantId: string, enabled: boolean) {
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
      showToast(enabled ? t("responsibleAssignedToast") : t("responsibleRemovedToast"), "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("responsibleUpdateFailed"), "error");
    }
  }

  async function toggleResponsibilityLock(templateElementId: string, participantId: string) {
    try {
      await saveElementResponsibility(templateElementId, (current) => ({
        name_display_mode: responsibilityNameMode,
        assignments: current.assignments.map((assignment) =>
          assignment.participant_id === participantId && assignment.list_definition_id && assignment.list_entry_id
            ? { ...assignment, locked: !assignment.locked }
            : assignment
        ),
      }));
      showToast(t("tableLinkUpdatedToast"), "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("tableLinkUpdateFailed"), "error");
    }
  }


  async function linkElementToResponsibleRow() {
    if (!responsibilityModalElement || !manualLinkListMeta || !manualLinkEntryId) {
      return;
    }
    const entryId = manualLinkEntryId;
    const listDefinitionId = manualLinkListMeta.definition.id;
    try {
      const entries = await ensureResponsibleListEntries(listDefinitionId);
      const selectedEntry = entries.find((entry) => entry.id === entryId);
      if (!selectedEntry) {
        showToast(t("tableRowNotFoundToast"), "error");
        return;
      }
      const participantIds = listParticipantIds(selectedEntry, manualLinkListMeta.participantColumn, manualLinkListMeta.participantValueType);
      if (!participantIds.length) {
        showToast(t("tableRowNoParticipantsToast"), "error");
        return;
      }
      await saveElementResponsibility(responsibilityModalElement.id, (current) => {
        const nextAssignmentsByParticipant = new Map<string, ResponsibilityAssignment>();
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
      showToast(t("elementLinkedToRowToast"), "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("tableRowLinkSaveFailed"), "error");
    }
  }

  function responsibilityLinkTooltip(assignment: ResponsibilityAssignment) {
    if (!assignment.list_definition_id || !assignment.list_entry_id) {
      return "";
    }
    const listMeta = eligibleResponsibleLists.find((item) => item.definition.id === assignment.list_definition_id);
    const listName = listMeta?.definition.name ?? t("unknownList");
    const linkedEntry = listEntriesByListId[assignment.list_definition_id]?.find((entry) => entry.id === assignment.list_entry_id);
    const rowLabel = linkedEntry && listMeta
      ? listTextValue(linkedEntry, listMeta.textColumn) || t("emptyRow")
      : t("unknownRow");
    return `${listName} · ${rowLabel}`;
  }


  function isParticipantResponsible(templateElement: TemplateElement, participantId: string) {
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
          next_event_id: templateMeta.next_event_id ? templateMeta.next_event_id : null,
          last_event_id: templateMeta.last_event_id ? templateMeta.last_event_id : null,
          todo_due_event_tag: templateMeta.todo_due_event_tag || null,
          protocol_number_pattern: templateMeta.protocol_number_pattern || null,
          title_pattern: templateMeta.title_pattern || null,
          auto_create_next_protocol: templateMeta.auto_create_next_protocol,
          cycle_config_id: templateMeta.cycle_config_id ? templateMeta.cycle_config_id : null,
        })
      });
      setTemplate(updated);
      showToast(t("templateSavedToast"), "success");
      setShowSettingsModal(false);
      router.refresh();
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("templateSaveFailed"), "error");
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
      showToast(t("participantAssignmentsSavedToast"), "success");
      router.refresh();
      if (closeAfter) {
        setShowParticipantModal(false);
      }
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("participantAssignmentsSaveFailed"), "error");
    }
  }

  async function persistTemplateOrder(nextOrdered: TemplateElement[], successMessage: string) {
    const seq = ++templateOrderSeqRef.current;
    const previousElements = elements;
    const previousSortIndexById = new Map(previousElements.map((item) => [item.id, item.sort_index]));
    const resequenced = resequenceTemplateElements(nextOrdered);
    flushSync(() => {
      setElements([...resequenced].sort((left, right) => left.sort_index - right.sort_index));
    });
    const changedItems = resequenced.filter((item) => previousSortIndexById.get(item.id) !== item.sort_index);
    if (changedItems.length === 0) {
      return true;
    }
    try {
      await Promise.all(
        changedItems.map((item, index) =>
          browserApiFetch<TemplateElement>(`/api/template-elements/${item.id}`, {
            method: "PATCH",
            body: JSON.stringify({ sort_index: 1000000 + index })
          })
        )
      );
      const updatedItems = await Promise.all(
        changedItems.map((item) =>
          browserApiFetch<TemplateElement>(`/api/template-elements/${item.id}`, {
            method: "PATCH",
            body: JSON.stringify({ sort_index: item.sort_index })
          })
        )
      );
      // A newer reorder has since started and already applied its own optimistic + server
      // state - let it own `elements` from here on, this stale response must not overwrite it.
      if (seq !== templateOrderSeqRef.current) {
        return true;
      }
      setElements((current) => {
        const byId = new Map(current.map((item) => [item.id, item]));
        for (const updated of updatedItems) {
          byId.set(updated.id, updated);
        }
        return Array.from(byId.values()).sort((left, right) => left.sort_index - right.sort_index);
      });
      showToast(successMessage, "success");
      router.refresh();
      return true;
    } catch (error) {
      if (seq === templateOrderSeqRef.current) {
        setElements(previousElements);
      }
      showToast(error instanceof Error ? error.message : t("orderSaveFailed"), "error");
      return false;
    }
  }

  return (
    <div className="session-studio">
      <div className="page-header">
        <div>
          <h1 className="page-title">{template.name}</h1>
          <p className="muted">{tStudio("intro")}</p>
        </div>
        <div className="table-toolbar-actions">
          <button type="button" className="button-ghost button-secondary" onClick={() => setShowAutoAssignModal(true)}>
            {tStudio("responsibleMapping")}
          </button>
          {canManage ? (
            <>
              <button type="button" className="button-ghost button-secondary" onClick={() => setShowSettingsModal(true)}>
                {tStudio("settings")}
              </button>
              <button type="button" className="button-ghost button-secondary" onClick={() => setShowParticipantModal(true)}>
                {tStudio("participants")}
              </button>
              {financeAccounts ? (
                <button type="button" className="button-ghost button-secondary" onClick={() => setShowFineTariffModal(true)}>
                  {t("fineTariff.button")}
                </button>
              ) : null}
            </>
          ) : null}
        </div>
      </div>
      <Tabs
        activeId={view}
        onChange={(id) => setView(id as StudioView)}
        tabs={[
          {
            id: "editor",
            label: tStudio("view.editor"),
            content: (
              <SessionTemplateWorkspace
                templateId={template.id}
                elements={elements}
                onElementsChange={setElements}
                onReorder={(next) => persistTemplateOrder(next, t("orderSavedToast"))}
                onOpenResponsibility={(elementId) => setShowResponsibilityModalFor(elementId)}
                responsibilityTitle={currentResponsibilityTitle}
                blockEditorData={blockEditorData}
                cycleConfigs={availableCycleConfigs}
              />
            ),
          },
          { id: "pdf", label: tStudio("view.pdf"), content: view === "pdf" ? <SessionDesignView sessionTemplate={template} documentType="protocol" /> : null },
          { id: "invitation", label: tStudio("view.invitation"), content: view === "invitation" ? <SessionDesignView sessionTemplate={template} documentType="invitation" /> : null },
        ]}
      />

      {financeAccounts ? (
        <TemplateFineTariffModal
          open={showFineTariffModal}
          templateId={template.id}
          accounts={financeAccounts}
          onClose={() => setShowFineTariffModal(false)}
        />
      ) : null}

      <Modal
        open={showSettingsModal}
        onClose={() => setShowSettingsModal(false)}
        title={t("settingsTitle")}
        description={t("settingsDescription")}
        size="wide"
      >
        <ModalSaveForm className="grid" onSubmit={saveTemplate}>
          <label className="field-stack">
            <span className="field-label">{t("nameLabel")}</span>
            <input value={templateMeta.name} onChange={(event) => setTemplateMeta((current) => ({ ...current, name: event.target.value }))} />
          </label>
          <label className="field-stack">
            <span className="field-label">{t("descriptionLabel")}</span>
            <textarea rows={4} value={templateMeta.description} onChange={(event) => setTemplateMeta((current) => ({ ...current, description: event.target.value }))} />
          </label>
          <div className="two-col">
            <label className="field-stack">
              <span className="field-label">{t("protocolNumberPatternLabel")}</span>
              <input value={templateMeta.protocol_number_pattern} onChange={(event) => setTemplateMeta((current) => ({ ...current, protocol_number_pattern: event.target.value }))} placeholder={t("protocolNumberPatternPlaceholder")} />
              <span className="field-help">{t("protocolNumberPatternHelp")}</span>
            </label>
            <label className="field-stack">
              <span className="field-label">{t("titlePatternLabel")}</span>
              <input value={templateMeta.title_pattern} onChange={(event) => setTemplateMeta((current) => ({ ...current, title_pattern: event.target.value }))} placeholder={t("titlePatternPlaceholder")} />
              <span className="field-help">{t("titlePatternHelp")}</span>
            </label>
          </div>
          <label className="field-stack">
            <span className="field-label">{t("cycleLabel")}</span>
            <SearchableSelect
              options={availableCycleConfigs}
              getId={(cc) => cc.id}
              getLabel={(cc) => cc.name}
              value={templateMeta.cycle_config_id || null}
              onChange={(cc) => setTemplateMeta((current) => ({ ...current, cycle_config_id: cc ? String(cc.id) : "" }))}
              nullLabel={t("noCycle")}
            />
            <span className="field-help">{t("cycleHelp")}</span>
          </label>
          <label className="field-stack">
            <span className="field-label">{t("todoEventTagLabel")}</span>
            <SearchableSelect
              options={Array.from(new Set(availableEvents.map((e) => e.tag).filter((tag): tag is string => Boolean(tag)))).sort()}
              getId={(tag) => tag}
              getLabel={(tag) => tag}
              value={templateMeta.todo_due_event_tag || null}
              onChange={(tag) => setTemplateMeta((current) => ({ ...current, todo_due_event_tag: tag ?? "" }))}
              nullLabel={t("allEvents")}
            />
            <span className="field-help">{t("todoEventTagHelp")}</span>
          </label>
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={templateMeta.auto_create_next_protocol}
              onChange={(event) =>
                setTemplateMeta((current) => ({ ...current, auto_create_next_protocol: event.target.checked }))
              }
            />
            <span>{t("autoCreateNextProtocolLabel")}</span>
          </label>
          <div className="info-note">
            {t("patternTokensInfo")}
          </div>
          <div className="table-toolbar-actions">
            <button data-modal-save type="submit" className="button-secondary">{t("saveTemplate")}</button>
          </div>
        </ModalSaveForm>
      </Modal>

      <Modal
        open={showParticipantModal}
        onClose={() => setShowParticipantModal(false)}
        title={t("chooseParticipantsTitle")}
        description={t("chooseParticipantsDescription")}
        size="fullscreen"
      >
        <div className="grid">
          <label className="field-stack">
            <span className="field-label">{t("searchLabel")}</span>
            <SearchInput value={participantPickerSearch} onChange={setParticipantPickerSearch} placeholder={t("searchParticipantsPlaceholder")} autoFocus />
          </label>
          <div className="status-row">
            <span className="pill">{assignedParticipantIds.length} ausgewaehlt</span>
            <span className="pill">{excludedAttendanceCount} ohne Anwesenheitskontrolle</span>
            <span className="pill">{filteredPickerParticipants.length} sichtbar</span>
          </div>
          <div className="table-toolbar-actions">
            <button
              type="button"
              className="button-ghost button-secondary"
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
            {filteredPickerParticipants.map((participant) => {
              const assignment = participantAssignmentsById.get(participant.id);
              const checked = Boolean(assignment);
              return (
                <label key={participant.id} className={`selection-card selection-card-checkbox${checked ? " selection-card-active" : ""}`}>
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
                  <div>
                    <strong>{participant.display_name}</strong>
                    <div className="muted">
                      {[participant.first_name, participant.last_name].filter(Boolean).join(" ") || participant.email || t("participantFallback")}
                    </div>
                    {checked ? (
                      <span className="checkbox-row" onClick={(event) => event.stopPropagation()}>
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
                        <span>{t("removeFromAttendance")}</span>
                      </span>
                    ) : null}
                  </div>
                </label>
              );
            })}
          </div>
          <div className="table-toolbar-actions table-actions-end">
            <button type="button" className="button-secondary" onClick={() => void saveTemplateParticipants(true)}>
              Auswahl speichern
            </button>
          </div>
        </div>
      </Modal>

      <Modal
        open={showAutoAssignModal}
        onClose={() => setShowAutoAssignModal(false)}
        title={t("responsibilityTitle")}
        description={t("responsibilityDescription")}
        size="wide"
      >
        <div className="grid">
          <div className="three-col">
            <label className="field-stack">
              <span className="field-label">{t("nameDisplayLabel")}</span>
              <select
                value={responsibilityNameMode}
                disabled={bulkAssignBusy}
                onChange={(event) => void applyResponsibilityNameMode(event.target.value as ResponsibleNameMode)}
              >
                <option value="display_name">{t("displayNameOption")}</option>
                <option value="first_name">{t("firstNameOption")}</option>
                <option value="last_name">{t("lastNameOption")}</option>
              </select>
              <span className="field-help">{t("nameDisplayHelp")}</span>
            </label>
            <label className="field-stack">
              <span className="field-label">{t("initialListAssignmentLabel")}</span>
              <SearchableSelect
                options={eligibleResponsibleLists}
                getId={(item) => item.definition.id}
                getLabel={(item) => item.definition.name}
                value={responsibilityAutoListId || null}
                disabled={bulkAssignBusy}
                onChange={(item) => {
                  const nextValue = item ? item.definition.id : "";
                  setResponsibilityAutoListId(nextValue);
                  if (nextValue) {
                    void autoAssignResponsiblesFromList(nextValue);
                  }
                }}
                nullLabel={t("noListSelected")}
              />
              <span className="field-help">{t("initialListAssignmentHelp")}</span>
            </label>
            <div className="table-toolbar-actions align-end">
              <button
                type="button"
                className="button-ghost button-secondary"
                disabled={!responsibilityAutoListId || bulkAssignBusy}
                onClick={() => responsibilityAutoListId && void autoAssignResponsiblesFromList(responsibilityAutoListId)}
              >
                {bulkAssignBusy ? "…" : t("reconcile")}
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
                {t("autoListLabel", { name: eligibleResponsibleLists.find((item) => String(item.definition.id) === responsibilityAutoListId)?.definition.name ?? t("unknownList") })}
              </span>
            ) : null}
          </div>
        </div>
      </Modal>

      <Modal
        open={!!responsibilityModalElement}
        onClose={() => setShowResponsibilityModalFor(null)}
        title={responsibilityModalElement ? t("responsibleForNamed", { title: responsibilityModalElement.title }) : t("responsibleTitle")}
        description={t("assignResponsibilityDescription")}
        size="fullscreen"
      >
        {responsibilityModalElement ? (() => {
          const responsibility = parseResponsibilityConfig(responsibilityModalElement.configuration_json);
          const assignments = responsibility.assignments;
          const availableManualEntries = manualLinkListMeta ? (listEntriesByListId[manualLinkListMeta.definition.id] ?? []) : [];
          return (
            <div className="grid section-stack">
              <article className="card">
                <div className="eyebrow">{t("titlePreviewLabel")}</div>
                <h3>{currentResponsibilityTitle(responsibilityModalElement)}</h3>
                <p className="muted">{t("titlePreviewHelp")}</p>
                <div className="status-row">
                  <span className="pill">{assignments.length} zugewiesen</span>
                  <span className="pill">
                    {t("displayModeLabel", { mode: responsibilityNameMode === "display_name" ? t("displayNameOption") : responsibilityNameMode === "first_name" ? t("firstNameOption") : t("lastNameOption") })}
                  </span>
                </div>
              </article>

              <article className="card">
                <div className="eyebrow">{t("currentResponsibleLabel")}</div>
                {assignments.length ? (
                  <div className="responsibility-list">
                    {assignments.map((assignment) => {
                      const participant = participantsById.get(assignment.participant_id);
                      const sourceLabel = assignment.list_definition_id
                        ? assignment.locked
                          ? t("linkedFixedToRow")
                          : t("detectedFromList")
                        : t("assignedManually");
                      const lockTitle = responsibilityLinkTooltip(assignment);
                      return (
                        <div className="responsibility-card" key={`responsibility-${responsibilityModalElement.id}-${assignment.participant_id}`}>
                          <div className="responsibility-card-head">
                            <div>
                              <strong>{participantName(participant, responsibilityNameMode, t)}</strong>
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
                                className="button-ghost button-secondary"
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
                  <div className="responsibility-empty">{t("noResponsibleYet")}</div>
                )}
              </article>

              <article className="card">
                <div className="eyebrow">{t("linkToTableRow")}</div>
                <div className="two-col">
                  <label className="field-stack">
                    <span className="field-label">{t("listLabel")}</span>
                    <SearchableSelect
                      options={eligibleResponsibleLists}
                      getId={(item) => item.definition.id}
                      getLabel={(item) => item.definition.name}
                      value={manualLinkListId || null}
                      onChange={(item) => setManualLinkListId(item ? item.definition.id : "")}
                      placeholder={t("chooseListPlaceholder")}
                    />
                  </label>
                  <label className="field-stack">
                    <span className="field-label">{t("rowLabel")}</span>
                    <SearchableSelect
                      options={manualLinkListMeta ? availableManualEntries : []}
                      getId={(entry) => entry.id}
                      getLabel={(entry) => rowOptionLabel(entry, manualLinkListMeta!, participantsById, responsibilityNameMode, t)}
                      value={manualLinkEntryId || null}
                      onChange={(entry) => setManualLinkEntryId(entry ? entry.id : "")}
                      disabled={!manualLinkListMeta || loadingResponsibleListId === manualLinkListMeta.definition.id}
                      placeholder={
                        !manualLinkListMeta
                          ? t("chooseListFirst")
                          : loadingResponsibleListId === manualLinkListMeta.definition.id
                          ? t("rowsLoading")
                          : t("chooseRow")
                      }
                    />
                  </label>
                </div>
                <div className="table-toolbar-actions">
                  <button
                    type="button"
                    className="button-secondary"
                    disabled={!manualLinkEntryId}
                    onClick={() => void linkElementToResponsibleRow()}
                  >
                    Zeile verknüpfen
                  </button>
                </div>
                <span className="field-help">{t("linkRowHint")}</span>
              </article>

              <article className="card">
                <div className="eyebrow">{t("assignManuallyTitle")}</div>
                <label className="field-stack">
                  <span className="field-label">{t("search")}</span>
                  <SearchInput value={responsibilitySearch} onChange={setResponsibilitySearch} placeholder={t("searchParticipantsPlaceholder")} />
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
                          <strong>{participantName(participant, responsibilityNameMode, t)}</strong>
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
                  <div className="responsibility-empty">{t("noMatchingParticipants")}</div>
                ) : null}
              </article>
            </div>
          );
        })() : null}
      </Modal>

    </div>
  );
}
