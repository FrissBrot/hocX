"use client";

import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { DataTable, DataToolbar } from "@/components/ui/data-table";
import { SearchInput } from "@/components/ui/search-input";
import { AdminDomainSummary } from "@/types/api";

type Props = {
  initialDomains: AdminDomainSummary[];
};

export function AdminDomainOverview({ initialDomains }: Props) {
  const [search, setSearch] = useState("");

  const visibleDomains = initialDomains.filter((d) => {
    const term = search.trim().toLowerCase();
    if (!term) return true;
    return d.domain.toLowerCase().includes(term) || d.tenant_name.toLowerCase().includes(term);
  });

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

      <DataTable columns={["Mandant", "Zweck", "Domain", "Status", "Zuletzt geprüft"]} emptyMessage="Keine Domains gefunden.">
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
          </tr>
        ))}
      </DataTable>
    </div>
  );
}
