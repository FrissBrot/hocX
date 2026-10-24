import { useTranslations } from "next-intl";

import { TenantDomain, TenantDomainPurpose } from "@/types/api";

type TFunc = (key: string) => string;

const PURPOSE_LABEL_KEYS: Record<TenantDomainPurpose, string> = {
  app: "purposeApp",
  abgabebox: "purposeAbgabebox",
  verify: "purposeVerify",
};

export function domainPurposeLabel(purpose: TenantDomainPurpose, t: TFunc): string {
  return t(PURPOSE_LABEL_KEYS[purpose] ?? "purposeApp");
}

// Welches Abo-Feature eine Domain je Zweck braucht (Backend: traefik_config_service.FEATURE_BY_PURPOSE).
// Die Prüf-Domain ist ein eigenes Feature, unabhängig von eigenen App-/Abgabebox-Domains.
export const DOMAIN_FEATURE_BY_PURPOSE: Record<TenantDomainPurpose, string> = {
  app: "custom_domain",
  abgabebox: "custom_domain",
  verify: "verify_domain",
};

export function bookablePurposes(enabledFeatures: string[]): TenantDomainPurpose[] {
  return (Object.keys(DOMAIN_FEATURE_BY_PURPOSE) as TenantDomainPurpose[]).filter((purpose) =>
    enabledFeatures.includes(DOMAIN_FEATURE_BY_PURPOSE[purpose])
  );
}

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
        {domainPurposeLabel(domain.purpose, t)} · {status.label}
      </div>
    </div>
  );
}
