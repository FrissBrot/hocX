"use client";

import { FormEvent, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import { DataTable } from "@/components/ui/data-table";
import { EmptyState } from "@/components/ui/empty-state";
import { FineCreateModal } from "@/components/finances/fine-create-modal";
import { restoreFine as restoreFineRequest, useFineDelete } from "@/components/finances/fine-delete";
import { TodoFineSection } from "@/components/finances/todo-fine-section";
import { Modal, ModalSaveForm } from "@/components/ui/modal";
import { StatusBanner } from "@/components/ui/status-banner";
import { FilterTabs } from "@/components/ui/filter-tabs";
import { SearchInput } from "@/components/ui/search-input";
import { browserApiFetch } from "@/lib/api/client";
import { useToast } from "@/contexts/toast-context";
import { useInfiniteScroll } from "@/lib/hooks/use-infinite-scroll";
import { fineTypeLabels } from "@/lib/constants/fine-types";
import { formatDate, formatDateTime } from "@/lib/utils/format";
import type { Locale } from "@/i18n/locale-config.generated";
import { AttendanceFineListItem, FinanceAccount, TodoFineListItem, TodoFineStatus } from "@/types/api";

const PAGE_SIZE = 50;

type SortKey = "participant_name_snapshot" | "protocol_number" | "fine_type" | "amount" | "status";

type Props = {
  initialFines: AttendanceFineListItem[];
  /** Pendenzen-Bussen (Feature todo_fines) in derselben Liste; null = Feature nicht gebucht. */
  initialTodoFines?: TodoFineListItem[] | null;
  /** false, wenn todo_fines nur noch lesbar ist (abgeschaltet). */
  todoFinesWritable?: boolean;
  accounts: FinanceAccount[];
  canWrite: boolean;
  /** Link auf die Bussen-Konfiguration (finances.read). */
  canConfigure?: boolean;
  ownOnly: boolean;
};

// Eine Zeile der gemeinsamen Liste: Anwesenheitsbusse (Protokoll) oder Pendenzen-Busse.
type Row =
  | { kind: "attendance"; key: string; fine: AttendanceFineListItem }
  | { kind: "todo"; key: string; fine: TodoFineListItem };

const TODO_STATUS_VARIANT: Record<TodoFineStatus, "neutral" | "warning" | "success" | "danger" | "info"> = {
  running: "info",
  conflict: "warning",
  pending: "neutral",
  collected: "success",
  deleted: "danger",
};

/** Laufende und strittige Pendenzen-Bussen zählen wie offene Bussen («Offen»). */
function bucket(row: Row): "pending" | "collected" | "deleted" {
  if (row.kind === "attendance") return row.fine.status as "pending" | "collected" | "deleted";
  return row.fine.status === "collected" ? "collected" : row.fine.status === "deleted" ? "deleted" : "pending";
}

export function FinesView({ initialFines, initialTodoFines = null, todoFinesWritable = true, accounts, canWrite, canConfigure = false, ownOnly }: Props) {
  const t = useTranslations("finances");
  const tCommon = useTranslations("common");
  const fineTypeLabel = useMemo(() => fineTypeLabels(t), [t]);
  const locale = useLocale();
  const router = useRouter();
  const showToast = useToast();
  const [fines, setFines] = useState<AttendanceFineListItem[]>(initialFines);
  const [statusFilter, setStatusFilter] = useState<"pending" | "collected" | "deleted" | "all">("pending");
  const [search, setSearch] = useState("");
  const [busy, setBusy] = useState<Record<string, boolean>>({});
  const [sortKey, setSortKey] = useState<SortKey>("participant_name_snapshot");
  const [sortDirection, setSortDirection] = useState<"asc" | "desc">("asc");
  const [hasMore, setHasMore] = useState(initialFines.length === PAGE_SIZE);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const { requestDelete, dialog: deleteDialog } = useFineDelete();
  const [todoFines, setTodoFines] = useState<TodoFineListItem[]>(initialTodoFines ?? []);
  const [waiveTarget, setWaiveTarget] = useState<TodoFineListItem | null>(null);
  const [waiveReason, setWaiveReason] = useState("");
  const [resolveTarget, setResolveTarget] = useState<TodoFineListItem | null>(null);
  const canWriteTodo = canWrite && todoFinesWritable;

  const accountMap = new Map(accounts.map((a) => [a.id, a]));

  async function loadMore() {
    setIsLoadingMore(true);
    try {
      const next = await browserApiFetch<AttendanceFineListItem[]>(`/api/fines?skip=${fines.length}&limit=${PAGE_SIZE}`);
      setFines((current) => [...current, ...(next ?? [])]);
      setHasMore((next ?? []).length === PAGE_SIZE);
    } finally {
      setIsLoadingMore(false);
    }
  }

  const loadMoreSentinelRef = useInfiniteScroll({
    hasMore,
    isLoading: isLoadingMore,
    onLoadMore: () => void loadMore(),
  });

  function toggleSort(key: SortKey) {
    setSortKey((cur) => {
      if (cur === key) { setSortDirection((d) => d === "asc" ? "desc" : "asc"); return cur; }
      setSortDirection("asc");
      return key;
    });
  }

  const rows = useMemo<Row[]>(() => [
    ...fines.map((fine) => ({ kind: "attendance" as const, key: `a-${fine.id}`, fine })),
    ...todoFines.map((fine, index) => ({
      kind: "todo" as const,
      key: fine.id ? `t-${fine.id}` : `t-${fine.status}-${fine.todo_id}-${fine.participant_id}-${index}`,
      fine,
    })),
  ], [fines, todoFines]);

  const rowName = (row: Row) => (row.kind === "attendance" ? row.fine.participant_name_snapshot : row.fine.participant_name ?? "");
  const rowSource = (row: Row) => (row.kind === "attendance" ? row.fine.protocol_number ?? "" : row.fine.task);
  const rowReason = (row: Row) => (row.kind === "attendance" ? fineTypeLabel[row.fine.fine_type] ?? row.fine.fine_type : t("todoFineReason"));

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    const dir = sortDirection === "asc" ? 1 : -1;
    return rows
      .filter((row) => {
        const matchStatus = statusFilter === "all" || bucket(row) === statusFilter;
        const matchSearch = !q || [rowName(row), rowSource(row), rowReason(row), row.kind === "todo" ? row.fine.rule_name ?? "" : ""]
          .some((value) => value.toLowerCase().includes(q));
        return matchStatus && matchSearch;
      })
      .sort((a, b) => {
        if (sortKey === "amount") return (a.fine.amount - b.fine.amount) * dir;
        if (sortKey === "fine_type") return rowReason(a).localeCompare(rowReason(b)) * dir;
        if (sortKey === "protocol_number") return rowSource(a).localeCompare(rowSource(b)) * dir;
        if (sortKey === "status") return bucket(a).localeCompare(bucket(b)) * dir;
        return rowName(a).localeCompare(rowName(b)) * dir;
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows, statusFilter, search, sortKey, sortDirection]);

  // Counts only reflect the currently loaded page(s), not the tenant-wide total, once
  // pagination kicks in (hasMore === true) — same trade-off as the other paginated lists
  // in this app (search/sort/filter also only ever operate on what's already loaded).
  const counts = useMemo(() => ({
    pending: rows.filter((row) => bucket(row) === "pending").length,
    collected: rows.filter((row) => bucket(row) === "collected").length,
    deleted: rows.filter((row) => bucket(row) === "deleted").length,
  }), [rows]);
  const conflicts = todoFines.filter((fine) => fine.status === "conflict").length;

  async function reloadTodoFines() {
    if (initialTodoFines === null) return;
    try {
      setTodoFines(await browserApiFetch<TodoFineListItem[]>("/api/todo-fines"));
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("reloadFailed"), "error");
    }
  }

  async function actTodo(fine: TodoFineListItem, action: "collect" | "reopen" | "restore") {
    if (!fine.id) return;
    const id = fine.id;
    setBusy((b) => ({ ...b, [id]: true }));
    try {
      const updated = await browserApiFetch<TodoFineListItem>(`/api/todo-fines/${id}/${action}`, { method: "POST" });
      setTodoFines((current) => current.map((item) => (item.id === updated.id ? updated : item)));
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("todoFines.actionFailed"), "error");
    } finally {
      setBusy((b) => ({ ...b, [id]: false }));
    }
  }

  async function waiveTodo(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!waiveTarget?.id || !waiveReason.trim()) return;
    const id = waiveTarget.id;
    setBusy((b) => ({ ...b, [id]: true }));
    try {
      const updated = await browserApiFetch<TodoFineListItem>(`/api/todo-fines/${id}/waive`, {
        method: "POST",
        body: JSON.stringify({ reason: waiveReason.trim() }),
      });
      setTodoFines((current) => current.map((item) => (item.id === updated.id ? updated : item)));
      setWaiveTarget(null);
      setWaiveReason("");
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("todoFines.actionFailed"), "error");
    } finally {
      setBusy((b) => ({ ...b, [id]: false }));
    }
  }

  async function collectFine(fine: AttendanceFineListItem) {
    setBusy((b) => ({ ...b, [fine.id]: true }));
    try {
      const updated = await browserApiFetch<AttendanceFineListItem>(`/api/fines/${fine.id}/collect`, { method: "POST" });
      if (updated) setFines((prev) => prev.map((f) => f.id === updated.id ? { ...f, ...updated } : f));
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("collectFailed"), "error");
    } finally {
      setBusy((b) => ({ ...b, [fine.id]: false }));
    }
  }

  async function deleteFine(fine: AttendanceFineListItem) {
    const outcome = await requestDelete(fine);
    if (outcome === "hard") setFines((prev) => prev.filter((f) => f.id !== fine.id));
    // Mit Begründung gelöscht: Status, Begründung und Protokoll kommen vom Server.
    else if (outcome === "soft") await reloadFines();
  }

  async function restoreFine(fine: AttendanceFineListItem) {
    setBusy((b) => ({ ...b, [fine.id]: true }));
    try {
      const updated = await restoreFineRequest(fine.id);
      setFines((prev) => prev.map((f) => f.id === updated.id ? { ...f, ...updated } : f));
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("restoreFineFailed"), "error");
    } finally {
      setBusy((b) => ({ ...b, [fine.id]: false }));
    }
  }

  async function reopenFine(fine: AttendanceFineListItem) {
    setBusy((b) => ({ ...b, [fine.id]: true }));
    try {
      const updated = await browserApiFetch<AttendanceFineListItem>(`/api/fines/${fine.id}/reopen`, { method: "POST" });
      if (updated) setFines((prev) => prev.map((f) => f.id === updated.id ? { ...f, ...updated } : f));
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("reopenFailed"), "error");
    } finally {
      setBusy((b) => ({ ...b, [fine.id]: false }));
    }
  }

  async function reloadFines() {
    try {
      const latest = await browserApiFetch<AttendanceFineListItem[]>(`/api/fines?limit=${PAGE_SIZE}`);
      setFines(latest ?? []);
      setHasMore((latest ?? []).length === PAGE_SIZE);
      setCreateOpen(false);
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("reloadFailed"), "error");
    }
  }

  const hasNoFines = rows.length === 0 && !hasMore;
  const canCreate = canWrite && accounts.length > 0;

  const sd = (key: SortKey) => (sortKey === key ? sortDirection : null);

  function renderTodoRow(fine: TodoFineListItem, key: string) {
    const isCollected = fine.status === "collected";
    const isClosed = isCollected || fine.status === "deleted";
    const account = fine.account_id ? accountMap.get(fine.account_id) : undefined;
    const cur = fine.currency_label ?? account?.currency_label ?? "";
    const isBusy = fine.id ? busy[fine.id] : false;
    return (
      <tr key={key} className={isClosed ? "table-row-done" : ""}>
        {canWrite && (
          <td>
            {fine.status === "pending" || isCollected ? (
              <button
                type="button"
                className={`todo-check${isCollected ? " todo-check-done" : ""}`}
                title={isCollected ? t("alreadyCollected") : t("markCollected")}
                disabled={isBusy || isClosed || !canWriteTodo}
                onClick={() => !isClosed && void actTodo(fine, "collect")}
              >
                {isCollected ? (
                  <svg viewBox="0 0 16 16" fill="none"><rect x="1" y="1" width="14" height="14" rx="4" fill="currentColor"/><path d="M4.5 8.5l2.5 2.5 4.5-4.5" stroke="var(--on-solid)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/></svg>
                ) : (
                  <svg viewBox="0 0 16 16" fill="none"><rect x="1" y="1" width="14" height="14" rx="4" strokeWidth="1.5"/></svg>
                )}
              </button>
            ) : null}
          </td>
        )}
        <td><strong>{fine.participant_name ?? "—"}</strong>{fine.tariff_name ? <div className="muted">{fine.tariff_name}</div> : null}</td>
        <td>
          {fine.task}
          <div className="muted">
            {fine.due_date ? formatDate(fine.due_date) : "—"}
            {fine.completed_on ? ` · ${t("todoFines.completedOn", { date: formatDate(fine.completed_on) })}` : ""}
          </div>
        </td>
        <td>
          {t("todoFineReason")}
          <div className="muted">
            {t("todoFines.daysLate", { count: fine.days_late })}
            {" · "}
            {fine.status === "conflict" ? fine.matching_rules.map((rule) => rule.name).join(", ") : fine.rule_name ?? t("todoFines.fixedAmount")}
          </div>
        </td>
        <td>{account?.name ?? "—"}</td>
        <td>{fine.status === "conflict" ? "—" : `${fine.amount.toFixed(2)} ${cur}`.trim()}</td>
        <td>
          <Badge variant={TODO_STATUS_VARIANT[fine.status]}>{t(`todoFines.status.${fine.status}`)}</Badge>
          {fine.status === "deleted" && fine.delete_comment ? <div className="muted fines-collected-note">{fine.delete_comment}</div> : null}
          {isCollected && fine.collected_by_display_name ? <div className="muted fines-collected-note">{fine.collected_by_display_name}</div> : null}
          {fine.status === "running" ? <div className="muted fines-collected-note">{t("todoFineRunningHint")}</div> : null}
          {fine.status === "conflict" ? <div className="muted fines-collected-note">{t("todoFines.conflictHint")}</div> : null}
        </td>
        {canWrite && (
          <td>
            {canWriteTodo ? (
              <div className="table-actions table-actions-start">
                {fine.status === "pending" ? (
                  <button type="button" className="row-text-action row-text-action-danger" disabled={isBusy} onClick={() => { setWaiveReason(""); setWaiveTarget(fine); }}>
                    {t("todoFines.waive")}
                  </button>
                ) : null}
                {isCollected && fine.can_reopen ? (
                  <button type="button" className="row-text-action" disabled={isBusy} onClick={() => void actTodo(fine, "reopen")}>{t("reopen")}</button>
                ) : null}
                {fine.status === "deleted" ? (
                  <button type="button" className="row-text-action" disabled={isBusy} onClick={() => void actTodo(fine, "restore")}>{t("restoreFine")}</button>
                ) : null}
                {fine.status === "conflict" && fine.todo_id ? (
                  <button type="button" className="row-text-action" onClick={() => setResolveTarget(fine)}>{t("todoFines.resolve")}</button>
                ) : null}
              </div>
            ) : null}
          </td>
        )}
      </tr>
    );
  }

  return (
    <div className="grid">
      <div className="page-header">
        <div>
          <h1 className="page-title">{t("finesPageTitle")}</h1>
          <p className="muted">{ownOnly ? t("ownOnlyDescription") : t("allDescription")}</p>
        </div>
        {canConfigure && !ownOnly ? (
          <Link className="button-secondary" href="/fine-settings">{t("fineSettings.openSettings")}</Link>
        ) : null}
      </div>
      {initialTodoFines !== null && !todoFinesWritable ? <StatusBanner tone="neutral" message={t("todoFines.readOnlyNotice")} /> : null}
      {conflicts !== 0 && !ownOnly ? <StatusBanner tone="error" message={t("todoFines.conflictBanner", { count: conflicts })} /> : null}

      {hasNoFines ? (
        <EmptyState
          title={t("noFinesTitle")}
          description={t("noFinesDescription")}
          actions={
            canCreate ? (
              <button type="button" className="button-primary" onClick={() => setCreateOpen(true)}>
                {t("addFine")}
              </button>
            ) : null
          }
          hint={t("noFinesHint")}
        />
      ) : (
      <>
      <div className="list-filter-row">
        <FilterTabs
          options={[
            { value: "pending", label: t("filterPending"), count: counts.pending || undefined },
            { value: "collected", label: t("filterCollected"), count: counts.collected || undefined },
            ...(counts.deleted ? [{ value: "deleted" as const, label: t("filterDeleted"), count: counts.deleted }] : []),
            { value: "all", label: t("filterAll") },
          ]}
          value={statusFilter}
          onChange={setStatusFilter}
        />
        <div className="list-filter-search">
          <SearchInput value={search} onChange={setSearch} placeholder={t("finesSearchPlaceholder")} />
        </div>
      </div>

      <DataTable
        className="data-table-lg"
        columns={[
          ...(canWrite ? [{ key: "collect", label: "" }] : []),
          { key: "participant_name_snapshot", label: t("colParticipant"), sortable: true, sortDirection: sd("participant_name_snapshot"), onSort: () => toggleSort("participant_name_snapshot") },
          { key: "protocol_number", label: t("colSource"), sortable: true, sortDirection: sd("protocol_number"), onSort: () => toggleSort("protocol_number") },
          { key: "fine_type", label: t("colReason"), sortable: true, sortDirection: sd("fine_type"), onSort: () => toggleSort("fine_type") },
          t("colAccount"),
          { key: "amount", label: t("colAmount"), sortable: true, sortDirection: sd("amount"), onSort: () => toggleSort("amount") },
          { key: "status", label: t("colStatus"), sortable: true, sortDirection: sd("status"), onSort: () => toggleSort("status") },
          ...(canWrite ? [tCommon("actions")] : []),
        ]}
        emptyMessage={t("emptyFines")}
      >
        {filtered.map((row) => {
          if (row.kind === "todo") return renderTodoRow(row.fine, row.key);
          const fine = row.fine;
          const isCollected = fine.status === "collected";
          const isDeleted = fine.status === "deleted";
          const isClosed = isCollected || isDeleted;
          const account = accountMap.get(fine.account_id);
          const cur = fine.currency_label ?? account?.currency_label ?? "";
          return (
            <tr key={row.key} className={isClosed ? "table-row-done" : ""}>
              {canWrite && (
                <td>
                  <button
                    type="button"
                    className={`todo-check${isCollected ? " todo-check-done" : ""}`}
                    title={isCollected ? t("alreadyCollected") : t("markCollected")}
                    disabled={busy[fine.id] || isClosed}
                    onClick={() => !isClosed && void collectFine(fine)}
                  >
                    {isCollected ? (
                      <svg viewBox="0 0 16 16" fill="none"><rect x="1" y="1" width="14" height="14" rx="4" fill="currentColor"/><path d="M4.5 8.5l2.5 2.5 4.5-4.5" stroke="var(--on-solid)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/></svg>
                    ) : (
                      <svg viewBox="0 0 16 16" fill="none"><rect x="1" y="1" width="14" height="14" rx="4" strokeWidth="1.5"/></svg>
                    )}
                  </button>
                </td>
              )}
              <td><strong>{fine.participant_name_snapshot}</strong></td>
              <td>
                <button type="button" className="todo-protocol-link" onClick={() => router.push(`/protocols/${fine.protocol_id}`)}>
                  <span className="todo-protocol-num">{fine.protocol_number ?? "—"}</span>
                  {fine.protocol_date ? <span className="todo-protocol-title">{formatDate(fine.protocol_date)}</span> : null}
                </button>
              </td>
              <td>{fineTypeLabel[fine.fine_type] ?? fine.fine_type}</td>
              <td>{account?.name ?? t("unknownAccount")}</td>
              <td>{fine.amount.toFixed(2)} {cur}</td>
              <td>
                {isDeleted ? (
                  <Badge variant="danger">{t("statusDeleted")}</Badge>
                ) : (
                  <Badge variant={isCollected ? "success" : "neutral"}>{isCollected ? t("statusCollected") : t("statusPending")}</Badge>
                )}
                {isDeleted && fine.deleted_at ? (
                  <div className="muted fines-collected-note">
                    {fine.deleted_by_display_name
                      ? t("deletedNoteWithUser", { date: formatDateTime(fine.deleted_at, locale as Locale), user: fine.deleted_by_display_name, reason: fine.delete_comment ?? "" })
                      : t("deletedNote", { date: formatDateTime(fine.deleted_at, locale as Locale), reason: fine.delete_comment ?? "" })}
                  </div>
                ) : null}
                {isCollected && fine.collected_at ? (
                  <div className="muted fines-collected-note">
                    {fine.collected_by_display_name
                      ? t("collectedNoteWithUser", { date: formatDateTime(fine.collected_at, locale as Locale), user: fine.collected_by_display_name })
                      : t("collectedNote", { date: formatDateTime(fine.collected_at, locale as Locale) })}
                  </div>
                ) : null}
              </td>
              {canWrite && (
                <td>
                  <div className="table-actions table-actions-start">
                    {!isClosed && (
                      <button type="button" className="row-text-action row-text-action-danger" onClick={() => void deleteFine(fine)}>
                        {tCommon("delete")}
                      </button>
                    )}
                    {isDeleted && fine.can_restore && (
                      <button type="button" className="row-text-action" disabled={busy[fine.id]} onClick={() => void restoreFine(fine)}>
                        {t("restoreFine")}
                      </button>
                    )}
                    {isCollected && fine.can_reopen && (
                      <button type="button" className="row-text-action" disabled={busy[fine.id]} onClick={() => void reopenFine(fine)}>
                        {t("reopen")}
                      </button>
                    )}
                  </div>
                </td>
              )}
            </tr>
          );
        })}
      </DataTable>
      </>
      )}

      {hasMore && (
        <div className="load-more-row" ref={loadMoreSentinelRef}>
          {isLoadingMore ? (
            <span className="muted">{t("loadingMoreFines")}</span>
          ) : (
            <button type="button" className="button-secondary button-ghost" onClick={() => void loadMore()}>
              {t("loadMoreFines", { count: fines.length })}
            </button>
          )}
        </div>
      )}

      {deleteDialog}
      <Modal open={resolveTarget !== null} onClose={() => { setResolveTarget(null); void reloadTodoFines(); }} title={resolveTarget?.task ?? ""}>
        {resolveTarget?.todo_id ? <TodoFineSection todoId={resolveTarget.todo_id} /> : null}
      </Modal>
      <Modal open={waiveTarget !== null} onClose={() => setWaiveTarget(null)} title={t("todoFines.waiveTitle")}
        description={waiveTarget ? t("todoFines.waiveDescription", { name: waiveTarget.participant_name ?? "", task: waiveTarget.task }) : undefined}>
        <ModalSaveForm className="grid" onSubmit={waiveTodo}>
          <label className="field-stack">
            <span className="field-label">{t("todoFines.waiveReason")}</span>
            <textarea value={waiveReason} maxLength={1000} rows={3} autoFocus onChange={(event) => setWaiveReason(event.target.value)} />
          </label>
          <div className="modal-actions">
            <button type="button" className="button-ghost" onClick={() => setWaiveTarget(null)}>{tCommon("cancel")}</button>
            <button data-modal-save type="submit" className="button-danger" disabled={!waiveReason.trim()}>{t("todoFines.waive")}</button>
          </div>
        </ModalSaveForm>
      </Modal>
      <FineCreateModal open={createOpen} accounts={accounts} onClose={() => setCreateOpen(false)} onCreated={() => void reloadFines()} />
    </div>
  );
}
