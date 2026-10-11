"use client";

import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";

import { AdminAvatar } from "@/components/admin/admin-plan-utils";
import { AdminTenantSettingsModal } from "@/components/admin/admin-tenant-settings-modal";
import { Badge } from "@/components/ui/badge";
import { DataTable } from "@/components/ui/data-table";
import { AdminPlan, AdminStoragePackage, AdminTenantSummary } from "@/types/api";

type Props = {
  tenants: AdminTenantSummary[] | null;
  plans: AdminPlan[];
  storagePackages: AdminStoragePackage[];
  onTenantSaved: (tenant: AdminTenantSummary) => void;
};

/** Gleiche Regel wie list_tenants(needs_rebooking=True) im Backend - damit eine Zeile nach dem
 * Umbuchen im Modal sofort verschwindet, ohne die Liste neu zu laden. */
export function needsRebooking(tenant: AdminTenantSummary, plans: AdminPlan[], storagePackages: AdminStoragePackage[]): boolean {
  const plan = plans.find((p) => p.code === tenant.plan_code);
  if (plan && !plan.is_bookable) return true;
  return tenant.assigned_storage_packages.some((assigned) => storagePackages.find((p) => p.code === assigned.package_code)?.is_bookable === false);
}

/** Mandanten auf einem nicht buchbaren Plan oder mit einem nicht buchbaren Speicherpaket, z.B.
 * nach einem Katalog-Import mit "Überschreiben". "Umbuchen" öffnet die Mandanten-Einstellungen. */
export function AdminCatalogRebooking({ tenants, plans, storagePackages, onTenantSaved }: Props) {
  const t = useTranslations("admin.catalogRebooking");
  const [selected, setSelected] = useState<AdminTenantSummary | null>(null);
  const bookableByPackage = useMemo(() => new Map(storagePackages.map((p) => [p.code, p.is_bookable])), [storagePackages]);
  const bookableByPlan = useMemo(() => new Map(plans.map((p) => [p.code, p.is_bookable])), [plans]);

  return (
    <>
      <DataTable
        columns={[t("colTenant"), t("colPlan"), t("colPackages"), ""]}
        emptyMessage={tenants === null ? t("loading") : t("empty")}
      >
        {(tenants ?? []).map((tenant) => {
          const planBookable = tenant.plan_code === null || bookableByPlan.get(tenant.plan_code) !== false;
          return (
            <tr key={tenant.id}>
              <td>
                <div className="admin-rebooking-tenant">
                  <AdminAvatar name={tenant.name} imageUrl={tenant.profile_image_url} toneKey={tenant.id} size="sm" />
                  <strong>{tenant.name}</strong>
                </div>
              </td>
              <td>
                {tenant.plan_name === null ? (
                  <span className="muted">–</span>
                ) : planBookable ? (
                  <span className="muted">{tenant.plan_name}</span>
                ) : (
                  <Badge variant="warning">{tenant.plan_name}</Badge>
                )}
              </td>
              <td>
                <div className="admin-badge-row">
                  {tenant.assigned_storage_packages.length === 0 ? <span className="muted">–</span> : null}
                  {tenant.assigned_storage_packages.map((pkg) => (
                    <Badge key={pkg.package_code} variant={bookableByPackage.get(pkg.package_code) === false ? "warning" : "neutral"}>
                      {t("packageQuantity", { name: pkg.name, count: pkg.quantity })}
                    </Badge>
                  ))}
                </div>
              </td>
              <td className="admin-cell-end">
                <button type="button" className="button-secondary" onClick={() => setSelected(tenant)}>
                  {t("rebook")}
                </button>
              </td>
            </tr>
          );
        })}
      </DataTable>
      <p className="muted admin-page-footnote">{t("footnote")}</p>

      <AdminTenantSettingsModal
        open={selected !== null}
        onClose={() => setSelected(null)}
        tenant={selected}
        onSaved={(updated) => {
          setSelected(updated);
          onTenantSaved(updated);
        }}
      />
    </>
  );
}
