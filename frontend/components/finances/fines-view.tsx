"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import { DataTable } from "@/components/ui/data-table";
import { browserApiFetch } from "@/lib/api/client";
import { formatDate, formatDateTime } from "@/lib/utils/format";
import { AttendanceFineListItem, FinanceAccount } from "@/types/api";

const FINE_TYPE_LABEL: Record<string, string> = {
  late: "Verspätet",
  absent: "Unentschuldigt",
};

type SortKey = "participant_name_snapshot" | "protocol_number" | "fine_type" | "amount" | "status";

type Props = {
  initialFines: AttendanceFineListItem[];
  accounts: FinanceAccount[];
  isAdmin: boolean;
};

export function FinesView({ initialFines, accounts, isAdmin }: Props) {
  const router = useRouter();
  const [fines, setFines] = useState<AttendanceFineListItem[]>(initialFines);
  const [statusFilter, setStatusFilter] = useState<"pending" | "collected" | "all">("pending");
  const [search, setSearch] = useState("");
  const [busy, setBusy] = useState<Record<number, boolean>>({});
  const [sortKey, setSortKey] = useState<SortKey>("participant_name_snapshot");
  const [sortDirection, setSortDirection] = useState<"asc" | "desc">("asc");

  const accountMap = new Map(accounts.map((a) => [a.id, a]));

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

  const counts = useMemo(() => ({
    pending: fines.filter((f) => f.status === "pending").length,
    collected: fines.filter((f) => f.status === "collected").length,
  }), [fines]);

  async function collectFine(fine: AttendanceFineListItem) {
    setBusy((b) => ({ ...b, [fine.id]: true }));
    try {
      const updated = await browserApiFetch<AttendanceFineListItem>(`/api/fines/${fine.id}/collect`, { method: "POST" });
      if (updated) setFines((prev) => prev.map((f) => f.id === updated.id ? { ...f, ...updated } : f));
    } finally {
      setBusy((b) => ({ ...b, [fine.id]: false }));
    }
  }

  async function deleteFine(fine: AttendanceFineListItem) {
    if (!confirm(`Busse von ${fine.participant_name_snapshot} löschen?`)) return;
    await browserApiFetch(`/api/fines/${fine.id}`, { method: "DELETE" });
    setFines((prev) => prev.filter((f) => f.id !== fine.id));
  }

  async function reopenFine(fine: AttendanceFineListItem) {
    setBusy((b) => ({ ...b, [fine.id]: true }));
    try {
      const updated = await browserApiFetch<AttendanceFineListItem>(`/api/fines/${fine.id}/reopen`, { method: "POST" });
      if (updated) setFines((prev) => prev.map((f) => f.id === updated.id ? { ...f, ...updated } : f));
    } finally {
      setBusy((b) => ({ ...b, [fine.id]: false }));
    }
  }

  const sd = (key: SortKey) => (sortKey === key ? sortDirection : null);

  return (
    <div className="grid">
      <div className="protocol-list-toolbar">
        <div className="segment-control">
          <button type="button" className={`segment-button${statusFilter === "pending" ? " segment-button-active" : ""}`} onClick={() => setStatusFilter("pending")}>
            Ausstehend {counts.pending > 0 ? <span className="todo-count-badge">{counts.pending}</span> : null}
          </button>
          <button type="button" className={`segment-button${statusFilter === "collected" ? " segment-button-active" : ""}`} onClick={() => setStatusFilter("collected")}>
            Kassiert {counts.collected > 0 ? <span className="todo-count-badge">{counts.collected}</span> : null}
          </button>
          <button type="button" className={`segment-button${statusFilter === "all" ? " segment-button-active" : ""}`} onClick={() => setStatusFilter("all")}>
            Alle
          </button>
        </div>
        <div className="protocol-list-toolbar-right">
          <input className="protocol-search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Suchen…" />
          <span className="muted protocol-count">{filtered.length} / {fines.length}</span>
        </div>
      </div>

      <DataTable
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
                      <svg viewBox="0 0 16 16" fill="none"><circle cx="8" cy="8" r="7" strokeWidth="1.5"/><path d="M4.5 8.5l2.5 2.5 4.5-4.5" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/></svg>
                    ) : (
                      <svg viewBox="0 0 16 16" fill="none"><circle cx="8" cy="8" r="7" strokeWidth="1.5"/></svg>
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
                <span className={`pill pill-sm ${isCollected ? "todo-status-done" : "todo-status-open"}`}>
                  {isCollected ? "Kassiert" : "Ausstehend"}
                </span>
                {isCollected && fine.collected_at ? (
                  <div className="muted" style={{ fontSize: "0.78rem", marginTop: 2 }}>
                    {formatDateTime(fine.collected_at)}
                    {fine.collected_by_display_name ? ` von ${fine.collected_by_display_name}` : ""}
                  </div>
                ) : null}
              </td>
              {isAdmin && (
                <td>
                  <div className="table-actions table-actions-start">
                    {!isCollected && (
                      <button type="button" className="button-inline button-danger" onClick={() => void deleteFine(fine)}>
                        Löschen
                      </button>
                    )}
                    {isCollected && fine.can_reopen && (
                      <button type="button" className="button-inline button-ghost" disabled={busy[fine.id]} onClick={() => void reopenFine(fine)}>
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
    </div>
  );
}
