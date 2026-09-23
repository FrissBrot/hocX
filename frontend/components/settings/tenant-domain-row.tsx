import { TenantDomain } from "@/types/api";

export function domainStatus(d: TenantDomain): { label: string; variant: "success" | "danger" | "neutral"; title?: string } {
  if (d.status === "pending") return { label: "Ausstehend", variant: "neutral" };
  if (d.is_healthy) return { label: "Verifiziert", variant: "success" };
  return {
    label: "Nicht erreichbar",
    variant: "danger",
    title: "Domain zeigt bei der letzten Prüfung nicht mehr auf hocX — DNS-Einträge prüfen",
  };
}

// Host + status text of a domain row - shared between the read-only preview on the Allgemein
// tab and the full manageable list on the Domains tab. Callers wrap this in their own
// `.tenant-domain-row` with whatever trailing actions (or none) fit their context.
export function TenantDomainRowContent({ domain }: { domain: TenantDomain }) {
  const status = domainStatus(domain);
  return (
    <div>
      <div className="tenant-domain-row-host">{domain.domain}</div>
      <div className={`tenant-domain-row-status tenant-domain-row-status-${status.variant}`} title={status.title}>
        {domain.purpose === "app" ? "hocX-App" : "Abgabebox"} · {status.label}
      </div>
    </div>
  );
}
