import { notFound } from "next/navigation";

import { TenantSecurityTab } from "@/components/admin/tenant-detail/tenant-extra-tabs";
import { adminIsOwner, loadAdminTenant } from "@/lib/admin/tenant-detail-server";

// Sicherheit (1.5.1): Anmeldeereignisse mit Kontonamen - nur owner (require_admin_owner, auditiert).
export default async function AdminTenantSecurityTab({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const [tenant, isOwner] = await Promise.all([loadAdminTenant(id), adminIsOwner()]);
  if (!isOwner) notFound();
  return <TenantSecurityTab tenantId={tenant.id} />;
}
