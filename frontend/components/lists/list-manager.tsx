"use client";

import { DocumentExportDialog } from "@/components/documents/export-dialog";
import { useParticipantSelectable } from "@/contexts/participant-date-context";

import { FormEvent, useMemo, useState } from "react";
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
import { browserApiFetch } from "@/lib/api/client";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { useHistoricalList } from "@/lib/hooks/use-historical-list";
import {
  EventSummary,
  ParticipantSummary,
  StructuredListDefinition,
  StructuredListEntry,
  StructuredListValueType,
} from "@/types/api";

type ListManagerProps = {
  initialLists: StructuredListDefinition[];
  initialEntriesByList: Record<string, StructuredListEntry[]>;
  availableParticipants: ParticipantSummary[];
  availableEvents: EventSummary[];
};

type ListDefinitionFormState = {
  name: string;
  description: string;
  column_one_title: string;
  column_one_value_type: StructuredListValueType;
  column_two_title: string;
  column_two_value_type: StructuredListValueType;
  is_active: boolean;
};

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
  return {
    name: "",
    description: "",
    column_one_title: t("defaultColumnOne"),
    column_one_value_type: "text",
    column_two_title: t("defaultColumnTwo"),
    column_two_value_type: "text",
    is_active: true,
  };
}

function formFromDefinition(definition: StructuredListDefinition): ListDefinitionFormState {
  return {
    name: definition.name,
    description: definition.description ?? "",
    column_one_title: definition.column_one_title,
    column_one_value_type: definition.column_one_value_type,
    column_two_title: definition.column_two_title,
    column_two_value_type: definition.column_two_value_type,
    is_active: definition.is_active,
  };
}

export function ListManager({
  initialLists,
  initialEntriesByList,
  availableParticipants,
  availableEvents,
}: ListManagerProps) {
  const isParticipantSelectable = useParticipantSelectable();
  const t = useTranslations("lists");
  const showToast = useToast();
  const confirm = useConfirm();
  const [lists, setLists] = useState(initialLists);
  const [entriesByList, setEntriesByList] = useState(initialEntriesByList);
  const [selectedListId, setSelectedListId] = useState<string | null>(initialLists[0]?.id ?? null);
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
    return (["one", "two"] as const).some((column) => {
      const type = displayedDefinition[`column_${column}_value_type`];
      const value = entry[`column_${column}_value`];
      return type === "participant" ? !value.participant_id
        : type === "participants" ? !Array.isArray(value.participant_ids) || !value.participant_ids.length
        : type === "event" ? !value.event_id : false;
    });
  }
  const unassignedCount = displayedEntries.filter(isUnassigned).length;
  const showUnassignedFilter = unassignedCount > 0 || onlyUnassigned;
  const visibleEntries = displayedEntries.filter((entry) => {
    if (onlyUnassigned && !isUnassigned(entry)) return false;
    const query = search.trim().toLocaleLowerCase();
    if (!query) return true;
    const searchable = [entry.column_one_value, entry.column_two_value].map((value) => {
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
      const payload = {
        name: form.name,
        description: form.description || null,
        column_one_title: form.column_one_title,
        column_one_value_type: form.column_one_value_type,
        column_two_title: form.column_two_title,
        column_two_value_type: form.column_two_value_type,
        is_active: form.is_active,
      };
      const saved = editingListId
        ? await browserApiFetch<StructuredListDefinition>(`/api/lists/${editingListId}`, {
            method: "PATCH",
            body: JSON.stringify(payload),
          })
        : await browserApiFetch<StructuredListDefinition>("/api/lists", {
            method: "POST",
            body: JSON.stringify(payload),
          });

      setLists((current) =>
        editingListId ? current.map((item) => (item.id === saved.id ? saved : item)) : [saved, ...current]
      );
      setEntriesByList((current) => ({ ...current, [saved.id]: current[saved.id] ?? [] }));
      setSelectedListId(saved.id);
      setModalOpen(false);
      showToast(editingListId ? t("toasts.listSaved") : t("toasts.listCreated"), "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("toasts.listSaveFailed"), "error");
    }
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
      showToast(error instanceof Error ? error.message : t("toasts.listDeleteFailed"), "error");
    }
  }

  async function createEntry(listId: string, payload: { sort_index: number; column_one_value: Record<string, unknown>; column_two_value: Record<string, unknown> }) {  // i18n-ok: TS-Typannotation, kein JSX
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
    payload: Partial<{ sort_index: number; column_one_value: Record<string, unknown>; column_two_value: Record<string, unknown> }>  // i18n-ok: TS-Typannotation, kein JSX
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
    payload: Partial<{ sort_index: number; column_one_value: Record<string, unknown>; column_two_value: Record<string, unknown> }>  // i18n-ok: TS-Typannotation, kein JSX
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
    payload: Partial<{ sort_index: number; column_one_value: Record<string, unknown>; column_two_value: Record<string, unknown> }>  // i18n-ok: TS-Typannotation, kein JSX
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
            <button data-modal-save form="list-definition-form" type="submit" className="button-primary" disabled={!form.name.trim() || !form.column_one_title.trim() || !form.column_two_title.trim()}>{editingListId ? t("formModal.save") : t("formModal.create")}</button></div>
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
          <div className="list-definition-section"><strong>{t("formModal.columns")}</strong><span className="muted">{t("formModal.columnsHint")}</span></div>
          <div className="two-col">
            {(["one", "two"] as const).map((column, index) => (
              <fieldset className="list-definition-column" key={column} aria-label={t(index === 0 ? "formModal.column1" : "formModal.column2")}>
                <label className="list-definition-title"><span className="list-definition-number">{index + 1}</span>
                  <input aria-label={t(index === 0 ? "formModal.column1" : "formModal.column2")} value={form[`column_${column}_title`]} onChange={(event) => setForm((current) => ({ ...current, [`column_${column}_title`]: event.target.value }))} required />
                </label>
                <div className="list-definition-types" role="group" aria-label={t("formModal.dataType")}>
                  {valueTypeOptions(t).map((option) => (
                    <button type="button" key={option.value} aria-pressed={form[`column_${column}_value_type`] === option.value}
                      className={`list-definition-type${form[`column_${column}_value_type`] === option.value ? " list-definition-type-selected" : ""}`}
                      onClick={() => setForm((current) => ({ ...current, [`column_${column}_value_type`]: option.value }))}>
                      <span className="list-definition-type-icon" aria-hidden="true"><ListValueTypeIcon type={option.value} /></span>
                      <span><strong>{option.label}</strong><span className="muted">{t(`typeHints.${option.value}`)}</span></span>
                    </button>
                  ))}
                </div>
              </fieldset>
            ))}
          </div>
          <div className="field-stack"><span className="field-label">{t("formModal.preview")}</span>
            <div className="list-definition-preview"><table className="data-table"><thead><tr>{(["one", "two"] as const).map((column) => <th key={column}>{form[`column_${column}_title`]} <span className="muted">· {t(`valueTypes.${form[`column_${column}_value_type`]}`)}</span></th>)}</tr></thead>
              <tbody>{[0, 1].map((row) => <tr key={row}>{(["one", "two"] as const).map((column) => <td key={column}><span className={form[`column_${column}_value_type`] === "text" ? "" : "list-definition-example"}>{t(`previewValues.${form[`column_${column}_value_type`]}.${row}`)}</span></td>)}</tr>)}</tbody>
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
