import { TenantDetailHeader } from "@/components/admin/tenant-detail/tenant-detail-header";
import { adminIsOwner, loadAdminTenant } from "@/lib/admin/tenant-detail-server";

// Mandanten-Detailseite (Admin-Redesign §5.2): Kopfbereich + Tabs als Unterrouten, damit jeder Tab
// eine eigene URL (Deep Link, Zurück-Taste) und nur seine eigenen Daten lädt.
export default async function AdminTenantDetailLayout({
  children,
  params,
}: Readonly<{ children: React.ReactNode; params: Promise<{ id: string }> }>) {
  const { id } = await params;
  const [tenant, isOwner] = await Promise.all([loadAdminTenant(id), adminIsOwner()]);
  return (
    <div className="grid admin-tenant-detail">
      <TenantDetailHeader tenant={tenant} isOwner={isOwner} />
      {children}
    </div>
  );
}
