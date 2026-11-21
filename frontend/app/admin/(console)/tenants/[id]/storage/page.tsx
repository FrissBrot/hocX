import { TenantSettingsPanel } from "@/components/admin/tenant-detail/tenant-detail-panels";
import { adminIsOwner, loadAdminTenant } from "@/lib/admin/tenant-detail-server";

export default async function AdminTenantDetailTab({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const [tenant, isOwner] = await Promise.all([loadAdminTenant(id), adminIsOwner()]);
  return <TenantSettingsPanel tenant={tenant} tab="speicher" readOnly={!isOwner} />;
}
