import { notFound } from "next/navigation";

import { TenantErrorsPanel, TenantSettingsPanel } from "@/components/admin/tenant-detail/tenant-detail-panels";
import { adminIsOwner, loadAdminTenant } from "@/lib/admin/tenant-detail-server";
import { backendFetchWithSession } from "@/lib/api/server";
import { SystemErrorLogPage } from "@/types/api";

// Fehlerprotokoll (require_admin_owner, auditiert) und Aufräumen (Schreiben, Step-up) - nur owner.
export default async function AdminTenantTechnicalTab({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const [tenant, isOwner] = await Promise.all([loadAdminTenant(id), adminIsOwner()]);
  if (!isOwner) notFound();
  const errors = await backendFetchWithSession<SystemErrorLogPage>(`/api/admin/error-logs?tenant_id=${tenant.id}&limit=25&offset=0`);
  return (
    <>
      <TenantErrorsPanel tenantId={tenant.id} initialPage={errors ?? { items: [], total: 0 }} />
      <TenantSettingsPanel tenant={tenant} tab="aufraeumen" readOnly={false} />
    </>
  );
}
