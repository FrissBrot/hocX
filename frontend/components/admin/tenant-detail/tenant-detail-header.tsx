"use client";

// Kopfbereich und Tab-Leiste der Mandanten-Detailseite /admin/tenants/[id] (Admin-Redesign §5.2).

import Link from "next/link";
import type { Route } from "next";
import { usePathname, useRouter } from "next/navigation";
import { useState } from "react";
import { useTranslations } from "next-intl";

import { AdminAvatar, PlanBadge } from "@/components/admin/admin-plan-utils";
import { TenantCloneModal, TenantExportModal, useTenantDelete } from "@/components/admin/tenant-detail/tenant-action-modals";
import { TenantStatusBadges } from "@/components/admin/tenant-detail/tenant-status-badges";
import { ActionMenu } from "@/components/ui/action-menu";
import { CopyField } from "@/components/ui/copy-field";
import { RouteTabs } from "@/components/ui/route-tabs";
import { formatDate } from "@/lib/utils/format";
import { AdminTenantSummary } from "@/types/api";

/** Unterrouten der Detailseite; `owner` = Tab zeigt Daten aus require_admin_owner-Quellen (für support ausgeblendet). */
export const TENANT_DETAIL_TABS = [
  { segment: "", key: "overview", owner: false },
  { segment: "profile", key: "profile", owner: false },
  { segment: "subscription", key: "subscription", owner: false },
  { segment: "features", key: "features", owner: false },
  { segment: "users", key: "users", owner: true },
  { segment: "domains", key: "domains", owner: false },
  { segment: "verification", key: "verification", owner: false },
  { segment: "storage", key: "storage", owner: false },
  { segment: "usage", key: "usage", owner: false },
  { segment: "activity", key: "activity", owner: true },
  { segment: "security", key: "security", owner: true },
  { segment: "technical", key: "technical", owner: true },
] as const;

export function tenantDetailHref(tenantId: string, segment = ""): string {
  return segment ? `/admin/tenants/${tenantId}/${segment}` : `/admin/tenants/${tenantId}`;
}

export function TenantDetailHeader({ tenant, isOwner }: { tenant: AdminTenantSummary; isOwner: boolean }) {
  const t = useTranslations("adminTenantDetail");
  const router = useRouter();
  const pathname = usePathname();
  const deleteTenant = useTenantDelete();
  const [cloneTenant, setCloneTenant] = useState<AdminTenantSummary | null>(null);
  const [exportTenant, setExportTenant] = useState<AdminTenantSummary | null>(null);

  const tabs = TENANT_DETAIL_TABS.filter((tab) => isOwner || !tab.owner).map((tab) => ({
    href: tenantDetailHref(tenant.id, tab.segment),
    label: t(`tabs.${tab.key}`),
  }));

  return (
    <>
      <div className="page-header admin-tenant-detail-header">
        <div className="admin-tenant-detail-identity">
          <AdminAvatar name={tenant.name} imageUrl={tenant.profile_image_url} toneKey={tenant.id} size="lg" />
          <div>
            <div className="eyebrow">{t("header.eyebrow")}</div>
            <h1 className="page-title">{tenant.name}</h1>
            <div className="admin-tenant-detail-meta">
              <TenantStatusBadges tenant={tenant} />
              {tenant.plan_code ? <PlanBadge name={tenant.plan_name ?? tenant.plan_code} tone="neutral" /> : null}
              <span className="muted">{t("header.created", { date: formatDate(tenant.created_at) })}</span>
            </div>
          </div>
        </div>
        <div className="table-toolbar-actions">
          {/* support: Stammdaten sind dort nur lesbar (Formular gesperrt), Aktionsmenü entfällt */}
          <Link href={tenantDetailHref(tenant.id, "profile") as Route} className="button-primary">
            {t("header.edit")}
          </Link>
          {isOwner ? (
            <ActionMenu
              ariaLabel={t("header.actions")}
              items={[
                { label: t("header.clone"), onClick: () => setCloneTenant(tenant) },
                { label: t("header.export"), onClick: () => setExportTenant(tenant) },
                { label: t("header.cleanup"), onClick: () => router.push(tenantDetailHref(tenant.id, "technical") as Route) },
                {
                  label: t("header.delete"),
                  danger: true,
                  onClick: async () => {
                    if (await deleteTenant(tenant)) router.push("/admin/tenants" as Route);
                  },
                },
              ]}
            />
          ) : null}
        </div>
      </div>
      <div className="admin-tenant-detail-id">
        <CopyField label={t("header.id")} value={tenant.id} />
      </div>
      <RouteTabs tabs={tabs} activeHref={pathname} />
      <TenantCloneModal
        tenant={cloneTenant}
        onClose={() => setCloneTenant(null)}
        onCloned={(clone) => router.push(tenantDetailHref(clone.id) as Route)}
      />
      <TenantExportModal tenant={exportTenant} onClose={() => setExportTenant(null)} />
    </>
  );
}
