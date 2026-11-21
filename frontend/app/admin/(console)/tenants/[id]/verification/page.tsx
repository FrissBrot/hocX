import { AdminTenantVerificationPanel } from "@/components/admin/admin-identity-verification";
import { loadAdminTenant } from "@/lib/admin/tenant-detail-server";

export default async function AdminTenantVerificationTab({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const tenant = await loadAdminTenant(id);
  return (
    <section className="panel admin-tenant-detail-panel">
      <AdminTenantVerificationPanel tenantId={tenant.id} tenantName={tenant.name} />
    </section>
  );
}
