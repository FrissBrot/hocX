import { TenantDomainsPanel } from "@/components/admin/tenant-detail/tenant-detail-panels";
import { loadAdminTenant } from "@/lib/admin/tenant-detail-server";
import { backendFetchWithSession } from "@/lib/api/server";
import { AdminDomainPage } from "@/types/api";

export default async function AdminTenantDomainsTab({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const tenant = await loadAdminTenant(id);
  const page = await backendFetchWithSession<AdminDomainPage>(`/api/admin/domains?tenant_id=${tenant.id}&limit=25&offset=0`);
  return <TenantDomainsPanel tenantId={tenant.id} initialPage={page ?? { items: [], total: 0 }} />;
}
