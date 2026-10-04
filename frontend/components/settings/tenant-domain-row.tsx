import { useTranslations } from "next-intl";

import { TenantDomain } from "@/types/api";

type TFunc = (key: string) => string;

export function domainStatus(d: TenantDomain, t: TFunc): { label: string; variant: "success" | "danger" | "neutral"; title?: string } {
  if (d.status === "pending") return { label: t("statusPending"), variant: "neutral" };
  if (d.is_healthy) return { label: t("statusVerified"), variant: "success" };
  return {
    label: t("statusUnreachable"),
    variant: "danger",
    title: t("statusUnreachableHint"),
  };
}

// Host + status text of a domain row - shared between the read-only preview on the Allgemein
// tab and the full manageable list on the Domains tab. Callers wrap this in their own
// `.tenant-domain-row` with whatever trailing actions (or none) fit their context.
export function TenantDomainRowContent({ domain }: { domain: TenantDomain }) {
  const t = useTranslations("tenantSettings");
  const status = domainStatus(domain, t);
  return (
    <div>
      <div className="tenant-domain-row-host">{domain.domain}</div>
      <div className={`tenant-domain-row-status tenant-domain-row-status-${status.variant}`} title={status.title}>
        {domain.purpose === "app" ? t("purposeApp") : t("purposeAbgabebox")} · {status.label}
      </div>
    </div>
  );
}
