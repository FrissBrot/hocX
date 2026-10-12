"use client";

import { FormEvent, useMemo, useState } from "react";
import { useTranslations } from "next-intl";

import { ActionIcon } from "@/components/ui/action-icons";
import { ActionMenu } from "@/components/ui/action-menu";
import { Badge } from "@/components/ui/badge";
import { DataTable, DataToolbar } from "@/components/ui/data-table";
import { EmptyState } from "@/components/ui/empty-state";
import { Modal, ModalSaveForm } from "@/components/ui/modal";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import { formatCycleName } from "@/lib/utils/cycle";
import {
  CycleConfigSummary,
  ParticipantSummary,
  StructuredListDefinition,
  StructuredListEntry,
  TaskPackage,
  TaskPackageItem,
  TaskPackagePreview,
  TaskPackageTodoDeleteMode,
} from "@/types/api";
import { TaskPackageItemModal, TaskPackageItemPayload } from "@/components/task-packages/task-package-item-modal";
import {
  ResponsibleContext,
  currentCycleYear,
  dueRuleLabel,
  previewDate,
  recurrenceLabel,
  responsibleLabel,
} from "@/components/task-packages/task-package-labels";

type Props = {
  initialPackages: TaskPackage[];
  cycleConfigs: CycleConfigSummary[];
  responsibleLists: StructuredListDefinition[];
  entriesByList: Record<string, StructuredListEntry[]>;
  participants: ParticipantSummary[];
  eventTags: string[];
};

type PackageForm = { name: string; description: string; isActive: boolean };

/** Löschen eines Pakets oder einer Zyklus-Zuweisung: beides fragt, was mit den Aufgaben passiert. */
type RemovalTarget =
  | { kind: "package"; pkg: TaskPackage }
  | { kind: "cycle"; pkg: TaskPackage; cycleId: string; cycleName: string };

const DELETE_MODES: TaskPackageTodoDeleteMode[] = ["all", "future", "none"];

function sortPackages(packages: TaskPackage[]) {
  return [...packages].sort((a, b) => a.name.localeCompare(b.name));
}

export function TaskPackageManager({ initialPackages, cycleConfigs, responsibleLists, entriesByList, participants, eventTags }: Props) {
  const t = useTranslations("taskPackages");
  const tCommon = useTranslations("common");
  const confirm = useConfirm();
  const showToast = useToast();
  const [packages, setPackages] = useState(() => sortPackages(initialPackages));

  const [packageModal, setPackageModal] = useState<{ pkg: TaskPackage | null } | null>(null);
  const [packageForm, setPackageForm] = useState<PackageForm>({ name: "", description: "", isActive: true });
  const [itemModal, setItemModal] = useState<{ pkg: TaskPackage; item: TaskPackageItem | null } | null>(null);
  const [cycleModal, setCycleModal] = useState<TaskPackage | null>(null);
  const [cycleForm, setCycleForm] = useState<{ cycleConfigId: string | null; startYear: number | null }>({ cycleConfigId: null, startYear: null });
  const [removal, setRemoval] = useState<RemovalTarget | null>(null);
  const [removalMode, setRemovalMode] = useState<TaskPackageTodoDeleteMode>("future");
  const [previewTarget, setPreviewTarget] = useState<TaskPackage | null>(null);
  const [preview, setPreview] = useState<TaskPackagePreview | null>(null);
  const [previewCycleId, setPreviewCycleId] = useState<string | null>(null);
  const [previewYear, setPreviewYear] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);

  const context: ResponsibleContext = useMemo(
    () => ({
      listsById: new Map(responsibleLists.map((definition) => [definition.id, definition])),
      entriesByList,
      participantsById: new Map(participants.map((participant) => [participant.id, participant])),
    }),
    [responsibleLists, entriesByList, participants]
  );
  const cyclesById = useMemo(() => new Map(cycleConfigs.map((config) => [config.id, config])), [cycleConfigs]);

  function replacePackage(updated: TaskPackage) {
    setPackages((current) => sortPackages(current.some((pkg) => pkg.id === updated.id) ? current.map((pkg) => (pkg.id === updated.id ? updated : pkg)) : [...current, updated]));
  }

  async function run<T>(action: () => Promise<T>, successMessage?: string | ((result: T) => string)): Promise<T | null> {
    setBusy(true);
    try {
      const result = await action();
      if (successMessage) showToast(typeof successMessage === "function" ? successMessage(result) : successMessage, "success");
      return result;
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("errorGeneric"), "error");
      return null;
    } finally {
      setBusy(false);
    }
  }

  // ── Pakete ──────────────────────────────────────────────────────────────

  function openPackageModal(pkg: TaskPackage | null) {
    setPackageForm({ name: pkg?.name ?? "", description: pkg?.description ?? "", isActive: pkg?.is_active ?? true });
    setPackageModal({ pkg });
  }

  async function savePackage(event: FormEvent) {
    event.preventDefault();
    const pkg = packageModal?.pkg ?? null;
    const body = JSON.stringify({ name: packageForm.name.trim(), description: packageForm.description.trim() || null, is_active: packageForm.isActive });
    const saved = await run(
      () => browserApiFetch<TaskPackage>(pkg ? `/api/task-packages/${pkg.id}` : "/api/task-packages", { method: pkg ? "PUT" : "POST", body }),
      pkg ? t("savedToast") : t("createdToast")
    );
    if (saved) {
      replacePackage(saved);
      setPackageModal(null);
    }
  }

  async function toggleActive(pkg: TaskPackage) {
    const saved = await run(
      () => browserApiFetch<TaskPackage>(`/api/task-packages/${pkg.id}`, { method: "PUT", body: JSON.stringify({ is_active: !pkg.is_active }) }),
      pkg.is_active ? t("pausedToast") : t("resumedToast")
    );
    if (saved) replacePackage(saved);
  }

  async function syncPackage(pkg: TaskPackage) {
    const result = await run(
      () => browserApiFetch<{ created: number; updated: number }>(`/api/task-packages/${pkg.id}/sync`, { method: "POST" }),
      (value) => t("syncedToast", { created: value.created, updated: value.updated })
    );
    if (result) {
      const refreshed = await run(() => browserApiFetch<TaskPackage>(`/api/task-packages/${pkg.id}`));
      if (refreshed) replacePackage(refreshed);
    }
  }

  // ── Aufgaben ────────────────────────────────────────────────────────────

  async function saveItem(payload: TaskPackageItemPayload) {
    if (!itemModal) return;
    const { pkg, item } = itemModal;
    const saved = await run(
      () =>
        browserApiFetch<TaskPackage>(item ? `/api/task-packages/${pkg.id}/items/${item.id}` : `/api/task-packages/${pkg.id}/items`, {
          method: item ? "PUT" : "POST",
          body: JSON.stringify(payload),
        }),
      t("savedToast")
    );
    if (saved) {
      replacePackage(saved);
      setItemModal(null);
    }
  }

  async function deleteItem(pkg: TaskPackage, item: TaskPackageItem) {
    if (!(await confirm({ message: t("deleteItemConfirm", { task: item.task }), tone: "danger", confirmLabel: t("remove") }))) return;
    const saved = await run(() => browserApiFetch<TaskPackage>(`/api/task-packages/${pkg.id}/items/${item.id}`, { method: "DELETE" }), t("itemRemovedToast"));
    if (saved) replacePackage(saved);
  }

  async function moveItem(pkg: TaskPackage, index: number, direction: -1 | 1) {
    const ids = pkg.items.map((item) => item.id);
    const target = index + direction;
    if (target < 0 || target >= ids.length) return;
    [ids[index], ids[target]] = [ids[target], ids[index]];
    const saved = await run(() =>
      browserApiFetch<TaskPackage>(`/api/task-packages/${pkg.id}/items/reorder`, { method: "POST", body: JSON.stringify({ item_ids: ids }) })
    );
    if (saved) replacePackage(saved);
  }

  // ── Zyklen ──────────────────────────────────────────────────────────────

  function availableCycles(pkg: TaskPackage) {
    const assigned = new Set(pkg.cycles.map((cycle) => cycle.cycle_config_id));
    return cycleConfigs.filter((config) => !assigned.has(config.id));
  }

  function openCycleModal(pkg: TaskPackage) {
    const first = availableCycles(pkg)[0] ?? null;
    setCycleForm({ cycleConfigId: first?.id ?? null, startYear: first ? currentCycleYear(first) : null });
    setCycleModal(pkg);
  }

  async function assignCycle(event: FormEvent) {
    event.preventDefault();
    if (!cycleModal || !cycleForm.cycleConfigId) return;
    const saved = await run(
      () =>
        browserApiFetch<TaskPackage>(`/api/task-packages/${cycleModal.id}/cycles`, {
          method: "POST",
          body: JSON.stringify({ cycle_config_id: cycleForm.cycleConfigId, start_cycle_year: cycleForm.startYear }),
        }),
      t("cycleAssignedToast")
    );
    if (saved) {
      replacePackage(saved);
      setCycleModal(null);
    }
  }

  // ── Löschen ─────────────────────────────────────────────────────────────

  function openRemoval(target: RemovalTarget) {
    setRemovalMode("future");
    setRemoval(target);
  }

  async function confirmRemoval(event: FormEvent) {
    event.preventDefault();
    if (!removal) return;
    const path =
      removal.kind === "package"
        ? `/api/task-packages/${removal.pkg.id}?todos=${removalMode}`
        : `/api/task-packages/${removal.pkg.id}/cycles/${removal.cycleId}?todos=${removalMode}`;
    const result = await run(
      () => browserApiFetch<{ deleted: number; kept: number }>(path, { method: "DELETE" }),
      (value) => t("removedToast", { deleted: value.deleted, kept: value.kept })
    );
    if (!result) return;
    if (removal.kind === "package") {
      setPackages((current) => current.filter((pkg) => pkg.id !== removal.pkg.id));
    } else {
      const refreshed = await run(() => browserApiFetch<TaskPackage>(`/api/task-packages/${removal.pkg.id}`));
      if (refreshed) replacePackage(refreshed);
    }
    setRemoval(null);
  }

  // ── Vorschau ────────────────────────────────────────────────────────────

  async function loadPreview(pkg: TaskPackage, cycleId: string, year: number) {
    setPreviewCycleId(cycleId);
    setPreviewYear(year);
    const result = await run(() =>
      browserApiFetch<TaskPackagePreview>(`/api/task-packages/${pkg.id}/preview?cycle_config_id=${cycleId}&cycle_year=${year}`)
    );
    setPreview(result);
  }

  function openPreview(pkg: TaskPackage) {
    setPreview(null);
    setPreviewTarget(pkg);
    const first = pkg.cycles[0];
    if (first) void loadPreview(pkg, first.cycle_config_id, first.current_cycle_year);
  }

  const previewCycle = previewTarget?.cycles.find((cycle) => cycle.cycle_config_id === previewCycleId) ?? null;
  const previewConfig = previewCycleId ? cyclesById.get(previewCycleId) : undefined;
  const cycleModalConfig = cycleForm.cycleConfigId ? cyclesById.get(cycleForm.cycleConfigId) : undefined;
  const cycleModalCurrent = cycleModalConfig ? currentCycleYear(cycleModalConfig) : null;

  return (
    <div className="grid">
      <div className="page-header">
        <div>
          <h1 className="page-title">{t("pageTitle")}</h1>
          <p className="muted">{t("pageDescription")}</p>
        </div>
        <button type="button" className="button-primary" onClick={() => openPackageModal(null)}>
          {t("newPackage")}
        </button>
      </div>

      {packages.length === 0 ? (
        <EmptyState
          title={t("emptyTitle")}
          description={t("emptyDescription")}
          actions={
            <button type="button" className="button-secondary" onClick={() => openPackageModal(null)}>
              {t("newPackage")}
            </button>
          }
        />
      ) : (
        <div className="section-stack">
          {packages.map((pkg) => (
            <section key={pkg.id} className="section-card task-package-card">
              <div className="task-package-header">
                <div className="task-package-title">
                  <h2>{pkg.name}</h2>
                  <Badge variant={pkg.is_active ? "success" : "neutral"} dot>
                    {pkg.is_active ? t("statusActive") : t("statusPaused")}
                  </Badge>
                  <span className="muted">{t("todoCounts", { open: pkg.open_todo_count, total: pkg.todo_count })}</span>
                </div>
                <ActionMenu
                  ariaLabel={t("actionsLabel", { name: pkg.name })}
                  items={[
                    { label: tCommon("edit"), onClick: () => openPackageModal(pkg) },
                    { label: t("actionPreview"), onClick: () => openPreview(pkg) },
                    { label: t("actionSync"), onClick: () => void syncPackage(pkg) },
                    { label: pkg.is_active ? t("actionPause") : t("actionResume"), onClick: () => void toggleActive(pkg) },
                    { label: tCommon("delete"), onClick: () => openRemoval({ kind: "package", pkg }), danger: true },
                  ]}
                />
              </div>
              {pkg.description ? <p className="muted">{pkg.description}</p> : null}

              <div className="task-package-cycles">
                <span className="field-label">{t("cyclesTitle")}</span>
                {pkg.cycles.length === 0 ? <span className="muted">{t("noCycles")}</span> : null}
                {pkg.cycles.map((cycle) => {
                  const config = cyclesById.get(cycle.cycle_config_id);
                  const startLabel = config ? formatCycleName(config.name_pattern, cycle.start_cycle_year) : String(cycle.start_cycle_year);
                  return (
                    <span key={cycle.id} className="task-package-chip">
                      <Badge variant="info">{t("cycleChip", { cycle: cycle.cycle_config_name, start: startLabel })}</Badge>
                      <button
                        type="button"
                        className="button-icon-soft button-icon-soft-sm"
                        aria-label={t("removeCycleLabel", { cycle: cycle.cycle_config_name })}
                        title={t("removeCycleLabel", { cycle: cycle.cycle_config_name })}
                        onClick={() => openRemoval({ kind: "cycle", pkg, cycleId: cycle.id, cycleName: cycle.cycle_config_name })}
                      >
                        <ActionIcon name="close" />
                      </button>
                    </span>
                  );
                })}
                {availableCycles(pkg).length > 0 ? (
                  <button type="button" className="button-secondary button-ghost" onClick={() => openCycleModal(pkg)}>
                    {t("assignCycle")}
                  </button>
                ) : null}
              </div>

              <DataToolbar
                title={t("itemsTitle")}
                actions={
                  <button type="button" className="button-secondary" onClick={() => setItemModal({ pkg, item: null })}>
                    {t("addItem")}
                  </button>
                }
              />
              <DataTable
                columns={[
                  { key: "task", label: t("colTask") },
                  { key: "responsible", label: t("colResponsible") },
                  { key: "recurrence", label: t("colRecurrence") },
                  { key: "due", label: t("colDue") },
                  { key: "actions", label: t("colActions") },
                ]}
                emptyMessage={t("noItems")}
              >
                {pkg.items.map((item, index) => (
                  <tr key={item.id}>
                    <td>
                      <span className="todo-row-task-text">{item.task}</span>
                      {item.tags.length > 0 ? <span className="muted task-package-tags">{item.tags.join(", ")}</span> : null}
                    </td>
                    <td>
                      {item.responsible.length === 0 ? (
                        <span className="muted">{t("responsibleNone")}</span>
                      ) : (
                        item.responsible.map((entry, position) => (
                          <span key={`${entry.list_entry_id ?? entry.participant_id}-${position}`} className="task-package-responsible">
                            {responsibleLabel(entry, context, t)}
                          </span>
                        ))
                      )}
                    </td>
                    <td>{recurrenceLabel(item.recurrence, t)}</td>
                    <td>{dueRuleLabel(item.due_rule, item.recurrence, t)}</td>
                    <td>
                      <div className="task-package-row-actions">
                        <button
                          type="button"
                          className="button-icon-soft button-icon-soft-sm"
                          aria-label={t("editItemLabel", { task: item.task })}
                          title={t("editItemLabel", { task: item.task })}
                          onClick={() => setItemModal({ pkg, item })}
                        >
                          <ActionIcon name="edit" />
                        </button>
                        <ActionMenu
                          ariaLabel={t("itemActionsLabel", { task: item.task })}
                          items={[
                            ...(index > 0 ? [{ label: t("moveUp"), onClick: () => void moveItem(pkg, index, -1) }] : []),
                            ...(index < pkg.items.length - 1 ? [{ label: t("moveDown"), onClick: () => void moveItem(pkg, index, 1) }] : []),
                            { label: t("remove"), onClick: () => void deleteItem(pkg, item), danger: true },
                          ]}
                        />
                      </div>
                    </td>
                  </tr>
                ))}
              </DataTable>
            </section>
          ))}
        </div>
      )}

      <Modal open={packageModal !== null} title={packageModal?.pkg ? t("editTitle") : t("createTitle")} onClose={() => setPackageModal(null)}>
        <ModalSaveForm className="grid" onSubmit={savePackage}>
          <label className="field-stack">
            <span className="field-label">{t("nameLabel")}</span>
            <input value={packageForm.name} onChange={(event) => setPackageForm({ ...packageForm, name: event.target.value })} placeholder={t("namePlaceholder")} required autoFocus />
          </label>
          <label className="field-stack">
            <span className="field-label">{t("descriptionLabel")}</span>
            <textarea rows={3} value={packageForm.description} onChange={(event) => setPackageForm({ ...packageForm, description: event.target.value })} />
          </label>
          <label className="field-radio-option">
            <input type="checkbox" checked={packageForm.isActive} onChange={(event) => setPackageForm({ ...packageForm, isActive: event.target.checked })} />
            <span>
              <strong>{t("activeLabel")}</strong>
              <span className="field-help task-package-option-help">{t("activeHelp")}</span>
            </span>
          </label>
          <div className="modal-actions">
            <button type="button" className="button-ghost" onClick={() => setPackageModal(null)}>
              {tCommon("cancel")}
            </button>
            <button type="submit" className="button-primary" disabled={busy || !packageForm.name.trim()}>
              {packageModal?.pkg ? tCommon("save") : t("create")}
            </button>
          </div>
        </ModalSaveForm>
      </Modal>

      <Modal open={cycleModal !== null} title={t("assignTitle", { name: cycleModal?.name ?? "" })} onClose={() => setCycleModal(null)}>
        <ModalSaveForm className="grid" onSubmit={assignCycle}>
          {cycleConfigs.length === 0 ? (
            <p className="muted">{t("noCycleConfigs")}</p>
          ) : (
            <>
              <div className="field-stack">
                <span className="field-label">{t("cycleLabel")}</span>
                <SearchableSelect
                  options={cycleModal ? availableCycles(cycleModal) : []}
                  getId={(config) => config.id}
                  getLabel={(config) => config.name}
                  value={cycleForm.cycleConfigId}
                  onChange={(config) => setCycleForm({ cycleConfigId: config?.id ?? null, startYear: config ? currentCycleYear(config) : null })}
                />
              </div>
              {cycleModalConfig && cycleModalCurrent !== null ? (
                <label className="field-stack">
                  <span className="field-label">{t("startLabel")}</span>
                  <select value={cycleForm.startYear ?? cycleModalCurrent} onChange={(event) => setCycleForm({ ...cycleForm, startYear: Number(event.target.value) })}>
                    <option value={cycleModalCurrent}>{t("startCurrent", { label: formatCycleName(cycleModalConfig.name_pattern, cycleModalCurrent) })}</option>
                    <option value={cycleModalCurrent + 1}>{t("startNext", { label: formatCycleName(cycleModalConfig.name_pattern, cycleModalCurrent + 1) })}</option>
                  </select>
                  <span className="field-help">{t("assignHelp")}</span>
                </label>
              ) : null}
            </>
          )}
          <div className="modal-actions">
            <button type="button" className="button-ghost" onClick={() => setCycleModal(null)}>
              {tCommon("cancel")}
            </button>
            <button type="submit" className="button-primary" disabled={busy || !cycleForm.cycleConfigId}>
              {t("assignConfirm")}
            </button>
          </div>
        </ModalSaveForm>
      </Modal>

      <Modal
        open={removal !== null}
        title={removal?.kind === "cycle" ? t("unassignTitle", { cycle: removal.cycleName }) : t("deleteTitle", { name: removal?.pkg.name ?? "" })}
        onClose={() => setRemoval(null)}
      >
        <ModalSaveForm className="grid" onSubmit={confirmRemoval}>
          <p>{t("removalQuestion")}</p>
          <div className="task-package-mode-list" role="radiogroup" aria-label={t("removalQuestion")}>
            {DELETE_MODES.map((mode) => (
              <label key={mode} className="field-radio-option">
                <input type="radio" name="task-package-removal" value={mode} checked={removalMode === mode} onChange={() => setRemovalMode(mode)} />
                <span>
                  <strong>{t(`removalMode.${mode}`)}</strong>
                  <span className="field-help task-package-option-help">{t(`removalModeHelp.${mode}`)}</span>
                </span>
              </label>
            ))}
          </div>
          <div className="modal-actions">
            <button type="button" className="button-ghost" onClick={() => setRemoval(null)}>
              {tCommon("cancel")}
            </button>
            <button type="submit" className="button-danger" disabled={busy}>
              {removal?.kind === "cycle" ? t("unassignConfirm") : t("deleteConfirm")}
            </button>
          </div>
        </ModalSaveForm>
      </Modal>

      <Modal open={previewTarget !== null} title={t("previewTitle", { name: previewTarget?.name ?? "" })} onClose={() => setPreviewTarget(null)} size="wide">
        {previewTarget && previewTarget.cycles.length === 0 ? (
          <p className="muted">{t("noCycles")}</p>
        ) : previewTarget ? (
          <div className="grid">
            <div className="two-col">
              <label className="field-stack">
                <span className="field-label">{t("cycleLabel")}</span>
                <select
                  value={previewCycleId ?? ""}
                  onChange={(event) => {
                    const cycle = previewTarget.cycles.find((candidate) => candidate.cycle_config_id === event.target.value);
                    if (cycle) void loadPreview(previewTarget, cycle.cycle_config_id, cycle.current_cycle_year);
                  }}
                >
                  {previewTarget.cycles.map((cycle) => (
                    <option key={cycle.id} value={cycle.cycle_config_id}>
                      {cycle.cycle_config_name}
                    </option>
                  ))}
                </select>
              </label>
              {previewCycle && previewConfig ? (
                <label className="field-stack">
                  <span className="field-label">{t("previewYearLabel")}</span>
                  <select value={previewYear ?? previewCycle.current_cycle_year} onChange={(event) => void loadPreview(previewTarget, previewCycle.cycle_config_id, Number(event.target.value))}>
                    <option value={previewCycle.current_cycle_year}>
                      {t("startCurrentShort", { label: formatCycleName(previewConfig.name_pattern, previewCycle.current_cycle_year) })}
                    </option>
                    <option value={previewCycle.current_cycle_year + 1}>
                      {t("startNext", { label: formatCycleName(previewConfig.name_pattern, previewCycle.current_cycle_year + 1) })}
                    </option>
                  </select>
                </label>
              ) : null}
            </div>
            <p className="field-help">{t("previewHelp")}</p>
            <DataTable
              columns={[
                { key: "date", label: t("colDate") },
                { key: "task", label: t("colTask") },
                { key: "due", label: t("colDue") },
                { key: "responsible", label: t("colResponsible") },
                { key: "status", label: t("colStatus") },
              ]}
              emptyMessage={preview ? t("previewEmpty") : t("previewLoading")}
            >
              {(preview?.entries ?? []).map((entry) => (
                <tr key={`${entry.item_id}-${entry.occurrence_key}`}>
                  <td>{previewDate(entry.occurrence_date)}</td>
                  <td>{entry.task}</td>
                  <td>{previewDate(entry.due_date)}</td>
                  <td>{entry.assignee_names.length ? entry.assignee_names.join(", ") : <span className="muted">{t("responsibleNone")}</span>}</td>
                  <td>
                    <Badge variant={entry.exists ? "success" : "neutral"}>{entry.exists ? t("statusExists") : t("statusNew")}</Badge>
                  </td>
                </tr>
              ))}
            </DataTable>
          </div>
        ) : null}
      </Modal>

      <TaskPackageItemModal
        open={itemModal !== null}
        item={itemModal?.item ?? null}
        responsibleLists={responsibleLists}
        entriesByList={entriesByList}
        participants={participants}
        eventTags={eventTags}
        onClose={() => setItemModal(null)}
        onSave={saveItem}
      />
    </div>
  );
}
