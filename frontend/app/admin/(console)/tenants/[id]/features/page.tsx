import { TenantFeaturesTab } from "@/components/admin/tenant-detail/tenant-extra-tabs";
import { adminIsOwner, loadAdminTenant } from "@/lib/admin/tenant-detail-server";

// Features & Module (1.5.1): Stand je Katalog-Feature; Ändern bleibt unter «Abo & Abrechnung».
export default async function AdminTenantFeaturesTab({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const [tenant, isOwner] = await Promise.all([loadAdminTenant(id), adminIsOwner()]);
  return <TenantFeaturesTab tenantId={tenant.id} readOnly={!isOwner} />;
}
