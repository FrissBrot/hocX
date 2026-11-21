import Link from "next/link";
import type { Route } from "next";
import { getLocale, getTranslations } from "next-intl/server";

import { Badge } from "@/components/ui/badge";
import { adminIsOwner, loadAdminTenant } from "@/lib/admin/tenant-detail-server";
import { backendFetchWithSession } from "@/lib/api/server";
import { describeAuditAction } from "@/lib/audit-labels";
import { formatDateTime, formatFileSize, formatRappen } from "@/lib/utils/format";
import { AuditLogPage, TenantChargePage } from "@/types/api";

// Übersicht eines Mandanten: Kennzahlen aus vorhandenen Quellen (keine Verläufe - die kommen aus der
// Aggregation, Phase D) und die letzten Audit-Einträge (nur owner, require_admin_owner).
export default async function AdminTenantOverviewPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const [tenant, isOwner, locale] = await Promise.all([loadAdminTenant(id), adminIsOwner(), getLocale()]);
  const t = await getTranslations("adminTenantDetail.overview");
  const tActions = await getTranslations("common.auditActions");
  const [charges, audit] = await Promise.all([
    backendFetchWithSession<TenantChargePage>(`/api/admin/cashflow/charges?tenant_id=${tenant.id}&status=open&limit=1&offset=0`),
    isOwner ? backendFetchWithSession<AuditLogPage>(`/api/admin/audit-log?tenant_id=${tenant.id}&limit=10&offset=0`) : Promise.resolve(null),
  ]);
  const quota = tenant.storage_quota_bytes;
  const storageRatio = quota ? tenant.storage_used_bytes / quota : null;
  const openTotals = charges?.totals.open;
  const overdueTotals = charges?.totals.overdue;
  const base = `/admin/tenants/${tenant.id}`;

  const tiles = [
    {
      key: "users",
      label: t("users"),
      value: tenant.effective_user_limit !== null ? t("usersOfLimit", { count: tenant.user_count, limit: tenant.effective_user_limit }) : String(tenant.user_count),
      href: isOwner ? `${base}/users` : `${base}/subscription`,
      status: tenant.effective_user_limit !== null && tenant.user_count > tenant.effective_user_limit ? "danger" : null,
    },
    { key: "participants", label: t("participants"), value: String(tenant.participant_count), href: null, status: null },
    {
      key: "storage",
      label: t("storage"),
      value: quota ? t("storageOfQuota", { used: formatFileSize(tenant.storage_used_bytes), quota: formatFileSize(quota) }) : t("storageUnlimited", { used: formatFileSize(tenant.storage_used_bytes) }),
      href: `${base}/storage`,
      status: storageRatio === null ? null : storageRatio > 1 ? "danger" : storageRatio >= 0.85 ? "warning" : null,
    },
    {
      key: "charges",
      label: t("openCharges"),
      value: openTotals ? formatRappen(openTotals.amount_rp, locale) : "—",
      href: `${base}/subscription`,
      status: overdueTotals && overdueTotals.count > 0 ? "danger" : null,
      hint: overdueTotals && overdueTotals.count > 0 ? t("overdue", { count: overdueTotals.count }) : null,
    },
  ] as const;

  return (
    <>
      <div className="admin-tenant-kpis">
        {tiles.map((tile) => (
          <article key={tile.key} className={tile.status ? `card admin-tenant-kpi admin-tenant-kpi-${tile.status}` : "card admin-tenant-kpi"}>
            <div className="eyebrow">{tile.label}</div>
            <strong className="admin-tenant-kpi-value">{tile.value}</strong>
            {"hint" in tile && tile.hint ? <Badge variant="danger" dot>{tile.hint}</Badge> : null}
            {tile.href ? (
              <Link href={tile.href as Route} className="admin-tenant-kpi-link">
                {t("details")}
              </Link>
            ) : null}
          </article>
        ))}
      </div>
      {isOwner ? (
        <section className="panel admin-tenant-detail-panel">
          <div className="admin-tenant-detail-section-head">
            <h2>{t("recentActivity")}</h2>
            <Link href={`${base}/activity` as Route}>{t("allActivity")}</Link>
          </div>
          {audit && audit.items.length > 0 ? (
            <ul className="admin-tenant-activity-list">
              {audit.items.map((entry) => (
                <li key={entry.id}>
                  <span className="muted">{formatDateTime(entry.created_at, locale)}</span>
                  <span>{describeAuditAction(entry.action, tActions)}</span>
                  {entry.outcome === "failure" ? <Badge variant="danger" dot>{t("failure")}</Badge> : null}
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted">{t("noActivity")}</p>
          )}
        </section>
      ) : null}
    </>
  );
}
