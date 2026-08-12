"use client";

import { useState } from "react";

import { ActionMenu } from "@/components/ui/action-menu";
import { Badge } from "@/components/ui/badge";
import { DataTable, DataToolbar } from "@/components/ui/data-table";
import { SearchInput } from "@/components/ui/search-input";
import { browserApiFetch } from "@/lib/api/client";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { AdminDomainSummary } from "@/types/api";

type Props = {
  initialDomains: AdminDomainSummary[];
};

export function AdminDomainOverview({ initialDomains }: Props) {
  const showToast = useToast();
  const confirm = useConfirm();
  const [search, setSearch] = useState("");
  const [domains, setDomains] = useState(initialDomains);

  const visibleDomains = domains.filter((d) => {
    const term = search.trim().toLowerCase();
    if (!term) return true;
    return d.domain.toLowerCase().includes(term) || d.tenant_name.toLowerCase().includes(term);
  });

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
      setDomains((current) => current.filter((d) => d.id !== domain.id));
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

      <DataTable columns={["Mandant", "Zweck", "Domain", "Status", "Zuletzt geprüft", "Aktionen"]} emptyMessage="Keine Domains gefunden.">
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
    </div>
  );
}
