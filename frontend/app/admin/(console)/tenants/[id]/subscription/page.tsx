import { TenantChargesPanel, TenantSettingsPanel } from "@/components/admin/tenant-detail/tenant-detail-panels";
import { adminIsOwner, loadAdminTenant } from "@/lib/admin/tenant-detail-server";
import { backendFetchWithSession } from "@/lib/api/server";
import { TenantChargePage } from "@/types/api";

export default async function AdminTenantSubscriptionTab({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const [tenant, isOwner] = await Promise.all([loadAdminTenant(id), adminIsOwner()]);
  const charges = await backendFetchWithSession<TenantChargePage>(`/api/admin/cashflow/charges?tenant_id=${tenant.id}&limit=25&offset=0`);
  return (
    <>
      <TenantSettingsPanel tenant={tenant} tab="abo" readOnly={!isOwner} />
      <TenantChargesPanel tenantId={tenant.id} initialPage={charges ?? { items: [], total: 0, totals: {} as TenantChargePage["totals"] }} />
    </>
  );
}
