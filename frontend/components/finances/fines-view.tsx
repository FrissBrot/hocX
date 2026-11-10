"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import { DataTable } from "@/components/ui/data-table";
import { EmptyState } from "@/components/ui/empty-state";
import { FineCreateModal } from "@/components/finances/fine-create-modal";
import { restoreFine as restoreFineRequest, useFineDelete } from "@/components/finances/fine-delete";
import { FineTariffModal } from "@/components/finances/fine-tariff-modal";
import { FilterTabs } from "@/components/ui/filter-tabs";
import { SearchInput } from "@/components/ui/search-input";
import { browserApiFetch } from "@/lib/api/client";
import { useToast } from "@/contexts/toast-context";
import { useInfiniteScroll } from "@/lib/hooks/use-infinite-scroll";
import { fineTypeLabels } from "@/lib/constants/fine-types";
import { formatDate, formatDateTime } from "@/lib/utils/format";
import type { Locale } from "@/i18n/locale-config.generated";
import { AttendanceFineListItem, FinanceAccount, FineTariff } from "@/types/api";

const PAGE_SIZE = 50;

type SortKey = "participant_name_snapshot" | "protocol_number" | "fine_type" | "amount" | "status";

type Props = {
  initialFines: AttendanceFineListItem[];
  accounts: FinanceAccount[];
  canWrite: boolean;
  ownOnly: boolean;
};

export function FinesView({ initialFines, accounts, canWrite, ownOnly }: Props) {
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
  const [tariff, setTariff] = useState<FineTariff | null>(null);
  const [tariffOpen, setTariffOpen] = useState(false);
  const { requestDelete, dialog: deleteDialog } = useFineDelete();

  useEffect(() => {
    if (ownOnly) return;
    let cancelled = false;
    browserApiFetch<FineTariff>("/api/fines/tariff")
      .then((loaded) => { if (!cancelled) setTariff(loaded); })
      .catch(() => { if (!cancelled) setTariff(null); });
    return () => { cancelled = true; };
  }, [ownOnly]);

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

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    const dir = sortDirection === "asc" ? 1 : -1;
    return fines
      .filter((f) => {
        const matchStatus =
          statusFilter === "all" ||
          f.status === statusFilter;
        const matchSearch =
          !q ||
          f.participant_name_snapshot.toLowerCase().includes(q) ||
          (f.protocol_number ?? "").toLowerCase().includes(q) ||
          (fineTypeLabel[f.fine_type] ?? f.fine_type).toLowerCase().includes(q);
        return matchStatus && matchSearch;
      })
      .sort((a, b) => {
        if (sortKey === "amount") return (a.amount - b.amount) * dir;
        if (sortKey === "fine_type") return (fineTypeLabel[a.fine_type] ?? "").localeCompare(fineTypeLabel[b.fine_type] ?? "") * dir;
        if (sortKey === "protocol_number") return (a.protocol_number ?? "").localeCompare(b.protocol_number ?? "") * dir;
        if (sortKey === "status") return a.status.localeCompare(b.status) * dir;
        return a.participant_name_snapshot.localeCompare(b.participant_name_snapshot) * dir;
      });
  }, [fines, statusFilter, search, sortKey, sortDirection]);

  // Counts only reflect the currently loaded page(s), not the tenant-wide total, once
  // pagination kicks in (hasMore === true) — same trade-off as the other paginated lists
  // in this app (search/sort/filter also only ever operate on what's already loaded).
  const counts = useMemo(() => ({
    pending: fines.filter((f) => f.status === "pending").length,
    collected: fines.filter((f) => f.status === "collected").length,
    deleted: fines.filter((f) => f.status === "deleted").length,
  }), [fines]);

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

  const hasNoFines = fines.length === 0 && !hasMore;
  const canCreate = canWrite && accounts.length > 0;

  const sd = (key: SortKey) => (sortKey === key ? sortDirection : null);

  return (
    <div className="grid">
      <div className="page-header">
        <div>
          <h1 className="page-title">{t("finesPageTitle")}</h1>
          <p className="muted">{ownOnly ? t("ownOnlyDescription") : t("allDescription")}</p>
          {tariff ? (
            <p className="muted">
              {tariff.account_id
                ? t("tariffSummary", {
                    late: tariff.amount_late.toFixed(2),
                    absent: tariff.amount_absent.toFixed(2),
                    account: accountMap.get(tariff.account_id)?.name ?? t("unknownAccount"),
                  })
                : t("tariffNotSet")}
            </p>
          ) : null}
        </div>
        {canWrite && tariff ? (
          <button type="button" className="button-secondary" onClick={() => setTariffOpen(true)}>
            {t("tariffButton")}
          </button>
        ) : null}
      </div>
      {tariff ? (
        <FineTariffModal open={tariffOpen} tariff={tariff} accounts={accounts} onClose={() => setTariffOpen(false)} onSaved={setTariff} />
      ) : null}

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
          { key: "protocol_number", label: t("colProtocol"), sortable: true, sortDirection: sd("protocol_number"), onSort: () => toggleSort("protocol_number") },
          { key: "fine_type", label: t("colReason"), sortable: true, sortDirection: sd("fine_type"), onSort: () => toggleSort("fine_type") },
          t("colAccount"),
          { key: "amount", label: t("colAmount"), sortable: true, sortDirection: sd("amount"), onSort: () => toggleSort("amount") },
          { key: "status", label: t("colStatus"), sortable: true, sortDirection: sd("status"), onSort: () => toggleSort("status") },
          ...(canWrite ? [tCommon("actions")] : []),
        ]}
        emptyMessage={t("emptyFines")}
      >
        {filtered.map((fine) => {
          const isCollected = fine.status === "collected";
          const isDeleted = fine.status === "deleted";
          const isClosed = isCollected || isDeleted;
          const account = accountMap.get(fine.account_id);
          const cur = fine.currency_label ?? account?.currency_label ?? "";
          return (
            <tr key={fine.id} className={isClosed ? "table-row-done" : ""}>
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
      <FineCreateModal open={createOpen} accounts={accounts} onClose={() => setCreateOpen(false)} onCreated={() => void reloadFines()} />
    </div>
  );
}
