"use client";

// Inhalte der Tabs auf /admin/tenants/[id] (Admin-Redesign §5.2). Stammdaten/Abo/Benutzer/Speicher/
// Aufräumen kommen unverändert aus dem bisherigen Einstellungs-Modal (eingebetteter Modus), der Rest
// sind kleine, auf den Mandanten gefilterte Listen.

import Link from "next/link";
import type { Route } from "next";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { AdminTenantSettingsModal, SettingsTab } from "@/components/admin/admin-tenant-settings-modal";
import { Badge } from "@/components/ui/badge";
import { DataTable } from "@/components/ui/data-table";
import { Pagination } from "@/components/ui/pagination";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import { describeAuditAction } from "@/lib/audit-labels";
import { formatDate, formatDateTime, formatRappen } from "@/lib/utils/format";
import { AdminDomainPage, AdminTenantSummary, AuditLogPage, SystemErrorLogPage, TenantChargePage } from "@/types/api";

const PAGE_SIZE = 25;

/** Ein Tab des bisherigen Einstellungs-Modals, eingebettet in die Seite. */
export function TenantSettingsPanel({ tenant, tab, readOnly }: { tenant: AdminTenantSummary; tab: SettingsTab; readOnly: boolean }) {
  const router = useRouter();
  const [current, setCurrent] = useState(tenant);
  useEffect(() => setCurrent(tenant), [tenant]);
  return (
    <AdminTenantSettingsModal
      open
      onClose={() => undefined}
      tenant={current}
      embeddedTab={tab}
      readOnly={readOnly}
      onSaved={(updated) => {
        setCurrent(updated);
        // Kopfbereich (Name, Plan, Status) neu vom Server holen
        router.refresh();
      }}
    />
  );
}

/** Seitenweise Liste mit Nachladen über die Admin-API; `path` enthält schon den Mandantenfilter. */
function usePagedList<T extends { total: number }>(path: string, initialPage: T) {
  const showToast = useToast();
  const t = useTranslations("adminTenantDetail");
  const [page, setPage] = useState(initialPage);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    if (offset === 0) {
      setPage(initialPage);
      return;
    }
    let cancelled = false;
    setLoading(true);
    const separator = path.includes("?") ? "&" : "?";
    browserApiFetch<T>(`${path}${separator}limit=${PAGE_SIZE}&offset=${offset}`)
      .then((result) => {
        if (!cancelled) setPage(result);
      })
      .catch((error: unknown) => showToast(error instanceof Error ? error.message : t("loadFailed"), "error"))
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [offset, path, initialPage, showToast, t]);
  return { page, offset, setOffset, loading };
}

export function TenantDomainsPanel({ tenantId, initialPage }: { tenantId: string; initialPage: AdminDomainPage }) {
  const t = useTranslations("adminTenantDetail.domains");
  const tDomains = useTranslations("admin.domains");
  const locale = useLocale();
  const { page, offset, setOffset, loading } = usePagedList(`/api/admin/domains?tenant_id=${tenantId}`, initialPage);
  return (
    <section className="panel admin-tenant-detail-panel">
      <div className="admin-tenant-detail-section-head">
        <div>
          <h2>{t("title")}</h2>
          <p className="muted">{t("description")}</p>
        </div>
        <Link href={"/admin/domains" as Route}>{t("allDomains")}</Link>
      </div>
      <DataTable
        columns={[tDomains("purpose"), tDomains("domain"), tDomains("status"), tDomains("lastChecked")]}
        emptyMessage={loading ? tDomains("loading") : t("empty")}
      >
        {page.items.map((domain) => (
          <tr key={domain.id}>
            <td>{domain.purpose === "app" ? tDomains("purposeApp") : tDomains("purposeAbgabebox")}</td>
            <td className="domain-row-domain">{domain.domain}</td>
            <td>
              {domain.status === "pending" ? (
                <Badge variant="neutral">{tDomains("statusPending")}</Badge>
              ) : domain.is_healthy ? (
                <Badge variant="success">{tDomains("statusActive")}</Badge>
              ) : (
                <Badge variant="danger">{tDomains("statusUnreachable")}</Badge>
              )}
            </td>
            <td className="muted">{domain.last_checked_at ? formatDateTime(domain.last_checked_at, locale) : "—"}</td>
          </tr>
        ))}
      </DataTable>
      <Pagination offset={offset} limit={PAGE_SIZE} total={page.total} onOffsetChange={setOffset} />
    </section>
  );
}

export function TenantActivityPanel({ tenantId, initialPage }: { tenantId: string; initialPage: AuditLogPage }) {
  const t = useTranslations("adminTenantDetail.activity");
  const tActions = useTranslations("common.auditActions");
  const locale = useLocale();
  const { page, offset, setOffset, loading } = usePagedList(`/api/admin/audit-log?tenant_id=${tenantId}`, initialPage);
  return (
    <section className="panel admin-tenant-detail-panel">
      <div className="admin-tenant-detail-section-head">
        <div>
          <h2>{t("title")}</h2>
          <p className="muted">{t("description")}</p>
        </div>
      </div>
      <DataTable columns={[t("time"), t("action"), t("outcome"), t("actor")]} emptyMessage={loading ? t("loading") : t("empty")}>
        {page.items.map((entry) => (
          <tr key={entry.id}>
            <td className="muted">{formatDateTime(entry.created_at, locale)}</td>
            <td>{describeAuditAction(entry.action, tActions)}</td>
            <td>
              <Badge variant={entry.outcome === "success" ? "success" : "danger"} dot>
                {entry.outcome === "success" ? t("success") : t("failure")}
              </Badge>
            </td>
            <td>{entry.actor_name ?? entry.actor_email ?? <span className="muted">—</span>}</td>
          </tr>
        ))}
      </DataTable>
      <Pagination offset={offset} limit={PAGE_SIZE} total={page.total} onOffsetChange={setOffset} />
    </section>
  );
}

export function TenantErrorsPanel({ tenantId, initialPage }: { tenantId: string; initialPage: SystemErrorLogPage }) {
  const t = useTranslations("adminTenantDetail.technical");
  const locale = useLocale();
  const { page, offset, setOffset, loading } = usePagedList(`/api/admin/error-logs?tenant_id=${tenantId}`, initialPage);
  return (
    <section className="panel admin-tenant-detail-panel">
      <div className="admin-tenant-detail-section-head">
        <div>
          <h2>{t("errorsTitle")}</h2>
          <p className="muted">{t("errorsDescription")}</p>
        </div>
        <Link href={"/admin/error-logs" as Route}>{t("allErrors")}</Link>
      </div>
      <DataTable columns={[t("time"), t("type"), t("request"), t("status")]} emptyMessage={loading ? t("loading") : t("errorsEmpty")}>
        {page.items.map((entry) => (
          <tr key={entry.id}>
            <td className="muted">{formatDateTime(entry.created_at, locale)}</td>
            <td>
              <strong>{entry.error_type}</strong>
              <div className="muted admin-cell-sub">{entry.error_message}</div>
            </td>
            <td className="muted">{entry.request_method && entry.request_path ? `${entry.request_method} ${entry.request_path}` : "—"}</td>
            <td className="admin-cell-number">{entry.status_code ?? "—"}</td>
          </tr>
        ))}
      </DataTable>
      <Pagination offset={offset} limit={PAGE_SIZE} total={page.total} onOffsetChange={setOffset} />
    </section>
  );
}

export function TenantChargesPanel({ tenantId, initialPage }: { tenantId: string; initialPage: TenantChargePage }) {
  const t = useTranslations("adminTenantDetail.charges");
  const locale = useLocale();
  const { page, offset, setOffset, loading } = usePagedList(`/api/admin/cashflow/charges?tenant_id=${tenantId}`, initialPage);
  return (
    <section className="panel admin-tenant-detail-panel">
      <div className="admin-tenant-detail-section-head">
        <div>
          <h2>{t("title")}</h2>
          <p className="muted">{t("description")}</p>
        </div>
        <Link href={"/admin/cashflow" as Route}>{t("allCharges")}</Link>
      </div>
      <DataTable columns={[t("period"), t("amount"), t("status"), t("due")]} emptyMessage={loading ? t("loading") : t("empty")}>
        {page.items.map((charge) => (
          <tr key={charge.id}>
            <td>
              {formatDate(charge.period_start)} – {formatDate(charge.period_end)}
            </td>
            <td className="admin-cell-number">{formatRappen(charge.amount_rp, locale)}</td>
            <td>
              {charge.is_overdue ? (
                <Badge variant="danger" dot>{t("overdue")}</Badge>
              ) : (
                <Badge variant={charge.status === "paid" ? "success" : charge.status === "waived" ? "neutral" : "warning"} dot>
                  {t(`status_${charge.status}`)}
                </Badge>
              )}
            </td>
            <td className="muted">{formatDate(charge.due_on)}</td>
          </tr>
        ))}
      </DataTable>
      <Pagination offset={offset} limit={PAGE_SIZE} total={page.total} onOffsetChange={setOffset} />
    </section>
  );
}
