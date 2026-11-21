import { notFound } from "next/navigation";

import { TenantActivityPanel } from "@/components/admin/tenant-detail/tenant-detail-panels";
import { adminIsOwner, loadAdminTenant } from "@/lib/admin/tenant-detail-server";
import { backendFetchWithSession } from "@/lib/api/server";
import { AuditLogPage } from "@/types/api";

// Audit-Log ist require_admin_owner - für support ausgeblendet (Tab fehlt, direkte URL 404).
export default async function AdminTenantActivityTab({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const [tenant, isOwner] = await Promise.all([loadAdminTenant(id), adminIsOwner()]);
  if (!isOwner) notFound();
  const page = await backendFetchWithSession<AuditLogPage>(`/api/admin/audit-log?tenant_id=${tenant.id}&limit=25&offset=0`);
  return <TenantActivityPanel tenantId={tenant.id} initialPage={page ?? { items: [], total: 0 }} />;
}
