"use client";

import { FormEvent, useMemo, useState } from "react";
import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import { DataTable } from "@/components/ui/data-table";
import { FilterTabs } from "@/components/ui/filter-tabs";
import { Modal, ModalSaveForm } from "@/components/ui/modal";
import { SearchInput } from "@/components/ui/search-input";
import { StatusBanner } from "@/components/ui/status-banner";
import { Tabs } from "@/components/ui/tabs";
import { TodoFineRules } from "@/components/finances/todo-fine-rules";
import { TodoFineTariffs } from "@/components/finances/todo-fine-tariffs";
import { TodoFineSection } from "@/components/finances/todo-fine-section";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import { formatDate } from "@/lib/utils/format";
import type { FinanceAccount, FineTariffGroup, TodoFineListItem, TodoFineRule, TodoFineStatus } from "@/types/api";

type Filter = "running" | "conflict" | "pending" | "collected" | "deleted" | "all";

type Props = {
  initialFines: TodoFineListItem[];
  initialRules: TodoFineRule[];
  initialTariffs: FineTariffGroup[];
  accounts: FinanceAccount[];
  canManage: boolean;
  canReadSettings: boolean;
  ownOnly: boolean;
  readOnly: boolean;
};

const STATUS_VARIANT: Record<TodoFineStatus, "neutral" | "warning" | "success" | "danger" | "info"> = {
  running: "info",
  conflict: "warning",
  pending: "neutral",
  collected: "success",
  deleted: "danger",
};

/** Pendenzen-Bussen: Liste (laufend, Konflikte, eingefroren), Regeln und Tarife. */
export function TodoFinesView({ initialFines, initialRules, initialTariffs, accounts, canManage, canReadSettings, ownOnly, readOnly }: Props) {
  const t = useTranslations("finances");
  const [fines, setFines] = useState(initialFines);
  const [rules, setRules] = useState(initialRules);
  const [tariffs, setTariffs] = useState(initialTariffs);
  const conflicts = fines.filter((fine) => fine.status === "conflict").length;
  const showConflictBanner = conflicts > 0 && !ownOnly;

  async function reload() {
    setFines(await browserApiFetch<TodoFineListItem[]>("/api/todo-fines"));
  }

  const list = <TodoFineList fines={fines} setFines={setFines} accounts={accounts} canManage={canManage && !readOnly} onReload={reload} />;
  return (
    <div className="grid">
      <div className="page-header">
        <div>
          <h1 className="page-title">{t("todoFines.pageTitle")}</h1>
          <p className="muted">{ownOnly ? t("todoFines.ownOnlyDescription") : t("todoFines.description")}</p>
        </div>
      </div>
      {readOnly ? <StatusBanner tone="neutral" message={t("todoFines.readOnlyNotice")} /> : null}
      {showConflictBanner ? <StatusBanner tone="error" message={t("todoFines.conflictBanner", { count: conflicts })} /> : null}
      {canReadSettings ? (
        <Tabs
          tabs={[
            { id: "fines", label: t("todoFines.tabFines"), content: list },
            {
              id: "rules",
              label: t("todoFines.tabRules"),
              content: <TodoFineRules rules={rules} setRules={setRules} tariffs={tariffs} accounts={accounts} canManage={canManage && !readOnly} onChanged={reload} />,
            },
            ...(canManage
              ? [{ id: "tariffs", label: t("todoFines.tabTariffs"), content: <TodoFineTariffs tariffs={tariffs} setTariffs={setTariffs} canManage={!readOnly} onChanged={reload} /> }]
              : []),
          ]}
        />
      ) : list}
    </div>
  );
}

function TodoFineList({ fines, setFines, accounts, canManage, onReload }: {
  fines: TodoFineListItem[];
  setFines: (update: (current: TodoFineListItem[]) => TodoFineListItem[]) => void;
  accounts: FinanceAccount[];
  canManage: boolean;
  onReload: () => Promise<void>;
}) {
  const t = useTranslations("finances");
  const tCommon = useTranslations("common");
  const showToast = useToast();
  const [filter, setFilter] = useState<Filter>("running");
  const [search, setSearch] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [waiveTarget, setWaiveTarget] = useState<TodoFineListItem | null>(null);
  const [reason, setReason] = useState("");
  const [resolveTarget, setResolveTarget] = useState<TodoFineListItem | null>(null);
  const accountMap = useMemo(() => new Map(accounts.map((account) => [account.id, account])), [accounts]);

  const counts = useMemo(() => {
    const result: Record<string, number> = {};
    for (const fine of fines) result[fine.status] = (result[fine.status] ?? 0) + 1;
    return result;
  }, [fines]);

  const visible = useMemo(() => {
    const query = search.trim().toLowerCase();
    return fines.filter((fine) => (filter === "all" || fine.status === filter) && (!query
      || fine.task.toLowerCase().includes(query)
      || (fine.participant_name ?? "").toLowerCase().includes(query)
      || (fine.rule_name ?? "").toLowerCase().includes(query)));
  }, [fines, filter, search]);

  async function act(fine: TodoFineListItem, action: "collect" | "reopen" | "restore") {
    if (!fine.id) return;
    setBusy(fine.id);
    try {
      const updated = await browserApiFetch<TodoFineListItem>(`/api/todo-fines/${fine.id}/${action}`, { method: "POST" });
      setFines((current) => current.map((item) => item.id === updated.id ? updated : item));
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("todoFines.actionFailed"), "error");
    } finally {
      setBusy(null);
    }
  }

  async function waive(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!waiveTarget?.id || !reason.trim()) return;
    setBusy(waiveTarget.id);
    try {
      const updated = await browserApiFetch<TodoFineListItem>(`/api/todo-fines/${waiveTarget.id}/waive`, {
        method: "POST",
        body: JSON.stringify({ reason: reason.trim() }),
      });
      setFines((current) => current.map((item) => item.id === updated.id ? updated : item));
      setWaiveTarget(null);
      setReason("");
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("todoFines.actionFailed"), "error");
    } finally {
      setBusy(null);
    }
  }

  const options: { value: Filter; label: string; count?: number }[] = [
    { value: "running", label: t("todoFines.filterRunning"), count: counts.running || undefined },
    ...(counts.conflict ? [{ value: "conflict" as const, label: t("todoFines.filterConflict"), count: counts.conflict }] : []),
    { value: "pending", label: t("todoFines.filterPending"), count: counts.pending || undefined },
    { value: "collected", label: t("todoFines.filterCollected"), count: counts.collected || undefined },
    ...(counts.deleted ? [{ value: "deleted" as const, label: t("todoFines.filterDeleted"), count: counts.deleted }] : []),
    { value: "all", label: t("todoFines.filterAll") },
  ];

  return (
    <div className="grid">
      <div className="list-filter-row">
        <FilterTabs options={options} value={filter} onChange={setFilter} />
        <div className="list-filter-search">
          <SearchInput value={search} onChange={setSearch} placeholder={t("todoFines.searchPlaceholder")} />
        </div>
        <button type="button" className="button-secondary button-ghost" onClick={() => void onReload()}>{t("todoFines.refresh")}</button>
      </div>
      <DataTable
        className="data-table-lg"
        columns={[
          t("todoFines.colPerson"),
          t("todoFines.colTask"),
          t("todoFines.colDue"),
          t("todoFines.colDaysLate"),
          t("todoFines.colRule"),
          t("todoFines.colAmount"),
          t("todoFines.colStatus"),
          ...(canManage ? [tCommon("actions")] : []),
        ]}
        emptyMessage={t("todoFines.empty")}
      >
        {visible.map((fine, index) => {
          const currency = fine.currency_label ?? (fine.account_id ? accountMap.get(fine.account_id)?.currency_label : "") ?? "";
          return (
            <tr key={fine.id ?? `${fine.status}-${fine.todo_id}-${fine.participant_id}-${index}`} className={fine.status === "collected" || fine.status === "deleted" ? "table-row-done" : ""}>
              <td><strong>{fine.participant_name ?? "—"}</strong>{fine.tariff_name ? <div className="muted">{fine.tariff_name}</div> : null}</td>
              <td>{fine.task}</td>
              <td>{fine.due_date ? formatDate(fine.due_date) : "—"}{fine.completed_on ? <div className="muted">{t("todoFines.completedOn", { date: formatDate(fine.completed_on) })}</div> : null}</td>
              <td>{t("todoFines.daysLate", { count: fine.days_late })}</td>
              <td>
                {fine.status === "conflict"
                  ? <span className="muted">{fine.matching_rules.map((rule) => rule.name).join(", ")}</span>
                  : fine.rule_name ?? <span className="muted">{t("todoFines.fixedAmount")}</span>}
              </td>
              <td>{fine.status === "conflict" ? "—" : `${fine.amount.toFixed(2)} ${currency}`.trim()}</td>
              <td>
                <Badge variant={STATUS_VARIANT[fine.status]}>{t(`todoFines.status.${fine.status}`)}</Badge>
                {fine.status === "deleted" && fine.delete_comment ? <div className="muted fines-collected-note">{fine.delete_comment}</div> : null}
                {fine.status === "collected" && fine.collected_by_display_name ? <div className="muted fines-collected-note">{fine.collected_by_display_name}</div> : null}
                {fine.status === "conflict" ? <div className="muted fines-collected-note">{t("todoFines.conflictHint")}</div> : null}
              </td>
              {canManage ? (
                <td>
                  <div className="table-actions table-actions-start">
                    {fine.status === "pending" ? <>
                      <button type="button" className="row-text-action" disabled={busy === fine.id} onClick={() => void act(fine, "collect")}>{t("todoFines.collect")}</button>
                      <button type="button" className="row-text-action row-text-action-danger" disabled={busy === fine.id} onClick={() => { setReason(""); setWaiveTarget(fine); }}>{t("todoFines.waive")}</button>
                    </> : null}
                    {fine.status === "collected" && fine.can_reopen ? <button type="button" className="row-text-action" disabled={busy === fine.id} onClick={() => void act(fine, "reopen")}>{t("todoFines.reopen")}</button> : null}
                    {fine.status === "deleted" ? <button type="button" className="row-text-action" disabled={busy === fine.id} onClick={() => void act(fine, "restore")}>{t("todoFines.restore")}</button> : null}
                    {fine.status === "conflict" && fine.todo_id ? <button type="button" className="row-text-action" onClick={() => setResolveTarget(fine)}>{t("todoFines.resolve")}</button> : null}
                  </div>
                </td>
              ) : null}
            </tr>
          );
        })}
      </DataTable>
      <Modal open={resolveTarget !== null} onClose={() => { setResolveTarget(null); void onReload(); }} title={resolveTarget?.task ?? ""}>
        {resolveTarget?.todo_id ? <TodoFineSection todoId={resolveTarget.todo_id} /> : null}
      </Modal>
      <Modal open={waiveTarget !== null} onClose={() => setWaiveTarget(null)} title={t("todoFines.waiveTitle")}
        description={waiveTarget ? t("todoFines.waiveDescription", { name: waiveTarget.participant_name ?? "", task: waiveTarget.task }) : undefined}>
        <ModalSaveForm className="grid" onSubmit={waive}>
          <label className="field-stack">
            <span className="field-label">{t("todoFines.waiveReason")}</span>
            <textarea value={reason} maxLength={1000} rows={3} autoFocus onChange={(event) => setReason(event.target.value)} />
          </label>
          <div className="modal-actions">
            <button type="button" className="button-ghost" onClick={() => setWaiveTarget(null)}>{tCommon("cancel")}</button>
            <button data-modal-save type="submit" className="button-danger" disabled={!reason.trim() || busy !== null}>{t("todoFines.waive")}</button>
          </div>
        </ModalSaveForm>
      </Modal>
    </div>
  );
}
