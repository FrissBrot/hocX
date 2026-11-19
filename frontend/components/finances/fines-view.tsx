"use client";

import { FormEvent, ReactNode, useMemo, useState } from "react";
import Link from "next/link";
import type { Route } from "next";
import { useLocale, useTranslations } from "next-intl";

import { Badge, type BadgeVariant } from "@/components/ui/badge";
import { DataTable } from "@/components/ui/data-table";
import { EmptyState } from "@/components/ui/empty-state";
import { FineCreateModal } from "@/components/finances/fine-create-modal";
import { restoreFine as restoreFineRequest, useFineDelete } from "@/components/finances/fine-delete";
import { TodoFineSection } from "@/components/finances/todo-fine-section";
import { KasseHeader } from "@/components/finances/kasse-header";
import {
  FINES_PAGE_SIZE,
  buildRows,
  bucket,
  computeKpis,
  countBuckets,
  filterRows,
  groupByPerson,
  initials,
  isCollectible,
  rowAmount,
  rowName,
  rowSource,
  type FineRow,
  type FineRowStatus,
  type FineStatusFilter,
} from "@/components/finances/fines-model";
import { Modal, ModalSaveForm } from "@/components/ui/modal";
import { StatusBanner } from "@/components/ui/status-banner";
import { FilterTabs } from "@/components/ui/filter-tabs";
import { SearchInput } from "@/components/ui/search-input";
import { HelpPopover } from "@/components/ui/help-popover";
import { browserApiFetch } from "@/lib/api/client";
import { useToast } from "@/contexts/toast-context";
import { useConfirm } from "@/contexts/confirm-context";
import { useInfiniteScroll } from "@/lib/hooks/use-infinite-scroll";
import { fineTypeLabels } from "@/lib/constants/fine-types";
import { formatDate, formatMoney } from "@/lib/utils/format";
import { financeErrorMessage } from "@/components/finances/finance-errors";
import { AttendanceFineListItem, FinanceAccount, TodoFineListItem } from "@/types/api";


type SortKey = "name" | "source" | "reason" | "amount" | "status";
type ViewMode = "person" | "list";

type Props = {
  initialFines: AttendanceFineListItem[];
  /** Pendenzen-Bussen (Feature todo_fines) in derselben Liste; null = Feature nicht gebucht. */
  initialTodoFines?: TodoFineListItem[] | null;
  /** false, wenn todo_fines nur noch lesbar ist (abgeschaltet). */
  todoFinesWritable?: boolean;
  accounts: FinanceAccount[];
  canWrite: boolean;
  ownOnly: boolean;
  /** Feature «finance» nach Downgrade nur noch lesend: Hinweisbanner. */
  readOnly?: boolean;
  /** Reiter «Konten» anzeigen (finances.read). */
  showAccountsTab?: boolean;
  /** Vereinswährung (Mandanten-Einstellungen) für Summen ohne eigene Währung. */
  currency?: string;
};

const STATUS_VARIANT: Record<FineRowStatus, BadgeVariant> = {
  running: "info",
  conflict: "warning",
  pending: "neutral",
  collected: "success",
  deleted: "danger",
};

function CheckIcon() {
  return (
    <svg viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path d="M4 8.5l2.5 2.5L12 5.5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function FinesView({
  initialFines,
  initialTodoFines = null,
  todoFinesWritable = true,
  accounts,
  canWrite,
  ownOnly,
  readOnly = false,
  showAccountsTab = false,
  currency: tenantCurrency = "",
}: Props) {
  const t = useTranslations("finances");
  const tCommon = useTranslations("common");
  const fineTypeLabel = useMemo(() => fineTypeLabels(t), [t]);
  const locale = useLocale();
  const showToast = useToast();
  const confirm = useConfirm();
  const [fines, setFines] = useState<AttendanceFineListItem[]>(initialFines);
  const [todoFines, setTodoFines] = useState<TodoFineListItem[]>(initialTodoFines ?? []);
  const [statusFilter, setStatusFilter] = useState<FineStatusFilter>("pending");
  const [conflictsOnly, setConflictsOnly] = useState(false);
  const [search, setSearch] = useState("");
  const [view, setView] = useState<ViewMode>("person");
  const [busy, setBusy] = useState<Record<string, boolean>>({});
  const [sortKey, setSortKey] = useState<SortKey>("name");
  const [sortDirection, setSortDirection] = useState<"asc" | "desc">("asc");
  const [hasMore, setHasMore] = useState(initialFines.length === FINES_PAGE_SIZE);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const { requestDelete, dialog: deleteDialog } = useFineDelete();
  const [waiveTarget, setWaiveTarget] = useState<TodoFineListItem | null>(null);
  const [waiveReason, setWaiveReason] = useState("");
  const [resolveTarget, setResolveTarget] = useState<TodoFineListItem | null>(null);
  const canWriteTodo = canWrite && todoFinesWritable;
  const currentYear = new Date().getFullYear();

  const accountMap = useMemo(() => new Map(accounts.map((a) => [a.id, a])), [accounts]);

  async function loadMore() {
    setIsLoadingMore(true);
    try {
      const next = await browserApiFetch<AttendanceFineListItem[]>(`/api/fines?skip=${fines.length}&limit=${FINES_PAGE_SIZE}`);
      setFines((current) => [...current, ...(next ?? [])]);
      setHasMore((next ?? []).length === FINES_PAGE_SIZE);
    } catch (error) {
      showToast(financeErrorMessage(error, t, "reloadFailed"), "error");
    } finally {
      setIsLoadingMore(false);
    }
  }

  const loadMoreSentinelRef = useInfiniteScroll({
    hasMore,
    isLoading: isLoadingMore,
    onLoadMore: () => void loadMore(),
  });

  const rows = useMemo(() => buildRows(fines, todoFines), [fines, todoFines]);
  const reasonLabel = (row: FineRow) => (row.kind === "attendance" ? fineTypeLabel[row.fine.fine_type] ?? row.fine.fine_type : t("todoFineReason"));
  const accountOf = (row: FineRow) => (row.fine.account_id ? accountMap.get(row.fine.account_id) : undefined);
  const currencyOf = (row: FineRow) => row.fine.currency_label ?? accountOf(row)?.currency_label ?? tenantCurrency;
  const money = (amount: number, currency: string) => formatMoney(amount, currency, locale, { currencyFirst: true });
  const sumCurrency = rows.find((row) => row.fine.currency_label)?.fine.currency_label ?? tenantCurrency;

  const filtered = useMemo(() => {
    const dir = sortDirection === "asc" ? 1 : -1;
    return filterRows(rows, {
      status: statusFilter,
      search,
      conflictsOnly,
      searchText: (row) => [reasonLabel(row), accountOf(row)?.name ?? ""],
    }).sort((a, b) => {
      if (sortKey === "amount") return (rowAmount(a) - rowAmount(b)) * dir;
      if (sortKey === "reason") return reasonLabel(a).localeCompare(reasonLabel(b), locale) * dir;
      if (sortKey === "source") return rowSource(a).localeCompare(rowSource(b), locale) * dir;
      if (sortKey === "status") return a.fine.status.localeCompare(b.fine.status) * dir;
      return rowName(a).localeCompare(rowName(b), locale) * dir;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows, statusFilter, search, conflictsOnly, sortKey, sortDirection, accountMap, locale]);

  const groups = useMemo(() => groupByPerson(filtered, locale), [filtered, locale]);
  // Zähler und Kennzahlen beruhen auf allem Geladenen (bei mehr als FINES_PAGE_SIZE Präsenz-Bussen
  // nur auf den geladenen Seiten - wie Suche und Sortierung).
  const counts = useMemo(() => countBuckets(rows), [rows]);
  const kpis = useMemo(() => computeKpis(rows, currentYear), [rows, currentYear]);
  const conflicts = todoFines.filter((fine) => fine.status === "conflict").length;

  function toggleSort(key: SortKey) {
    if (sortKey === key) {
      setSortDirection((d) => (d === "asc" ? "desc" : "asc"));
      return;
    }
    setSortKey(key);
    setSortDirection("asc");
  }

  function setBusyFor(ids: (string | null)[], value: boolean) {
    setBusy((current) => {
      const next = { ...current };
      for (const id of ids) if (id) next[id] = value;
      return next;
    });
  }

  function replaceRow(updated: FineRow) {
    if (updated.kind === "attendance") {
      setFines((prev) => prev.map((f) => (f.id === updated.fine.id ? { ...f, ...updated.fine } : f)));
    } else {
      setTodoFines((prev) => prev.map((f) => (f.id === updated.fine.id ? updated.fine : f)));
    }
  }

  async function postAction(row: FineRow, action: "collect" | "reopen" | "restore"): Promise<FineRow> {
    if (row.kind === "attendance") {
      const updated = action === "restore"
        ? await restoreFineRequest(row.fine.id)
        : await browserApiFetch<AttendanceFineListItem>(`/api/fines/${row.fine.id}/${action}`, { method: "POST" });
      const merged: FineRow = { ...row, fine: { ...row.fine, ...updated } };
      replaceRow(merged);
      return merged;
    }
    const updated = await browserApiFetch<TodoFineListItem>(`/api/todo-fines/${row.fine.id}/${action}`, { method: "POST" });
    const merged: FineRow = { ...row, fine: updated };
    replaceRow(merged);
    return merged;
  }

  function actionError(error: unknown, action: "collect" | "reopen" | "restore", row: FineRow): string {
    if (row.kind === "todo") return error instanceof Error && error.message ? error.message : t("todoFines.actionFailed");
    const fallback = action === "collect" ? "collectFailed" : action === "reopen" ? "reopenFailed" : "restoreFineFailed";
    return financeErrorMessage(error, t, fallback);
  }

  /** Führt eine Aktion für mehrere Zeilen nacheinander aus (kein Bulk-Endpunkt nötig); bricht beim
   * ersten Fehler ab und liefert, was geklappt hat. */
  async function runSequential(targets: FineRow[], action: "collect" | "reopen" | "restore"): Promise<FineRow[]> {
    const done: FineRow[] = [];
    const ids = targets.map((row) => row.fine.id);
    setBusyFor(ids, true);
    try {
      for (const row of targets) {
        try {
          done.push(await postAction(row, action));
        } catch (error) {
          showToast(actionError(error, action, row), "error");
          break;
        }
      }
    } finally {
      setBusyFor(ids, false);
    }
    return done;
  }

  const undoLabel = t("kasse.undo");

  async function collect(targets: FineRow[], name: string) {
    const done = await runSequential(targets.filter(isCollectible), "collect");
    if (done.length === 0) return;
    const total = done.reduce((sum, row) => sum + rowAmount(row), 0);
    const undoable = done.filter((row) => row.fine.can_reopen);
    showToast(
      t("kasse.toast.collected", { name, amount: money(total, currencyOf(done[0])) }),
      "success",
      undoable.length ? { action: { label: undoLabel, onClick: () => void undo(undoable, "reopen", name) } } : undefined,
    );
  }

  /** Rückgängig im Toast: nur die serverseitige Gegenaktion (kassiert → wieder öffnen,
   * gelöscht/erlassen → wiederherstellen, wieder geöffnet → kassieren). */
  async function undo(targets: FineRow[], action: "collect" | "reopen" | "restore", name: string) {
    const done = await runSequential(targets, action);
    if (done.length) showToast(t("kasse.toast.undone", { name }), "info");
  }

  /** Wieder öffnen löscht die Finanzbuchung der Einkassierung: immer nachfragen (Audit Bereich 03). */
  async function reopen(row: FineRow) {
    const ok = await confirm({
      message: t("reopenConfirm", { name: rowName(row) || "—", amount: formatMoney(rowAmount(row), currencyOf(row), locale) }),
      tone: "danger",
      confirmLabel: t("kasse.action.reopen"),
    });
    if (!ok) return;
    const [done] = await runSequential([row], "reopen");
    if (!done) return;
    showToast(t("kasse.toast.reopened", { name: rowName(done) }), "success", {
      action: { label: undoLabel, onClick: () => void undo([done], "collect", rowName(done)) },
    });
  }

  async function restore(row: FineRow) {
    const [done] = await runSequential([row], "restore");
    if (done) showToast(t("kasse.toast.restored", { name: rowName(done) }), "success");
  }

  async function deleteAttendance(row: Extract<FineRow, { kind: "attendance" }>) {
    const outcome = await requestDelete(row.fine);
    const name = row.fine.participant_name_snapshot;
    if (outcome === "hard") {
      // Im offenen Ursprungsprotokoll endgültig gelöscht: serverseitig nicht wiederherstellbar.
      setFines((prev) => prev.filter((f) => f.id !== row.fine.id));
      showToast(t("kasse.toast.deleted", { name }), "success");
    } else if (outcome === "soft") {
      // Mit Begründung gelöscht: Status, Begründung und Protokoll kommen vom Server.
      await reloadFines();
      showToast(t("kasse.toast.deleted", { name }), "success", {
        action: { label: undoLabel, onClick: () => void undo([row], "restore", name) },
      });
    }
  }

  async function waiveTodo(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!waiveTarget?.id || !waiveReason.trim()) return;
    const id = waiveTarget.id;
    setBusyFor([id], true);
    try {
      const updated = await browserApiFetch<TodoFineListItem>(`/api/todo-fines/${id}/waive`, {
        method: "POST",
        body: JSON.stringify({ reason: waiveReason.trim() }),
      });
      const row: FineRow = { kind: "todo", key: `t-${id}`, fine: updated };
      replaceRow(row);
      setWaiveTarget(null);
      setWaiveReason("");
      const name = updated.participant_name ?? "—";
      showToast(t("kasse.toast.waived", { name }), "success", {
        action: { label: undoLabel, onClick: () => void undo([row], "restore", name) },
      });
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("todoFines.actionFailed"), "error");
    } finally {
      setBusyFor([id], false);
    }
  }

  async function reloadFines() {
    try {
      const latest = await browserApiFetch<AttendanceFineListItem[]>(`/api/fines?limit=${FINES_PAGE_SIZE}`);
      setFines(latest ?? []);
      setHasMore((latest ?? []).length === FINES_PAGE_SIZE);
      setCreateOpen(false);
    } catch (error) {
      showToast(financeErrorMessage(error, t, "reloadFailed"), "error");
    }
  }

  async function reloadTodoFines() {
    if (initialTodoFines === null) return;
    try {
      setTodoFines(await browserApiFetch<TodoFineListItem[]>("/api/todo-fines"));
    } catch (error) {
      showToast(financeErrorMessage(error, t, "reloadFailed"), "error");
    }
  }

  const hasNoFines = rows.length === 0 && !hasMore;
  const canCreate = canWrite && accounts.length > 0;
  const rowWritable = (row: FineRow) => (row.kind === "todo" ? canWriteTodo : canWrite);

  // ── Zellen (gleich in «Nach Person» und «Liste») ─────────────────────────────

  function renderCheck(row: FineRow): ReactNode {
    const status = row.fine.status;
    if (status !== "pending" && status !== "collected") return null;
    const collected = status === "collected";
    const isBusy = row.fine.id ? busy[row.fine.id] : false;
    return (
      <button
        type="button"
        className={`kasse-check${collected ? " kasse-check-done" : ""}`}
        title={collected ? t("alreadyCollected") : t("kasse.markCollected")}
        aria-label={collected ? t("alreadyCollected") : t("kasse.markCollectedFor", { name: rowName(row) })}
        aria-pressed={collected}
        disabled={collected || isBusy || !rowWritable(row) || !isCollectible(row)}
        onClick={() => void collect([row], rowName(row))}
      >
        <CheckIcon />
      </button>
    );
  }

  function renderSource(row: FineRow): ReactNode {
    const account = accountOf(row);
    if (row.kind === "attendance") {
      return (
        <div className="kasse-cell">
          <span className="kasse-source">
            <Link className="kasse-source-link" href={`/protocols/${row.fine.protocol_id}` as Route}>{row.fine.protocol_number ?? "—"}</Link>
            {row.fine.protocol_date ? <span className="muted"> {formatDate(row.fine.protocol_date)}</span> : null}
          </span>
          <span className="kasse-sub">{t("kasse.sourceProtocol", { account: account?.name ?? t("unknownAccount") })}</span>
        </div>
      );
    }
    return (
      <div className="kasse-cell">
        <span className="kasse-source">
          <strong>{row.fine.task}</strong>
          {row.fine.due_date ? <span className="muted"> {t("kasse.due", { date: formatDate(row.fine.due_date).slice(0, 6) })}</span> : null}
        </span>
        <span className="kasse-sub">{t("kasse.sourceTodo", { account: account?.name ?? "—" })}</span>
      </div>
    );
  }

  function renderReason(row: FineRow): ReactNode {
    let detail: string | null = null;
    if (row.kind === "todo") {
      const rule = row.fine.status === "conflict"
        ? row.fine.matching_rules.map((r) => r.name).join(", ")
        : row.fine.rule_name ? t("kasse.ruleName", { name: row.fine.rule_name }) : t("todoFines.fixedAmount");
      detail = t("kasse.reasonDetail", { days: t("todoFines.daysLate", { count: row.fine.days_late }), rule });
      if (row.fine.completed_on) detail = `${detail} · ${t("todoFines.completedOn", { date: formatDate(row.fine.completed_on) })}`;
    }
    return (
      <div className="kasse-cell">
        <span>{reasonLabel(row)}</span>
        {detail ? <span className="kasse-sub">{detail}</span> : null}
      </div>
    );
  }

  function renderAmount(row: FineRow): ReactNode {
    const deleted = row.fine.status === "deleted";
    return (
      <span className={`kasse-amount${deleted ? " kasse-amount-struck" : ""}`}>
        {row.fine.status === "conflict" ? "—" : money(row.fine.amount, currencyOf(row))}
      </span>
    );
  }

  function statusHint(row: FineRow): string | null {
    const fine = row.fine;
    if (fine.status === "running") return t("kasse.hint.running");
    if (fine.status === "conflict" && row.kind === "todo") return t("todoFines.todo.v2.rulesMatch", { count: row.fine.matching_rules.length });
    if (fine.status === "collected" && fine.collected_at) {
      const date = formatDate(fine.collected_at).slice(0, 6);
      return fine.collected_by_display_name ? t("kasse.hint.collectedBy", { date, user: fine.collected_by_display_name }) : date;
    }
    if (fine.status === "deleted") {
      if (fine.delete_comment) return fine.delete_comment;
      return fine.deleted_at ? formatDate(fine.deleted_at).slice(0, 6) : null;
    }
    return null;
  }

  function renderStatus(row: FineRow): ReactNode {
    const hint = statusHint(row);
    return (
      <div className="kasse-cell">
        <Badge variant={STATUS_VARIANT[row.fine.status]}>{t(`kasse.status.${row.fine.status}`)}</Badge>
        {hint ? <span className="kasse-sub" title={hint}>{hint}</span> : null}
      </div>
    );
  }

  function renderAction(row: FineRow): ReactNode {
    if (!rowWritable(row)) return null;
    const fine = row.fine;
    const isBusy = fine.id ? busy[fine.id] : false;
    if (fine.status === "pending") {
      if (row.kind === "attendance") {
        return <button type="button" className="row-text-action row-text-action-danger" disabled={isBusy} onClick={() => void deleteAttendance(row)}>{t("kasse.action.delete")}</button>;
      }
      return <button type="button" className="row-text-action row-text-action-danger" disabled={isBusy} onClick={() => { setWaiveReason(""); setWaiveTarget(row.fine); }}>{t("kasse.action.waive")}</button>;
    }
    if (fine.status === "collected" && fine.can_reopen) {
      return <button type="button" className="row-text-action" disabled={isBusy} onClick={() => void reopen(row)}>{t("kasse.action.reopen")}</button>;
    }
    if (fine.status === "deleted" && (row.kind === "todo" || row.fine.can_restore)) {
      return <button type="button" className="row-text-action" disabled={isBusy} onClick={() => void restore(row)}>{t("kasse.action.restore")}</button>;
    }
    if (fine.status === "conflict" && row.kind === "todo" && row.fine.todo_id) {
      const target = row.fine;
      return <button type="button" className="row-text-action" onClick={() => setResolveTarget(target)}>{t("kasse.action.chooseRule")}</button>;
    }
    return null;
  }

  // ── Leerzustand im Filter ────────────────────────────────────────────────────

  function renderFilteredEmpty() {
    const [title, text] = search.trim()
      ? [t("kasse.empty.searchTitle"), t("kasse.empty.searchText")]
      : statusFilter === "pending" && !conflictsOnly
        ? [t("kasse.empty.openTitle"), t("kasse.empty.openText")]
        : [t("kasse.empty.filterTitle"), t("kasse.empty.filterText")];
    return (
      <div className="kasse-empty" role="status">
        <strong>{title}</strong>
        <span className="muted">{text}</span>
      </div>
    );
  }

  function renderPersonView() {
    return (
      <div className="kasse-people">
        {groups.map((group) => {
          const more = group.rows.length - group.openCount;
          const summary = [
            group.tariff,
            group.openCount ? t("kasse.person.open", { count: group.openCount }) : t("kasse.person.nothingOpen"),
            more > 0 ? t("kasse.person.more", { count: more }) : null,
          ].filter(Boolean).join(" · ");
          const collectible = group.collectible.filter(rowWritable);
          return (
            <section key={group.key} className="kasse-person" aria-label={group.name}>
              <header className="kasse-person-head">
                <span className="kasse-avatar" aria-hidden="true">{initials(group.name)}</span>
                <div className="kasse-person-name">
                  <strong>{group.name}</strong>
                  <span className="kasse-sub">{summary}</span>
                </div>
                <div className="kasse-person-total">
                  {group.openCount ? <span className="kasse-person-sum">{money(group.openAmount, sumCurrency)}</span> : null}
                  {collectible.length > 0 ? (
                    <button
                      type="button"
                      className="button-primary kasse-collect-button"
                      disabled={collectible.some((row) => row.fine.id && busy[row.fine.id])}
                      onClick={() => void collect(collectible, group.name)}
                    >
                      <CheckIcon />
                      {collectible.length === 1 ? t("kasse.collect") : t("kasse.collectAll")}
                    </button>
                  ) : null}
                </div>
              </header>
              <ul className="kasse-rows">
                {group.rows.map((row) => (
                  <li key={row.key} className={`kasse-row${bucket(row) !== "pending" ? " kasse-row-done" : ""}`}>
                    <span className="kasse-row-check">{canWrite ? renderCheck(row) : null}</span>
                    {renderSource(row)}
                    {renderReason(row)}
                    <span className="kasse-row-amount">{renderAmount(row)}</span>
                    {renderStatus(row)}
                    <span className="kasse-row-action">{renderAction(row)}</span>
                  </li>
                ))}
              </ul>
            </section>
          );
        })}
      </div>
    );
  }

  function renderListView() {
    const sd = (key: SortKey) => (sortKey === key ? sortDirection : null);
    return (
      <DataTable
        className="data-table-lg kasse-table"
        columns={[
          ...(canWrite ? [{ key: "collect", label: "" }] : []),
          { key: "name", label: t("colParticipant"), sortable: true, sortDirection: sd("name"), onSort: () => toggleSort("name") },
          { key: "source", label: t("colSource"), sortable: true, sortDirection: sd("source"), onSort: () => toggleSort("source") },
          { key: "reason", label: t("colReason"), sortable: true, sortDirection: sd("reason"), onSort: () => toggleSort("reason") },
          t("colAccount"),
          { key: "amount", label: t("colAmount"), sortable: true, sortDirection: sd("amount"), onSort: () => toggleSort("amount") },
          { key: "status", label: t("colStatus"), sortable: true, sortDirection: sd("status"), onSort: () => toggleSort("status") },
          ...(canWrite ? [tCommon("actions")] : []),
        ]}
      >
        {filtered.map((row) => {
          const tariff = row.kind === "todo" ? row.fine.tariff_name : null;
          return (
            <tr key={row.key} className={bucket(row) !== "pending" ? "table-row-done" : ""}>
              {canWrite ? <td>{renderCheck(row)}</td> : null}
              <td><div className="kasse-cell"><strong>{rowName(row) || "—"}</strong>{tariff ? <span className="kasse-sub">{tariff}</span> : null}</div></td>
              <td>{renderSource(row)}</td>
              <td>{renderReason(row)}</td>
              <td>{accountOf(row)?.name ?? (row.kind === "attendance" ? t("unknownAccount") : "—")}</td>
              <td>{renderAmount(row)}</td>
              <td>{renderStatus(row)}</td>
              {canWrite ? <td>{renderAction(row)}</td> : null}
            </tr>
          );
        })}
      </DataTable>
    );
  }

  return (
    <div className="grid kasse">
      <KasseHeader
        active="/fines"
        showAccountsTab={showAccountsTab}
        openCount={counts.pending}
        lead={ownOnly ? t("ownOnlyDescription") : t("kasse.leadFines")}
        titleExtra={<HelpPopover topic={t("finesHelpTopic")} docs={{ page: "finanzen", anchor: "bussen-einkassieren" }}>{t("finesHelp")}</HelpPopover>}
        actions={canCreate && !hasNoFines ? (
          <button type="button" className="button-secondary" onClick={() => setCreateOpen(true)}>{t("addFine")}</button>
        ) : null}
      />
      {readOnly ? <StatusBanner tone="neutral" message={t("readOnlyBanner")} /> : null}
      {initialTodoFines !== null && !todoFinesWritable ? <StatusBanner tone="neutral" message={t("todoFines.readOnlyNotice")} /> : null}

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
          <dl className="kasse-kpis">
            <div className="kasse-kpi">
              <dt>{t("kasse.kpi.open")}</dt>
              <dd className="kasse-kpi-value">{money(kpis.openAmount, sumCurrency)}</dd>
              <dd className="kasse-sub">{t("kasse.kpi.fines", { count: kpis.openCount })}</dd>
            </div>
            <div className="kasse-kpi">
              <dt>{t("kasse.kpi.collected", { year: String(currentYear) })}</dt>
              <dd className="kasse-kpi-value kasse-kpi-success">{money(kpis.collectedAmount, sumCurrency)}</dd>
              <dd className="kasse-sub">{t("kasse.kpi.fines", { count: kpis.collectedCount })}</dd>
            </div>
            <div className="kasse-kpi">
              <dt>{t("kasse.kpi.people")}</dt>
              <dd className="kasse-kpi-value">{kpis.peopleOpen}</dd>
              <dd className="kasse-sub">{t("kasse.kpi.ofTotal", { count: kpis.peopleTotal })}</dd>
            </div>
          </dl>

          {conflicts !== 0 && !ownOnly ? (
            <div className="kasse-conflict" role="alert">
              <span className="kasse-conflict-icon" aria-hidden="true">!</span>
              <div className="kasse-conflict-text">
                <strong>{t("kasse.conflict.title", { count: conflicts })}</strong>
                <span>{t("kasse.conflict.text")}</span>
              </div>
              <button type="button" className="button-secondary" onClick={() => { setConflictsOnly(true); setStatusFilter("pending"); setSearch(""); }}>
                {t("kasse.conflict.show")}
              </button>
            </div>
          ) : null}

          <div className="kasse-toolbar">
            <FilterTabs
              options={[
                { value: "pending", label: t("kasse.filter.open"), count: counts.pending },
                { value: "collected", label: t("kasse.filter.collected"), count: counts.collected },
                ...(counts.deleted ? [{ value: "deleted" as const, label: t("kasse.filter.deleted"), count: counts.deleted }] : []),
                { value: "all", label: t("kasse.filter.all") },
              ]}
              value={statusFilter}
              onChange={(value) => { setStatusFilter(value); setConflictsOnly(false); }}
            />
            <div className="kasse-search">
              <SearchInput value={search} onChange={setSearch} placeholder={t("kasse.searchPlaceholder")} aria-label={t("kasse.searchPlaceholder")} />
            </div>
            {conflictsOnly ? (
              <button type="button" className="button-pill kasse-conflict-chip" onClick={() => setConflictsOnly(false)} aria-label={t("kasse.conflict.clear")}>
                {t("kasse.conflict.onlyConflicts")}
              </button>
            ) : null}
            <div className="kasse-view-toggle">
              <span className="kasse-view-label">{t("kasse.view.label")}</span>
              <FilterTabs
                options={[{ value: "person", label: t("kasse.view.person") }, { value: "list", label: t("kasse.view.list") }]}
                value={view}
                onChange={setView}
              />
            </div>
          </div>

          {filtered.length === 0 ? renderFilteredEmpty() : view === "person" ? renderPersonView() : renderListView()}
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
