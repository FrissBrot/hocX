"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import { Badge } from "@/components/ui/badge";
import { DataTable } from "@/components/ui/data-table";
import { FilterTabs } from "@/components/ui/filter-tabs";
import { SearchInput } from "@/components/ui/search-input";
import { browserApiFetch } from "@/lib/api/client";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { useInfiniteScroll } from "@/lib/hooks/use-infinite-scroll";
import { FINE_TYPE_LABEL } from "@/lib/constants/fine-types";
import { formatDate, formatDateTime } from "@/lib/utils/format";
import { AttendanceFineListItem, FinanceAccount } from "@/types/api";

const PAGE_SIZE = 50;

type SortKey = "participant_name_snapshot" | "protocol_number" | "fine_type" | "amount" | "status";

type Props = {
  initialFines: AttendanceFineListItem[];
  accounts: FinanceAccount[];
  isAdmin: boolean;
};

export function FinesView({ initialFines, accounts, isAdmin }: Props) {
  const router = useRouter();
  const confirm = useConfirm();
  const showToast = useToast();
  const [fines, setFines] = useState<AttendanceFineListItem[]>(initialFines);
  const [statusFilter, setStatusFilter] = useState<"pending" | "collected" | "all">("pending");
  const [search, setSearch] = useState("");
  const [busy, setBusy] = useState<Record<string, boolean>>({});
  const [sortKey, setSortKey] = useState<SortKey>("participant_name_snapshot");
  const [sortDirection, setSortDirection] = useState<"asc" | "desc">("asc");
  const [hasMore, setHasMore] = useState(initialFines.length === PAGE_SIZE);
  const [isLoadingMore, setIsLoadingMore] = useState(false);

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
          (statusFilter === "pending" ? f.status === "pending" : f.status === "collected");
        const matchSearch =
          !q ||
          f.participant_name_snapshot.toLowerCase().includes(q) ||
          (f.protocol_number ?? "").toLowerCase().includes(q) ||
          (FINE_TYPE_LABEL[f.fine_type] ?? f.fine_type).toLowerCase().includes(q);
        return matchStatus && matchSearch;
      })
      .sort((a, b) => {
        if (sortKey === "amount") return (a.amount - b.amount) * dir;
        if (sortKey === "fine_type") return (FINE_TYPE_LABEL[a.fine_type] ?? "").localeCompare(FINE_TYPE_LABEL[b.fine_type] ?? "") * dir;
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
  }), [fines]);

  async function collectFine(fine: AttendanceFineListItem) {
    setBusy((b) => ({ ...b, [fine.id]: true }));
    try {
      const updated = await browserApiFetch<AttendanceFineListItem>(`/api/fines/${fine.id}/collect`, { method: "POST" });
      if (updated) setFines((prev) => prev.map((f) => f.id === updated.id ? { ...f, ...updated } : f));
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Busse konnte nicht kassiert werden", "error");
    } finally {
      setBusy((b) => ({ ...b, [fine.id]: false }));
    }
  }

  async function deleteFine(fine: AttendanceFineListItem) {
    if (!(await confirm({ message: `Busse von ${fine.participant_name_snapshot} löschen?`, tone: "danger", confirmLabel: "Löschen" }))) return;
    try {
      await browserApiFetch(`/api/fines/${fine.id}`, { method: "DELETE" });
      setFines((prev) => prev.filter((f) => f.id !== fine.id));
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Busse konnte nicht gelöscht werden", "error");
    }
  }

  async function reopenFine(fine: AttendanceFineListItem) {
    setBusy((b) => ({ ...b, [fine.id]: true }));
    try {
      const updated = await browserApiFetch<AttendanceFineListItem>(`/api/fines/${fine.id}/reopen`, { method: "POST" });
      if (updated) setFines((prev) => prev.map((f) => f.id === updated.id ? { ...f, ...updated } : f));
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Busse konnte nicht zurückgesetzt werden", "error");
    } finally {
      setBusy((b) => ({ ...b, [fine.id]: false }));
    }
  }

  const sd = (key: SortKey) => (sortKey === key ? sortDirection : null);

  return (
    <div className="grid">
      <div className="page-header">
        <div>
          <h1 className="page-title">Bussen</h1>
          <p className="muted">Alle Verspätungs- und Absenzbussen dieses Mandanten.</p>
        </div>
      </div>

      <div className="list-filter-row">
        <FilterTabs
          options={[
            { value: "pending", label: "Ausstehend", count: counts.pending || undefined },
            { value: "collected", label: "Kassiert", count: counts.collected || undefined },
            { value: "all", label: "Alle" },
          ]}
          value={statusFilter}
          onChange={setStatusFilter}
        />
        <div className="list-filter-search">
          <SearchInput value={search} onChange={setSearch} placeholder="Bussen durchsuchen" />
        </div>
      </div>

      <DataTable
        className="data-table-lg"
        columns={[
          ...(isAdmin ? [{ key: "collect", label: "" }] : []),
          { key: "participant_name_snapshot", label: "Teilnehmer", sortable: true, sortDirection: sd("participant_name_snapshot"), onSort: () => toggleSort("participant_name_snapshot") },
          { key: "protocol_number", label: "Protokoll", sortable: true, sortDirection: sd("protocol_number"), onSort: () => toggleSort("protocol_number") },
          { key: "fine_type", label: "Grund", sortable: true, sortDirection: sd("fine_type"), onSort: () => toggleSort("fine_type") },
          "Konto",
          { key: "amount", label: "Betrag", sortable: true, sortDirection: sd("amount"), onSort: () => toggleSort("amount") },
          { key: "status", label: "Status", sortable: true, sortDirection: sd("status"), onSort: () => toggleSort("status") },
          ...(isAdmin ? ["Aktionen"] : []),
        ]}
        emptyMessage="Keine Bussen gefunden."
      >
        {filtered.map((fine) => {
          const isCollected = fine.status === "collected";
          const account = accountMap.get(fine.account_id);
          const cur = fine.currency_label ?? account?.currency_label ?? "";
          return (
            <tr key={fine.id} className={isCollected ? "table-row-done" : ""}>
              {isAdmin && (
                <td>
                  <button
                    type="button"
                    className={`todo-check${isCollected ? " todo-check-done" : ""}`}
                    title={isCollected ? "Bereits kassiert" : "Busse kassieren"}
                    disabled={busy[fine.id] || isCollected}
                    onClick={() => !isCollected && void collectFine(fine)}
                  >
                    {isCollected ? (
                      <svg viewBox="0 0 16 16" fill="none"><rect x="1" y="1" width="14" height="14" rx="4" fill="currentColor"/><path d="M4.5 8.5l2.5 2.5 4.5-4.5" stroke="#fff" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/></svg>
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
              <td>{FINE_TYPE_LABEL[fine.fine_type] ?? fine.fine_type}</td>
              <td>{account?.name ?? `Konto ${fine.account_id}`}</td>
              <td>{fine.amount.toFixed(2)} {cur}</td>
              <td>
                <Badge variant={isCollected ? "success" : "neutral"}>{isCollected ? "Kassiert" : "Ausstehend"}</Badge>
                {isCollected && fine.collected_at ? (
                  <div className="muted fines-collected-note">
                    {formatDateTime(fine.collected_at)}
                    {fine.collected_by_display_name ? ` von ${fine.collected_by_display_name}` : ""}
                  </div>
                ) : null}
              </td>
              {isAdmin && (
                <td>
                  <div className="table-actions table-actions-start">
                    {!isCollected && (
                      <button type="button" className="row-text-action row-text-action-danger" onClick={() => void deleteFine(fine)}>
                        Löschen
                      </button>
                    )}
                    {isCollected && fine.can_reopen && (
                      <button type="button" className="row-text-action" disabled={busy[fine.id]} onClick={() => void reopenFine(fine)}>
                        Rückgängig
                      </button>
                    )}
                  </div>
                </td>
              )}
            </tr>
          );
        })}
      </DataTable>

      {hasMore && (
        <div className="load-more-row" ref={loadMoreSentinelRef}>
          {isLoadingMore ? (
            <span className="muted">Lädt weitere Bussen…</span>
          ) : (
            <button type="button" className="button-inline button-ghost" onClick={() => void loadMore()}>
              Mehr laden ({fines.length} geladen)
            </button>
          )}
        </div>
      )}
    </div>
  );
}
