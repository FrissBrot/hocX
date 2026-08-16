"use client";

import { useEffect, useState } from "react";

import { ActionMenu } from "@/components/ui/action-menu";
import { Badge } from "@/components/ui/badge";
import { DataTable, DataToolbar } from "@/components/ui/data-table";
import { Pagination } from "@/components/ui/pagination";
import { SearchInput } from "@/components/ui/search-input";
import { browserApiFetch } from "@/lib/api/client";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { AdminDomainPage, AdminDomainSummary } from "@/types/api";

type Props = {
  initialPage: AdminDomainPage;
};

const PAGE_SIZE = 50;

export function AdminDomainOverview({ initialPage }: Props) {
  const showToast = useToast();
  const confirm = useConfirm();
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(initialPage);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(false);
  const domains = page.items;

  // Server now applies `search` before pagination (audit A1, 2026-08-16 - fetchPage below
  // sends it as `q`), so page.items is already the matching set for the current page.
  const visibleDomains = domains;

  async function fetchPage(nextOffset: number, query: string) {
    setLoading(true);
    try {
      const q = query.trim();
      const result = await browserApiFetch<AdminDomainPage>(
        `/api/admin/domains?limit=${PAGE_SIZE}&offset=${nextOffset}${q ? `&q=${encodeURIComponent(q)}` : ""}`
      );
      setPage(result);
    } catch {
      // keep showing the previous page rather than blanking the table on a transient error
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void fetchPage(offset, search);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [offset]);

  // Debounced re-fetch from offset 0 whenever the search text changes - see the identical
  // pattern in admin-user-management.tsx.
  useEffect(() => {
    const timer = window.setTimeout(() => {
      if (offset !== 0) {
        setOffset(0);
      } else {
        void fetchPage(0, search);
      }
    }, 300);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  async function deleteDomain(domain: AdminDomainSummary) {
    const confirmed = await confirm({
      title: `"${domain.domain}" entfernen?`,
      message: `Diese Domain wird vom Mandanten "${domain.tenant_name}" entfernt. Der Mandant kann danach eine neue Domain hinterlegen und erneut verifizieren.`,
      tone: "danger",
      confirmLabel: "Entfernen"
    });
    if (!confirmed) return;
    try {
      await browserApiFetch(`/api/admin/domains/${domain.id}`, { method: "DELETE" });
      // Deleting the last item on a page would strand the view past the new end - fall
      // back a page first if that's about to happen (changing offset re-triggers the load).
      if (domains.length === 1 && offset > 0) {
        setOffset(offset - PAGE_SIZE);
      } else {
        await fetchPage(offset, search);
      }
      showToast("Domain entfernt", "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Domain konnte nicht entfernt werden", "error");
    }
  }

  return (
    <div className="grid">
      <DataToolbar
        title="Domains"
        description="Alle Custom Domains über alle Mandanten hinweg, mit Status und Gesundheitsprüfung."
      />

      <article className="card">
        <label className="field-stack">
          <span className="field-label">Suche</span>
          <SearchInput value={search} onChange={setSearch} placeholder="Domain oder Mandant durchsuchen" />
        </label>
      </article>

      <DataTable
        columns={["Mandant", "Zweck", "Domain", "Status", "Zuletzt geprüft", "Aktionen"]}
        emptyMessage={loading ? "Wird geladen…" : "Keine Domains gefunden."}
      >
        {visibleDomains.map((d) => (
          <tr key={d.id}>
            <td>{d.tenant_name}</td>
            <td>{d.purpose === "app" ? "hocX-App" : "Abgabebox"}</td>
            <td className="domain-row-domain">{d.domain}</td>
            <td>
              {d.status === "pending" ? (
                <Badge variant="neutral">Ausstehend</Badge>
              ) : d.is_healthy ? (
                <Badge variant="success">Aktiv</Badge>
              ) : (
                <Badge variant="danger">Nicht erreichbar</Badge>
              )}
            </td>
            <td className="muted">
              {d.last_checked_at ? new Date(d.last_checked_at).toLocaleString("de-CH") : "—"}
            </td>
            <td>
              <ActionMenu items={[{ label: "Entfernen", onClick: () => deleteDomain(d), danger: true }]} />
            </td>
          </tr>
        ))}
      </DataTable>

      <Pagination offset={offset} limit={PAGE_SIZE} total={page.total} onOffsetChange={setOffset} />
    </div>
  );
}
