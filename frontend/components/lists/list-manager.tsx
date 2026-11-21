"use client";

import { DocumentExportDialog } from "@/components/documents/export-dialog";
import { useParticipantSelectable } from "@/contexts/participant-date-context";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";

import { EmptyState } from "@/components/ui/empty-state";
import { ListValueTypeIcon } from "@/components/lists/list-value-type-icon";
import { StructuredListTable } from "@/components/lists/structured-list-table";
import { HistoricalEditConfirmModal, HistoricalViewBanner, ReconstructionBanner } from "@/components/ui/historical-view-banner";
import { Modal, ModalSaveForm } from "@/components/ui/modal";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { ActionMenu } from "@/components/ui/action-menu";
import { Badge } from "@/components/ui/badge";
import { formatDate } from "@/lib/utils/format";
import { SearchInput } from "@/components/ui/search-input";
import { ApiError, browserApiFetch } from "@/lib/api/client";
import { Select } from "@/components/ui/select";
import { ActionIcon } from "@/components/ui/action-icons";
import { HelpPopover } from "@/components/ui/help-popover";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { useHistoricalList } from "@/lib/hooks/use-historical-list";
import { ColumnFormState, createListDefinition, isPersonType, ListSaveRequest, MAX_COLUMNS, newLocalId, updateListDefinition } from "@/lib/lists/save-list";
import {
  EventSummary,
  ParticipantSummary,
  StructuredListDefinition,
  StructuredListEntry,
  StructuredListValueType,
  ListValues,
} from "@/types/api";

type ListManagerProps = {
  initialLists: StructuredListDefinition[];
  initialEntriesByList: Record<string, StructuredListEntry[]>;
  availableParticipants: ParticipantSummary[];
  availableEvents: EventSummary[];
  /** Liste, die beim Öffnen gewählt wird (?open=<id>, z. B. aus der globalen Suche) */
  autoOpenId?: string | null;
};

type ListDefinitionFormState = {
  name: string;
  description: string;
  columns: ColumnFormState[];
  /** localId der Spalten mit Rolle «Bezeichnung» bzw. «Verantwortliche» */
  labelColumn: string;
  responsibleColumn: string;
  is_active: boolean;
  is_group_source: boolean;
};



type ListUsage = { kind: "element" | "protocol"; name: string; number?: string };

/** 409 beim Löschen: Fundstellen nennen statt nur «noch verknüpft» (Audit 07, U4). */
export function listDeleteErrorMessage(error: unknown, t: TFunc): string | null {
  if (!(error instanceof ApiError) || error.status !== 409) return null;
  const detail = error.detail as { code?: string; usages?: ListUsage[] } | undefined;
  if (detail?.code !== "list_in_use" || !Array.isArray(detail.usages)) return null;
  const places = detail.usages
    .map((usage) => (usage.kind === "protocol" ? t("usage.protocol", { number: usage.number ?? usage.name }) : t("usage.element", { name: usage.name })))
    .join(", ");
  return t("toasts.listInUse", { places });
}

type TFunc = (key: string, values?: Record<string, string | number | Date>) => string;

function valueTypeOptions(t: TFunc): Array<{ value: StructuredListValueType; label: string }> {
  return [
    { value: "text", label: t("valueTypes.text") },
    { value: "participant", label: t("valueTypes.participant") },
    { value: "participants", label: t("valueTypes.participants") },
    { value: "event", label: t("valueTypes.event") },
  ];
}

function initialFormState(t: TFunc): ListDefinitionFormState {
  const first = newLocalId();
  return {
    name: "",
    description: "",
    columns: [
      { localId: first, title: t("defaultColumnOne"), value_type: "text" },
      { localId: newLocalId(), title: t("defaultColumnTwo"), value_type: "text" },
    ],
    labelColumn: first,
    responsibleColumn: "",
    is_active: true,
    is_group_source: false,
  };
}

function formFromDefinition(definition: StructuredListDefinition): ListDefinitionFormState {
  const columns = [...definition.columns]
    .sort((left, right) => left.sort_index - right.sort_index)
    .map((column) => ({ localId: column.id, id: column.id, title: column.title, value_type: column.value_type, savedType: column.value_type }));
  return {
    name: definition.name,
    description: definition.description ?? "",
    columns,
    labelColumn: definition.label_column_id ?? "",
    responsibleColumn: definition.responsible_column_id ?? "",
    is_active: definition.is_active,
    is_group_source: definition.is_group_source ?? false,
  };
}

export function ListManager({
  initialLists,
  initialEntriesByList,
  availableParticipants,
  availableEvents,
  autoOpenId = null,
}: ListManagerProps) {
  const isParticipantSelectable = useParticipantSelectable();
  const t = useTranslations("lists");
  const showToast = useToast();
  const confirm = useConfirm();
  const [lists, setLists] = useState(initialLists);
  const [entriesByList, setEntriesByList] = useState(initialEntriesByList);
  const [selectedListId, setSelectedListId] = useState<string | null>(
    (autoOpenId && initialLists.some((definition) => definition.id === autoOpenId) ? autoOpenId : initialLists[0]?.id) ?? null
  );
  // Erneut gesucht, während /lists schon offen ist: neue ?open=-Liste wählen
  useEffect(() => {
    if (autoOpenId && lists.some((definition) => definition.id === autoOpenId)) setSelectedListId(autoOpenId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoOpenId]);
  const [search, setSearch] = useState("");
  const [onlyUnassigned, setOnlyUnassigned] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [editingListId, setEditingListId] = useState<string | null>(null);
  const [form, setForm] = useState(() => initialFormState(t));

  const [exportOpen, setExportOpen] = useState(false);

  const selectedList = useMemo(
    () => lists.find((definition) => definition.id === selectedListId) ?? null,
    [lists, selectedListId]
  );

  const historical = useHistoricalList(selectedListId);
  const isHistorical = historical.mode === "historical";
  const isReconstructing = historical.mode === "reconstructing";
  const isLive = historical.mode === "live";
  const [showUnlockConfirm, setShowUnlockConfirm] = useState(false);
  const [isConfirmingReconstruction, setIsConfirmingReconstruction] = useState(false);
  const displayedDefinition = isLive ? selectedList : historical.definition;
  const displayedEntries = isLive ? entriesByList[selectedList?.id ?? ""] ?? [] : historical.entries;

  function isUnassigned(entry: StructuredListEntry) {
    if (!displayedDefinition) return false;
    return displayedDefinition.columns.some((column) => {
      const value = entry.values?.[column.id] ?? {};
      return column.value_type === "participant" ? !value.participant_id
        : column.value_type === "participants" ? !Array.isArray(value.participant_ids) || !value.participant_ids.length
        : column.value_type === "event" ? !value.event_id : false;
    });
  }
  const unassignedCount = displayedEntries.filter(isUnassigned).length;
  const showUnassignedFilter = unassignedCount > 0 || onlyUnassigned;
  const visibleEntries = displayedEntries.filter((entry) => {
    if (onlyUnassigned && !isUnassigned(entry)) return false;
    const query = search.trim().toLocaleLowerCase();
    if (!query) return true;
    const searchable = Object.values(entry.values ?? {}).map((value) => {
      const ids = Array.isArray(value.participant_ids) ? value.participant_ids : [value.participant_id];
      return [value.text_value, value.participant_name, ...(Array.isArray(value.participant_names) ? value.participant_names : []),
        ...availableParticipants.filter((p) => ids.includes(p.id)).map((p) => p.display_name),
        availableEvents.find((event) => event.id === value.event_id)?.title].join(" ");
    }).join(" ");
    return searchable.toLocaleLowerCase().includes(query);
  });

  function openCreate() {
    setEditingListId(null);
    setForm(initialFormState(t));
    setModalOpen(true);
  }

  function openEdit(definition: StructuredListDefinition) {
    setEditingListId(definition.id);
    setSelectedListId(definition.id);
    setForm(formFromDefinition(definition));
    setModalOpen(true);
  }

  async function saveDefinition(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      const saved = editingListId ? await saveExistingDefinition(editingListId) : await createDefinition();
      if (!saved) return;
      setLists((current) =>
        editingListId ? current.map((item) => (item.id === saved.id ? saved : item)) : [saved, ...current]
      );
      setEntriesByList((current) => ({ ...current, [saved.id]: current[saved.id] ?? [] }));
      if (editingListId) await reloadEntries(saved.id);
      setSelectedListId(saved.id);
      setModalOpen(false);
      showToast(editingListId ? t("toasts.listSaved") : t("toasts.listCreated"), "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("toasts.listSaveFailed"), "error");
    }
  }

  async function reloadEntries(listId: string) {
    const entries = await browserApiFetch<StructuredListEntry[]>(`/api/lists/${listId}/entries`);
    setEntriesByList((current) => ({ ...current, [listId]: entries }));
  }

  function saveRequest(): ListSaveRequest {
    return {
      name: form.name,
      description: form.description,
      is_active: form.is_active,
      is_group_source: form.is_group_source,
      columns: form.columns,
      labelColumn: form.labelColumn,
      responsibleColumn: form.responsibleColumn,
    };
  }

  function createDefinition() {
    return createListDefinition(saveRequest());
  }

  function saveExistingDefinition(listId: string) {
    const original = lists.find((item) => item.id === listId);
    if (!original) return Promise.resolve(null);
    return updateListDefinition(original, saveRequest(), {
      confirmRemove: (column, usages) => confirm({
        message: usages.length
          ? t("columns.deleteConfirmUsed", { title: column.title, places: usages.map((usage) => usage.label).join(", ") })
          : t("columns.deleteConfirm", { title: column.title }),
        tone: "danger",
        confirmLabel: t("columns.deleteLabel"),
      }),
      confirmRetype: (titles) => confirm({
        message: t("columns.typeChangeConfirm", { titles: titles.join(", ") }),
        tone: "danger",
        confirmLabel: t("columns.typeChangeLabel"),
      }),
    });
  }

  function updateColumn(localId: string, patch: Partial<ColumnFormState>) {
    setForm((current) => {
      const columns = current.columns.map((column) => (column.localId === localId ? { ...column, ...patch } : column));
      const typeOf = (id: string) => columns.find((column) => column.localId === id)?.value_type;
      const label = current.labelColumn && typeOf(current.labelColumn) && !isPersonType(typeOf(current.labelColumn)!) ? current.labelColumn : "";
      const responsible = current.responsibleColumn && typeOf(current.responsibleColumn) && isPersonType(typeOf(current.responsibleColumn)!) ? current.responsibleColumn : "";
      return { ...current, columns, labelColumn: label, responsibleColumn: responsible };
    });
  }

  function moveColumn(localId: string, direction: -1 | 1) {
    setForm((current) => {
      const index = current.columns.findIndex((column) => column.localId === localId);
      const target = index + direction;
      if (index < 0 || target < 0 || target >= current.columns.length) return current;
      const columns = [...current.columns];
      [columns[index], columns[target]] = [columns[target], columns[index]];
      return { ...current, columns };
    });
  }

  function removeColumn(localId: string) {
    setForm((current) => ({
      ...current,
      columns: current.columns.filter((column) => column.localId !== localId),
      labelColumn: current.labelColumn === localId ? "" : current.labelColumn,
      responsibleColumn: current.responsibleColumn === localId ? "" : current.responsibleColumn,
    }));
  }

  function addColumn() {
    setForm((current) => ({
      ...current,
      columns: [...current.columns, { localId: newLocalId(), title: t("columns.newTitle", { number: current.columns.length + 1 }), value_type: "text" }],
    }));
  }

  async function deleteDefinition(listId: string) {
    const ok = await confirm({
      message: t("toasts.deleteListConfirm"),
      tone: "danger",
      confirmLabel: t("toasts.deleteLabel")
    });
    if (!ok) return;
    try {
      await browserApiFetch(`/api/lists/${listId}`, { method: "DELETE" });
      const remainingLists = lists.filter((item) => item.id !== listId);
      setLists(remainingLists);
      setEntriesByList((current) => {
        const next = { ...current };
        delete next[listId];
        return next;
      });
      setSelectedListId((current) => (current === listId ? (remainingLists[0]?.id ?? null) : current));
      showToast(t("toasts.listDeleted"), "success");
    } catch (error) {
      showToast(listDeleteErrorMessage(error, t) ?? (error instanceof Error ? error.message : t("toasts.listDeleteFailed")), "error");
    }
  }

  async function createEntry(listId: string, payload: { sort_index: number; values: ListValues }) {
    try {
      const created = await browserApiFetch<StructuredListEntry>(`/api/lists/${listId}/entries`, {
        method: "POST",
        body: JSON.stringify(payload),
      });
      setEntriesByList((current) => ({
        ...current,
        [listId]: [...(current[listId] ?? []), created].sort((left, right) => left.sort_index - right.sort_index),
      }));
      showToast(t("toasts.entryCreated"), "success");
      return true;
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("toasts.entryCreateFailed"), "error");
      return false;
    }
  }

  async function updateEntry(
    listId: string,
    entryId: string,
    payload: Partial<{ sort_index: number; values: ListValues }>
  ) {
    try {
      const updated = await browserApiFetch<StructuredListEntry>(`/api/list-entries/${entryId}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      });
      setEntriesByList((current) => ({
        ...current,
        [listId]: (current[listId] ?? []).map((entry) => (entry.id === entryId ? updated : entry)),
      }));
      showToast(t("toasts.entrySaved"), "success");
      return true;
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("toasts.entrySaveFailed"), "error");
      return false;
    }
  }

  async function deleteEntry(listId: string, entryId: string) {
    const ok = await confirm({
      message: t("toasts.deleteEntryConfirm"),
      tone: "danger",
      confirmLabel: t("toasts.deleteLabel")
    });
    if (!ok) return;
    try {
      await browserApiFetch(`/api/list-entries/${entryId}`, { method: "DELETE" });
      setEntriesByList((current) => ({
        ...current,
        [listId]: (current[listId] ?? []).filter((entry) => entry.id !== entryId),
      }));
      showToast(t("toasts.entryDeleted"), "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("toasts.entryDeleteFailed"), "error");
    }
  }

  async function updateHistoricalEntry(
    entryId: string,
    payload: Partial<{ sort_index: number; values: ListValues }>
  ) {
    if (!historical.editUnlocked) {
      setShowUnlockConfirm(true);
      return false;
    }
    try {
      await historical.saveHistoricalEntry(entryId, payload);
      showToast(t("toasts.historicalEntrySaved"), "success");
      return true;
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("toasts.historicalEntrySaveFailed"), "error");
      return false;
    }
  }

  async function deleteHistoricalEntry(entryId: string) {
    if (!historical.editUnlocked) {
      setShowUnlockConfirm(true);
      return;
    }
    const ok = await confirm({
      message: t("toasts.deleteHistoricalEntryConfirm"),
      tone: "danger",
      confirmLabel: t("toasts.removeLabel")
    });
    if (!ok) return;
    try {
      await historical.deleteHistoricalEntry(entryId);
      showToast(t("toasts.historicalEntryRemoved"), "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("toasts.entryRemoveFailed"), "error");
    }
  }

  // Reconstruction-mode edits stay purely local (no network call) until "Bestätigen" -
  // see useHistoricalList.confirmReconstruction.
  async function updateDraftEntry(
    entryId: string,
    payload: Partial<{ sort_index: number; values: ListValues }>
  ) {
    historical.updateDraftEntry(entryId, payload);
    return true;
  }

  async function deleteDraftEntry(entryId: string) {
    const ok = await confirm({
      message: t("toasts.deleteDraftEntryConfirm"),
      tone: "danger",
      confirmLabel: t("toasts.removeLabel")
    });
    if (!ok) return;
    historical.deleteDraftEntry(entryId);
  }

  async function confirmReconstruction() {
    setIsConfirmingReconstruction(true);
    try {
      await historical.confirmReconstruction();
      showToast(t("toasts.snapshotCreated"), "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("toasts.snapshotCreateFailed"), "error");
    } finally {
      setIsConfirmingReconstruction(false);
    }
  }

  return (
    <div className="grid">
      <div className="page-header">
        <div>
          <h1 className="page-title">{t("pageTitle")}</h1>
          <p className="muted">{lists.length === 0 ? t("pageDescriptionEmpty") : t("pageDescription")}</p>
        </div>
        {lists.length > 0 ? <button type="button" className="button-primary" onClick={openCreate}>{t("newList")}</button> : null}
      </div>
      {lists.length === 0 ? (
        <EmptyState
          title={t("emptyState.title")}
          description={t("emptyState.description")}
          actions={
            <button type="button" className="button-primary" onClick={openCreate}>
              {t("newList")}
            </button>
          }
          hint={t("emptyState.hint")}
        />
      ) : (
      <div className="list-manager-layout">

        <div className="list-manager-tabs" role="tablist" aria-label={t("pageTitle")}>
          {lists.map((definition) => (
            <button type="button" role="tab" key={definition.id}
              aria-selected={selectedListId === definition.id}
              aria-controls="list-manager-panel"
              className={`tabs-trigger${selectedListId === definition.id ? " tabs-trigger-active" : ""}`}
              onClick={() => { setSelectedListId(definition.id); setSearch(""); setOnlyUnassigned(false); }}>
              {definition.name} <span className="muted">{(entriesByList[definition.id] ?? []).length}</span>
              {!definition.is_active && <Badge variant="neutral">{t("inactive")}</Badge>}
              <span className="list-manager-dot" aria-hidden="true" />
            </button>
          ))}
        </div>

        {/* Right: content */}
        <div className="list-manager-content" id="list-manager-panel" role="tabpanel">
          {selectedList ? (
            <div className="grid">

              {isHistorical && historical.cycleYear !== null && (
                <HistoricalViewBanner
                  cycleConfigName={historical.cycleConfigName ?? ""}
                  cycleYear={historical.cycleYear}
                  isEdited={historical.isEdited}
                  editUnlocked={historical.editUnlocked}
                  onRequestUnlock={() => setShowUnlockConfirm(true)}
                />
              )}

              {isReconstructing && historical.cycleYear !== null && (
                <ReconstructionBanner
                  cycleConfigName={historical.cycleConfigName ?? ""}
                  cycleYear={historical.cycleYear}
                  source={historical.reconstructSource}
                  isConfirming={isConfirmingReconstruction}
                  onConfirm={() => void confirmReconstruction()}
                  onCancel={historical.cancelReconstruction}
                />
              )}

              {!isLive && !historical.isLoading && !historical.definition ? (
                <p className="muted">
                  {isReconstructing
                    ? t("noDataForReconstruct")
                    : t("notFoundInCycle")}
                </p>
              ) : (
                displayedDefinition && (
                  <StructuredListTable
                    key={`${selectedList.id}-${historical.mode}-${historical.cycleConfigId}-${historical.cycleYear}`}
                    definition={displayedDefinition}
                    masterList
                    heading={
                      <div className="list-manager-filter">
                        <SearchInput value={search} onChange={setSearch} placeholder={t("searchList", { name: displayedDefinition.name })} />
                        {showUnassignedFilter && <button type="button" className={`button-secondary${onlyUnassigned ? " list-manager-filter-active" : ""}`} aria-pressed={onlyUnassigned} onClick={() => setOnlyUnassigned((value) => !value)}><span className="list-manager-dot" />{t("unassigned", { count: unassignedCount })}</button>}
                        <span className="muted">{displayedDefinition.description} · {t("sidebar.entryCount", { count: displayedEntries.length })}{displayedDefinition.updated_at ? ` · ${t("changed", { date: formatDate(displayedDefinition.updated_at) })}` : ""}</span>
                      </div>
                    }
                    headingActions={
                      <>
                  {(
                    <SearchableSelect
                      options={[
                        { id: "live", label: t("currentView"), cycle: null },
                        ...historical.availableCycles.map((cycle) => ({
                          id: `${cycle.cycle_config_id}:${cycle.cycle_year}`,
                          label: `${cycle.cycle_config_name} ${cycle.cycle_year}${cycle.has_snapshot ? ` ${t("viewOption.historical")}` : ` ${t("viewOption.noSnapshot")}`}`,
                          cycle,
                        })),
                      ]}
                      getId={(option) => option.id}
                      getLabel={(option) => option.label}
                      value={isLive ? "live" : `${historical.cycleConfigId}:${historical.cycleYear}`}
                      triggerProps={{ "aria-label": t("viewOption.viewAriaLabel") }}
                      onChange={(option) => {
                        if (!option) return;
                        if (option.cycle) {
                          historical.switchToHistorical(option.cycle.cycle_config_id, option.cycle.cycle_year, option.cycle.has_snapshot);
                        } else {
                          historical.switchToLive();
                        }
                      }}
                    />
                  )}
                  {isLive && <ActionMenu items={[
                    { label: t("export"), onClick: () => setExportOpen(true) },
                    { label: t("edit"), onClick: () => openEdit(selectedList) },
                    { label: t("deleteList"), danger: true, onClick: () => void deleteDefinition(selectedList.id) },
                  ]} />}
                      </>
                    }
                    highlightDepartedParticipants={isLive}
                    entries={displayedEntries}
                    visibleEntryIds={visibleEntries.map((entry) => entry.id)}
                    availableParticipants={availableParticipants}
                    availableEvents={availableEvents}
                    fullWidth
                    editable={isLive || isReconstructing || historical.editUnlocked}
                    allowCreate={isLive}
                    onCreateEntry={
                      isLive
                        ? (payload) => createEntry(selectedList.id, payload)
                        : async () => {
                            showToast(t("noNewEntries"), "error");
                            return false;
                          }
                    }
                    onUpdateEntry={
                      isLive
                        ? (entryId, payload) => updateEntry(selectedList.id, entryId, payload)
                        : isReconstructing
                          ? updateDraftEntry
                          : updateHistoricalEntry
                    }
                    onDeleteEntry={
                      isLive
                        ? (entryId) => deleteEntry(selectedList.id, entryId)
                        : isReconstructing
                          ? deleteDraftEntry
                          : deleteHistoricalEntry
                    }
                  />
                )
              )}
            </div>
          ) : (
            <p className="muted">{t("selectListPrompt")}</p>
          )}
        </div>
      </div>
      )}

      {exportOpen && selectedListId && (
        <DocumentExportDialog open={exportOpen} onClose={() => setExportOpen(false)} context={{ documentType: "list", params: { list_id: selectedListId } }} />
      )}

      <Modal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        title={editingListId ? t("formModal.editTitle") : t("formModal.createTitle")}
        description={t("formModal.description")}
        size="wide"
        className="list-definition-modal"
        footer={<div className="list-definition-footer">
          <label className="list-definition-active"><input type="checkbox" role="switch" checked={form.is_active} onChange={(event) => setForm((current) => ({ ...current, is_active: event.target.checked }))} />{t("formModal.active")}</label>
          <div className="modal-actions"><button type="button" className="button-secondary" onClick={() => setModalOpen(false)}>{t("formModal.cancel")}</button>
            <button data-modal-save form="list-definition-form" type="submit" className="button-primary" disabled={!form.name.trim() || !form.columns.length || form.columns.some((column) => !column.title.trim())}>{editingListId ? t("formModal.save") : t("formModal.create")}</button></div>
        </div>}
      >
        <ModalSaveForm id="list-definition-form" className="grid list-definition-form" onSubmit={saveDefinition}>
          <div className="two-col">
            <label className="field-stack"><span className="field-label">{t("formModal.name")}</span>
              <input value={form.name} placeholder={t("formModal.namePlaceholder")} onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))} required />
            </label>
            <label className="field-stack"><span className="field-label">{t("formModal.description2")} · <span className="muted">{t("formModal.optional")}</span></span>
              <input value={form.description} onChange={(event) => setForm((current) => ({ ...current, description: event.target.value }))} placeholder={t("formModal.descriptionPlaceholder")} />
            </label>
          </div>
          <div className="list-definition-section">
            <strong>{t("formModal.columns")}</strong>
            <span className="muted">{t("formModal.columnsHint")}</span>
            <HelpPopover topic={t("formModal.dataType")} docs={{ page: "listen", anchor: "datentypen" }}>
              {t("help.dataType")}
            </HelpPopover>
          </div>
          <ol className="list-definition-columns">
            {form.columns.map((column, index) => (
              <li className="list-definition-column-row" key={column.localId}>
                <span className="list-definition-number" aria-hidden="true">{index + 1}</span>
                <input
                  aria-label={t("columns.titleLabel", { number: index + 1 })}
                  value={column.title}
                  onChange={(event) => updateColumn(column.localId, { title: event.target.value })}
                  required
                />
                <Select
                  aria-label={t("columns.typeLabel", { number: index + 1 })}
                  value={column.value_type}
                  onChange={(event) => updateColumn(column.localId, { value_type: event.target.value as StructuredListValueType })}
                >
                  {valueTypeOptions(t).map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                </Select>
                <div className="list-definition-column-actions">
                  <button type="button" className="button-icon-soft" aria-label={t("columns.moveUp", { title: column.title })} title={t("columns.moveUp", { title: column.title })} disabled={index === 0} onClick={() => moveColumn(column.localId, -1)}>↑</button>
                  <button type="button" className="button-icon-soft" aria-label={t("columns.moveDown", { title: column.title })} title={t("columns.moveDown", { title: column.title })} disabled={index === form.columns.length - 1} onClick={() => moveColumn(column.localId, 1)}>↓</button>
                  <button type="button" className="button-icon-soft button-icon-soft-danger" aria-label={t("columns.remove", { title: column.title })} title={t("columns.remove", { title: column.title })} disabled={form.columns.length <= 1} onClick={() => removeColumn(column.localId)}><ActionIcon name="delete" /></button>
                </div>
                {column.savedType && column.savedType !== column.value_type ? (
                  <span className="field-help list-definition-column-warning">{t("columns.typeChangeHint")}</span>
                ) : null}
              </li>
            ))}
          </ol>
          <div>
            <button type="button" className="button-secondary" disabled={form.columns.length >= MAX_COLUMNS} onClick={addColumn}>{t("columns.add")}</button>
            {form.columns.length >= MAX_COLUMNS ? <span className="field-help">{t("columns.limit", { max: MAX_COLUMNS })}</span> : null}{/* i18n-ok: Vergleich, kein Text */}
          </div>
          <div className="two-col">
            <label className="field-stack">
              <span className="field-label">{t("columns.roleLabel")}</span>
              <Select value={form.labelColumn} onChange={(event) => setForm((current) => ({ ...current, labelColumn: event.target.value }))}>
                <option value="">{t("columns.roleNone")}</option>
                {form.columns.filter((column) => !isPersonType(column.value_type)).map((column) => <option key={column.localId} value={column.localId}>{column.title}</option>)}
              </Select>
              <span className="field-help">{t("columns.roleLabelHelp")}</span>
            </label>
            <label className="field-stack">
              <span className="field-label">{t("columns.roleResponsible")}</span>
              <Select value={form.responsibleColumn} onChange={(event) => setForm((current) => ({ ...current, responsibleColumn: event.target.value }))}>
                <option value="">{t("columns.roleNone")}</option>
                {form.columns.filter((column) => isPersonType(column.value_type)).map((column) => <option key={column.localId} value={column.localId}>{column.title}</option>)}
              </Select>
              <span className="field-help">{t("columns.roleResponsibleHelp")}</span>
            </label>
          </div>
          <div className="list-definition-group-source">
            <label className="list-definition-active">
              <input type="checkbox" role="switch" checked={form.is_group_source} onChange={(event) => setForm((current) => ({ ...current, is_group_source: event.target.checked }))} />
              {t("formModal.groupSource")}
            </label>
            <HelpPopover topic={t("formModal.groupSource")} docs={{ page: "statistik", anchor: "gruppen" }}>
              {t("help.groupSource")}
            </HelpPopover>
          </div>
          <div className="field-stack"><span className="field-label">{t("formModal.preview")}</span>
            <div className="list-definition-preview"><table className="data-table"><thead><tr>{form.columns.map((column) => <th key={column.localId}>{column.title} <span className="muted">· {t(`valueTypes.${column.value_type}`)}</span></th>)}</tr></thead>
              <tbody>{[0, 1].map((row) => <tr key={row}>{form.columns.map((column) => <td key={column.localId}><span className={column.value_type === "text" ? "" : "list-definition-example"}>{t(`previewValues.${column.value_type}.${row}`)}</span></td>)}</tr>)}</tbody>
            </table></div>
          </div>
        </ModalSaveForm>
      </Modal>

      <HistoricalEditConfirmModal
        open={showUnlockConfirm}
        onCancel={() => setShowUnlockConfirm(false)}
        onConfirm={() => {
          historical.unlockEditing();
          setShowUnlockConfirm(false);
        }}
      />
    </div>
  );
}
