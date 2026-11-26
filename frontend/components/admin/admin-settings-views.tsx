"use client";

import Link from "next/link";
import type { Route } from "next";
import { useLocale, useTranslations } from "next-intl";

import { useAdminResource } from "@/components/admin/security/use-admin-resource";
import { Badge } from "@/components/ui/badge";
import { DataTable } from "@/components/ui/data-table";
import { HealthBadge, type HealthState } from "@/components/ui/health-badge";
import { StatusBanner } from "@/components/ui/status-banner";
import { formatDateTime } from "@/lib/utils/format";

// Einstellungen › Sicherheit & Anmeldung, Integrationen, Technik (1.5.1, Plan §2 G) - read-only.

type SettingsSecurity = {
  admin_login: { password: boolean; passkey_required: boolean; totp_allowed: boolean };
  admin_session_ttl_hours: number;
  step_up_flow_minutes: number;
  step_up_actions: { method: string; path: string; purpose: string }[];
};

type IntegrationItem = {
  key: string;
  configured: boolean;
  status: "ok" | "warning" | "critical" | "unknown" | "off";
  params: Record<string, string | number | boolean | null>;
  href: string;
};

type SettingsIntegrations = { collected_at: string | null; items: IntegrationItem[] };

type SettingsSystem = {
  version: string | null;
  environment: string;
  server_location: string;
  alembic_revision: string | null;
  postgres_version: string | null;
  python_version: string;
  catalogs: { permissions: number; features: number; features_in_database: number; locales: string[] };
  domains: Record<string, string | null>;
};

const KNOWN_PURPOSES = new Set([
  "passkey-manage", "admin-manage", "tenant-delete", "tenant-export", "tenant-import", "storage-destructive", "backup-restore",
  "backup-settings", "catalog-change", "user-mfa-reset", "user-manage", "user-credentials", "platform-settings", "security-block",
  "security-export", "security-resolve", "cloud-import-cancel", "security-incident",
]);
const INTEGRATION_KEYS = new Set(["smtp", "ntfy", "status_endpoint", "object_storage", "captcha", "clamav", "docker_proxy", "backup"]);
const DOMAIN_KEYS = ["app", "admin", "abgabebox", "docs", "website"] as const;

function Loading({ failed, forbidden }: { failed: boolean; forbidden: boolean }) {
  const t = useTranslations("admin.settingsPages");
  if (forbidden) return <StatusBanner tone="neutral" message={t("ownerOnly")} />;
  if (failed) return <StatusBanner tone="error" message={t("loadFailed")} />;
  return null;
}

export function AdminSettingsSecurityView() {
  const t = useTranslations("admin.settingsPages.security");
  const data = useAdminResource<SettingsSecurity>("/api/admin/settings/security");
  if (!data.data) return <Loading failed={data.failed} forbidden={data.forbidden} />;
  const value = data.data;
  // Nach Zweck gruppiert: welche Aktionen eine frische Passkey-Bestätigung verlangen
  const byPurpose = new Map<string, SettingsSecurity["step_up_actions"]>();
  for (const action of value.step_up_actions) byPurpose.set(action.purpose, [...(byPurpose.get(action.purpose) ?? []), action]);
  return (
    <div className="grid">
      <section className="card section-stack">
        <h2 className="section-title">{t("loginTitle")}</h2>
        <dl className="admin-key-value">
          <div>
            <dt>{t("password")}</dt>
            <dd><Badge variant="success">{t("required")}</Badge></dd>
          </div>
          <div>
            <dt>{t("passkey")}</dt>
            <dd><Badge variant="success">{t("required")}</Badge></dd>
          </div>
          <div>
            <dt>{t("totp")}</dt>
            <dd><Badge variant="neutral">{t("notAllowed")}</Badge></dd>
          </div>
          <div>
            <dt>{t("sessionTtl")}</dt>
            <dd>{t("hours", { count: value.admin_session_ttl_hours })}</dd>
          </div>
          <div>
            <dt>{t("stepUpFlow")}</dt>
            <dd>{t("minutes", { count: value.step_up_flow_minutes })}</dd>
          </div>
        </dl>
        <p className="muted">
          {t("policyHint")} <Link href={"/admin/security/policy" as Route}>{t("policyLink")}</Link>
        </p>
      </section>
      <section className="card section-stack">
        <h2 className="section-title">{t("stepUpTitle")}</h2>
        <p className="muted">{t("stepUpDescription")}</p>
        <DataTable columns={[t("columns.purpose"), t("columns.actions")]} emptyMessage={t("empty")}>
          {[...byPurpose.entries()].map(([purpose, actions]) => (
            <tr key={purpose}>
              <td>
                <strong>{KNOWN_PURPOSES.has(purpose) ? t(`purposes.${purpose}`) : purpose}</strong>
                <div className="muted admin-cell-sub"><code>{purpose}</code></div>
              </td>
              <td>
                <ul className="admin-plain-list">
                  {actions.map((action) => (
                    <li key={`${action.method} ${action.path}`}><code>{`${action.method} ${action.path}`}</code></li>
                  ))}
                </ul>
              </td>
            </tr>
          ))}
        </DataTable>
      </section>
    </div>
  );
}

function integrationState(item: IntegrationItem): HealthState {
  if (item.status === "off") return "unknown";
  return item.status;
}

function integrationDetail(item: IntegrationItem, t: ReturnType<typeof useTranslations>): string | null {
  const p = item.params;
  switch (item.key) {
    case "smtp":
      return p.host ? t("details.smtp", { host: String(p.host), port: String(p.port ?? ""), security: String(p.security ?? "") }) : null;
    case "ntfy":
      return p.server ? t("details.ntfy", { server: String(p.server) }) : null;
    case "object_storage":
      return p.profile ? t("details.objectStorage", { profile: String(p.profile), provider: String(p.provider ?? "") }) : null;
    case "captcha":
      return t(p.region === "eu" ? "details.captchaEu" : "details.captchaGlobal");
    default:
      return null;
  }
}

export function AdminSettingsIntegrationsView() {
  const t = useTranslations("admin.settingsPages.integrations");
  const locale = useLocale();
  const data = useAdminResource<SettingsIntegrations>("/api/admin/settings/integrations");
  if (!data.data) return <Loading failed={data.failed} forbidden={data.forbidden} />;
  return (
    <section className="card section-stack">
      <p className="muted">
        {data.data.collected_at ? t("collectedAt", { time: formatDateTime(data.data.collected_at, locale) }) : t("noSnapshot")}
      </p>
      <DataTable columns={[t("columns.service"), t("columns.configured"), t("columns.status"), t("columns.details"), ""]} emptyMessage={t("empty")}>
        {data.data.items.map((item) => (
          <tr key={item.key}>
            <td><strong>{INTEGRATION_KEYS.has(item.key) ? t(`services.${item.key}`) : item.key}</strong></td>
            <td>{item.configured ? <Badge variant="success">{t("yes")}</Badge> : <Badge variant="neutral">{t("no")}</Badge>}</td>
            <td>{item.status === "off" ? <Badge variant="neutral">{t("off")}</Badge> : <HealthBadge state={integrationState(item)} />}</td>
            <td className="muted">{integrationDetail(item, t) ?? "—"}</td>
            <td>
              <Link href={item.href as Route}>{t("open")}</Link>
            </td>
          </tr>
        ))}
      </DataTable>
    </section>
  );
}

export function AdminSettingsSystemView() {
  const t = useTranslations("admin.settingsPages.system");
  const data = useAdminResource<SettingsSystem>("/api/admin/settings/system");
  if (!data.data) return <Loading failed={data.failed} forbidden={data.forbidden} />;
  const value = data.data;
  return (
    <div className="grid">
      <section className="card section-stack">
        <h2 className="section-title">{t("versionTitle")}</h2>
        <dl className="admin-key-value">
          <div>
            <dt>{t("version")}</dt>
            <dd>{value.version ?? t("unknown")}</dd>
          </div>
          <div>
            <dt>{t("environment")}</dt>
            <dd><code>{value.environment}</code></dd>
          </div>
          <div>
            <dt>{t("location")}</dt>
            <dd><code>{value.server_location}</code></dd>
          </div>
          <div>
            <dt>{t("migration")}</dt>
            <dd><code>{value.alembic_revision ?? "—"}</code></dd>
          </div>
          <div>
            <dt>{t("postgres")}</dt>
            <dd>{value.postgres_version ?? "—"}</dd>
          </div>
          <div>
            <dt>{t("python")}</dt>
            <dd>{value.python_version}</dd>
          </div>
        </dl>
      </section>
      <section className="card section-stack">
        <h2 className="section-title">{t("catalogTitle")}</h2>
        <dl className="admin-key-value">
          <div>
            <dt>{t("permissions")}</dt>
            <dd>{value.catalogs.permissions}</dd>
          </div>
          <div>
            <dt>{t("features")}</dt>
            <dd>
              {t("featuresValue", { catalog: value.catalogs.features, database: value.catalogs.features_in_database })}
              {value.catalogs.features !== value.catalogs.features_in_database ? (
                <> <Badge variant="warning">{t("featuresMismatch")}</Badge></>
              ) : null}
            </dd>
          </div>
          <div>
            <dt>{t("locales")}</dt>
            <dd>{value.catalogs.locales.join(", ")}</dd>
          </div>
        </dl>
      </section>
      <section className="card section-stack">
        <h2 className="section-title">{t("domainsTitle")}</h2>
        <dl className="admin-key-value">
          {DOMAIN_KEYS.map((key) => (
            <div key={key}>
              <dt>{t(`domains.${key}`)}</dt>
              <dd>{value.domains[key] ? <code>{value.domains[key]}</code> : <span className="muted">{t("notSet")}</span>}</dd>
            </div>
          ))}
        </dl>
      </section>
    </div>
  );
}
