import { useSyncExternalStore } from "react";
import { useTranslations } from "next-intl";

import { ApiError } from "@/lib/api/client";
import { getRuntimeConfig } from "@/lib/runtime-config";
import { TenantDomain, TenantDomainPurpose } from "@/types/api";

type TFunc = (key: string, values?: Record<string, string | number>) => string;

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

export function domainStatus(d: TenantDomain, t: TFunc): { label: string; variant: "success" | "danger" | "neutral"; hint?: string } {
  if (d.status === "pending") return { label: t("statusPending"), variant: "neutral" };
  if (d.is_healthy) return { label: t("statusVerified"), variant: "success" };
  return {
    label: t("statusUnreachable"),
    variant: "danger",
    hint: t("statusUnreachableHint"),
  };
}

const noSubscribe = () => () => {};

/** Haupt-Domain der Instanz (Runtime-Config, erst nach der Hydration bekannt) oder null. */
export function useMainAppDomain(): string | null {
  return useSyncExternalStore(noSubscribe, () => getRuntimeConfig().mainAppDomain ?? null, () => null);
}

/** Hinweis, dass die Standard-Adressen immer erreichbar bleiben - mit der echten Instanz-Domain. */
export function domainsDescriptionText(t: TFunc, mainDomain: string | null): string {
  return mainDomain ? t("domainsDescriptionWithDomain", { appDomain: mainDomain }) : t("domainsDescription");
}

// Fehlercodes der Domain-Routen (Backend: tenant_service._domain_error) -> übersetzter Text.
const DOMAIN_ERROR_CODES = new Set([
  "domain_invalid_format",
  "domain_reserved",
  "domain_domain_taken",
  "domain_already_active",
  "domain_txt_missing",
  "domain_not_routed",
]);

/** Übersetzte Meldung zu einem Fehler der Domain-Routen; unbekannte Fehler behalten ihren Text. */
export function domainErrorMessage(error: unknown, t: TFunc, fallbackKey: string): string {
  if (error instanceof ApiError) {
    if (error.status === 429) return t("errors.rateLimited");
    const detail = error.detail as { code?: unknown; record?: unknown; target?: unknown; domain?: unknown } | undefined;
    const code = detail && typeof detail === "object" && typeof detail.code === "string" ? detail.code : null;
    if (code && DOMAIN_ERROR_CODES.has(code)) {
      return t(`errors.${code}`, {
        record: String(detail?.record ?? ""),
        target: String(detail?.target ?? ""),
        domain: String(detail?.domain ?? ""),
      });
    }
  }
  return error instanceof Error && error.message ? error.message : t(fallbackKey);
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
      <div className={`tenant-domain-row-status tenant-domain-row-status-${status.variant}`}>
        {domainPurposeLabel(domain.purpose, t)} · {status.label}
      </div>
      {/* Hinweis als Text statt nur im title-Attribut (Touch, Screenreader; Audit 08) */}
      {status.hint ? <div className="field-help">{status.hint}</div> : null}
      {domain.status === "pending" && domain.replaces_domain ? (
        <div className="field-help">{t("replacesDomainHint", { domain: domain.replaces_domain })}</div>
      ) : null}
    </div>
  );
}
