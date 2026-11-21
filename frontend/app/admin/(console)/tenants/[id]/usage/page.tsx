import { TenantUsageTab } from "@/components/admin/tenant-detail/tenant-extra-tabs";
import { loadAdminTenant } from "@/lib/admin/tenant-detail-server";

// Nutzung (1.5.1): Tageswerte aus dem Kennzahlen-Rollup, nur Zählwerte.
export default async function AdminTenantUsageTab({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const tenant = await loadAdminTenant(id);
  return <TenantUsageTab tenantId={tenant.id} />;
}
