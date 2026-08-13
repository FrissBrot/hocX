"use client";

import { useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { DataTable, DataToolbar } from "@/components/ui/data-table";
import { Pagination } from "@/components/ui/pagination";
import { browserApiFetch } from "@/lib/api/client";
import { AdminTenantSummary, SystemErrorLogEntry, SystemErrorLogFilterOptions, SystemErrorLogPage } from "@/types/api";

type Props = {
  initialPage: SystemErrorLogPage;
  initialFilterOptions: SystemErrorLogFilterOptions;
  tenants: AdminTenantSummary[];
};

const PAGE_SIZE = 50;

const SOURCE_LABELS: Record<string, string> = {
  backend: "hocX",
  "abgabebox-backend": "Abgabebox",
};

export function AdminErrorLog({ initialPage, initialFilterOptions, tenants }: Props) {
  const [page, setPage] = useState(initialPage);
  const [filterOptions] = useState(initialFilterOptions);
  const [tenantId, setTenantId] = useState<string>("");
  const [errorType, setErrorType] = useState<string>("");
  const [source, setSource] = useState<string>("");
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(false);
  const [expandedId, setExpandedId] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      try {
        const params = new URLSearchParams();
        if (tenantId) params.set("tenant_id", tenantId);
        if (errorType) params.set("error_type", errorType);
        if (source) params.set("source", source);
        params.set("limit", String(PAGE_SIZE));
        params.set("offset", String(offset));
        const result = await browserApiFetch<SystemErrorLogPage>(`/api/admin/error-logs?${params.toString()}`);
        if (!cancelled) setPage(result);
      } catch {
        // keep showing the previous page rather than blanking the table on a transient error
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [tenantId, errorType, source, offset]);

  function resetAndSet(setter: (value: string) => void) {
    return (value: string) => {
      setter(value);
      setOffset(0);
      setExpandedId(null);
    };
  }

  return (
    <div className="grid">
      <DataToolbar
        title="Fehlerprotokoll"
        description="Unerwartete Backend-Fehler aus der ganzen Anwendung (hocX + Abgabebox) - normale Nutzer sehen davon nie mehr als eine generische Meldung."
      />

      <article className="card">
        <div className="filter-row" style={{ display: "flex", gap: "1rem", flexWrap: "wrap" }}>
          <label className="field-stack">
            <span className="field-label">Mandant</span>
            <select value={tenantId} onChange={(e) => resetAndSet(setTenantId)(e.target.value)}>
              <option value="">Alle</option>
              {tenants.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name}
                </option>
              ))}
            </select>
          </label>
          <label className="field-stack">
            <span className="field-label">Fehlertyp</span>
            <select value={errorType} onChange={(e) => resetAndSet(setErrorType)(e.target.value)}>
              <option value="">Alle</option>
              {filterOptions.error_types.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </label>
          <label className="field-stack">
            <span className="field-label">Quelle</span>
            <select value={source} onChange={(e) => resetAndSet(setSource)(e.target.value)}>
              <option value="">Alle</option>
              {filterOptions.sources.map((s) => (
                <option key={s} value={s}>
                  {SOURCE_LABELS[s] ?? s}
                </option>
              ))}
            </select>
          </label>
        </div>
      </article>

      <DataTable
        columns={["Zeitpunkt", "Mandant", "Quelle", "Typ", "Status", "Route", "Nachricht"]}
        emptyMessage={loading ? "Wird geladen…" : "Keine Fehler gefunden."}
      >
        {page.items.map((entry) => (
          <ErrorRow key={entry.id} entry={entry} expanded={expandedId === entry.id} onToggle={() => setExpandedId(expandedId === entry.id ? null : entry.id)} />
        ))}
      </DataTable>

      <Pagination offset={offset} limit={PAGE_SIZE} total={page.total} onOffsetChange={setOffset} />
    </div>
  );
}

function ErrorRow({ entry, expanded, onToggle }: { entry: SystemErrorLogEntry; expanded: boolean; onToggle: () => void }) {
  return (
    <>
      <tr className="table-row-clickable" onClick={onToggle}>
        <td className="muted">{new Date(entry.created_at).toLocaleString("de-CH")}</td>
        <td>{entry.tenant_name ?? <span className="muted">—</span>}</td>
        <td>{SOURCE_LABELS[entry.source] ?? entry.source}</td>
        <td>
          <Badge variant="danger">{entry.error_type}</Badge>
        </td>
        <td className="muted">{entry.status_code ?? "—"}</td>
        <td className="muted">
          {entry.request_method ? `${entry.request_method} ` : ""}
          {entry.request_path ?? "—"}
        </td>
        <td>{entry.error_message}</td>
      </tr>
      {expanded && (
        <tr>
          <td colSpan={7}>
            <div className="grid" style={{ gap: "0.5rem" }}>
              {entry.actor_email && (
                <div className="muted">Ausgelöst von: {entry.actor_email}</div>
              )}
              {entry.traceback && (
                <pre style={{ whiteSpace: "pre-wrap", fontSize: "0.8rem", overflowX: "auto" }}>{entry.traceback}</pre>
              )}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}
