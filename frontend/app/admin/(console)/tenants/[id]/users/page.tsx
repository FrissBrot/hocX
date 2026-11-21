import { notFound } from "next/navigation";

import { TenantSettingsPanel } from "@/components/admin/tenant-detail/tenant-detail-panels";
import { adminIsOwner, loadAdminTenant } from "@/lib/admin/tenant-detail-server";

// Benutzerliste ist require_admin_owner und auditiert (admin.tenant_users_viewed) - nur owner.
export default async function AdminTenantUsersTab({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const [tenant, isOwner] = await Promise.all([loadAdminTenant(id), adminIsOwner()]);
  if (!isOwner) notFound();
  return <TenantSettingsPanel tenant={tenant} tab="benutzer" readOnly={false} />;
}
